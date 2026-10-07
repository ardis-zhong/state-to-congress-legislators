#!/usr/bin/env python3
"""
Add party affiliation (including changes over time) and gender for every
legislator in person_level.csv, sourced from the @unitedstates/congress-legislators
project -- a public-domain, bulk-downloadable dataset maintained specifically
for this kind of research. No API key needed, no rate limits.

Why not Congress.gov's Member API: its /member/{bioguideId} endpoint has no
gender field at all, and its own documentation says the top-level "party"
field "does not currently reflect party changes." This bulk dataset instead
gives each term its own "party" field (and, for a genuine mid-term switch, a
more granular "party_affiliations" list) -- exactly what's needed here.

SOURCE FILES (downloaded automatically, cached locally after the first run):
    https://unitedstates.github.io/congress-legislators/legislators-current.json
    https://unitedstates.github.io/congress-legislators/legislators-historical.json

INPUT:
    person_level.csv (for the BioguideId/Name list to look up) -- pass a
    different path as the first argument if needed.

OUTPUT:
    replication/data/processed/legislator_demographics.csv, columns:
    BioguideId, Name, Gender, MostRecentParty, PartyChanged, PartyHistory, Matched

USAGE:
    python3 fetch_legislator_party_gender.py [person_level.csv]
"""

import csv
import json
import os
import sys
import urllib.request

CURRENT_URL = "https://unitedstates.github.io/congress-legislators/legislators-current.json"
HISTORICAL_URL = "https://unitedstates.github.io/congress-legislators/legislators-historical.json"


def download(url, dest):
    if os.path.exists(dest):
        print(f"  (using cached {dest})")
        return
    print(f"  downloading {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "sdsu-research-script/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with open(dest, "wb") as f:
        f.write(data)


def build_party_history(terms):
    """Chronological list of (start_year, end_year, party), merging adjacent
    same-party spans, expanding any mid-term party_affiliations for finer
    granularity where present."""
    spans = []
    for term in terms:
        if term.get("party_affiliations"):
            for pa in term["party_affiliations"]:
                start = (pa.get("start") or "")[:4]
                end = (pa.get("end") or "")[:4]
                party = pa.get("party", "")
                if party:
                    spans.append((start, end, party))
        else:
            start = str(term.get("start", ""))[:4]
            end = str(term.get("end", ""))[:4]
            party = term.get("party", "")
            if party:
                spans.append((start, end, party))

    merged = []
    for start, end, party in spans:
        if merged and merged[-1][2] == party:
            prev_start, prev_end, prev_party = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end), prev_party)
        else:
            merged.append((start, end, party))
    return merged


def main():
    person_level_path = sys.argv[1] if len(sys.argv) > 1 else "replication/data/population/person_level.csv"

    os.makedirs("replication/data/processed", exist_ok=True)

    print("Downloading congress-legislators bulk data (public domain, no API key needed)...")
    download(CURRENT_URL, "legislators-current.json")
    download(HISTORICAL_URL, "legislators-historical.json")

    print("Loading and indexing by BioguideId...")
    by_bioguide = {}
    for path in ("legislators-current.json", "legislators-historical.json"):
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
        for e in entries:
            bg = e.get("id", {}).get("bioguide")
            if bg:
                by_bioguide[bg] = e
    print(f"  {len(by_bioguide)} legislators indexed (current + historical)")

    print(f"Loading target population from {person_level_path}...")
    with open(person_level_path, newline="", encoding="utf-8") as f:
        targets = list(csv.DictReader(f))
    print(f"  {len(targets)} legislators to look up")

    out_rows = []
    matched = 0
    for t in targets:
        bg = t["BioguideId"]
        name = t.get("Name", "")
        entry = by_bioguide.get(bg)
        if not entry:
            out_rows.append({
                "BioguideId": bg, "Name": name, "Gender": "",
                "MostRecentParty": "", "PartyChanged": "", "PartyHistory": "",
                "Matched": "No",
            })
            continue
        matched += 1
        gender = entry.get("bio", {}).get("gender", "")
        terms = entry.get("terms", [])
        history = build_party_history(terms)
        parties = {p for _, _, p in history}
        history_str = "; ".join(f"{p} ({s}-{e})" for s, e, p in history)
        most_recent = history[-1][2] if history else ""
        out_rows.append({
            "BioguideId": bg,
            "Name": name,
            "Gender": gender,
            "MostRecentParty": most_recent,
            "PartyChanged": "Yes" if len(parties) > 1 else "No",
            "PartyHistory": history_str,
            "Matched": "Yes",
        })

    out_path = "replication/data/processed/legislator_demographics.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["BioguideId", "Name", "Gender",
                                           "MostRecentParty", "PartyChanged",
                                           "PartyHistory", "Matched"])
        w.writeheader()
        w.writerows(out_rows)

    changed = sum(1 for r in out_rows if r["PartyChanged"] == "Yes")
    unmatched = sum(1 for r in out_rows if r["Matched"] == "No")
    print(f"\nDone. Wrote {out_path}")
    print(f"  {matched}/{len(targets)} matched in the congress-legislators dataset")
    if unmatched:
        print(f"  {unmatched} NOT matched -- check these manually, could be a BioguideId "
              f"typo or someone missing from both current/historical files")
    print(f"  {changed} legislator(s) show more than one party across their career")


if __name__ == "__main__":
    main()
