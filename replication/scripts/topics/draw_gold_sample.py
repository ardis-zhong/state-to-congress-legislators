#!/usr/bin/env python3
"""
Gold-standard sample for the Table 6 topic classifier: 400 state bills for hand coding with Congress.gov policy areas.

Design: stratified random sample, 80 bills from each of five eras (1969-1988, 1989-1998, 1999-2008, 2009-2016,
2017-2026), simple random within each era (so states and sources appear in proportion to their bills in that era).
Equal allocation oversamples the older, smaller eras so accuracy can be reported by era; `weight` (bills in the era
divided by bills sampled from it) gives population estimates. 80 rows (20%, random) are flagged for a second coder,
for intercoder reliability. Fixed seed, so the draw is reproducible.

The coder sees only the bill (state, year, title, text excerpt), never the model's label or the committee/subject
evidence.

Outputs (documentation/topic_gold_sample/):
  gold_sample_coding.xlsx   coding sheet: one row per bill, a policy-area dropdown, confidence, honorary flag, notes
  gold_sample_key.csv       sample_id, bill_id, era, weight, second_coder (for joining the codes back)

USAGE (from the repo root, after build_topic_data.py):  python3 replication/scripts/topics/draw_gold_sample.py
"""

import csv
import gzip
import os
import random
import sys
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

csv.field_size_limit(sys.maxsize)
sys.path.insert(0, os.path.dirname(__file__))
from build_topic_data import CURRENT  # noqa: E402

SRC = "topics_data/state_topic_data.csv.gz"
OUT = "documentation/topic_gold_sample"
SEED = 20261121
PER_ERA = 80
ERAS = [(1969, 1988), (1989, 1998), (1999, 2008), (2009, 2016), (2017, 2026)]
EXCERPT = 2500


def era_of(year):
    for lo, hi in ERAS:
        if lo <= year <= hi:
            return f"{lo}-{hi}"
    return None


def main():
    by_era = defaultdict(list)
    with gzip.open(SRC, "rt", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            e = era_of(int(r["year"]))
            if e and r["body"].strip():
                by_era[e].append(r)
    rng = random.Random(SEED)
    picked = []
    for lo, hi in ERAS:
        e = f"{lo}-{hi}"
        pool = sorted(by_era[e], key=lambda r: r["bill_id"])
        take = rng.sample(pool, min(PER_ERA, len(pool)))
        w = len(pool) / len(take)
        picked += [(e, w, r) for r in take]
        print(f"  {e}: {len(take)} of {len(pool):,} bills (weight {w:.1f})")
    rng.shuffle(picked)                       # coding order mixes eras and states
    second = set(rng.sample(range(len(picked)), len(picked) // 5))

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "gold_sample_key.csv"), "w", newline="", encoding="utf-8") as g:
        w = csv.writer(g, lineterminator="\n")
        w.writerow(["sample_id", "bill_id", "era", "weight", "second_coder"])
        for i, (e, wt, r) in enumerate(picked, 1):
            w.writerow([f"G{i:03d}", r["bill_id"], e, f"{wt:.4f}", "Yes" if i - 1 in second else "No"])

    wb = Workbook()
    ws = wb.active
    ws.title = "coding"
    head = ["sample_id", "state", "year", "title", "text_excerpt", "policy_area", "second_choice_if_unsure",
            "confidence", "honorary_or_commemorative", "notes", "second_coder"]
    ws.append(head)
    for i, (e, wt, r) in enumerate(picked, 1):
        body = r["body"][:EXCERPT] + (" ..." if len(r["body"]) > EXCERPT else "")
        ws.append([f"G{i:03d}", r["state"], int(r["year"]), r["title"], body, "", "", "", "", "",
                   "Yes" if i - 1 in second else "No"])
    lists = wb.create_sheet("lists")
    for j, a in enumerate(CURRENT, 1):
        lists.cell(row=j, column=1, value=a)
    for j, a in enumerate(["High", "Medium", "Low"], 1):
        lists.cell(row=j, column=2, value=a)
    for j, a in enumerate(["Yes", "No"], 1):
        lists.cell(row=j, column=3, value=a)
    lists.sheet_state = "hidden"
    n = len(picked) + 1
    for col, ref in (("F", f"lists!$A$1:$A${len(CURRENT)}"), ("G", f"lists!$A$1:$A${len(CURRENT)}"),
                     ("H", "lists!$B$1:$B$3"), ("I", "lists!$C$1:$C$2")):
        dv = DataValidation(type="list", formula1=f"={ref}", allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{n}")
    widths = {"A": 10, "B": 7, "C": 7, "D": 45, "E": 90, "F": 34, "G": 30, "H": 12, "I": 14, "J": 30, "K": 12}
    for c, wd in widths.items():
        ws.column_dimensions[c].width = wd
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
    for row in ws.iter_rows(min_row=2, max_row=n):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "F2"
    wb.save(os.path.join(OUT, "gold_sample_coding.xlsx"))
    print(f"Wrote {OUT}/gold_sample_coding.xlsx and gold_sample_key.csv: {len(picked)} bills, "
          f"{len(second)} flagged for a second coder")


if __name__ == "__main__":
    main()
