#!/usr/bin/env python3
"""
Evaluate the Table 6 expanding-window runs (finetune_topics.py outputs in topic_runs_out/) and estimate how well the
state bills are labeled.

Per run:
  federal   accuracy and macro-F1 on the held-out federal test set(s) (true Congress.gov labels);
            committee consistency = share of test bills with committee evidence whose predicted area is among the
            areas their committees point to (topic_proxies.py), and the same share for the TRUE label (the ceiling)
  state     committee consistency, subject-term consistency (legislatures' own subject indexes, via LegiScan) and
            California-heading consistency of the predicted labels; agreement with the final model (size_all_s1)
  gold      once documentation/topic_gold_sample/gold_sample_coded.xlsx exists: era-weighted accuracy against the
            hand codes (strict = first choice; lenient = first or second choice), and the gold labels' own committee
            consistency (the state ceiling)

Calibration: across the size-design runs, federal accuracy is regressed on federal committee consistency; the fitted
line turns each run's state committee consistency into an estimated state accuracy. This assumes committee evidence
relates to topic in states as it does in Congress; the gold sample tests that (state ceiling vs federal ceiling, and
estimated vs gold accuracy).

Outputs: documentation/topic_model_report.md, documentation/topic_learning_curve.png, topics_data/topic_eval_runs.csv,
topics_data/topic_eval_final_by_group.csv.

USAGE (from the repo root):  python3 replication/scripts/topics/evaluate_topics.py [--runs-dir topic_runs_out]
"""

import argparse
import csv
import glob
import gzip
import json
import os
import sys
from collections import defaultdict

import numpy as np

csv.field_size_limit(sys.maxsize)
DATA = "topics_data"
GOLD_CODED = "documentation/topic_gold_sample/gold_sample_coded.xlsx"
GOLD_KEY = "documentation/topic_gold_sample/gold_sample_key.csv"
REPORT = "documentation/topic_model_report.md"
FIG = "documentation/topic_learning_curve.png"
FINAL = "size_all_s1"


def load_proxies(kind):
    out = {}
    with open(os.path.join(DATA, f"{kind}_topic_proxies.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["bill_id"]] = {k: set(filter(None, r[k].split("|")))
                                 for k in ("committee_areas", "subject_areas", "heading_areas")}
    return out


def consistency(pairs):
    """pairs: (label, evidence set); share of pairs with evidence where the label is in the set."""
    ev = [(l, s) for l, s in pairs if s]
    return (sum(l in s for l, s in ev) / len(ev), len(ev)) if ev else (None, 0)


def load_gold():
    if not os.path.exists(GOLD_CODED):
        return {}
    from openpyxl import load_workbook
    key = {r["sample_id"]: r for r in csv.DictReader(open(GOLD_KEY, newline="", encoding="utf-8"))}
    ws = load_workbook(GOLD_CODED, read_only=True)["coding"]
    rows = list(ws.iter_rows(values_only=True))
    head = list(rows[0])
    gold = {}
    for row in rows[1:]:
        d = dict(zip(head, row))
        k = key.get(d["sample_id"])
        if k and d.get("policy_area"):
            gold[k["bill_id"]] = (d["policy_area"], d.get("second_choice_if_unsure") or "", float(k["weight"]), k["era"])
    return gold


def wmean(vals):
    num = sum(v * w for v, w in vals)
    den = sum(w for _, w in vals)
    return num / den if den else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default="topic_runs_out")
    a = ap.parse_args()
    fprox, sprox = load_proxies("federal"), load_proxies("state")
    smeta = {}
    with gzip.open(os.path.join(DATA, "state_topic_data.csv.gz"), "rt", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            smeta[r["bill_id"]] = (r["state"], int(r["year"]), "LegiScan" if r["text_source"] == "LegiScan" else "Archive")
    gold = load_gold()

    runs, state_preds = [], {}
    for mfile in sorted(glob.glob(os.path.join(a.runs_dir, "*", "metrics.json"))):
        d = os.path.dirname(mfile)
        m = json.load(open(mfile))
        if m.get("smoke"):
            continue
        rid = m["run_id"]
        fed = list(csv.DictReader(open(os.path.join(d, "federal_test_predictions.csv"), newline="", encoding="utf-8")))
        main_set = "test" if m["design"] == "size" else "out_of_time"
        ft = [r for r in fed if r["test_set"] == main_set]
        row = dict(run_id=rid, design=m["design"], train_size=m["n_train"], seed=m["seed"],
                   train_through=m.get("train_through", ""), label_set=m["label_set"],
                   fed_accuracy=m.get(f"{main_set}_accuracy"), fed_macro_f1=m.get(f"{main_set}_macro_f1"),
                   fed_in_window_accuracy=m.get("in_window_accuracy"))
        row["fed_committee_consistency"], _ = consistency([(r["pred"], fprox.get(r["bill_id"], {}).get("committee_areas", set())) for r in ft])
        row["fed_committee_ceiling"], row["fed_committee_n"] = consistency([(r["label"], fprox.get(r["bill_id"], {}).get("committee_areas", set())) for r in ft])
        sp = {}
        with gzip.open(os.path.join(d, "state_predictions.csv.gz"), "rt", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sp[r["bill_id"]] = r["pred"]
        state_preds[rid] = sp
        for k, name in (("committee_areas", "committee"), ("subject_areas", "subject"), ("heading_areas", "ca_heading")):
            row[f"state_{name}_consistency"], row[f"state_{name}_n"] = consistency(
                [(p, sprox.get(b, {}).get(k, set())) for b, p in sp.items()])
        if gold:
            g = [(sp.get(b) == lab, w) for b, (lab, _, w, _) in gold.items() if b in sp]
            gl = [((sp.get(b) in (lab, sec)), w) for b, (lab, sec, w, _) in gold.items() if b in sp]
            row["gold_accuracy"], row["gold_accuracy_lenient"], row["gold_n"] = wmean(g), wmean(gl), len(g)
        runs.append(row)
    if not runs:
        sys.exit(f"no finished runs in {a.runs_dir}")
    final = state_preds.get(FINAL)
    for row in runs:
        if final:
            sp = state_preds[row["run_id"]]
            row["state_agreement_with_final"] = float(np.mean([sp[b] == final[b] for b in final if b in sp]))

    # calibration: federal accuracy ~ federal committee consistency, across size runs
    pts = [(r["fed_committee_consistency"], r["fed_accuracy"]) for r in runs
           if r["design"] == "size" and r["label_set"] == "current" and r["fed_committee_consistency"] is not None]
    # ceiling adjustment: committees fit topics differently in Congress (e.g. Energy and Commerce takes health bills)
    # than in the states; the gold labels' own committee consistency is the state ceiling, and state consistency is
    # rescaled to the federal ceiling before the federal line is applied (no adjustment until the sample is coded)
    fed_ceiling = np.mean([r["fed_committee_ceiling"] for r in runs if r["design"] == "size" and r["fed_committee_ceiling"]])
    state_ceiling = None
    if gold:
        ev = [((lab in sprox[b]["committee_areas"]), w) for b, (lab, _, w, _) in gold.items()
              if b in sprox and sprox[b]["committee_areas"]]
        state_ceiling = wmean(ev)
    scale = fed_ceiling / state_ceiling if state_ceiling else 1.0
    slope = intercept = None
    if len(pts) >= 3:
        x, y = np.array(pts).T
        slope, intercept = np.polyfit(x, y, 1)
        for r in runs:
            if r["state_committee_consistency"] is not None:
                r["state_accuracy_estimated"] = float(np.clip(intercept + slope * r["state_committee_consistency"] * scale, 0, 1))
    os.makedirs(DATA, exist_ok=True)
    cols = list(dict.fromkeys(k for r in runs for k in r))
    with open(os.path.join(DATA, "topic_eval_runs.csv"), "w", newline="", encoding="utf-8") as g:
        w = csv.DictWriter(g, cols, lineterminator="\n")
        w.writeheader()
        w.writerows(runs)

    # final model by group: era x source, state
    groups = []
    if final:
        by = defaultdict(list)
        for b, p in final.items():
            st, yr, src = smeta[b]
            era = "1969-1988" if yr < 1989 else "1989-1998" if yr < 1999 else "1999-2008" if yr < 2009 else \
                "2009-2016" if yr < 2017 else "2017-2026"
            by[("era", era)].append(b)
            by[("source", src)].append(b)
            by[("state", st)].append(b)
        for (kind, val), bills in sorted(by.items()):
            c, n = consistency([(final[b], sprox[b]["committee_areas"]) for b in bills])
            s, sn = consistency([(final[b], sprox[b]["subject_areas"]) for b in bills])
            est = float(np.clip(intercept + slope * c * scale, 0, 1)) if (c is not None and slope is not None) else None
            groups.append(dict(group=kind, value=val, bills=len(bills), committee_consistency=c, committee_n=n,
                               subject_consistency=s, subject_n=sn, accuracy_estimated=est))
        with open(os.path.join(DATA, "topic_eval_final_by_group.csv"), "w", newline="", encoding="utf-8") as g:
            w = csv.DictWriter(g, list(groups[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(groups)

    plot(runs)
    write_report(runs, groups, slope, intercept, gold, fed_ceiling, state_ceiling)
    print(f"Wrote {REPORT}, {FIG}, {DATA}/topic_eval_runs.csv ({len(runs)} runs)")


def plot(runs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    size = [r for r in runs if r["design"] == "size" and r["label_set"] == "current"]
    if not size:
        return
    fig, ax = plt.subplots(figsize=(7, 4.2))
    series = [("fed_accuracy", "Federal accuracy (true labels)", "#2b6cb0", "-"),
              ("fed_committee_consistency", "Federal committee consistency", "#2b6cb0", "--"),
              ("state_committee_consistency", "State committee consistency", "#c05621", "--"),
              ("state_subject_consistency", "State subject-term consistency", "#c05621", ":"),
              ("state_accuracy_estimated", "State accuracy (estimated)", "#c05621", "-"),
              ("gold_accuracy", "State accuracy (gold sample)", "#276749", "-")]
    for key, lab, col, ls in series:
        by = defaultdict(list)
        for r in size:
            if r.get(key) is not None:
                by[r["train_size"]].append(r[key])
        if not by:
            continue
        xs = sorted(by)
        ax.plot(xs, [np.mean(by[x]) for x in xs], ls, color=col, marker="o", ms=3, label=lab)
    ax.set_xscale("log")
    ax.set_xlabel("Federal bills used for fine-tuning (log scale)")
    ax.set_ylabel("Share")
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(FIG, dpi=200)


def fmt(v, pct=True):
    if v is None or v == "":
        return "–"
    return f"{v:.1%}" if pct else f"{v:,}"


def write_report(runs, groups, slope, intercept, gold, fed_ceiling, state_ceiling):
    L = ["# Table 6 topic classifier: evaluation", "",
         "Generated by `replication/scripts/topics/evaluate_topics.py` from the runs in `topic_runs_out/`.", ""]
    size = sorted([r for r in runs if r["design"] == "size"], key=lambda r: (r["label_set"], r["train_size"], r["seed"]))
    L += ["## How much fine-tuning (training-set size window)", "",
          "| Run | Federal bills | Federal accuracy | Federal macro-F1 | Federal committee consistency (ceiling) | "
          "State committee consistency | State subject consistency | CA heading consistency | Est. state accuracy | "
          "Gold accuracy (lenient) | Agreement with final |", "|" + "---|" * 11]
    for r in size:
        L.append(f"| {r['run_id']} | {fmt(r['train_size'], False)} | {fmt(r['fed_accuracy'])} | {fmt(r['fed_macro_f1'])} | "
                 f"{fmt(r['fed_committee_consistency'])} ({fmt(r['fed_committee_ceiling'])}) | "
                 f"{fmt(r['state_committee_consistency'])} | {fmt(r['state_subject_consistency'])} | "
                 f"{fmt(r['state_ca_heading_consistency'])} | {fmt(r.get('state_accuracy_estimated'))} | "
                 f"{fmt(r.get('gold_accuracy'))} ({fmt(r.get('gold_accuracy_lenient'))}) | "
                 f"{fmt(r.get('state_agreement_with_final'))} |")
    L += ["", f"![Learning curve]({os.path.basename(FIG)})", ""]
    time_runs = sorted([r for r in runs if r["design"] == "time"], key=lambda r: int(r["train_through"]))
    if time_runs:
        L += ["## Drift over time (time window)", "",
              "| Trained on Congresses | Federal bills | In-window accuracy | Next two Congresses accuracy | "
              "State committee consistency | Agreement with final |", "|---|---|---|---|---|---|"]
        for r in time_runs:
            L.append(f"| 93–{r['train_through']} | {fmt(r['train_size'], False)} | {fmt(r['fed_in_window_accuracy'])} | "
                     f"{fmt(r['fed_accuracy'])} | {fmt(r['state_committee_consistency'])} | "
                     f"{fmt(r.get('state_agreement_with_final'))} |")
        L.append("")
    if slope is not None:
        L += ["## Calibration", "",
              f"Across the size runs, federal accuracy ≈ {intercept:.3f} + {slope:.3f} × federal committee consistency. "
              "Applied to state committee consistency, this gives the estimated state accuracy above. It assumes "
              "committees relate to topics in the states as they do in Congress"
              + ("; the gold sample checks this." if gold else "; the gold sample, once coded, will check this."), "",
              f"Ceiling (true or hand-coded label inside its committees' areas): federal {fmt(fed_ceiling)}, "
              f"state {fmt(state_ceiling) if state_ceiling else 'not yet known (gold sample not coded; no adjustment)'}.", ""]
    if groups:
        L += ["## Final model by era, source and state", "",
              "| Group | Value | Bills | Committee consistency (n) | Subject consistency (n) | Est. accuracy |",
              "|---|---|---|---|---|---|"]
        for g in groups:
            L.append(f"| {g['group']} | {g['value']} | {g['bills']:,} | {fmt(g['committee_consistency'])} ({g['committee_n']:,}) | "
                     f"{fmt(g['subject_consistency'])} ({g['subject_n']:,}) | {fmt(g['accuracy_estimated'])} |")
    open(REPORT, "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
