#!/usr/bin/env python3
"""
legiscan_session_chambers.py -- the chamber each person sat in, per LegiScan session, so Table 4 can drop
"Primary Sponsor" rows on bills from the OTHER chamber (decided by Ardis 2026-11-10).

LegiScan marks some legislators "Primary Sponsor" on bills that began in the other chamber: the senator who
carries a House bill through the Senate (Indiana's "Senate sponsors", Texas, Oklahoma), or the sponsors of a
New Jersey Senate companion listed on the Assembly bill. The state-archive sources in Table 4 count only the
member who introduced the bill in their own chamber, so the LegiScan rows follow the same rule.

LegiScan's people records give a person's latest role, not their role in an old session, so the chamber is
inferred from the bills themselves: the chamber of origin (LegiScan's bill "body": H/A = lower, S = upper)
of the bills on which the person is listed first (sponsor order 1), or of all their primary-sponsor bills
when none lists them first; at least 70% in one chamber decides it, anything closer is marked REVIEW.
Sessions without sponsor roles are "any" (Table 4 keeps only sole-sponsor or first-named rows there, the
person's own introductions). Reviewed decisions live in
replication/data/reference/legiscan_chamber_overrides.csv (state, session_id, bioguide_id, chamber, note).

INPUT:  state_legislation_sponsored.csv (local; legiscan_fetch_state_bills.py, with the Body column)
OUTPUT: replication/data/reference/legiscan_session_chambers.csv
USAGE (from the repo root):  python3 replication/scripts/state/legiscan_session_chambers.py
"""

import collections
import csv
import os

SPONSORED = "state_legislation_sponsored.csv"
OVERRIDES = "replication/data/reference/legiscan_chamber_overrides.csv"
OUT = "replication/data/reference/legiscan_session_chambers.csv"
UNICAMERAL = {"NE"}
LOWER, UPPER = {"H", "A"}, {"S"}


def side(body):
    return "lower" if body in LOWER else "upper" if body in UPPER else ""


def main():
    csv.field_size_limit(10 ** 9)
    first = collections.defaultdict(collections.Counter)   # (state, session, bioguide) -> chamber counts
    every = collections.defaultdict(collections.Counter)
    meta, roles = {}, {}
    with open(SPONSORED, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["StateAbbr"] in UNICAMERAL:
                continue
            key = (r["StateAbbr"], r["SessionId"], r["BioguideId"])
            meta[key] = (r["Name"], r["SessionTitle"])
            c = side(r.get("Body", ""))
            if not c or r["SponsorType"] not in ("Primary Sponsor", "Sponsor"):
                continue
            roles[key] = r["SessionHasRoles"] == "Yes"
            every[key][c] += 1
            if r["SponsorOrder"] == "1":
                first[key][c] += 1
    overrides = {}
    if os.path.exists(OVERRIDES):
        with open(OVERRIDES, newline="", encoding="utf-8") as f:
            overrides = {(r["state"], r["session_id"], r["bioguide_id"]): r for r in csv.DictReader(f)}
    rows = []
    for key in sorted(meta):
        st, sid, bg = key
        n = first[key]
        if key in overrides:
            chamber, basis = overrides[key]["chamber"], "reviewed: " + overrides[key]["note"]
        elif not roles.get(key):
            # no sponsor roles: Table 4 keeps only sole-sponsor or first-named rows there, which are the
            # person's own introductions, so nothing is dropped
            chamber, basis = "any", "session records no sponsor roles"
        else:
            src, n = ("first-listed", first[key]) if sum(first[key].values()) else ("all", every[key])
            lo, up = n["lower"], n["upper"]
            if lo + up == 0:
                chamber, basis = "any", "no primary-sponsor bill"
            elif max(lo, up) / (lo + up) >= 0.7:
                chamber, basis = ("lower" if lo > up else "upper"), f"chamber of most {src} bills"
            else:
                chamber, basis = "REVIEW", f"{src} bills split between chambers"
        rows.append({"state": st, "session_id": sid, "session_title": meta[key][1], "bioguide_id": bg,
                     "name": meta[key][0], "chamber": chamber, "first_listed_lower": first[key]["lower"],
                     "first_listed_upper": first[key]["upper"],
                     "all_lower": every[key]["lower"], "all_upper": every[key]["upper"], "basis": basis})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    c = collections.Counter(r["chamber"] for r in rows)
    print(f"Wrote {OUT}: {len(rows)} person-sessions; {dict(c)}")


if __name__ == "__main__":
    main()
