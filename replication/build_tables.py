#!/usr/bin/env python3
"""
Build the 7 final tables in datasets/ from the ingredient files in
replication/data/. This is the ONE script that produces the deliverables;
everything under replication/scripts/ produces ingredients for it.

USAGE (run from the repo root):
    python3 replication/build_tables.py            # build every table that is ready
    python3 replication/build_tables.py 1 2        # build only tables 1 and 2

Each table is written as CSV (datasets/csv/) and as Stata .dta (datasets/dta/).
All are keyed on bioguide_id.
Tables 4 and 5 (full bill text) are too large for GitHub; they are gitignored
here and published on Harvard Dataverse.

A table whose ingredients or design decisions aren't settled yet is reported as
PENDING with the reason, rather than written out partially.
"""

import csv
import datetime
import json
import os
import re
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
         "text_source", "text_version", "bill_text"]),
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
        mine = sles[sles.sles_id.isin(ids) & sles.state.isin(m["state"].split(";"))
                    & ~sles.term.isin(m.get("exclude_terms", "").split(";"))]  # CEL errors, see sles_review.csv
        for r in mine.itertuples():
            rows.append([m["bioguide_id"], people[m["bioguide_id"]], r.term.replace("_", "-"),
                         int(r.term[:4]), None if pd.isna(r.sles) else round(float(r.sles), 6), "State",
                         "Upper" if r.chamber == "upper" else "Lower"])
    rows.sort(key=lambda r: (r[0], r[3], r[5], r[6]))
    return rows


# Bill texts removed after validation (garbled scans, wrong documents), with reasons.
EXCLUDED_TEXTS = "replication/data/reference/excluded_bill_texts.csv"


def excluded_texts(table):
    with open(EXCLUDED_TEXTS, newline="", encoding="utf-8") as f:
        return {r["bill_id"] for r in csv.DictReader(f) if r["table"] == str(table)}


STATE_SPONSORED = "state_legislation_sponsored.csv"  # local; see replication/README.md step 3
STATE_TEXT_MANIFEST = "bill_text_manifest.csv"       # local; written by legiscan_fetch_bill_text.py
LEGISCAN_SPONSOR_CHECK = "replication/data/reference/legiscan_sponsor_check.csv"  # legiscan_sponsor_check.py


def congress_on(date_str):
    """U.S. Congress in session on a YYYY-MM-DD date (each starts Jan 3 of an odd year)."""
    y, m, d = (int(x) for x in date_str.split("-"))
    if (m, d) < (1, 3):
        y -= 1
    return (y - 1787) // 2


def state_bill_rows():
    """Sponsor rows for state bills (decided 2026-10-09, widened 2026-10-13): 'Primary Sponsor'
    everywhere, 'Sponsor' in states whose LegiScan data never uses 'Primary Sponsor' (CT, MS, SD),
    and, in sessions that record no sponsor roles, bills whose sole listed sponsor is the person.
    CT, MS and SD 'Sponsor' rows are then checked against the legislature's own record of the first
    sponsor (legiscan_sponsor_check.py, decided 2026-10-28): rows where the person is not the first
    sponsor (co-sponsors, joint authors) are dropped."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "state"))
    from legiscan_fetch_bill_text import sponsor_rows_in_scope
    rows, _ = sponsor_rows_in_scope(STATE_SPONSORED)
    with open(LEGISCAN_SPONSOR_CHECK, newline="", encoding="utf-8") as f:
        not_first = {(c["StateAbbr"], c["BioguideId"], c["SessionId"], c["BillNumber"])
                     for c in csv.DictReader(f) if c["Verdict"] == "NotFirst"}
    return [r for r in rows if (r["StateAbbr"], r["BioguideId"], r["SessionId"], r["BillNumber"]) not in not_first]


def state_bill_dates(r):
    """(year, congress) from the introduced-text date, else the status date, else the session's
    first year. A date counts only if it is plausible for the bill's session: from two years
    before the session starts (bills prefiled for a two-year legislature and listed again in its
    second session) to one year after it ends. LegiScan records some impossible dates, e.g.
    0000-00-00, or 1969 for 2,396 New York bills from 2013-2014."""
    years = [int(y) for y in re.findall(r"(?:19|20)\d\d", r["SessionTitle"])]
    lo, hi = min(years), max(years)
    for d in (r["IntroducedDocDate"], r["StatusDate"]):
        if re.fullmatch(r"(19|20)\d\d-\d\d-\d\d", d or "") and lo - 2 <= int(d[:4]) <= hi + 1:
            return int(d[:4]), congress_on(d)
    return lo, (lo - 1787) // 2


def build_table4():
    """One row per state bill sponsored by a population member that has text (the version as
    introduced). From LegiScan (bill_id = state-LegiScan session id-bill number) and, for
    California before LegiScan's coverage, from the Legislature's own archives (see
    california_rows)."""
    for path in (STATE_SPONSORED, STATE_TEXT_MANIFEST):
        if not os.path.exists(path):
            raise Pending(f"{path} missing; run the LegiScan steps in replication/README.md")
    text_path = {}
    with open(STATE_TEXT_MANIFEST, newline="", encoding="utf-8") as f:
        for m in csv.DictReader(f):
            if int(m["TextLength"] or 0) > 0 and m["TextPath"]:
                text_path[m["DocId"]] = m["TextPath"]
    people = {p["BioguideId"]: (p["Name"], p["State"]) for p in load_person_level()}
    skip = excluded_texts(4)
    out = []
    for r in state_bill_rows():
        if f"{r['StateAbbr']}-{r['SessionId']}-{r['BillNumber']}" in skip:
            continue
        path = text_path.get(r["IntroducedDocId"])
        if r["BioguideId"] not in people or not path or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as tf:
            text = tf.read()
        year, congress = state_bill_dates(r)
        out.append([r["BioguideId"], people[r["BioguideId"]][0],
                    f"{r['StateAbbr']}-{r['SessionId']}-{r['BillNumber']}", " ".join(r["Title"].split()),
                    r["SessionTitle"], str(congress), year, r["StateAbbr"], "LegiScan",
                    r["IntroducedDocType"] or "Introduced", text])
    out.extend(archive_rows(people, skip))
    out.sort(key=lambda x: (x[0], x[6], x[2]))
    return out


# State bills from before LegiScan's coverage, from the legislatures' own archives (state-text
# pilots, decided by Ardis 2026-10-17/18). California: 1989-1992 and 1999-2008 from the
# Legislature's database downloads, 1993-1998 from its older website. Florida: 1998-2009 from
# flsenate.gov, which hosts both chambers' bills. Virginia: 1994-2009 from the legacy Legislative
# Information System (members' chief-patron lists). Ohio: 1997-2008 from the Ohio Legislature's
# public legislation data service (primary sponsors). Illinois: 1997-2008 from the General Assembly's
# legacy Legisnet archive and file repository (chief sponsors who introduced the bill). Michigan:
# 1989-2008 from legislature.mi.gov (primary sponsors named first in the introduced text). West
# Virginia: 1993-2009 from the Legislature's bill status archive (lead sponsors). Maryland: 1996-2008
# from the General Assembly's archived session pages (first-named sponsors). Pennsylvania: 1969-2008
# from palegis.us (prime sponsors; the lowest printer's number is the bill as introduced). Washington:
# 1991-2008 from the Legislature's Bills by sponsor report and document archive (primary sponsors).
# North Carolina: 1989-2008 from ncleg.gov (first-named primary sponsor in the introduced text).
# Wisconsin: 1995-2010 from docs.legis.wisconsin.gov (first-named author in the introduced text).
# New Jersey: 2000-2009 from njleg.state.nj.us (first prime sponsor, checked against the introduced
# text). Minnesota: 1995-2008 from the Revisor's bill status (chief authors; texts print no authors).
# Texas: 1993-2009 from the Legislature's FTP site (first author in the author reports, checked against the
# introduced text's "By:" line).
# Louisiana: 1997-2009 from legis.la.gov (primary author, checked against the original version's "BY ..." line).
# South Carolina: 1985-2008 from scstatehouse.gov (primary sponsors; earliest version online, checked against
# its "Introduced by" line where printed; 1985-1990 ratified acts only).
# Missouri: 1996-2009 Senate bills from senate.mo.gov (sponsor in the Senate's bill lists, checked against the
# introduced text's "INTRODUCED BY SENATOR" line where printed). House archive pages are closed to crawlers.
# Hawaii: 1999-2008 from data.capitol.hawaii.gov (first-named introducer in the Legislature's measures-introduced
# lists; Hawaii's introduced texts print no introducer names).
# Kentucky: 1998-2009 from the Legislative Record (apps.legislature.ky.gov/record; first-named sponsor on the
# record's bill page; texts print no sponsor).
# Arkansas: 1991-2000 from arkleg.state.ar.us (primary sponsor on the member's page, checked against the bill's
# "By:" line).
# Iowa: 1995-2002 and 2009-2010 from legis.iowa.gov (bills by sponsor; the Bill Book's jacket PDF up to the first
# amendment, checked against its "BY ..." line).
# Alaska: 1999-2008 from akleg.gov BASIS (first-named prime sponsor; introduced version A as plain text).
# New Mexico: 1997-2000 from nmlegis.gov (Bill Finder by Sponsor; introduced text's "INTRODUCED BY" line).
# Nevada: 1997 session from the Legislature's archive (primary sponsor in the 1997 tracking lists, checked against
# the introduced text's heading; robots.txt closes the other pre-2011 sessions' bill information).
# Oregon: 2007-2009 from the Legislature's OData service and OLIS (first chief sponsor, checked against the
# introduced text's "Sponsored by" line).
# Nevada 1999-2009: every introduced text in the archive read by number (the bill lists are under closed paths),
# kept when the heading's first sponsor is the person. Mississippi: 1999-2009 from the Bill Status System
# (measures by author, checked against the introduced text's "By:" line).
# Wyoming 2003-2007 (Barrasso) and Nebraska 1999-2010: introduced texts read by number, kept when the first sponsor
# ("Sponsored by:" / "Introduced by Smith, 48") is the person.
# South Dakota 1997-2008: the Legislature's API (prime sponsor of a measure from the person's own chamber, checked
# against the introduced text's "Introduced by:" line). North Dakota 1997-2010 (Berg): first-named introducer in the
# House journals' first readings, checked against the introduced text's "Introduced by" line. Rhode Island
# 1997-2002 (Cicilline): texts in the General Assembly's bill text archive whose "Introduced By:" names him first.
ARCHIVE_SOURCES = [
    ("ca_state_legislation_sponsored.csv", "CA", "California Legislature"),          # local; ca_pubinfo_bills.py
    ("ca_leginfo_state_legislation_sponsored.csv", "CA", "California Legislature"),  # local; ca_leginfo_archive.py
    ("fl_state_legislation_sponsored.csv", "FL", "Florida Legislature"),             # local; fl_senate_bills.py
    ("va_state_legislation_sponsored.csv", "VA", "Virginia General Assembly"),       # local; va_lis_bills.py
    ("oh_state_legislation_sponsored.csv", "OH", "Ohio General Assembly"),           # local; oh_solar_bills.py
    ("il_state_legislation_sponsored.csv", "IL", "Illinois General Assembly"),       # local; il_ilga_bills.py
    ("mi_state_legislation_sponsored.csv", "MI", "Michigan Legislature"),            # local; mi_legislature_bills.py
    ("wv_state_legislation_sponsored.csv", "WV", "West Virginia Legislature"),       # local; wv_legislature_bills.py
    ("md_state_legislation_sponsored.csv", "MD", "Maryland General Assembly"),       # local; md_mga_bills.py
    ("pa_state_legislation_sponsored.csv", "PA", "Pennsylvania General Assembly"),   # local; pa_palegis_bills.py
    ("wa_state_legislation_sponsored.csv", "WA", "Washington Legislature"),          # local; wa_leg_bills.py
    ("nc_state_legislation_sponsored.csv", "NC", "North Carolina General Assembly"), # local; nc_ncleg_bills.py
    ("wi_state_legislation_sponsored.csv", "WI", "Wisconsin Legislature"),           # local; wi_legis_bills.py
    ("nj_state_legislation_sponsored.csv", "NJ", "New Jersey Legislature"),          # local; nj_njleg_bills.py
    ("mn_state_legislation_sponsored.csv", "MN", "Minnesota Legislature"),           # local; mn_revisor_bills.py
    ("tx_state_legislation_sponsored.csv", "TX", "Texas Legislature"),               # local; tx_ftp_bills.py
    ("la_state_legislation_sponsored.csv", "LA", "Louisiana Legislature"),           # local; la_legis_bills.py
    ("sc_state_legislation_sponsored.csv", "SC", "South Carolina Legislature"),      # local; sc_statehouse_bills.py
    ("mo_senate_state_legislation_sponsored.csv", "MO", "Missouri Senate"),           # local; mo_senate_bills.py
    ("hi_state_legislation_sponsored.csv", "HI", "Hawaii State Legislature"),        # local; hi_capitol_bills.py
    ("ky_state_legislation_sponsored.csv", "KY", "Kentucky General Assembly"),       # local; ky_record_bills.py
    ("ar_state_legislation_sponsored.csv", "AR", "Arkansas General Assembly"),       # local; ar_arkleg_bills.py
    ("ia_state_legislation_sponsored.csv", "IA", "Iowa General Assembly"),           # local; ia_legis_bills.py
    ("ak_state_legislation_sponsored.csv", "AK", "Alaska Legislature"),              # local; ak_akleg_bills.py
    ("nm_state_legislation_sponsored.csv", "NM", "New Mexico Legislature"),          # local; nm_nmlegis_bills.py
    ("nv_state_legislation_sponsored.csv", "NV", "Nevada Legislature"),              # local; nv_leg_bills.py
    ("or_state_legislation_sponsored.csv", "OR", "Oregon Legislature"),              # local; or_olis_bills.py
    ("nv_scan_state_legislation_sponsored.csv", "NV", "Nevada Legislature"),         # local; nv_leg_bills.py --scan
    ("ms_state_legislation_sponsored.csv", "MS", "Mississippi Legislature"),         # local; ms_billstatus_bills.py
    ("wy_state_legislation_sponsored.csv", "WY", "Wyoming Legislature"),             # local; wy_wyoleg_bills.py
    ("ne_state_legislation_sponsored.csv", "NE", "Nebraska Legislature"),            # local; ne_nebraskalegislature_bills.py
    ("sd_state_legislation_sponsored.csv", "SD", "South Dakota Legislature"),        # local; sd_legis_bills.py
    ("nd_state_legislation_sponsored.csv", "ND", "North Dakota Legislative Assembly"),  # local; nd_legis_bills.py
    ("ri_state_legislation_sponsored.csv", "RI", "Rhode Island General Assembly"),   # local; ri_rilegislature_bills.py
    ("ga_state_legislation_sponsored.csv", "GA", "Georgia General Assembly (Internet Archive)"),  # local; ga_wayback_bills.py
    ("ct_state_legislation_sponsored.csv", "CT", "Connecticut General Assembly"),    # local; ct_cga_bills.py
]


def archive_rows(people, skip):
    """Table 4 rows for bills from state legislatures' own archives. bill_id =
    <state>-<session>-<type><number>: CA-<session start year>-AB2027 (X<n> marks extraordinary
    sessions), FL-<session code>-HB1705 (e.g. FL-2003A-HB23 for a special session),
    VA-<LIS session code>-HB120 (e.g. VA-941-HB120, 1994 regular session), OH-GA<General
    Assembly>-HB103 (e.g. OH-GA122-HB103, 1997-1998), IL-GA<General Assembly>-SB84 (e.g.
    IL-GA90-SB84, 1997-1998), MI-<session start year>-HB4001 (e.g. MI-1989-HB4001),
    WV-<year>[<special session>]-HB2234 (e.g. WV-1997-HB2234, WV-19951X-SB3), MD-<year>-SB193 (e.g. MD-1999-SB193),
    PA-<session start year>-HB100 (e.g. PA-1969-HB100), WA-<biennium start year>-HB1441 (e.g.
    WA-1991-HB1441), NC-<session year>-H100 (e.g. NC-1995-H100),
    WI-<session year>-AB80 (e.g. WI-1995-AB80), NJ-<session year>-A42 (e.g. NJ-2000-A42),
    MN-<Legislature>-HF11 (e.g. MN-79-HF11, 1995-1996), TX-<session code>-HB1801 (e.g. TX-73R-HB1801,
    TX-781-HB3 for the 78th Legislature's first called session), LA-<session code>-HB70 (e.g. LA-97RS-HB70,
    LA-051ES-SB1 for the 2005 First Extraordinary Session), SC-<session number>-H3651 (e.g. SC-111-H3651,
    1995-1996; resolutions SC-110-SCR106, joint resolutions SC-111-SJR1040), MO-<year>-SB282 (Missouri
    Senate, e.g. MO-1999-SB282), HI-<year>-HB228 (e.g. HI-1999-HB228, HI-2003-SCR4),
    KY-<session code>-SB97 (e.g. KY-03RS-SB97, KY-09SS-HR14), AR-<session code>-SB12 (e.g. AR-1995R-SB12,
    AR-1991S1-SB42), IA-GA<General Assembly>-SF123 (e.g. IA-GA76-SF123, 1995-1996),
    AK-<Legislature>-HB77 (e.g. AK-21-HB77, 1999-2000), NM-<session code>-HB322 (e.g. NM-1997R-HB322,
    NM-2000S2-HB10), NV-69-SB209 (Nevada's 69th Session, 1997), OR-<session key>-HB2871 (e.g.
    OR-2007R1-HB2871), NV-70-SB10 (Nevada's 70th Session, 1999), MS-<session code>-SB2004 (e.g. MS-2005-SB2004,
    MS-20051E-SB2003 for the 2005 First Extraordinary Session), WY-<year>-SF0001 (e.g. WY-2005-SF0001),
    NE-<Legislature>-LB100 (e.g. NE-99-LB100, 2005-2006), SD-<year>-SB111 (e.g. SD-1997-SB111, SD-1997s-SB1
    for a special session), ND-<Legislative Assembly>-HB1263 (e.g. ND-55-HB1263, 1997), RI-<year>-H5205
    (e.g. RI-1997-H5205), GA-<session start year>-HB159 (e.g. GA-1995-HB159, 1995-1996),
    CT-<year>-SB00199 (e.g. CT-2003-SB00199). California
    1989-1992 rows are enacted bills only, in their chaptered version (text_version = Chaptered),
    with the year chaptered as year; South Carolina 1985-1990 rows are likewise enacted bills only
    (ratified acts, text_version = Enrolled), with the year ratified. Without an introduced date, year = the session's first year."""
    out = []
    for path, state, source in ARCHIVE_SOURCES:
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["BillId"] in skip or r["BioguideId"] not in people or not r["TextPath"] \
                        or not os.path.exists(r["TextPath"]) or r.get("IntroducedByMatch") == "No":
                    continue
                with open(r["TextPath"], encoding="utf-8", errors="replace") as tf:
                    text = tf.read()
                lo = int(re.search(r"(?:19|20)\d\d", r["Session"]).group(0))  # first year named in the session
                d = r["IntroducedDate"]
                if re.fullmatch(r"(19|20)\d\d-\d\d-\d\d", d or "") and lo - 2 <= int(d[:4]) <= lo + 2:
                    year, congress = int(d[:4]), congress_on(d)
                else:
                    year, congress = lo, (lo - 1787) // 2
                out.append([r["BioguideId"], people[r["BioguideId"]][0], r["BillId"], " ".join(r["Title"].split()),
                            r["Session"], str(congress), year, state, source,
                            r.get("TextVersion") or "Introduced", text])
    return out


FEDERAL_TEXT_MANIFEST = "federal_bill_text_manifest.csv"  # local; written by fetch_federal_bill_text.py


def build_table5():
    """One row per sponsored bill or resolution that has digital text (the Introduced
    version, or the earliest version Congress.gov has). Same bills as Table 7; Congress.gov
    has almost no digital text before the 101st Congress (1989). chamber = chamber of origin."""
    for path in (FEDERAL_STATUS, FEDERAL_TEXT_MANIFEST):
        if not os.path.exists(path):
            raise Pending(f"{path} missing; run the federal steps in replication/README.md")
    text_path = {}
    with open(FEDERAL_TEXT_MANIFEST, newline="", encoding="utf-8") as f:
        for m in csv.DictReader(f):
            if int(m["TextLength"] or 0) > 0 and m["TextPath"]:
                text_path[(m["Congress"], m["BillType"].lower(), m["BillNumber"])] = m["TextPath"]
    people = {p["BioguideId"]: p["Name"] for p in load_person_level()}
    skip = excluded_texts(5)
    rows = []
    with open(FEDERAL_STATUS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["ItemCategory"] != "Bill/Resolution" or r["BioguideId"] not in people:
                continue
            if f"{r['Congress']}-{r['Type'].upper()}-{r['Number']}" in skip:
                continue
            path = text_path.get((r["Congress"], r["Type"].lower(), r["Number"]))
            if not path or not os.path.exists(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as tf:
                text = tf.read()
            rows.append([r["BioguideId"], people[r["BioguideId"]],
                         f"{r['Congress']}-{r['Type'].upper()}-{r['Number']}", " ".join(r["Title"].split()),
                         str(r["Congress"]), int(r["IntroducedDate"][:4]) if r["IntroducedDate"] else None,
                         "House" if r["Type"].upper().startswith("H") else "Senate", text])
    rows.sort(key=lambda r: (r[0], int(r[4]), r[2]))
    return rows


def build_table6():
    raise Pending("method for mapping state bills to Congress.gov topics not designed yet")


FEDERAL_STATUS = "sponsored_legislation_full_status.csv"  # local; see replication/README.md step 2
LAW_STATUSES = {"Became Law", "Became Law (Veto Overridden)"}


def federal_passed(bill_type, status, latest_action):
    """'Yes' if the measure became law or, for resolutions that never go to the President,
    was adopted (decided 2026-10-07). Simple resolutions need one chamber; concurrent
    resolutions need both, so an 'agreed to' must be the second chamber's vote."""
    t = bill_type.upper()
    if t in ("HR", "S", "HJRES", "SJRES"):
        return "Yes" if status in LAW_STATUSES else "No"
    if t in ("HRES", "SRES"):
        return "Yes" if status == "Agreed To (Resolution)" else "No"
    if t in ("HCONRES", "SCONRES"):
        origin, other = ("House", "Senate") if t == "HCONRES" else ("Senate", "House")
        adopted = status == "Agreed To (Resolution)" and re.search(
            rf"agreed to in (the )?{other}|{other} agreed to|message on {other} action", latest_action, re.I)
        return "Yes" if adopted else "No"
    return "No"


def build_table7():
    """One row per sponsored bill or resolution (amendments excluded: Congress.gov gives
    them no title or policy area). topic = Congress.gov policy area (blank if none);
    passed = became law / adopted; year = year introduced; congress = Congress number."""
    if not os.path.exists(FEDERAL_STATUS):
        raise Pending(f"{FEDERAL_STATUS} missing; run the federal steps in replication/README.md")
    people = {p["BioguideId"]: p["Name"] for p in load_person_level()}
    rows = []
    with open(FEDERAL_STATUS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["ItemCategory"] != "Bill/Resolution" or r["BioguideId"] not in people:
                continue
            rows.append([r["BioguideId"], people[r["BioguideId"]],
                         f"{r['Congress']}-{r['Type'].upper()}-{r['Number']}", " ".join(r["Title"].split()),
                         str(r["Congress"]), int(r["IntroducedDate"][:4]) if r["IntroducedDate"] else None,
                         r["PolicyArea"], federal_passed(r["Type"], r["BillStatus"], r["LatestActionText"])])
    rows.sort(key=lambda r: (r[0], int(r[4]), r[2]))
    return rows


BUILDERS = {1: build_table1, 2: build_table2, 3: build_table3, 4: build_table4,
            5: build_table5, 6: build_table6, 7: build_table7}


def write(num, rows):
    import pandas as pd
    fname, cols = TABLES[num]
    df = pd.DataFrame(rows, columns=cols)
    for fmt in ("csv", "dta"):
        os.makedirs(os.path.join(DATASETS_DIR, fmt), exist_ok=True)
    df.to_csv(os.path.join(DATASETS_DIR, "csv", fname + ".csv"), index=False)
    # Long text (e.g. bill titles) as Stata strL; fixed-width str columns would pad every row
    # to the longest value. Fixed timestamp so rebuilding unchanged data gives identical files.
    long_text = [c for c in df.columns if df[c].dtype == object and df[c].astype(str).str.len().max() > 244]
    df.to_stata(os.path.join(DATASETS_DIR, "dta", fname + ".dta"), write_index=False, version=118,
                convert_strl=long_text, time_stamp=datetime.datetime(2026, 1, 1))
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
