#!/usr/bin/env python3
"""
Missouri Senate bills, 1996-2009, from the Missouri Senate's website (senate.mo.gov), for population
members who served in the Senate before LegiScan's Missouri coverage (2010 session on). Missouri
state-text pilot (Ardis, 2026-10-26); regular sessions. robots.txt allows these pages.

  --members  Each session's Senate bill list names every bill's sponsor (by surname, with initials
             where senators share one). Our people's entries are written as candidates for the
             reviewed list replication/data/reference/mo_senate_sponsors_1996_2009.csv.
  --lists    The reviewed (year, sponsor) pairs' bills from each session's list:
             1996-2004 /<yy>info/bil-list.htm, 2005-2009 /<yy>info/BTS_Web/BillList.aspx?SessionType=R.
  --texts    The introduced text: 1996-2004 /<yy>info/billtext/<bill>.htm links the "Introduced"
             version (HTML; it prints no sponsor, so the Senate's sponsor record stands:
             IntroducedByMatch Unavailable); 2005-2009 BillText.aspx links the introduced PDF, whose
             "INTRODUCED BY SENATOR(S) X, ..." line must name the person first. Resolutions in
             1996-2004 have no text online.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under mo_senate_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/mo_senate_bills.py --members
    python3 replication/scripts/state/mo_senate_bills.py --lists
    python3 replication/scripts/state/mo_senate_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://www.senate.mo.gov"
CACHE = "mo_senate_cache"
YEARS = range(1996, 2010)
STATIC_LAST = 2004  # 1996-2004 static pages; 2005-2009 BTS_Web
PEOPLE = "replication/data/population/person_level.csv"
NAMES = "replication/data/reference/mo_senate_sponsors_1996_2009.csv"
CANDIDATES = "mo_senate_sponsor_candidates.csv"
LIST_OUT = "mo_senate_bills.csv"
TEXT_OUT = "mo_senate_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
_last = [0.0]


def fetch(url):
    """One polite request (no cache): the body as bytes, b'' for a 404, None if it keeps failing."""
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            time.sleep(30 * (attempt + 1))
        except Exception:
            time.sleep(30 * (attempt + 1))
    print(f"  could not fetch {url}", flush=True)
    return None


def cached(cache_path, make):
    """The cached body, or make() (a fetch) written to the cache when it succeeded."""
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()
    data = make()
    if data is None:
        return b""
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(data)
    return data


def plain(s):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", s)
    t = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return " ".join(t.split())


def session_list(year):
    """[(bill, sponsor label, title, url)] for a year's regular session."""
    yy = f"{year % 100:02d}"
    if year <= STATIC_LAST:
        page = cached(os.path.join(CACHE, "lists", f"{year}.html"),
                      lambda: fetch(f"{BASE}/{yy}info/bil-list.htm")).decode("latin-1")
        out = []
        for code, typ, num, spons, title in re.findall(
                r'<a href="[^"]*bills/(\w+)\.htm\s*">\s*([A-Z]+)\s+0*(\d+)\s*</a>\s*-?\s*<a href="[^"]*members/[^"]+">'
                r'\s*\(?([^)<]*?)\)?\s*</a>\s*-\s*(.*?)<br>', page, re.S):
            folder = "bltext" if year == 1996 else "billtext"  # 1996 pages use /96info/bltext/
            out.append((f"{typ}{num}", " ".join(spons.split()), plain(title), f"/{yy}info/{folder}/{code}.htm"))
        return out
    page = cached(os.path.join(CACHE, "lists", f"{year}.html"),
                  lambda: fetch(f"{BASE}/{yy}info/BTS_Web/BillList.aspx?SessionType=R")).decode("utf-8", "replace")
    out = []
    for bid, typ, num, spons, title in re.findall(
            r'href="Bill\.aspx\?SessionType=R&amp;BillID=(\d+)"[^>]*>\s*(?:<[^>]+>\s*)*([A-Z]+)\s+(\d+)\s*(?:<[^>]+>\s*)*'
            r'-\s*(?:<[^>]+>\s*)*([^<-][^<]*?)\s*(?:<[^>]+>\s*)*-\s*(?:<[^>]+>\s*)*([^<]+)', page):
        out.append((f"{typ}{num}", " ".join(spons.split()), " ".join(title.split()),
                    f"/{yy}info/BTS_Web/BillText.aspx?SessionType=R&BillID={bid}"))
    return out


def mo_senators():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Missouri":
                continue
            s, ys = r["StateLegYears"] + " " + r["StateLegChamber"], set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d)", s):
                ys |= set(range(int(a), int(z) + 1))
            if "Senate" in r["StateLegChamber"] and ys & set(YEARS):
                r["years"] = ys
                out.append(r)
    return out


def find_members():
    rows = []
    people = mo_senators()
    for year in YEARS:
        labels = {s for _, s, _, _ in session_list(year)}
        for p in people:
            if year not in p["years"]:
                continue
            last = re.sub(r",?\s+(Jr|Sr|II|III)\.?$", "", p["Name"]).split()[-1].lower()
            for lab in sorted(labels):
                if lab.lower().split()[-1] == last:
                    rows.append({"year": year, "label": lab, "bioguide_id": p["BioguideId"], "name": p["Name"],
                                 "state_leg_years": p["StateLegYears"], "state_leg_chamber": p["StateLegChamber"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {NAMES}")


def crawl_lists():
    with open(NAMES, newline="", encoding="utf-8") as f:
        names = {(int(r["year"]), r["label"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    out = []
    for year in YEARS:
        n = 0
        for bill, spons, title, url in session_list(year):
            r = names.get((year, spons))
            if r:
                out.append({"year": year, "bioguide_id": r["bioguide_id"], "name": r["name"], "label": spons,
                            "bill": bill, "title": title, "url": url})
                n += 1
        if n:
            print(f"{year}: {n} bills", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} bills")


def static_text(page):
    """Plain lines of a 1996-2004 introduced-text page."""
    s = re.sub(r"(?i)<br\s*/?>|</p>|<p[^>]*>|</h\d>|</tr>", "\n", page)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    lines = [" ".join(l.split()) for l in s.split("\n")]
    return "\n".join(l for l in lines if l)


def pdf_text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text(x_tolerance=1.5) or "") for p in pdf.pages)


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for i, b in enumerate(bills, 1):
        year, bill = int(b["year"]), b["bill"]
        txt = os.path.join(CACHE, "texts", f"{year}_{bill}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            versions = cached(os.path.join(CACHE, "versions", f"{year}_{bill}.html"),
                              lambda: fetch(BASE + b["url"])).decode("latin-1")
            intro = re.search(r'href\s*=\s*"([^"]+)"[^>]*>\s*Introduced\b', versions, re.I)
            if intro:
                url = html.unescape(intro.group(1))
                url = url if url.startswith("http") else BASE + url
                ext = ".pdf" if url.lower().endswith(".pdf") else ".htm"
                raw = cached(os.path.join(CACHE, "intro", f"{year}_{bill}{ext}"), lambda: fetch(url))
                if ext == ".pdf" and raw[:4] == b"%PDF":
                    text = pdf_text(os.path.join(CACHE, "intro", f"{year}_{bill}{ext}"))
                elif ext == ".htm" and raw:
                    text = static_text(raw.decode("latin-1"))
            if text:
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        m = re.search(r"INTRODUCED BY SENATORS?\s+(.*?)\.\n", text)
        names = " ".join(m.group(1).split()) if m else ""
        first = re.split(r",| AND ", names)[0].strip() if names else ""
        label = b["label"]
        ok = sq(first) == sq(label) or sq(first) == sq(label.split()[-1])
        match = "" if not text else "Unavailable" if not names else "Yes" if ok else "No"
        date = re.search(r"Pre-filed (\w+ \d+, \d{4})|Read 1st time (\w+ \d+, \d{4})", text)
        if date:
            d = time.strptime(date.group(1) or date.group(2), "%B %d, %Y")
            date = time.strftime("%Y-%m-%d", d)
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{year} Regular Session",
                    "BillNumber": bill, "BillId": f"MO-{year}-{bill}", "Title": b["title"],
                    "IntroducedDate": date or "", "House": "SENATE", "AuthorName": first or label,
                    "IntroducedBy": names[:200], "IntroducedByMatch": match, "TextVersion": "Introduced",
                    "TextPath": txt if text else ""})
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
