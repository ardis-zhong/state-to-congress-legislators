#!/usr/bin/env python3
"""
Filter sponsored_legislation_full.csv down to just our target legislators
(the ~247 people who served in a state legislature before/during Congress,
1979-present), using state_bill_targets.csv as the roster of who's
actually in scope for this study.

WHY THIS IS NEEDED:
sponsored_legislation_full.csv turned out to contain sponsored-legislation
records for 942 distinct legislators -- far more than our target population
of ~247. Left unfiltered, fetching full text for every bill in it would
mean spending Congress.gov API quota (and ~220 hours) on hundreds of
legislators outside this study. This produces a correctly-scoped file
first, no API calls involved.

USAGE:
    python3 filter_federal_targets.py sponsored_legislation_full.csv state_bill_targets.csv sponsored_legislation_final.csv
"""
import csv
import sys


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 filter_federal_targets.py "
              "sponsored_legislation_full.csv state_bill_targets.csv sponsored_legislation_final.csv")
        sys.exit(1)
    full_path, targets_path, out_path = sys.argv[1:4]

    with open(targets_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "BioguideId" not in (reader.fieldnames or []):
            print(f"ERROR: no 'BioguideId' column in {targets_path}. "
                  f"Columns found: {reader.fieldnames}")
            sys.exit(1)
        target_ids = {row["BioguideId"].strip() for row in reader if row.get("BioguideId", "").strip()}
    print(f"Loaded {len(target_ids)} target legislator(s) from {targets_path}")

    kept = 0
    total = 0
    with open(full_path, newline="", encoding="utf-8") as fin, \
         open(out_path, "w", newline="", encoding="utf-8") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            total += 1
            if row.get("BioguideId", "").strip() in target_ids:
                writer.writerow(row)
                kept += 1

    print(f"Kept {kept} of {total} row(s) -- wrote {out_path}")

    seen_ids = set()
    seen_bills = set()
    with open(out_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            seen_ids.add(row.get("BioguideId", ""))
            seen_bills.add((row.get("Congress", ""), row.get("Type", "").lower(), row.get("Number", "")))
    print(f"Sanity check: {len(seen_ids)} distinct legislator(s), "
          f"{len(seen_bills)} unique (Congress, Type, Number) bill(s) in the filtered file.")


if __name__ == "__main__":
    main()
