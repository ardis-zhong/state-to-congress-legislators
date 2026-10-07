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

import os
import sys

DATASETS_DIR = "datasets"

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


def build_table1():
    raise Pending("one row per person; 3 wrong Bioguide IDs to fix first")


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
