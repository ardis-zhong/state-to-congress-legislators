#!/usr/bin/env python3
"""
Writes replication/data/reference/topic_runs.csv: the runs of the Table 6 expanding-window design (one row per
fine-tuning run of finetune_topics.py).

  size  training-set size N = 1,000, 2,000, 5,000, 10,000, 20,000 (3 seeds each), 50,000 (2 seeds), 100,000 and all
        (1 seed): how much fine-tuning the labels need. size_all_s1 is the model that labels Table 6.
  time  train on Congresses 93..T for T = 98, 102, 106, 110, 114, 116; test on Congresses T+1..T+2: does an older
        training window carry to later Congresses?
  time_fixed  the same six windows, each trained on a random 25,000 bills from Congresses 93..T, so that the number of
        training bills is constant and only the period covered changes.
  sensitivity  size_all_commem_s1: all data, with the retired Commemorations area (used through 2008) as a 34th label.

USAGE (from the repo root):  python3 replication/scripts/topics/make_topic_runs.py
"""
import csv

OUT = "replication/data/reference/topic_runs.csv"
rows = []
for n, seeds in ((1000, 3), (2000, 3), (5000, 3), (10000, 3), (20000, 3), (50000, 2), (100000, 1), ("all", 1)):
    for s in range(1, seeds + 1):
        name = "all" if n == "all" else f"n{n}"
        rows.append([f"size_{name}_s{s}", "size", n, "", "", s, "current"])
for t in (98, 102, 106, 110, 114, 116):
    rows.append([f"time_through{t}", "time", "", t, f"{t + 1}-{t + 2}", 1, "current"])
FIXED = 25000   # below the smallest window's pool (29,316 through the 98th) and above 20,000, so every time run uses 3 epochs
for t in (98, 102, 106, 110, 114, 116):
    rows.append([f"time_fixed{FIXED}_through{t}", "time_fixed", FIXED, t, f"{t + 1}-{t + 2}", 1, "current"])
rows.append(["size_all_commem_s1", "size", "all", "", "", 1, "with_commemorations"])
with open(OUT, "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["run_id", "design", "train_size", "train_through", "test_congresses", "seed", "label_set"])
    w.writerows(rows)
print(f"Wrote {OUT}: {len(rows)} runs")
