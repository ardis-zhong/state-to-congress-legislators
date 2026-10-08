#!/usr/bin/env python3
"""
Merge the federal sponsored-legislation fetches into one de-duplicated file,
the input to classify_status.py.

WHY: fetch_all_sponsored_legislation.py pages through Congress.gov sorted by
updateDate; for long lists, items sharing an updateDate can shift across a
page boundary between requests, so some items come back twice (the gap-fill
re-fetch, gap_fill_missing_items.py, recovered the items this skipped).
Duplicates are removed on (BioguideId, Url) -- never on (Congress, Type,
Number), because House and Senate amendments share numbering.

INPUTS (repo root, gitignored):
    sponsored_legislation_full.csv      the original 907-person fetch (gap-fill merged in)
    sponsored_legislation_pending.csv   the fetch for extraction_queue_pending.csv
    fetch_log.csv, fetch_log_pending.csv   per-person API-reported totals
OUTPUT:
    sponsored_legislation_full_deduped.csv   only population members, one row per item

The script prints, for each person, any shortfall against the API's own
reported total (a known, accepted Congress.gov pagination quirk for some
high-volume sponsors; see the README).

USAGE (from the repo root):
    python3 replication/scripts/federal/merge_sponsored_legislation.py
"""

import csv
import os
from collections import Counter

INPUTS = ["sponsored_legislation_full.csv", "sponsored_legislation_pending.csv"]
LOGS = ["fetch_log.csv", "fetch_log_pending.csv"]
PERSON_LEVEL = "replication/data/population/person_level.csv"
OUT = "sponsored_legislation_full_deduped.csv"


def main():
    with open(PERSON_LEVEL, newline="", encoding="utf-8") as f:
        population = {r["BioguideId"] for r in csv.DictReader(f)}

    seen, rows, fields = set(), [], None
    read = dropped_dup = dropped_outside = 0
    for path in INPUTS:
        if not os.path.exists(path):
            print(f"  (skipping missing {path})")
            continue
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = fields or reader.fieldnames
            for r in reader:
                read += 1
                if r["BioguideId"] not in population:
                    dropped_outside += 1
                    continue
                key = (r["BioguideId"], r["Url"])
                if key in seen:
                    dropped_dup += 1
                    continue
                seen.add(key)
                rows.append(r)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    people = Counter(r["BioguideId"] for r in rows)
    print(f"read {read} rows -> {len(rows)} unique items for {len(people)} people "
          f"({dropped_dup} duplicates, {dropped_outside} outside the population removed)")

    expected = {}
    for path in LOGS:
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    exp = r.get("ApiReportedCount") or r.get("ExpectedCount") or ""
                    if exp.isdigit():
                        expected[r["BioguideId"]] = int(exp)
    short = [(bg, people.get(bg, 0), exp) for bg, exp in expected.items()
             if bg in population and people.get(bg, 0) < exp]
    print(f"{len(short)} people below the API-reported total; largest gaps:")
    for bg, got, exp in sorted(short, key=lambda x: x[1] - x[2])[:10]:
        print(f"  {bg}: {got} of {exp}")
    missing = sorted(population - set(people))
    print(f"{len(missing)} population members with no items: {missing[:20]}")


if __name__ == "__main__":
    main()
