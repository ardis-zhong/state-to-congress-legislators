#!/usr/bin/env python3
"""
Michigan state bills, 1989-2008, from the Michigan Legislature's website
(legislature.mi.gov), for population members who served in the Legislature before
LegiScan's Michigan coverage (2009 on). Michigan state-text pilot (Ardis, 2026-10-21).

  --members  Each session's "Browse Bills by Sponsor" page (/Bills/SearchBySponsor?session=...)
             lists the session's sponsors (one list per chamber); our people's entries are
             written as candidates for the reviewed list
             replication/data/reference/mi_sponsor_names_1989_2008.csv.
  --lists    For each reviewed (session, chamber, sponsor) the bills on which the person is the
             primary sponsor: /Search/ExecuteSearch?sessions=...&docTypes=<House|Senate> Bill
             &sponsorTypesList=primary&sponsor=<name>.
  --texts    Each bill as introduced: /documents/<session>/billintroduced/<House|Senate>/htm/
             <year>-<H|S>IB-<number>.htm (1997 on), else the .pdf (before 1997 the Library of
             Michigan's copies, text layer read with pdfplumber). The text's first line names
             who introduced the bill ("Introduced by Rep. Terrell", "Introduced by Senators
             ROGERS, SCHUETTE, ..."); IntroducedByMatch says whether the first member named is
             the person. A few bills (e.g. some 1997-1998 ones) have no introduced copy; then the
             first engrossed (else enrolled) version on the bill page is used, and TextVersion says so.

The Legislature's Automated Data Collection Policy permits automated collection at up to one
request per second; this script waits 2 seconds between requests, sends a User-Agent naming
the project, and caches every response under mi_legislature_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/mi_legislature_bills.py --members
    python3 replication/scripts/state/mi_legislature_bills.py --lists
    python3 replication/scripts/state/mi_legislature_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.legislature.mi.gov"
CACHE = "mi_legislature_cache"
SESSIONS = [f"{y}-{y + 1}" for y in range(1989, 2008, 2)]
PEOPLE = "replication/data/population/person_level.csv"
NAMES = "replication/data/reference/mi_sponsor_names_1989_2008.csv"
CANDIDATES = "mi_sponsor_name_candidates.csv"
LIST_OUT = "mi_primary_sponsor_bills.csv"
TEXT_OUT = "mi_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
_last = [0.0]


def get(path, cache_path, binary=False):
    """Fetch BASE+path once (cached). Returns the body, or empty for a 404."""
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            data = f.read()
        return data if binary else data.decode("utf-8", errors="replace")
    for attempt in range(5):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"User-Agent": UA}),
                                        timeout=120) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = b""
                break
            time.sleep(30 * (attempt + 1))
        except Exception:
            time.sleep(30 * (attempt + 1))
    else:
        raise SystemExit(f"giving up on {path}")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(data)
    return data if binary else data.decode("utf-8", errors="replace")


def plain(s):
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def pdf_text(path):
    import logging
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages).strip()
    except Exception:
        return ""


def mi_people():
    """Population members with Michigan Legislature service in 1989-2008."""
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Michigan":
                continue
            ys = set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d|present)", r["StateLegYears"]):
                ys |= set(range(int(a), (2026 if z == "present" else int(z)) + 1))
            ys |= {int(y) for y in re.findall(r"(?:19|20)\d\d", r["StateLegYears"])}
            if any(1989 <= y <= 2008 for y in ys):
                out.append(r)
    return out


def sponsor_lists(session):
    """{chamber: [sponsor value, ...]} from the session's Browse Bills by Sponsor page."""
    page = get(f"/Bills/SearchBySponsor?session={session}", os.path.join(CACHE, "sponsors", f"{session}.html"))
    out = {}
    for form in re.findall(r"(?is)<form[^>]*ExecuteSearch.*?</form>", page):
        doc = re.search(r'name="docTypes" value="(House|Senate) Bill"', form)
        if doc:
            out[doc.group(1)] = [html.unescape(v) for v in re.findall(r'<option[^>]*value="([^"]*)"', form)]
    return out


def find_members():
    people = mi_people()
    rows = []
    for session in SESSIONS:
        for chamber, names in sponsor_lists(session).items():
            for p in people:
                last = p["Name"].replace('"', "").split()[-1].lower()
                for n in names:
                    if re.search(rf"\b{re.escape(last)}\b", n.lower().replace(".", ". ")):
                        rows.append({"session": session, "chamber": chamber, "sponsor": n,
                                     "bioguide_id": p["BioguideId"], "name": p["Name"],
                                     "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates for {len(people)} people; review into {NAMES}")


def crawl_lists():
    with open(NAMES, newline="", encoding="utf-8") as f:
        names = list(csv.DictReader(f))
    out = []
    for n in names:
        q = urllib.parse.urlencode({"sessions": n["session"], "docTypes": f"{n['chamber']} Bill",
                                    "sponsorTypesList": "primary", "sponsor": n["sponsor"]})
        page = get(f"/Search/ExecuteSearch?{q}",
                   os.path.join(CACHE, "lists", f"{n['session']}_{n['chamber']}_{re.sub(r'[^A-Za-z]', '', n['sponsor'])}.html"))
        found = re.search(r"\((\d+) results found\)", page)
        bills = []
        for row in re.findall(r"(?is)<tr>(.*?)</tr>", page):
            m = re.search(r"objectName=(\d{4})-([HS]B)-(\d{4})\s*\"", row)
            cells = re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)
            if not m or len(cells) < 3:
                continue
            year, typ, num = m.groups()
            # the description cell: subject line, then what it amends, then "Last Action"
            title = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", cells[2].split("Last Action")[0])).split())
            bills.append({"session": n["session"], "bioguide_id": n["bioguide_id"], "name": n["name"],
                          "chamber": n["chamber"], "sponsor": n["sponsor"], "year": year, "type": typ,
                          "number": int(num), "title": title[:300]})
        seen = {(b["year"], b["type"], b["number"]) for b in bills}
        if found and int(found.group(1)) != len(seen):
            print(f"  WARNING {n['session']} {n['sponsor']}: {found.group(1)} results, {len(seen)} parsed")
        out.extend(bills)
        print(f"{n['session']} {n['chamber']} {n['sponsor']}: {len(bills)} bills", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} bills")


MONTHS = {m: i for i, m in enumerate("january february march april may june july august september october "
                                     "november december".split(), 1)}


def squash(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def introduced_line(text):
    """(ISO date, names as printed, squashed names) from the text's opening line, e.g. 'January 31,
    1995, Introduced by Senators ROGERS, SCHUETTE, ... and referred to ...'. Matching runs on the text
    with spaces and punctuation removed, because some scanned pre-1997 copies are letter-spaced
    ('In tro d u ced by S en ato r PETERS')."""
    head = squash(text[:3000])
    m = re.search(r"introducedby(?:representatives?|reps?|senators?|sen)(.*?)(?:and)?(?:referred|enrolled)", head)
    if not m:
        return "", "", ""
    d = re.search(r"(" + "|".join(MONTHS) + r")([0-9li]{1,2})(\d{4})introducedby", head)  # OCR can garble it
    iso = f"{d.group(3)}-{MONTHS[d.group(1)]:02d}-{int(d.group(2).replace('l', '1').replace('i', '1')):02d}" if d else ""
    spaced = re.search(r"Introduced\s+by\s+(?:Reps?\.|Representatives?|Senators?|Sen\.)\s+(.*?)\s+(?:and\s+)?referred",
                       text[:3000], flags=re.S | re.I)
    return iso, " ".join(spaced.group(1).split())[:200] if spaced else "", m.group(1)


def first_named(names_sq, surname):
    """Yes when the first member named is the person: the squashed name list starts with the
    surname, after at most two initials (e.g. 'nsmith' for 'N. SMITH'), allowing one OCR error
    in older scans ('Stunak' for Stupak)."""
    import difflib
    sur = squash(surname)
    for skip in (0, 1, 2):
        head = names_sq[skip:skip + len(sur)]
        if head == sur or (len(sur) >= 5 and difflib.SequenceMatcher(None, head, sur).ratio() >= 0.8):
            return True
    return False


VERSION_DIRS = [("billengrossed", "Engrossed"), ("billenrolled", "Enrolled")]


def earliest_other_version(s, year, typ, num):
    """When the session has no introduced copy of a bill (e.g. some 1997-1998 bills), the first
    engrossed or else enrolled version listed on its bill page: (text, version)."""
    page = get(f"/Bills/Bill?ObjectName={year}-{typ}-{num:04d}", os.path.join(CACHE, "bills", f"{year}-{typ}-{num:04d}.html"))
    for folder, version in VERSION_DIRS:
        links = re.findall(rf"href=\"?(/documents/{s}/{folder}/[^\"\s>]+\.(?:htm|pdf))", page)
        for link in sorted(links, key=lambda l: not l.endswith(".htm")):
            local = os.path.join(CACHE, "texts", os.path.basename(link))
            if link.endswith(".htm"):
                body = get(link, local)
                text = plain(body) if body else ""
            else:
                text = pdf_text(local) if get(link, local, binary=True) else ""
            if text:
                return text, version
    return "", ""


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        s, year, typ, num = b["session"], b["year"], b["type"], int(b["number"])
        house = "House" if typ == "HB" else "Senate"
        stem = f"{year}-{typ[0]}IB-{num:04d}"
        text, version = "", "Introduced"
        txt_path = os.path.join(CACHE, "texts", f"{stem}.txt")
        if os.path.exists(txt_path):
            with open(txt_path, encoding="utf-8") as f:
                text = f.read()
        if not text and int(year) >= 1997:
            page = get(f"/documents/{s}/billintroduced/{house}/htm/{stem}.htm", os.path.join(CACHE, "texts", f"{stem}.htm"))
            text = plain(page) if page else ""
        if not text or (int(year) >= 1997 and not introduced_line(text)[2]):
            # no .htm, or an .htm without the "Introduced by" line (some 1999-2002 copies): the .pdf
            pdf_path = os.path.join(CACHE, "texts", f"{stem}.pdf")
            if get(f"/documents/{s}/billintroduced/{house}/pdf/{stem}.pdf", pdf_path, binary=True):
                pdf = pdf_text(pdf_path)
                if pdf and (not text or introduced_line(pdf)[2]):
                    text = pdf
        if text:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            text, version = earliest_other_version(s, year, typ, num)
            if text:
                txt_path = os.path.join(CACHE, "texts", f"{stem}_{version.lower()}.txt")
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(text)
        iso, names, names_sq = introduced_line(text)
        surname = b["name"].replace('"', "").split()[-1]
        if not text:
            match = ""
        elif not names_sq:
            match = "Unavailable"
        else:
            match = "Yes" if first_named(names_sq, surname) else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{s} Regular Session",
                    "BillNumber": f"{typ}{num}", "BillId": f"MI-{s[:4]}-{typ}{num}", "Title": b["title"],
                    "IntroducedDate": iso, "House": house.upper(), "AuthorName": b["sponsor"],
                    "IntroducedBy": names or names_sq[:200], "IntroducedByMatch": match,
                    "TextVersion": version, "TextPath": txt_path if text else ""})
        if i % 100 == 0:
            print(f"  ...{i}/{len(bills)}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--members", action="store_true")
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N bills (smoke test)")
    args = ap.parse_args()
    if args.members:
        find_members()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
