#!/usr/bin/env python3
"""
California state bills, 1999-2008, from the Legislature's own database downloads
("pubinfo", https://downloads.leginfo.legislature.ca.gov/), for population members
who served in the California Legislature before LegiScan's coverage (2009 on).
Part of the California state-text pilot (Ardis, 2026-10-17).

Each session archive (pubinfo_1999.zip ... pubinfo_2007.zip, one per two-year
session) holds every bill, every version's text (CAML XML), the authors of each
version, and the session's legislator roster. pubinfo_1993/1995/1997.zip hold
only chaptered bills, so 1993-1998 comes from a separate step.

MATCHING (no model in the loop):
  1. Person -> roster: a population member whose researched California service
     (StateLegYears) overlaps the session is matched to the roster row with the
     same last name and first name or nickname, in the session's LEGISLATOR_TBL.
     The roster's AUTHOR_NAME is the exact string used in the authors table.
     Every match is written to replication/data/reference/ca_author_matches.csv;
     members not found in a roster are listed there as "not in roster".
  2. Bills: the person is the bill's sponsor when they are the PRIMARY lead author
     (primary_author_flg = Y; exactly one per introduced version) of the
     introduced version, in the same house as their roster row. This mirrors
     LegiScan's "Primary Sponsor" used for the rest of Table 4.
  3. Text: the introduced version's CAML XML with markup removed.

INPUT:   ca_pubinfo_cache/pubinfo_<year>.zip   (download with ca_fetch_pubinfo.sh)
OUTPUT:  ca_state_legislation_sponsored.csv     one row per (person, bill), local
         ca_billtext_cache/<bill_version_id>.txt introduced text, local
         replication/data/reference/ca_author_matches.csv   person -> roster matches

USAGE (from the repo root):
    python3 replication/scripts/state/ca_pubinfo_bills.py
"""

import csv
import html
import json
import os
import re
import sys
import unicodedata
import zipfile

CACHE = "ca_pubinfo_cache"
TEXT_DIR = "ca_billtext_cache"
SESSIONS = [1999, 2001, 2003, 2005, 2007]
PERSON_LEVEL = "replication/data/population/person_level.csv"
LEGISLATOR_FILES = ["legislators-current.json", "legislators-historical.json"]
OUT = "ca_state_legislation_sponsored.csv"
MATCHES = "replication/data/reference/ca_author_matches.csv"

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "effectiveness"))
from match_sles import NICKNAMES  # noqa: E402  (same nickname table as the SLES matching)


def norm(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def years(s):
    s = re.sub(r"\bpresent\b", "2026", s, flags=re.I)
    ys = set()
    for a, z in re.findall(r"(1[89]\d\d|20\d\d)\s*[-–]\s*(?:[A-Za-z]+\s+)?(1[89]\d\d|20\d\d|\d\d)\b", s):
        z = int(z) if len(z) == 4 else int(a[:2] + z)
        ys |= set(range(int(a), z + 1))
    for a in re.findall(r"(?<![-–\d])(1[89]\d\d|20\d\d)(?!\s*[-–])", s):
        ys.add(int(a))
    return ys


def given_names(name):
    out = {norm(name.get(k, "")) for k in ("first", "nickname", "middle") if name.get(k)}
    for g in list(out):
        out |= {norm(x) for x in NICKNAMES.get(g, [])}
        out |= {norm(k) for k, v in NICKNAMES.items() if g in [norm(x) for x in v]}
    return {g for g in out if g}


def rows(z, name):
    data = z.read(name).decode("utf-8", errors="replace")
    return [[c.strip("`") for c in line.split("\t")] for line in data.split("\n") if line.strip()]


def caml_header(xml):
    """A header like the one on California's own plain-text bill versions, built from the
    record's metadata: 'BILL NUMBER: AB 2027 / INTRODUCED BY Assembly Member Correa / date'."""
    def field(tag):
        m = re.search(rf"<caml:{tag}>(.*?)</caml:{tag}>", xml, flags=re.S)
        return html.unescape(m.group(1)).strip() if m else ""
    authors = re.search(r"<caml:Authors>(.*?)</caml:Authors>", xml, flags=re.S)
    leads = []
    for leg in re.findall(r"<caml:Legislator>(.*?)</caml:Legislator>", authors.group(1) if authors else "", flags=re.S):
        if "LEAD_AUTHOR" in leg:
            house = re.search(r"<caml:House>(.*?)</caml:House>", leg)
            name = re.search(r"<caml:Name>(.*?)</caml:Name>", leg)
            title = "Assembly Member" if house and house.group(1) == "ASSEMBLY" else "Senator"
            leads.append(f"{title} {html.unescape(name.group(1)) if name else ''}".strip())
    session = field("SessionNum")
    number = f"{field('MeasureType')} {field('MeasureNum')}" + (f" (Extraordinary Session {session})" if session not in ("", "0") else "")
    return (f"BILL NUMBER: {number}\nINTRODUCED BILL TEXT\n"
            f"INTRODUCED BY {' and '.join(leads) or 'Committee'}\n{field('ActionDate')}\n\n")


def caml_text(xml):
    """CAML XML -> plain text: keep paragraph and line breaks, drop markup."""
    header = caml_header(xml)
    xml = re.sub(r"<!--.*?-->", "", xml, flags=re.S)
    # drop the record metadata (ID, version, action history, session info, author list); keep the
    # title, the Legislative Counsel's digest, and the bill itself
    xml = re.sub(r"<caml:(Id|VersionNum|History|LegislativeInfo|Authors)\b.*?</caml:\1>", "", xml, flags=re.S)
    xml = re.sub(r"<(/?)(caml:)?(p|br|Content|Title|DigestText|Bill|BillSection|Num|ActionText|Heading)\b[^>]*>",
                 "\n", xml, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    text = re.sub(r"[ \t]+", " ", text)
    return header + re.sub(r"\n\s*\n+", "\n\n", text).strip()


def main():
    people = {}
    for path in LEGISLATOR_FILES:
        with open(path, encoding="utf-8") as f:
            for p in json.load(f):
                people[p["id"]["bioguide"]] = p
    with open(PERSON_LEVEL, newline="", encoding="utf-8") as f:
        ca = [r for r in csv.DictReader(f) if r["State"] == "California"]
    os.makedirs(TEXT_DIR, exist_ok=True)

    match_rows, out = [], []
    for year in SESSIONS:
        z = zipfile.ZipFile(os.path.join(CACHE, f"pubinfo_{year}.zip"))
        session = f"{year}-{year + 1}"
        roster = rows(z, "LEGISLATOR_TBL.dat")  # DISTRICT, SESSION_YEAR, LEGISLATOR_NAME, HOUSE_TYPE, AUTHOR_NAME, FIRST, LAST, ...
        author_key = {}  # (house, author_name) -> bioguide
        for r in ca:
            if not years(r["StateLegYears"]) & {year, year + 1}:
                continue
            nm = people[r["BioguideId"]]["name"]
            last = norm(nm["last"])
            hits = [x for x in roster
                    if (norm(x[6]) == last or last.endswith(norm(x[6])) or norm(x[6]).endswith(last))
                    and norm((x[5] or "").split()[0] if x[5] else "") in
                    given_names(nm) | {norm(r["Name"].split()[0])}]  # roster first names can include middle names
            if len(hits) == 1:
                x = hits[0]
                house = "ASSEMBLY" if x[3] == "A" else "SENATE"
                author_key[(house, x[4])] = r["BioguideId"]
                match_rows.append([r["BioguideId"], r["Name"], session, house, x[4], x[2], x[0], "matched"])
            else:
                match_rows.append([r["BioguideId"], r["Name"], session, "", "", "; ".join(x[2] for x in hits),
                                   "", "not in roster" if not hits else "ambiguous"])

        # Members who left during the session (e.g. for Congress) are missing from the end-of-session
        # roster. Fallback: an exact surname author name that no roster member uses, for a member who
        # served from the session's first year. Labelled for review in ca_author_matches.csv.
        primary_names = {(a[2], a[3]) for a in rows(z, "BILL_VERSION_AUTHORS_TBL.dat")
                         if len(a) > 9 and a[4] == "LEAD_AUTHOR" and a[9] == "Y" and a[1] == "Legislator"}
        roster_names = {("ASSEMBLY" if x[3] == "A" else "SENATE", x[4]) for x in roster}
        for m in match_rows:
            if m[2] != session or m[7] != "not in roster":
                continue
            r = next(r for r in ca if r["BioguideId"] == m[0])
            if year not in years(r["StateLegYears"]):
                continue
            last = people[m[0]]["name"]["last"]
            found = [k for k in primary_names if k[1] == last and k not in roster_names]
            if len(found) == 1:
                author_key[found[0]] = m[0]
                m[3], m[4], m[7] = found[0][0], found[0][1], "matched by surname (not in end-of-session roster; review)"

        bills = {b[0]: b for b in rows(z, "BILL_TBL.dat")}  # BILL_ID, SESSION_YEAR, SESSION_NUM, MEASURE_TYPE, MEASURE_NUM, MEASURE_STATE, ...
        versions = {v[0]: v for v in rows(z, "BILL_VERSION_TBL.dat") if v[4] == "Introduced"}
        for a in rows(z, "BILL_VERSION_AUTHORS_TBL.dat"):  # BILL_VERSION_ID, TYPE, HOUSE, NAME, CONTRIBUTION, ..., PRIMARY_AUTHOR_FLG
            if a[0] not in versions or a[4] != "LEAD_AUTHOR" or a[9] != "Y" or a[1] != "Legislator":
                continue
            bg = author_key.get((a[2], a[3]))
            if not bg:
                continue
            v = versions[a[0]]
            b = bills.get(v[1])
            if not b:
                continue
            lob = v[14]
            text_path = os.path.join(TEXT_DIR, a[0] + ".txt")
            if lob.endswith(".lob") and not os.path.exists(text_path):
                with open(text_path, "w", encoding="utf-8") as f:
                    f.write(caml_text(z.read(lob).decode("utf-8", errors="replace")))
            out.append({
                "BioguideId": bg, "Name": next(r["Name"] for r in ca if r["BioguideId"] == bg),
                "Session": session + (f" Extraordinary Session {b[2]}" if b[2] != "0" else " Regular Session"),
                "BillNumber": f"{b[3]}{b[4]}", "MeasureType": b[3], "SessionNum": b[2],
                "BillId": f"CA-{year}-{b[3]}{b[4]}" + (f"X{b[2]}" if b[2] != "0" else ""),
                "Title": v[6], "IntroducedDate": v[3][:10], "MeasureState": b[5],
                "Chaptered": "Yes" if b[5] == "Chaptered" else "No",
                "AuthorName": a[3], "House": a[2], "VersionId": a[0],
                "TextPath": text_path if os.path.exists(text_path) else "",
            })
        print(f"{session}: {sum(1 for m in match_rows if m[2] == session and m[7] == 'matched')} people matched, "
              f"{sum(1 for o in out if o['Session'].startswith(session))} primary-authored bills")

    with open(MATCHES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["bioguide_id", "name", "session", "house", "author_name", "roster_name", "district", "status"])
        w.writerows(match_rows)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {OUT}: {len(out)} rows for {len({o['BioguideId'] for o in out})} people; "
          f"{sum(1 for o in out if o['TextPath'])} with text")


if __name__ == "__main__":
    main()
