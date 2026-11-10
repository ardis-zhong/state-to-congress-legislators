#!/usr/bin/env python3
"""
New Hampshire House and Senate bills and resolutions, 1989-2008, from the General Court's bill text
files (gencourt.state.nh.us/legislation/<year>/HB0101.html, now gc.nh.gov), read from the Internet
Archive's copies (web.archive.org), for population members who served in the General Court before
LegiScan's New Hampshire coverage. New Hampshire state-text pilot (2026-10-28).

There is one file per measure: "AS INTRODUCED" for measures that died, "FINAL VERSION" for measures
that passed (text_version Introduced / Enrolled; other printings Amended). Each prints "SPONSORS:
Rep. Bradley, Carr 5; Rep. ..., Sen. ..." (bills of intent, 1991-1994: "INTRODUCED BY: Rep. X of
Carr 5"), the prime sponsor first. The General Court has no list of past bills by sponsor, so every
archived file in the years and chambers our people served is read; files whose first sponsor is a
reviewed (year, sponsor) in replication/data/reference/nh_sponsor_names_1989_2010.csv are kept.

  --cdx      The Wayback Machine's capture index for /legislation/ (earliest capture with status 200
             of each file, saved under nh_gencourt_cache/cdx/).
  --scan     Reads every archived file in scope; logs (year, file, first sponsor) to
             nh_gencourt_cache/sponsors.tsv (resumable) and caches each page.
  --texts    Writes nh_state_legislation_sponsored.csv from the log and the reviewed names.

The live site (robots.txt Crawl-delay 11) is not used; files the archive lacks are reported, not
fetched. Polite: one request at a time, at least 4 seconds apart, a User-Agent naming the project.

USAGE (from the repo root):
    python3 replication/scripts/state/nh_gencourt_bills.py --cdx
    python3 replication/scripts/state/nh_gencourt_bills.py --scan
    python3 replication/scripts/state/nh_gencourt_bills.py --texts
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

WAYBACK = "https://web.archive.org"
CACHE = "nh_gencourt_cache"
NAMES = "replication/data/reference/nh_sponsor_names_1989_2010.csv"
TEXT_OUT = "nh_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 4
_last = [0.0]
HOUSE_TYPES = {"HB", "HBI", "HR", "HCR", "HJR", "CACR"}
SENATE_TYPES = {"SB", "SBI", "SR", "SCR", "SJR", "CACR"}
HOUSE_YEARS = range(1990, 2007)   # Bradley 1990-2002, Guinta 2000-2004, Pappas 2002-2006
SENATE_YEARS = list(range(1989, 1997)) + list(range(2005, 2011))  # Bass, Humphrey, Shaheen; Hassan; Bradley 2009-10


def fetch(url):
    """One polite request (no cache): the body as bytes, b'' for a 404, None if it keeps failing."""
    for attempt in range(5):
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
            time.sleep(60 * (attempt + 1))
        except Exception:
            time.sleep(60 * (attempt + 1))
    print(f"  could not fetch {url}", flush=True)
    return None


def cached(cache_path, make):
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()
    data = make()
    if data is None:
        return None
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(data)
    return data


def in_scope(year, kind):
    return (kind in HOUSE_TYPES and year in HOUSE_YEARS) or (kind in SENATE_TYPES and year in SENATE_YEARS)


def files():
    """[(year, KIND, number, timestamp, original URL)] for archived measure files in scope."""
    q = urllib.parse.urlencode({"url": "gencourt.state.nh.us/legislation/", "matchType": "prefix",
                                "fl": "timestamp,original", "filter": "statuscode:200", "collapse": "urlkey"})
    raw = cached(os.path.join(CACHE, "cdx", "legislation.txt"), lambda: fetch(f"{WAYBACK}/cdx/search/cdx?{q}")) or b""
    out = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        parts = line.split(" ")
        if len(parts) != 2:
            continue
        ts, orig = parts
        m = re.search(r"/legislation/((?:19|20)\d\d)/([A-Za-z]+)(\d+)\.html?$", orig)
        if not m:
            continue
        year, kind, num = int(m.group(1)), m.group(2).upper(), int(m.group(3))
        if in_scope(year, kind) and ((year, kind, num) not in out or ts < out[(year, kind, num)][0]):
            out[(year, kind, num)] = (ts, orig)
    return sorted((y, k, n, ts, o) for (y, k, n), (ts, o) in out.items())


def plain(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())


def first_sponsor(text):
    """('Rep. Bradley, Carr 5', all sponsors) from the SPONSORS: / INTRODUCED BY: line."""
    m = re.search(r"SPONSORS?:\s*(.+?)(?:\n\s*COMMITTEE:|\n\s*REFERRED TO:|\n\s*ANALYSIS|\n\s*AN ACT|$)", text[:4000], re.S)
    if not m:
        m = re.search(r"INTRODUCED BY:\s*(.+?)(?:\n\s*REFERRED TO:|\n\s*RELATING TO:|$)", text[:4000], re.S)
    if not m:
        return "", ""
    names = " ".join(m.group(1).split())
    first = re.split(r";|,\s*(?=(?:Rep|Sen)\.)", names)[0].strip()
    return first, names


def page_path(year, kind, num):
    return os.path.join(CACHE, "pages", str(year), f"{kind}{num:04d}.html")


def scan():
    log = os.path.join(CACHE, "sponsors.tsv")
    done = set()
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            done = {tuple(line.split("\t")[:3]) for line in f}
    todo = [f for f in files() if (str(f[0]), f[1], str(f[2])) not in done]
    print(f"{len(todo)} archived files to read", flush=True)
    with open(log, "a", encoding="utf-8") as out:
        for i, (year, kind, num, ts, orig) in enumerate(todo):
            raw = cached(page_path(year, kind, num), lambda: fetch(f"{WAYBACK}/web/{ts}id_/{orig}"))
            if raw is None:
                continue  # retry on the next run
            first, _ = first_sponsor(plain(raw.decode("cp1252", "replace")))
            out.write(f"{year}\t{kind}\t{num}\t{first}\n")
            out.flush()
            if i % 500 == 0:
                print(f"  {year} {kind}{num}: {i}/{len(todo)}", flush=True)


LIVE = "https://gc.nh.gov"  # the General Court's own site (robots.txt: Crawl-delay 11), same files as the archive
LIVE_YEARS = (2009, 2010)     # the archive kept only ~135 of these years' Senate files
LIVE_DELAY = 11
LIVE_LOG = os.path.join(CACHE, "sponsors_live.tsv")
LIVE_OUT = "nh_live_state_legislation_sponsored.csv"
LEGISCAN_FROM = 2010  # first New Hampshire session in LegiScan (with sponsor roles)


def live_path(year, kind, num):
    return os.path.join(CACHE, "live", str(year), f"{kind}{num:04d}.html")


def live_scan():
    """Every Senate measure of 2009-2010 read by number from gc.nh.gov (files the archive does not hold)."""
    archived = {(y, k, n) for y, k, n, _, _ in files()}
    done = set()
    if os.path.exists(LIVE_LOG):
        with open(LIVE_LOG, encoding="utf-8") as f:
            done = {tuple(line.split("\t")[:3]) for line in f}
    limits = {"SB": 700, "SR": 40, "SCR": 40, "SJR": 40, "CACR": 50}
    with open(LIVE_LOG, "a", encoding="utf-8") as out:
        for year in LIVE_YEARS:
            for kind, top in limits.items():
                misses, hit = 0, False
                for num in range(1, top + 1):
                    if (year, kind, num) in archived:
                        hit, misses = True, 0
                        continue
                    key = (str(year), kind, str(num))
                    if key not in done:
                        time.sleep(LIVE_DELAY)
                        url = f"{LIVE}/legislation/{year}/{kind}{num:04d}.html"
                        try:
                            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90) as r:
                                raw = r.read()
                        except urllib.error.HTTPError as e:
                            raw = b"" if e.code == 404 else None
                        except Exception:
                            raw = None
                        if raw is None:
                            continue  # retry on the next run
                        if raw:
                            os.makedirs(os.path.dirname(live_path(year, kind, num)), exist_ok=True)
                            with open(live_path(year, kind, num), "wb") as f:
                                f.write(raw)
                        first = first_sponsor(plain(raw.decode("cp1252", "replace")))[0] if raw else "#404"
                        out.write(f"{year}\t{kind}\t{num}\t{first}\n")
                        out.flush()
                        found = bool(raw)
                    else:
                        found = os.path.exists(live_path(year, kind, num))
                    if found:
                        hit, misses = True, 0
                    else:
                        misses += 1
                    if hit and misses >= (150 if kind == "SB" else 25):
                        break
                print(f"  live {year} {kind}: up to {num}", flush=True)


def version_of(text):
    """Printing from the status line at the top: 'FINAL VERSION' / 'VERSION ADOPTED BY BOTH BODIES' = Enrolled,
    '... AMENDED BY THE HOUSE' = Amended, 'AS INTRODUCED' or no status line (the original printing; 1989-94
    files print 'INTRODUCED BY:' on every printing, so that line says nothing) = Introduced."""
    head = " ".join(text[:300].split()).upper()
    if "FINAL VERSION" in head or "ADOPTED BY BOTH BODIES" in head:
        return "Enrolled"
    if "AMENDED" in head or "AMENDED ANALYSIS" in text[:3000]:
        return "Amended"
    return "Introduced"


def crawl_texts(live=False):
    with open(NAMES, newline="", encoding="utf-8") as f:
        reviewed = {(r["year"], r["sponsor"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    with open(LIVE_LOG if live else os.path.join(CACHE, "sponsors.tsv"), encoding="utf-8") as f:
        log = [line.rstrip("\n").split("\t") for line in f]
    path_of = live_path if live else page_path
    out = []
    for year, kind, num, first in log:
        r = reviewed.get((year, first))
        if not r or not in_scope(int(year), kind) or kind not in (HOUSE_TYPES if r["chamber"] == "H" else SENATE_TYPES):
            continue
        with open(path_of(int(year), kind, int(num)), encoding="cp1252", errors="replace") as f:
            text = plain(f.read())
        bill = f"{kind}{int(num)}"
        # a bill retained in committee from the first year of the biennium sits in the second year's folder
        # but prints its own session ('1995 SESSION'); second-year bills are numbered from 1000
        y = re.search(r"\b(\d{4}) SESSION", text[:600])
        session = y.group(1) if y and int(y.group(1)) == int(year) - 1 and int(num) < 1000 else year
        if int(session) >= LEGISCAN_FROM:
            continue  # LegiScan has New Hampshire from 2010, with sponsor roles
        t = re.search(r"\bAN ACT\b(.+?)(?:\n\s*(?:SPONSORS?:|INTRODUCED BY:|REFERRED TO:|COMMITTEE:|AMENDED ANALYSIS|ANALYSIS|STATEMENT)|$)", text[:3000], re.S) or \
            re.search(r"\b(?:A RESOLUTION|JOINT RESOLUTION|RELATING TO:)\s*(.+?)(?:\n\s*(?:SPONSORS?:|INTRODUCED BY:|REFERRED TO:|COMMITTEE:|AMENDED ANALYSIS|ANALYSIS|STATEMENT)|$)", text[:3000], re.S)
        title = " ".join(t.group(0 if t.group(0).startswith("AN ACT") else 1).split()) if t else ""
        title = re.sub(r"\s*(?:SPONSORS?:|INTRODUCED BY:|REFERRED TO:|COMMITTEE:|AMENDED ANALYSIS|ANALYSIS|STATEMENT).*$", "", title)
        _, names = first_sponsor(text)
        txt = os.path.join(CACHE, "live_texts" if live else "texts", year, f"{bill}.txt")
        os.makedirs(os.path.dirname(txt), exist_ok=True)
        with open(txt, "w", encoding="utf-8") as f:
            f.write(text)
        out.append({"BioguideId": r["bioguide_id"], "Name": r["name"], "Session": f"{session} Session",
                    "BillNumber": bill, "BillId": f"NH-{session}-{bill}", "Title": title[:300], "IntroducedDate": "",
                    "House": "HOUSE" if kind in HOUSE_TYPES - {"CACR"} or (kind == "CACR" and r["chamber"] == "H")
                    else "SENATE", "AuthorName": first, "IntroducedBy": names[:200], "IntroducedByMatch": "Yes",
                    "TextVersion": version_of(text), "TextPath": txt, "_own_folder": session == year})
    # one row per bill: a 2009 bill retained into 2010 has a file in each year's folder; keep the one in its
    # own session's folder (and, for the live files, any bill the archive output already has is skipped)
    have = set()
    if live and os.path.exists(TEXT_OUT):
        with open(TEXT_OUT, newline="", encoding="utf-8") as f:
            have = {r["BillId"] for r in csv.DictReader(f)}
    out.sort(key=lambda r: not r["_own_folder"])
    kept = []
    for r in out:
        if r["BillId"] in have:
            continue
        have.add(r["BillId"])
        del r["_own_folder"]
        kept.append(r)
    out = kept
    dest = LIVE_OUT if live else TEXT_OUT
    with open(dest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["BioguideId"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {dest}: {len(out)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdx", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--live", action="store_true", help="2009-2010 Senate files from gc.nh.gov (scan, then --texts)")
    args = ap.parse_args()
    if args.live:
        live_scan()
    if args.cdx:
        fs = files()
        print(f"{len(fs)} archived measure files in scope")
    if args.scan:
        scan()
    if args.texts:
        crawl_texts()
        if os.path.exists(LIVE_LOG):
            crawl_texts(live=True)


if __name__ == "__main__":
    main()
