#!/usr/bin/env python3
"""
Federal bills of the 91st and 92nd Congresses (1969-1972) for Table 7. Congress.gov's API lists sponsored
legislation only from the 93rd Congress (1973), so for 1969-1972 the source is the Congressional Bills Project
(E. Scott Adler and John Wilkerson), distributed by the Comparative Agendas Project
(https://compagendas.la.utexas.edu/project/us/datasets, file US-Legislative-congressional_bills_19.3.csv), which
codes every public bill (H.R. and S.) introduced from 1947 with its sponsor, title and whether it became law.

The dataset names sponsors without an ID, so each population member serving in these Congresses was matched to
the sponsor-name spelling(s) used for them in that Congress and chamber, against the official roster
(@unitedstates/congress-legislators): surname, and where two members of the chamber share it, first name or
nickname (then middle name). The reviewed list is replication/data/reference/cbp_sponsor_names_1969_1972.csv
(congress, chamber, name_full, bioguide_id, name, note). Resolutions are not in the dataset, and it has no
Congress.gov policy area, so Table 7's topic is blank for these rows (the dataset's Policy Agendas topic codes
are not mixed in).

Output: cbp_sponsored_legislation_1969_1972.csv (BioguideId, Name, Congress, Type, Number, Title, Year, BecameLaw).

USAGE (from the repo root):  python3 replication/scripts/federal/cbp_bills_1969_1972.py
"""

import csv
import os

CBP = "congressional_bills_project/US-Legislative-congressional_bills_19.3.csv"
NAMES = "replication/data/reference/cbp_sponsor_names_1969_1972.csv"
OUT = "cbp_sponsored_legislation_1969_1972.csv"


def main():
    if not os.path.exists(CBP):
        raise SystemExit(f"{CBP} missing: download it from the Comparative Agendas Project (see the docstring)")
    with open(NAMES, newline="", encoding="utf-8") as f:
        who = {(r["congress"], "1" if r["chamber"] == "House" else "2", r["name_full"]): (r["bioguide_id"], r["name"])
               for r in csv.DictReader(f) if r["name_full"]}
    rows, seen = [], set()
    with open(CBP, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            p = who.get((r["cong"], r["chamber"], r["name_full"]))
            if not p or r["bill_type"] not in ("HR", "S"):
                continue
            k = (p[0], r["cong"], r["bill_type"], r["bill_no"])
            if k in seen:
                continue
            seen.add(k)
            rows.append({"BioguideId": p[0], "Name": p[1], "Congress": r["cong"], "Type": r["bill_type"],
                         "Number": r["bill_no"], "Title": " ".join((r["description"] or "").split()),
                         "Year": r["year"], "BecameLaw": "Yes" if r["filter_plaw"] == "1" else "No"})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {OUT}: {len(rows)} bills, {len({r['BioguideId'] for r in rows})} people, "
          f"{sum(1 for r in rows if r['BecameLaw'] == 'Yes')} became law")


if __name__ == "__main__":
    main()
