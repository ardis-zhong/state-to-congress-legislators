#!/usr/bin/env python3
"""
Writes replication/data/reference/topic_runs.csv: the runs of the Table 6 expanding-window design (one row per
fine-tuning run of finetune_topics.py).

  size  training-set size N = 1,000, 2,000, 5,000, 10,000, 20,000 (3 seeds each), 50,000 (2 seeds) and all
        (1 seed), from Congresses 101 on (1989, when every bill has text): how much fine-tuning the labels need. size_all_s1 is the model that labels Table 6.
  time  train on Congresses 101..T (1989 on, the first Congress whose bills all have text) for T = 102, 106, 110, 114,
        116; test on Congresses T+1..T+2: does an older training window carry to later Congresses?
  time_fixed  the same five windows, each trained on a random 9,500 bills from Congresses 101..T, so that the number of
        training bills is constant and only the period covered changes.
  sensitivity  size_all_commem_s1: all data, with the retired Commemorations area (used through 2008) as a 34th label.

USAGE (from the repo root):  python3 replication/scripts/topics/make_topic_runs.py
"""
import csv

OUT = "replication/data/reference/topic_runs.csv"
FROM = 101      # first Congress (1989) whose bills have text; all designs start here
rows = []
for n, seeds in ((1000, 3), (2000, 3), (5000, 3), (10000, 3), (20000, 3), (50000, 2), ("all", 1)):
    for s in range(1, seeds + 1):
        name = "all" if n == "all" else f"n{n}"
        rows.append([f"size_{name}_s{s}", "size", n, FROM, "", "", s, "current"])
for t in (102, 106, 110, 114, 116):
    rows.append([f"time_through{t}", "time", "", FROM, t, f"{t + 1}-{t + 2}", 1, "current"])
FIXED = 9500    # just under the smallest window's training pool (9,771 bills, 101st-102nd Congresses)
for t in (102, 106, 110, 114, 116):
    rows.append([f"time_fixed{FIXED}_through{t}", "time_fixed", FIXED, FROM, t, f"{t + 1}-{t + 2}", 1, "current"])
rows.append(["size_all_commem_s1", "size", "all", FROM, "", "", 1, "with_commemorations"])
with open(OUT, "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["run_id", "design", "train_size", "train_from", "train_through", "test_congresses", "seed", "label_set"])
    w.writerows(rows)
print(f"Wrote {OUT}: {len(rows)} runs")
