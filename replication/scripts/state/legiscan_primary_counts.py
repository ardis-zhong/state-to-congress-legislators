#!/usr/bin/env python3
"""
For Table 4's first_named column: how many primary sponsors LegiScan lists on each bill our people sponsor
(from the cached bulk datasets, legiscan_dataset_cache/<ST>_<session>.zip, bill/*.json sponsors with
sponsor_type_id 1 = primary). Used only where the bill's text prints no sponsor line: a person who is the
bill's only primary sponsor counts as first-named. Writes replication/data/processed/legiscan_primary_counts.csv
(StateAbbr, SessionId, BillNumber, Primaries, Sponsors).

USAGE (from the repo root): python3 replication/scripts/state/legiscan_primary_counts.py
"""

import collections
import csv
import json
import os
import zipfile

STATE_SPONSORED = "state_legislation_sponsored.csv"
CACHE = "legiscan_dataset_cache"
OUT = "replication/data/processed/legiscan_primary_counts.csv"


def main():
    need = collections.defaultdict(set)
    with open(STATE_SPONSORED, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            need[(r["StateAbbr"], r["SessionId"])].add(r["BillNumber"])
    out, missing = [], []
    for (st, sid), bills in sorted(need.items()):
        path = os.path.join(CACHE, f"{st}_{sid}.zip")
        if not os.path.exists(path):
            missing.append(f"{st}_{sid}")
            continue
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if "/bill/" not in name or not name.endswith(".json"):
                    continue
                try:
                    b = json.loads(z.read(name))["bill"]
                except (ValueError, KeyError):
                    continue
                if b.get("bill_number") in bills:
                    sp = b.get("sponsors") or []
                    out.append({"StateAbbr": st, "SessionId": sid, "BillNumber": b["bill_number"],
                                "Primaries": sum(1 for s in sp if s.get("sponsor_type_id") == 1), "Sponsors": len(sp)})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["StateAbbr", "SessionId", "BillNumber", "Primaries", "Sponsors"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {OUT}: {len(out)} bills; datasets missing: {missing}")


if __name__ == "__main__":
    main()
