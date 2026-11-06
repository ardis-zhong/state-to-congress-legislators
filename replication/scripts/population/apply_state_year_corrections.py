#!/usr/bin/env python3
"""
Applies replication/data/reference/state_years_corrections.csv (verified corrections to the researched
state-legislature service, found by the 2026-11-04 audit against Wikipedia, Wikidata and LegiScan rosters)
to person_level.csv and the LegiScan targets. build_final_datasets.py calls it after writing person_level.csv.

USAGE (from the repo root): python3 replication/scripts/population/apply_state_year_corrections.py
"""

import csv
import re

CORRECTIONS = "replication/data/reference/state_years_corrections.csv"
PERSON_LEVEL = "replication/data/population/person_level.csv"
TARGETS = "replication/data/targets/state_bill_targets_full.csv"


def apply(person_level=PERSON_LEVEL, targets=TARGETS):
    with open(CORRECTIONS, newline="", encoding="utf-8") as f:
        fixes = {r["bioguide_id"]: r for r in csv.DictReader(f)}
    with open(person_level, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    done = 0
    for r in rows:
        fix = fixes.get(r["BioguideId"])
        if fix:
            r["StateLegChamber"], r["StateLegYears"] = fix["state_leg_chamber"], fix["state_leg_years"]
            done += 1
    with open(person_level, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with open(targets, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        tfields, trows = reader.fieldnames, list(reader)
    for r in trows:
        fix = fixes.get(r["BioguideId"])
        if fix:
            years = [int(y) for y in re.findall(r"(?:19|20)\d\d", fix["state_leg_years"])]
            r["StateLegChamber"], r["StateLegYears"] = fix["state_leg_chamber"], fix["state_leg_years"]
            r["MinYear"], r["MaxYear"] = min(years), max(years)
    with open(targets, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=tfields)
        w.writeheader()
        w.writerows(trows)
    print(f"Applied {done} of {len(fixes)} corrections")


if __name__ == "__main__":
    apply()
