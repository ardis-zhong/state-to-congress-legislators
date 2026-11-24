#!/usr/bin/env python3
"""
Fine-tune RoBERTa on Congress.gov policy areas (federal bills) and label the state bills: one run of the Table 6
expanding-window design. Meant for a GPU (SDSU research computing, Colab); runs on CPU/Apple MPS only for smoke tests.

Three designs (rows of topic_runs.csv, made by make_topic_runs.py):
  size   train on a random N of the federal training pool (N = 1,000 ... all), several seeds for small N;
         tested on one fixed held-out federal test set. Shows how much fine-tuning data the labels need.
  time   train on Congresses 101..T (all with text), test on the next two Congresses (out of time) and on the in-window test bills.
         Shows how well labels from one era carry to later ones.
  time_fixed  the time windows with a constant number of training bills (random 9,500 from Congresses 101..T).
Every run also labels every state bill, so state-side evidence (committees, official subject terms, the gold
sample) can be traced along both windows.

Splits are fixed by a hash of bill_id (independent of row order and run): 10% of labeled federal bills = test,
3% = validation (best epoch chosen on validation macro-F1), the rest = training pool.

Input: the tokenizer gets (title, body) as a text pair, the longer part truncated until it fits MAX_LEN tokens. body is
the bill text with committee references removed (build_topic_data.py); bills without text use the title alone.

Outputs in <out>/<run_id>/:
  metrics.json                   run settings, best epoch, federal test accuracy and macro-F1 (both test sets for time)
  federal_test_predictions.csv   bill_id, congress, label, pred, prob, pred2, prob2   (+ test_set for time runs)
  state_predictions.csv.gz       bill_id, pred, prob, pred2, prob2
  model/                         only with --save-model (the final, all-data model for Table 6)

USAGE
  python3 replication/scripts/topics/finetune_topics.py --run-id size_n5000_s1      # one row of topic_runs.csv
  python3 replication/scripts/topics/finetune_topics.py --run-id size_n1000_s1 --smoke   # tiny CPU/MPS check
Options: --runs topic_runs.csv --data-dir topics_data --out topic_runs_out --model roberta-base --max-len 512
         --batch 16 --lr 2e-5 --save-model
"""

import argparse
import csv
import gzip
import hashlib
import json
import os
import random
import sys
import time

import numpy as np
import torch
from torch.utils.data import DataLoader
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

csv.field_size_limit(sys.maxsize)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_topic_data import CURRENT, RETIRED  # noqa: E402


def split_of(bill_id):
    h = int(hashlib.md5(bill_id.encode()).hexdigest(), 16) % 100
    return "test" if h < 10 else "val" if h < 13 else "train"


def read_gz(path, keep, keep_per_1000=1000):
    """Rows as dicts with only the `keep` fields; keep_per_1000 < 1000 takes a fixed hash subset (smoke tests)."""
    out = []
    with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if keep_per_1000 < 1000 and int(hashlib.md5(("s" + r["bill_id"]).encode()).hexdigest(), 16) % 1000 >= keep_per_1000:
                continue
            out.append({k: r[k] for k in keep})
    return out


def epochs_for(n):
    return 10 if n <= 5000 else 6 if n <= 20000 else 3


def macro_f1(y, p, k):
    f1s = []
    for c in range(k):
        tp = sum(1 for a, b in zip(y, p) if a == c and b == c)
        fp = sum(1 for a, b in zip(y, p) if a != c and b == c)
        fn = sum(1 for a, b in zip(y, p) if a == c and b != c)
        if tp + fp + fn:
            f1s.append(2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f1s)) if f1s else 0.0


class Collate:
    def __init__(self, tok, max_len):
        self.tok, self.max_len = tok, max_len

    def __call__(self, batch):
        titles = [b["title"] or "" for b in batch]
        bodies = [b["body"] or "" for b in batch]
        if any(bodies):
            enc = self.tok(titles, [x or "." for x in bodies], truncation="longest_first", max_length=self.max_len,
                           padding=True, return_tensors="pt")
        else:
            enc = self.tok(titles, truncation=True, max_length=self.max_len, padding=True, return_tensors="pt")
        if "y" in batch[0]:
            enc["labels"] = torch.tensor([b["y"] for b in batch])
        return enc


def predict(model, rows, collate, device, batch, amp):
    model.eval()
    out = []
    with torch.no_grad():
        for enc in DataLoader(rows, batch_size=batch * 2, shuffle=False, collate_fn=collate):
            enc.pop("labels", None)
            enc = {k: v.to(device) for k, v in enc.items()}
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=amp):
                logits = model(**enc).logits.float()
            pr = torch.softmax(logits, -1)
            top = torch.topk(pr, 2, dim=-1)
            out += list(zip(top.indices.tolist(), top.values.tolist()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--runs", default="replication/data/reference/topic_runs.csv")
    ap.add_argument("--data-dir", default="topics_data")
    ap.add_argument("--out", default="topic_runs_out")
    ap.add_argument("--model", default="roberta-base")
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--save-model", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="tiny run on CPU/MPS: 200 train, 200 test, 300 state bills")
    a = ap.parse_args()

    run = next((r for r in csv.DictReader(open(a.runs, newline="")) if r["run_id"] == a.run_id), None)
    if run is None:
        sys.exit(f"run {a.run_id} not in {a.runs}")
    labels = CURRENT + (RETIRED if run["label_set"] == "with_commemorations" else [])
    lid = {l: i for i, l in enumerate(labels)}
    seed = int(run["seed"])
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    sub = 30 if a.smoke else 1000
    fed = [r for r in read_gz(os.path.join(a.data_dir, "federal_topic_data.csv.gz"),
                              ("bill_id", "congress", "label", "title", "body"), sub) if r["label"] in lid]
    for r in fed:
        r["y"] = lid[r["label"]]
        r["split"] = split_of(r["bill_id"])
        r["congress"] = int(r["congress"])
    tests = {}
    if run["design"] == "size":
        pool = [r for r in fed if r["split"] == "train"]
        n = len(pool) if run["train_size"] == "all" else int(run["train_size"])
        random.Random(seed).shuffle(pool)
        train = pool[:n]                 # nested: with one seed, each larger window contains every smaller one
        val = [r for r in fed if r["split"] == "val"]
        tests["test"] = [r for r in fed if r["split"] == "test"]
    else:
        lo, hi = int(run["train_from"]), int(run["train_through"])
        t_lo, t_hi = (int(x) for x in run["test_congresses"].split("-"))
        train = [r for r in fed if lo <= r["congress"] <= hi and r["split"] == "train"]
        if run["design"] == "time_fixed":        # same number of bills in every window
            random.Random(seed).shuffle(train)
            n = int(run["train_size"])
            if len(train) < n and not a.smoke:
                sys.exit(f"window has only {len(train)} training bills, fewer than {n}")
            train = train[:n]
        val = [r for r in fed if lo <= r["congress"] <= hi and r["split"] == "val"]
        tests["in_window"] = [r for r in fed if lo <= r["congress"] <= hi and r["split"] == "test"]
        tests["out_of_time"] = [r for r in fed if t_lo <= r["congress"] <= t_hi]
    state = read_gz(os.path.join(a.data_dir, "state_topic_data.csv.gz"), ("bill_id", "title", "body"), sub)
    if a.smoke:
        rng = random.Random(0)
        train, val = rng.sample(train, min(200, len(train))), rng.sample(val, min(100, len(val)))
        tests = {k: rng.sample(v, min(200, len(v))) for k, v in tests.items()}
        state = rng.sample(state, min(300, len(state)))

    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    amp = device == "cuda"
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForSequenceClassification.from_pretrained(a.model, num_labels=len(labels)).to(device)
    collate = Collate(tok, 128 if a.smoke else a.max_len)
    # time designs: the same number of epochs in every window, so epochs never differ between windows
    epochs = 1 if a.smoke else 5 if run["design"] != "size" else epochs_for(len(train))
    loader = DataLoader(train, batch_size=a.batch, shuffle=True, collate_fn=collate,
                        generator=torch.Generator().manual_seed(seed))
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    steps = epochs * len(loader)
    sched = get_linear_schedule_with_warmup(opt, int(0.06 * steps), steps)
    scaler = torch.cuda.amp.GradScaler(enabled=amp)
    print(f"{a.run_id}: {len(train):,} train, {len(val):,} val, "
          + ", ".join(f"{len(v):,} {k}" for k, v in tests.items())
          + f", {len(state):,} state; {epochs} epochs on {device}", flush=True)

    best, best_state, best_epoch, t0 = -1.0, None, 0, time.time()
    for ep in range(1, epochs + 1):
        model.train()
        for i, enc in enumerate(loader, 1):
            enc = {k: v.to(device) for k, v in enc.items()}
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=amp):
                loss = model(**enc).loss
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            if i % 500 == 0:
                print(f"  epoch {ep} step {i}/{len(loader)} loss {loss.item():.3f} ({time.time() - t0:.0f}s)", flush=True)
        vp = predict(model, val, collate, device, a.batch, amp)
        f1 = macro_f1([r["y"] for r in val], [p[0][0] for p in vp], len(labels))
        acc = float(np.mean([r["y"] == p[0][0] for r, p in zip(val, vp)]))
        print(f"  epoch {ep}: validation accuracy {acc:.3f}, macro-F1 {f1:.3f}", flush=True)
        if f1 > best:
            best, best_epoch = f1, ep
            best_state = {k: v.detach().to("cpu", copy=True) for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)

    out = os.path.join(a.out, a.run_id)
    os.makedirs(out, exist_ok=True)
    metrics = dict(run, n_train=len(train), n_val=len(val), epochs=epochs, best_epoch=best_epoch,
                   val_macro_f1=round(best, 4), model=a.model, max_len=a.max_len, lr=a.lr, batch=a.batch,
                   device=device, smoke=a.smoke, labels=labels, seconds=round(time.time() - t0))
    with open(os.path.join(out, "federal_test_predictions.csv"), "w", newline="", encoding="utf-8") as g:
        w = csv.writer(g, lineterminator="\n")
        w.writerow(["test_set", "bill_id", "congress", "label", "pred", "prob", "pred2", "prob2"])
        for name, rows in tests.items():
            pr = predict(model, rows, collate, device, a.batch, amp)
            y, p = [r["y"] for r in rows], [x[0][0] for x in pr]
            metrics[f"{name}_n"] = len(rows)
            metrics[f"{name}_accuracy"] = round(float(np.mean([u == v for u, v in zip(y, p)])), 4) if rows else None
            metrics[f"{name}_macro_f1"] = round(macro_f1(y, p, len(labels)), 4) if rows else None
            for r, ((i1, i2), (p1, p2)) in zip(rows, pr):
                w.writerow([name, r["bill_id"], r["congress"], r["label"], labels[i1], f"{p1:.4f}", labels[i2], f"{p2:.4f}"])
    pr = predict(model, state, collate, device, a.batch, amp)
    with gzip.open(os.path.join(out, "state_predictions.csv.gz"), "wt", newline="", encoding="utf-8") as g:
        w = csv.writer(g, lineterminator="\n")
        w.writerow(["bill_id", "pred", "prob", "pred2", "prob2"])
        for r, ((i1, i2), (p1, p2)) in zip(state, pr):
            w.writerow([r["bill_id"], labels[i1], f"{p1:.4f}", labels[i2], f"{p2:.4f}"])
    metrics["seconds"] = round(time.time() - t0)
    json.dump(metrics, open(os.path.join(out, "metrics.json"), "w"), indent=1)
    if a.save_model:
        model.save_pretrained(os.path.join(out, "model"))
        tok.save_pretrained(os.path.join(out, "model"))
    print(f"Done {a.run_id}: " + ", ".join(f"{k} {v}" for k, v in metrics.items() if k.endswith(("accuracy", "macro_f1"))),
          flush=True)


if __name__ == "__main__":
    main()
