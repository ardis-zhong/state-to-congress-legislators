#!/usr/bin/env python3
"""
Validate the tables in datasets/ before publishing them.

CHECKS (no network access; reads datasets/, replication/data/, and the
congress-legislators term records at the repo root):
  Every table   columns match the spec; every bioguide_id is in the population;
                no duplicate rows on the table's key; required cells not blank;
                the CSV and .dta versions hold the same rows and values.
  Table 1-2     one row per person; values from the documented sets.
  Table 3       scores >= 0; federal scores only for Congresses the person
                served in (official term records).
  Table 4       bill year inside the person's researched state-legislature
                years (+/- 1; flags possible wrong-person matches); text present.
  Table 5, 7    every bill introduced while its sponsor served in that chamber
                (official term records); year consistent with Congress;
                Table 5's bills are all in Table 7.
  Table 4, 5    the bill text names its own bill number (flags mismatched text);
                the text is not a placeholder page.

Also writes a random spot-check sample, with links to the original source
pages, to validation_sample.tsv for checking by hand.

USAGE (from the repo root):
    python3 replication/validate_tables.py            # all tables present
    python3 replication/validate_tables.py 5 7        # just these
"""

import csv
import datetime
import json
import os
import random
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_tables import TABLES, DATASETS_DIR, PERSON_LEVEL, LEGISLATOR_FILES  # noqa: E402

SAMPLE_OUT = "validation_sample.tsv"
# Rows flagged by a check, looked at by hand, and found correct (with the reason).
REVIEWED = "replication/data/reference/validation_reviewed.csv"
TYPE_NAMES = {"HR": "house-bill", "S": "senate-bill", "HRES": "house-resolution",
              "SRES": "senate-resolution", "HJRES": "house-joint-resolution",
              "SJRES": "senate-joint-resolution", "HCONRES": "house-concurrent-resolution",
              "SCONRES": "senate-concurrent-resolution"}
TYPE_TEXT = {"HR": r"H\.\s?R\.", "S": r"S\.", "HRES": r"H\.\s?RES\.", "SRES": r"S\.\s?RES\.",
             "HJRES": r"H\.\s?J\.\s?RES\.", "SJRES": r"S\.\s?J\.\s?RES\.",
             "HCONRES": r"H\.\s?CON\.\s?RES\.", "SCONRES": r"S\.\s?CON\.\s?RES\."}
KEYS = {1: ["bioguide_id"], 2: ["bioguide_id"], 3: ["bioguide_id", "session", "level", "chamber"],
        4: ["bioguide_id", "bill_id"], 5: ["bioguide_id", "bill_id"], 6: ["bioguide_id", "bill_id"],
        7: ["bioguide_id", "bill_id"]}
ALLOWED = {
    1: {"federal_chamber": {"House", "Senate", "Both"}},
    2: {"gender": {"Male", "Female"}, "veteran": {"Yes", "No", "Not found"}},
    3: {"level": {"Federal", "State"}, "chamber": {"House", "Senate", "Upper", "Lower"}},
    4: {"text_source": {"LegiScan", "California Legislature", "Florida Legislature", "Virginia General Assembly",
                         "Ohio General Assembly", "Illinois General Assembly", "Michigan Legislature",
                         "West Virginia Legislature", "Maryland General Assembly",
                         "Pennsylvania General Assembly", "Washington Legislature",
                         "North Carolina General Assembly"},
        "text_version": {"Introduced", "Prefiled", "Draft", "Amended", "Reported", "Engrossed", "Adopted", "Enrolled", "Chaptered"}},
    5: {"chamber": {"House", "Senate"}},
    7: {"passed": {"Yes", "No"}},
}

problems = []


def report(table, check, failures, total, examples=(), warn_only=False):
    status = "OK  " if not failures else ("WARN" if warn_only else "FAIL")
    print(f"  [{status}] {check}: {failures} of {total}")
    for e in list(examples)[:5]:
        print(f"           e.g. {e}")
    if failures and not warn_only:
        problems.append((table, check, failures))


def load(n, text=True):
    fname, cols = TABLES[n]
    path = os.path.join(DATASETS_DIR, "csv", fname + ".csv")
    if not os.path.exists(path):
        return None, cols
    use = None if text else [c for c in cols if c not in ("bill_text",)]
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=use), cols


def service(people_terms):
    """bioguide -> list of (type 'rep'/'sen', start date, end date)."""
    out = {}
    for bg, terms in people_terms.items():
        out[bg] = [(t["type"], datetime.date.fromisoformat(t["start"]),
                    datetime.date.fromisoformat(t["end"])) for t in terms]
    return out


def main():
    nums = [int(a) for a in sys.argv[1:]] or sorted(TABLES)
    population = {}
    with open(PERSON_LEVEL, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            population[r["BioguideId"]] = r
    terms = {}
    for path in LEGISLATOR_FILES:
        with open(path, encoding="utf-8") as f:
            for p in json.load(f):
                terms[p["id"]["bioguide"]] = p["terms"]
    serv = service(terms)
    random.seed(20261011)
    sample = []
    tables = {}

    for n in nums:
        fname, cols = TABLES[n]
        df, _ = load(n)
        if df is None:
            print(f"\nTable {n} ({fname}): not built yet, skipped")
            continue
        tables[n] = df
        print(f"\nTable {n} ({fname}): {len(df):,} rows")
        report(n, "columns match the spec", int(list(df.columns) != cols), 1, [list(df.columns)])
        bad = df[~df.bioguide_id.isin(population)]
        report(n, "bioguide_id in population", len(bad), len(df), bad.bioguide_id.head())
        dup = df[df.duplicated(KEYS[n], keep=False)]
        report(n, f"unique on {'+'.join(KEYS[n])}", len(dup), len(df), dup[KEYS[n]].head().values.tolist())
        required = [c for c in cols if c not in ("topic", "bill_name")]
        blank = df[(df[required] == "").any(axis=1)]
        report(n, "no blank required cells", len(blank), len(df),
               [(r.bioguide_id, [c for c in required if r[c] == ""]) for _, r in blank.head().iterrows()])
        for col, ok in ALLOWED.get(n, {}).items():
            bad = df[~df[col].isin(ok)]
            report(n, f"{col} in {sorted(ok)}", len(bad), len(df), bad[col].head().tolist())

        # CSV vs .dta
        dta = os.path.join(DATASETS_DIR, "dta", fname + ".dta")
        if os.path.exists(dta):
            d = pd.read_stata(dta, columns=[c for c in cols if c != "bill_text"])
            same_shape = len(d) == len(df)
            mism = 0
            if same_shape:
                for c in d.columns:
                    if pd.api.types.is_numeric_dtype(d[c]):  # compare numbers as numbers
                        a = pd.to_numeric(df[c], errors="coerce")
                        mism += int((~((a - d[c]).abs() < 1e-6) & ~(a.isna() & d[c].isna())).sum())
                    else:                                     # text exactly
                        mism += int((df[c].values != d[c].fillna("").astype(str).values).sum())
            report(n, ".dta matches the CSV (rows and values)", int(not same_shape) + mism,
                   len(df), [] if same_shape else [f"{len(d)} vs {len(df)} rows"])

        if n == 3:
            les = pd.to_numeric(df.les, errors="coerce")
            report(n, "scores are numbers >= 0", int((les.isna() | (les < 0)).sum()), len(df))
            fed = df[df.level == "Federal"]
            bad = []
            for r in fed.itertuples():
                c = int(r.session)
                lo, hi = datetime.date(1787 + 2 * c, 1, 3), datetime.date(1789 + 2 * c, 1, 3)
                typ = "rep" if r.chamber == "House" else "sen"
                if not any(t == typ and s < hi and e > lo for t, s, e in serv.get(r.bioguide_id, [])):
                    bad.append((r.bioguide_id, r.name, r.chamber, c))
            report(n, "federal score only for a Congress served in that chamber", len(bad), len(fed), bad)
            for r in df.sample(min(10, len(df))).itertuples():
                sample.append([3, r.bioguide_id, r.name, f"{r.level} {r.chamber} {r.session}", r.les,
                               "https://thelawmakers.org/data-download"])

        if n in (5, 7):
            bad, badyear = [], []
            for r in df.itertuples():
                c, typ, num = r.bill_id.split("-")
                c = int(c)
                if r.year and not (1787 + 2 * c <= int(r.year) <= 1789 + 2 * c):
                    badyear.append((r.bill_id, r.year))
                chamber = "rep" if typ.startswith("H") else "sen"
                lo, hi = datetime.date(1787 + 2 * c, 1, 1), datetime.date(1789 + 2 * c, 1, 4)
                if not any(t == chamber and s < hi and e > lo for t, s, e in serv.get(r.bioguide_id, [])):
                    bad.append((r.bioguide_id, r.name, r.bill_id))
            report(n, "sponsor served in that chamber during that Congress", len(bad), len(df), bad)
            report(n, "year falls within the bill's Congress", len(badyear), len(df), badyear)

        if n == 5 and 7 in tables or (n == 7 and 5 in tables):
            t5, t7 = tables.get(5), tables.get(7)
            if t5 is not None and t7 is not None:
                k7 = set(zip(t7.bioguide_id, t7.bill_id))
                miss = [k for k in zip(t5.bioguide_id, t5.bill_id) if k not in k7]
                report(5, "every Table 5 bill is in Table 7", len(miss), len(t5), miss)

        if n == 4:
            bad = []
            for r in df.itertuples():
                yrs = [int(y) for y in re.findall(r"(?:19|20)\d\d", population[r.bioguide_id]["StateLegYears"])]
                if re.search(r"\bpresent\b", population[r.bioguide_id]["StateLegYears"], re.I):
                    yrs.append(2026)
                if yrs and not (min(yrs) - 1 <= int(r.year) <= max(yrs) + 1):
                    bad.append((r.bioguide_id, r.name, r.bill_id, r.year,
                                population[r.bioguide_id]["StateLegYears"][:40]))
            report(n, "bill year within researched state-legislature years (+/-1)", len(bad), len(df), bad)

        if n in (4, 5):
            # placeholder pages served instead of the document (e.g. Hawaii's "only the PDF
            # version of this document is available")
            stub = [(r.bill_id, r.bill_text[:80]) for r in df.itertuples()
                    if re.search(r"only the pdf version of this document is available|"
                                 r"document (is )?not (yet )?available", r.bill_text[:500], re.I)]
            report(n, "text is not a placeholder page", len(stub), len(df), stub)

            miss = []
            for r in df.itertuples():
                text = re.sub(r"\s+", " ", r.bill_text.replace("\xa0", " ")).upper()
                if n == 5:
                    c, typ, num = r.bill_id.split("-")
                    ok = re.search(TYPE_TEXT[typ] + r"\s*" + num + r"\b", text[:3000]) is not None
                else:
                    # California archive IDs end in X<n> for extraordinary sessions (CA-1993-SB2X1)
                    number = re.sub(r"X\d+$", "", r.bill_id.split("-", 2)[2]) if r.text_source != "LegiScan" \
                        else r.bill_id.split("-", 2)[2]
                    digits = re.sub(r"\D", "", number).lstrip("0")
                    if not digits:  # lettered numbers (e.g. Michigan "HJR F") can't be checked
                        continue
                    ok = re.search(r"(?<!\d)0*" + digits + r"(?!\d)", text) is not None
                if not ok:
                    miss.append((r.bill_id, text[:80]))
            with open(REVIEWED, newline="", encoding="utf-8") as f:
                accepted = {r["bill_id"] for r in csv.DictReader(f)
                            if r["table"] == str(n) and r["check"] == "bill_number_in_text"}
            if accepted:
                n_acc = sum(1 for m in miss if m[0] in accepted)
                miss = [m for m in miss if m[0] not in accepted]
                print(f"  [info] {n_acc} flagged row(s) reviewed by hand and accepted ({REVIEWED})")
            # Many states' documents omit the number (Kentucky drafts, Indiana "No. ____",
            # NC/SC/MN layouts), so for state bills this is a warning to look at, not an error.
            report(n, "text names its own bill number", len(miss), len(df), miss, warn_only=(n == 4))

        if n in (4, 5, 7):
            for r in df.sample(min(10, len(df))).itertuples():
                if n == 4 and r.text_source == "North Carolina General Assembly":
                    _, yr, num = r.bill_id.split("-", 2)
                    url = f"https://www.ncleg.gov/BillLookUp/{yr}/{num}"
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4 and r.text_source == "Washington Legislature":
                    _, yr, num = r.bill_id.split("-", 2)
                    url = f"https://app.leg.wa.gov/billsummary?BillNumber={re.sub(r'[A-Z]', '', num)}&Year={yr}"
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4 and r.text_source == "Pennsylvania General Assembly":
                    _, yr, num = r.bill_id.split("-", 2)
                    url = f"https://www.palegis.us/legislation/bills/{yr}/{num.lower()}"
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4 and r.text_source == "Maryland General Assembly":
                    _, yr, num = r.bill_id.split("-", 2)
                    typ, digits = re.match(r"([A-Z]+)(\d+)", num).groups()
                    url = f"https://mgaleg.maryland.gov/{yr}rs/billfile/{typ.lower()}{int(digits):04d}.htm"
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4 and r.text_source == "West Virginia Legislature":
                    _, sess, num = r.bill_id.split("-", 2)
                    st, digits = sess[4:] or "RS", re.sub(r"\D", "", num)
                    url = (f"https://www.wvlegislature.gov/Bill_Status/Bills_history.cfm?input={digits}"
                           f"&year={sess[:4]}&sessiontype={st}&btype=bill")
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4 and r.text_source == "Michigan Legislature":
                    _, start, num = r.bill_id.split("-", 2)
                    typ, digits = re.match(r"([A-Z]+)(\d+)", num).groups()
                    url = f"https://www.legislature.mi.gov/Bills/Bill?ObjectName={r.year}-{typ}-{int(digits):04d}"
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4 and r.text_source == "Illinois General Assembly":
                    _, ga, num = r.bill_id.split("-", 2)
                    typ, digits = re.match(r"([A-Z]+)(\d+)", num).groups()
                    url = (f"https://www.ilga.gov/documents/legislation/legisnet{ga[2:]}/summary/{ga[2:]}0{typ}{int(digits):04d}.html"
                           if int(ga[2:]) <= 92 else f"https://ftp.ilga.gov/legislation/{ga[2:]}/BillStatus/XML/0{ga[2:]}00"
                           f"{dict(HJR='HJ', SJR='SJ', HJRCA='HC', SJRCA='SC').get(typ, typ)}{int(digits):04d}.xml")
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4 and r.text_source == "Ohio General Assembly":
                    _, ga, num = r.bill_id.split("-", 2)
                    url = f"https://www.legislature.ohio.gov/legislation/{ga[2:5]}/{num.lower()}"
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4 and r.text_source == "Virginia General Assembly":
                    _, sess, num = r.bill_id.split("-", 2)
                    url = f"https://legacylis.virginia.gov/cgi-bin/legp604.exe?{sess}+sum+{num}"
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4 and r.text_source == "Florida Legislature":
                    _, sess, num = r.bill_id.split("-", 2)
                    digits = re.sub(r"\D", "", num)
                    url = f"https://www.flsenate.gov/Session/Bill/{sess}/{digits}"
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4 and r.text_source == "California Legislature":
                    _, yr, num = r.bill_id.split("-", 2)
                    m = re.match(r"([A-Z]+?)(\d+)(?:X(\d+))?$", num)
                    if int(yr) >= 1999:
                        url = ("https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id="
                               f"{yr}{int(yr) + 1}{m.group(3) or 0}{m.group(1)}{m.group(2)}")
                    else:
                        typ = m.group(1).lower() + (f"x{m.group(3)}" if m.group(3) else "")
                        url = (f"https://www.leginfo.ca.gov/cgi-bin/postquery?bill_number={typ}_{m.group(2)}"
                               f"&sess={yr[2:]}{int(yr[2:]) + 1:02d}&house=B&author=")
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                elif n == 4:
                    st, sess, num = r.bill_id.split("-", 2)
                    url = f"https://legiscan.com/{st}/bill/{num}/{r.year}"
                    detail = f"{r.state_session}; {r.bill_name[:60]}"
                else:
                    c, typ, num = r.bill_id.split("-")
                    url = f"https://www.congress.gov/bill/{c}th-congress/{TYPE_NAMES[typ]}/{num}"
                    detail = r.bill_name[:60] + (f"; passed={r.passed}; topic={r.topic}" if n == 7 else "")
                sample.append([n, r.bioguide_id, r.name, r.bill_id, detail, url])

        if n in (1, 2):
            report(n, "one row per person in the population", abs(len(df) - len(population)), len(population))
            for r in df.sample(5).itertuples():
                sample.append([n, r.bioguide_id, r.name, " | ".join(str(x) for x in r[3:]), "",
                               f"https://bioguide.congress.gov/search/bio/{r.bioguide_id}"])

    with open(SAMPLE_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["table", "bioguide_id", "name", "item", "detail", "check_at"])
        w.writerows(sample)
    print(f"\nWrote {len(sample)} spot-check rows to {SAMPLE_OUT}")
    print("\nSUMMARY:", "all checks passed" if not problems else
          "; ".join(f"Table {t}: {c} ({k})" for t, c, k in problems))


if __name__ == "__main__":
    main()
