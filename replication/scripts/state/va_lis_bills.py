#!/usr/bin/env python3
"""
Virginia state bills, 1994-2009, from the General Assembly's legacy Legislative Information
System (legacylis.virginia.gov), for population members who served in the General Assembly
before LegiScan's Virginia coverage (2010 on). Virginia state-text pilot (Ardis, 2026-10-19).
(LIS's newer API is not used: the General Assembly has not authorized extracting pre-2025
session data through it. The legacy site's robots.txt allows all robots.)

STEP 1 (--lists):
  - each session's member list (/<code>/mbr/MBR.HTM; code = 2-digit year + session number,
    e.g. 941 = 1994 regular session, 982 = 1998 special session I);
  - our people are matched to members by last name plus first, middle or nickname, among
    members of a session the person served in (researched StateLegYears); every match is
    written to replication/data/reference/va_member_matches.csv for review;
  - each matched member's "Legislation as Chief Patron" list (<code>+mbr+<id>C).
  Output: va_chief_patron_bills.csv.
STEP 2 (--texts): each bill's introduced text (<code>+ful+<bill>, the unsuffixed version),
  checked for "Patron--<surname>" naming our person first. Output: va_state_legislation_sponsored.csv.

Polite crawling: one request at a time, at least 3 seconds apart, a User-Agent naming the
project, and every response cached under va_lis_cache/ so a re-run only fetches what is missing.

USAGE (from the repo root):
    python3 replication/scripts/state/va_lis_bills.py --lists
    python3 replication/scripts/state/va_lis_bills.py --texts
"""

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

BASE = "https://legacylis.virginia.gov"
CACHE = "va_lis_cache"
FIRST_YEAR, LAST_YEAR = 1994, 2009
PERSON_LEVEL = "replication/data/population/person_level.csv"
LEGISLATOR_FILES = ["legislators-current.json", "legislators-historical.json"]
MATCHES = "replication/data/reference/va_member_matches.csv"
LIST_OUT = "va_chief_patron_bills.csv"
TEXT_OUT = "va_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 3
_last = [0.0]

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "effectiveness"))
from match_sles import NICKNAMES  # noqa: E402
NICKNAMES = dict(NICKNAMES, ben="benjamin")  # e.g. Ben Cline is "Benjamin L. Cline" in the member lists


def get(path, cache_path):
    """Fetch BASE+path once (cached). Returns the text, or '' for a 404."""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="latin-1") as f:
            return f.read()
    for attempt in range(5):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"User-Agent": UA}),
                                        timeout=90) as r:
                data = r.read().decode("latin-1")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = ""
                break
            time.sleep(20 * (attempt + 1))
        except Exception:
            time.sleep(20 * (attempt + 1))
    else:
        raise SystemExit(f"giving up on {path}")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="latin-1") as f:
        f.write(data)
    return data


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


def sessions():
    """Session codes that exist, 1994-2009: <yy>1 regular, <yy>2/<yy>3 special sessions."""
    out = []
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        for n in (1, 2, 3):
            code = f"{y % 100:02d}{n}"
            page = get(f"/{code}/mbr/MBR.HTM", os.path.join(CACHE, "members", f"{code}.html"))
            if re.search(r"\+mbr\+[HS]\d+", page):
                out.append((y, code))
            elif n > 1:
                break
    return out


def crawl_lists():
    people = {}
    for path in LEGISLATOR_FILES:
        with open(path, encoding="utf-8") as f:
            for p in json.load(f):
                people[p["id"]["bioguide"]] = p["name"]
    with open(PERSON_LEVEL, newline="", encoding="utf-8") as f:
        va = [r for r in csv.DictReader(f) if r["State"] == "Virginia"]
    matches, bills = [], []
    for year, code in sessions():
        page = get(f"/{code}/mbr/MBR.HTM", os.path.join(CACHE, "members", f"{code}.html"))
        members = re.findall(r'(\d{3})\+mbr\+([HS]\d+)"[^>]*>([^<]+)<', page)
        for r in va:
            # some researched rows give the years only in StateLegChamber (e.g. McEachin's House stints)
            if year not in years(r["StateLegYears"] + " " + r["StateLegChamber"]):
                continue
            nm = people[r["BioguideId"]]
            given = {norm(nm.get(k, "")) for k in ("first", "middle", "nickname") if nm.get(k)}
            given |= {norm(r["Name"].split()[0])}
            given |= {norm(x) for g in list(given) for x in ([NICKNAMES[g]] if isinstance(NICKNAMES.get(g), str) else NICKNAMES.get(g, []))}
            last = norm(nm["last"])
            hits = []
            for _, mid, full in members:
                toks = [t for t in re.split(r"[\s,.]+", html.unescape(full)) if t and t not in ("Jr", "Sr", "II", "III", "IV")]
                if toks and norm(toks[-1]) == last and any(norm(t) in given for t in toks[:-1]):
                    hits.append((mid, html.unescape(full).strip()))
            status = "matched" if len(hits) == 1 else ("not in member list" if not hits else "ambiguous")
            matches.append([r["BioguideId"], r["Name"], year, code, hits[0][0] if len(hits) == 1 else "",
                            "; ".join(h[1] for h in hits), status])
            if len(hits) == 1:
                mid = hits[0][0]
                chief = get(f"/cgi-bin/legp604.exe?{code}+mbr+{mid}C",
                            os.path.join(CACHE, "chief", f"{code}_{mid}.html"))
                for b, title in re.findall(rf'legp604\.exe\?{code}\+sum\+([A-Z]+\d+)"?[^>]*>[^<]*?([^<]*)</a>', chief):
                    bills.append({"bioguide_id": r["BioguideId"], "name": r["Name"], "year": year, "session": code,
                                  "member_id": mid, "bill": b,
                                  "title": re.sub(r"^[A-Z]+\s*\d+\s+", "", " ".join(title.split()))})
        print(f"{code}: {sum(1 for m in matches if m[3] == code and m[6] == 'matched')} people matched, "
              f"{sum(1 for b in bills if b['session'] == code)} chief-patron bills", flush=True)
    with open(MATCHES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["bioguide_id", "name", "year", "session_code", "member_id", "member_name", "status"])
        w.writerows(matches)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bioguide_id", "name", "year", "session", "member_id", "bill", "title"],
                           lineterminator="\n")
        w.writeheader()
        w.writerows(bills)
    print(f"Wrote {LIST_OUT}: {len(bills)} bills for {len({b['bioguide_id'] for b in bills})} people")


def bill_text(page):
    """The introduced-text page -> the bill text (from the LD/bill heading to the end of the bill)."""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", page)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>|</tr>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).replace("\xa0", " ")
    lines = [ln.strip() for ln in t.split("\n")]
    start = next((i for i, ln in enumerate(lines) if ln.lower() == "print version"), None)
    lines = lines[start + 1:] if start is not None else lines
    end = next((i for i, ln in enumerate(lines) if ln.startswith(("LIS Home", "Legislative Information System"))
                or "Division of Legislative Automated Systems" in ln), len(lines))
    text = "\n".join(lines[:end])
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    names = {}
    for path in LEGISLATOR_FILES:
        with open(path, encoding="utf-8") as f:
            for p in json.load(f):
                names[p["id"]["bioguide"]] = p["name"]["last"]
    out = []
    for i, b in enumerate(bills, 1):
        page = get(f"/cgi-bin/legp604.exe?{b['session']}+ful+{b['bill']}",
                   os.path.join(CACHE, "texts", f"{b['session']}_{b['bill']}.html"))
        text = bill_text(page) if page else ""
        pat = re.search(r"Patrons?[^A-Za-z\n]*([A-Z][^\n]+)", text)  # the dashes are sometimes another character
        first = re.split(r",|\band\b|;", pat.group(1))[0].strip() if pat else ""
        last = names[b["bioguide_id"]]
        match = "Yes" if norm(last) and norm(last) in norm(first) else ("No" if pat else "Unavailable")
        offered = re.search(r"Offered\s+([A-Z][a-z]+ \d{1,2}, \d{4})", text)
        date = time.strftime("%Y-%m-%d", time.strptime(offered.group(1), "%B %d, %Y")) if offered else ""
        text_path = ""
        if text:
            text_path = os.path.join(CACHE, "texts", f"{b['session']}_{b['bill']}.txt")
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text)
        y, code = int(b["year"]), b["session"]
        session = f"{y} Regular Session" if code.endswith("1") else f"{y} Special Session {'I' * (int(code[-1]) - 1)}"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": session,
                    "BillNumber": b["bill"], "BillId": f"VA-{code}-{b['bill']}", "Title": b["title"],
                    "IntroducedDate": date, "House": "HOUSE" if b["member_id"].startswith("H") else "SENATE",
                    "AuthorName": first, "IntroducedByMatch": match, "TextVersion": "Introduced",
                    "TextPath": text_path})
        if i % 100 == 0:
            print(f"  ...{i}/{len(bills)}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; patron check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
