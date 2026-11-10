#!/usr/bin/env python3
"""
Freeze-date refresh (Ardis, 2026-11-09: freeze on 2026-12-04). Writes the fetch queue for every population member
with a term in the current Congress, whose sponsored-legislation lists (new bills, and the latest actions that
decide passage status) change after the original fetch.

Run on the freeze date, after downloading fresh legislators-current.json / legislators-historical.json:
    python3 replication/scripts/federal/refresh_queue.py
    python3 replication/scripts/federal/fetch_all_sponsored_legislation.py --api-key "$CONGRESS_API_KEY" \\
        --queue replication/data/targets/extraction_queue_refresh.csv \\
        --output sponsored_legislation_refresh.csv --log fetch_log_refresh.csv
    python3 replication/scripts/federal/merge_sponsored_legislation.py
    python3 replication/scripts/federal/classify_status.py
    python3 replication/scripts/federal/fetch_federal_bill_text.py "$CONGRESS_API_KEY" sponsored_legislation_full_status.csv \\
        --min-congress 119 --delay 0.8
"""

import csv
import datetime
import json

PERSON_LEVEL = "replication/data/population/person_level.csv"
LEGISLATOR_FILES = ["legislators-current.json", "legislators-historical.json"]
OUT = "replication/data/targets/extraction_queue_refresh.csv"


def current_congress(today=None):
    today = today or datetime.date.today()
    year = today.year if not (today.month == 1 and today.day < 3) else today.year - 1
    return (year - 1789) // 2 + 1


def main():
    congress = current_congress()
    start = datetime.date(1789 + 2 * (congress - 1), 1, 3).isoformat()
    with open(PERSON_LEVEL, newline="", encoding="utf-8") as f:
        people = {r["BioguideId"]: r for r in csv.DictReader(f)}
    serving = {}
    for path in LEGISLATOR_FILES:
        with open(path, encoding="utf-8") as f:
            for p in json.load(f):
                bg = p["id"]["bioguide"]
                if bg in people and any(t["end"] > start for t in p["terms"]):
                    serving[bg] = p
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Name", "State", "Chambers", "BioguideId", "MaxCongress", "TotalSponsoredItems"])
        for bg in sorted(serving):
            r = people[bg]
            w.writerow([r["Name"], r["State"], r["Chambers"], bg, congress, ""])
    print(f"Wrote {OUT}: {len(serving)} members with a term in the {congress}th Congress")


if __name__ == "__main__":
    main()
