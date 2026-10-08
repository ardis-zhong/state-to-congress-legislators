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
        ["bioguide_id", "name", "session", "year", "les", "level", "chamber"]),
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


DEMOGRAPHICS = "replication/data/processed/legislator_demographics.csv"
RACE = "replication/data/processed/race_by_bioguide.csv"
VETERANS = "replication/data/processed/veterans_by_bioguide.csv"
GENDER = {"M": "Male", "F": "Female"}


def build_table2():
    """One row per person.
    gender, party: congress-legislators records (party = most recent party in Congress).
    race: Office of the House Historian lists of Black, Hispanic, and Asian and Pacific
          Islander members; anyone on none of them is "Not on House Historian lists".
    veteran: any military service per Congressional Directory biographies
             (Yes / No / Not found -- "Not found" = no biography located)."""
    for path in (DEMOGRAPHICS, RACE, VETERANS):
        if not os.path.exists(path):
            raise Pending(f"{path} missing; see replication/README.md step 1")

    def by_id(path, key):
        with open(path, newline="", encoding="utf-8") as f:
            return {r[key]: r for r in csv.DictReader(f)}

    demo = by_id(DEMOGRAPHICS, "BioguideId")
    race = by_id(RACE, "bioguide_id")
    vets = by_id(VETERANS, "bioguide_id")
    rows = []
    for p in load_person_level():
        bg = p["BioguideId"]
        if bg not in demo or bg not in vets:
            raise Pending(f"{bg} ({p['Name']}) missing from demographics or veteran file; rerun step 1")
        rows.append([bg, p["Name"], GENDER[demo[bg]["Gender"]], vets[bg]["veteran"],
                     demo[bg]["MostRecentParty"],
                     race[bg]["race"] if bg in race else "Not on House Historian lists"])
    return rows


CEL_HOUSE = "cel_cache/CELHouse93to118Reduced-REVISED-06.26.2025.dta"
CEL_SENATE = "cel_cache/CELSenate93to118Reduced.dta"
CEL_STATES = "cel_cache/sles_all_50_states_202609.dta"
SLES_MATCHES = "replication/data/processed/sles_matches.csv"


def build_table3():
    """One row per score (decided 2026-10-06/07):
    federal: Center for Effective Lawmaking LES Classic (1.0), 93rd-118th Congress, whole
             career, joined on CEL's bioguide_id; session = Congress number,
             year = first year of the Congress.
    state:   CEL State Legislative Effectiveness Scores through 2025, linked to Bioguide IDs
             by replication/scripts/effectiveness/match_sles.py; session = the state's
             two-year term as CEL labels it (e.g. 2019-2020), year = its first year."""
    for path in (CEL_HOUSE, CEL_SENATE, CEL_STATES, SLES_MATCHES):
        if not os.path.exists(path):
            raise Pending(f"{path} missing; run replication/scripts/effectiveness/ scripts first")
    import pandas as pd

    people = {p["BioguideId"]: p["Name"] for p in load_person_level()}
    rows = []
    for path, chamber in ((CEL_HOUSE, "House"), (CEL_SENATE, "Senate")):
        les = pd.read_stata(path)
        les = les[les.bioguide_id.isin(people)]
        for r in les.itertuples():
            rows.append([r.bioguide_id, people[r.bioguide_id], str(int(r.congress)), int(r.year),
                         None if pd.isna(r.lesclassic) else round(float(r.lesclassic), 6), "Federal", chamber])

    sles = pd.read_stata(CEL_STATES)
    with open(SLES_MATCHES, newline="", encoding="utf-8") as f:
        matches = [m for m in csv.DictReader(f) if m["status"] == "matched"]
    for m in matches:
        ids = [int(i) for i in m["sles_ids"].split(";")]
        mine = sles[sles.sles_id.isin(ids) & sles.state.isin(m["state"].split(";"))]
        for r in mine.itertuples():
            rows.append([m["bioguide_id"], people[m["bioguide_id"]], r.term.replace("_", "-"),
                         int(r.term[:4]), None if pd.isna(r.sles) else round(float(r.sles), 6), "State",
                         "Upper" if r.chamber == "upper" else "Lower"])
    rows.sort(key=lambda r: (r[0], r[3], r[5], r[6]))
    return rows


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
