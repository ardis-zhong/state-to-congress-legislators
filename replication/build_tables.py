#!/usr/bin/env python3
"""
Build the 7 final tables in datasets/ from the ingredient files in
replication/data/. This is the ONE script that produces the deliverables;
everything under replication/scripts/ produces ingredients for it.

USAGE (run from the repo root):
    python3 replication/build_tables.py            # build every table that is ready
    python3 replication/build_tables.py 1 2        # build only tables 1 and 2

Each table is written as CSV and as Stata .dta. All are keyed on bioguide_id.
Tables 4 and 5 (full bill text) are too large for GitHub; they are gitignored
here and published on Harvard Dataverse.

A table whose ingredients or design decisions aren't settled yet is reported as
PENDING with the reason, rather than written out partially.
"""

import csv
import datetime
import json
import os
import sys

DATASETS_DIR = "datasets"
PERSON_LEVEL = "replication/data/population/person_level.csv"
# Official term records from @unitedstates/congress-legislators. Downloaded to the repo
# root (gitignored) by replication/scripts/population/fetch_legislator_party_gender.py.
LEGISLATOR_FILES = ["legislators-current.json", "legislators-historical.json"]

# Column names are snake_case so they work as Stata variable names.
# For state bills, "Congressional Session" is two columns: state_session (the
# state legislature's own session, as LegiScan labels it) and congress (the
# U.S. Congress in session when the bill was introduced).
TABLES = {
    1: ("table1_state_to_federal",
        ["bioguide_id", "name", "state", "state_leg_years", "federal_years", "federal_chamber"]),
    2: ("table2_demographics",
        ["bioguide_id", "name", "gender", "veteran", "party", "race"]),
    3: ("table3_effectiveness_scores",  # one row per score; year = first calendar year it covers
        ["bioguide_id", "name", "session", "year", "les", "level"]),
    4: ("table4_state_bill_text",
        ["bioguide_id", "name", "bill_id", "bill_name", "state_session", "congress", "year", "state",
         "bill_text"]),
    5: ("table5_federal_bill_text",
        ["bioguide_id", "name", "bill_id", "bill_name", "congress", "year", "chamber", "bill_text"]),
    6: ("table6_state_bill_topics",
        ["bioguide_id", "name", "bill_id", "bill_name", "state_session", "congress", "year", "topic",
         "passed"]),
    7: ("table7_federal_bill_topics",
        ["bioguide_id", "name", "bill_id", "bill_name", "congress", "year", "topic", "passed"]),
}


class Pending(Exception):
    """Raised by a builder whose inputs or design decisions aren't settled yet."""


def load_person_level():
    with open(PERSON_LEVEL, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_terms():
    """Bioguide ID -> list of terms from the congress-legislators records."""
    terms = {}
    for path in LEGISLATOR_FILES:
        if not os.path.exists(path):
            raise Pending(f"{path} not found; run "
                          "replication/scripts/population/fetch_legislator_party_gender.py first")
        with open(path, encoding="utf-8") as f:
            for p in json.load(f):
                terms[p["id"]["bioguide"]] = p["terms"]
    return terms


def service_spans(terms, today):
    """Merge consecutive terms into year spans, e.g. '1973-1975, 1981-1991'.
    Terms less than 60 days apart count as continuous service; a term that
    hasn't ended yet is shown as '-present'."""
    spans = []
    for t in sorted(terms, key=lambda t: t["start"]):
        start = datetime.date.fromisoformat(t["start"])
        end = datetime.date.fromisoformat(t["end"])
        if spans and (start - spans[-1][1]).days <= 60:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    return ", ".join(f"{s.year}-{'present' if e > today else e.year}" for s, e in spans)


def build_table1():
    """One row per person. federal_years comes from the official term records;
    state_leg_years is the hand-researched text (no official source exists)."""
    terms = load_terms()
    today = datetime.date.today()
    rows = []
    for p in load_person_level():
        bg = p["BioguideId"]
        if bg not in terms:
            raise Pending(f"{bg} ({p['Name']}) missing from congress-legislators records")
        by_chamber = {}
        for t in terms[bg]:
            by_chamber.setdefault({"rep": "House", "sen": "Senate"}[t["type"]], []).append(t)
        if len(by_chamber) == 1:
            chamber = next(iter(by_chamber))
            years = service_spans(by_chamber[chamber], today)
        else:
            chamber = "Both"
            order = sorted(by_chamber, key=lambda c: min(t["start"] for t in by_chamber[c]))
            years = "; ".join(f"{service_spans(by_chamber[c], today)} ({c})" for c in order)
        rows.append([bg, p["Name"], p["State"], p["StateLegYears"], years, chamber])
    return rows


def build_table2():
    raise Pending("gender + party exist for the original 910 only; veteran and race have no source yet")


def build_table3():
    raise Pending("CEL LES/SLES data not downloaded yet (thelawmakers.org/data-download)")


def build_table4():
    raise Pending("full-population LegiScan fetch + bill-text fetch not run yet")


def build_table5():
    raise Pending("federal bill text exists for the 247-person LegiScan scope only")


def build_table6():
    raise Pending("method for mapping state bills to Congress.gov topics not designed yet")


def build_table7():
    raise Pending("federal sponsored-legislation fetch pending for the added people")


BUILDERS = {1: build_table1, 2: build_table2, 3: build_table3, 4: build_table4,
            5: build_table5, 6: build_table6, 7: build_table7}


def write(num, rows):
    import pandas as pd
    fname, cols = TABLES[num]
    df = pd.DataFrame(rows, columns=cols)
    os.makedirs(DATASETS_DIR, exist_ok=True)
    df.to_csv(os.path.join(DATASETS_DIR, fname + ".csv"), index=False)
    df.to_stata(os.path.join(DATASETS_DIR, fname + ".dta"), write_index=False, version=118)
    return len(df)


def main():
    nums = [int(a) for a in sys.argv[1:]] or sorted(TABLES)
    for n in nums:
        fname = TABLES[n][0]
        try:
            rows = BUILDERS[n]()
        except Pending as e:
            print(f"Table {n} ({fname}): PENDING -- {e}")
            continue
        print(f"Table {n} ({fname}): wrote {write(n, rows)} rows")


if __name__ == "__main__":
    main()
