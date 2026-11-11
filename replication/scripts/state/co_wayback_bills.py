#!/usr/bin/env python3
"""
Colorado House bills, 2007-2008, from the Internet Archive's copies of the General Assembly's former website
(www.leg.state.co.us/clics/clics<year>a/csl.nsf/...), for population members in the Colorado House before
LegiScan's Colorado coverage (2009 on). The old site is now behind a Cloudflare challenge (not used), and the
current site has bills from about 2014 on only.

The archive kept the bill PDFs for the 2007 and 2008 sessions (about 220 of each year's roughly 400 House
bills as introduced; almost nothing before 2007). The introduced version is the file <number>_01.pdf; its
first page prints "HOUSE BILL 07-1063 / BY REPRESENTATIVE(S) Gardner C., Lambert, ...; also SENATOR(S) ...",
the prime sponsor first. Every archived House introduced PDF is read; rows are kept when the first House
sponsor is a reviewed (year, name) in replication/data/reference/co_sponsor_names_2007_2008.csv (e.g.
"Gardner C." = Cory Gardner; "Gardner B." is Bob Gardner).

  --cdx    capture index for each session (cached under co_wayback_cache/cdx/)
  --scan   reads every House introduced PDF (earliest capture); logs (year, bill, first sponsor) to
           co_wayback_cache/sponsors.tsv (resumable) and keeps the texts
  --texts  writes co_state_legislation_sponsored.csv from the log and the reviewed names

Polite: one request at a time, at least 5 seconds apart, a User-Agent naming the project.
USAGE (from the repo root):  python3 replication/scripts/state/co_wayback_bills.py --cdx --scan --texts
"""

import argparse
import csv
import io
import os
import re
import time
import urllib.error
import urllib.request

WAYBACK = "https://web.archive.org"
CACHE = "co_wayback_cache"
NAMES = "replication/data/reference/co_sponsor_names_2007_2008.csv"
TEXT_OUT = "co_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 5
YEARS = (2007, 2008)
FILE = re.compile(r"/\$FILE/(1\d{3})_01\.pdf$", re.I)   # House bills are numbered 1001 on
_last = [0.0]


def fetch(url):
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


def cdx(year):
    path = os.path.join(CACHE, "cdx", f"{year}.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return [line.split(" ") for line in f.read().splitlines() if line]
    lines = []
    for host in ("www.leg.state.co.us", "leg.state.co.us"):
        url = (f"{WAYBACK}/cdx/search/cdx?url={host}/clics/clics{year}a/csl.nsf/*&output=txt&fl=timestamp,original"
               f"&filter=statuscode:200&filter=mimetype:application/pdf&limit=50000")
        raw = fetch(url)
        if raw is None or b"Temporarily Offline" in raw or b"<html" in raw[:200].lower():
            raise SystemExit("capture index unavailable; retry later")
        lines += [line.split(" ") for line in raw.decode("utf-8", "replace").splitlines() if line]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(" ".join(x) for x in lines) + "\n")
    return lines


def files():
    """{(year, number): (timestamp, url)}: the earliest capture of each House bill's introduced PDF."""
    best = {}
    for year in YEARS:
        for ts, orig in cdx(year):
            m = FILE.search(orig)
            if m:
                key = (year, int(m.group(1)))
                if key not in best or ts < best[key][0]:
                    best[key] = (ts, orig)
    return best


def pdf_text(data):
    from pdfminer.high_level import extract_text
    try:
        return extract_text(io.BytesIO(data)) or ""
    except Exception:
        return ""


def first_sponsor(text):
    """The prime House sponsor. The PDFs' text layer prints the sponsor names between the bill number and the
    'HOUSE SPONSORSHIP' label ('HOUSE BILL 07-1001 / Marshall, / Fitz-Gerald, / HOUSE SPONSORSHIP / SENATE
    SPONSORSHIP'), House sponsors first; others print them after the label ('HOUSE SPONSORSHIP Gibbs, Witwer,
    ...'); some copies print 'BY REPRESENTATIVE(S) Gardner C., ...' instead."""
    flat = " ".join(text[:4000].split())
    m = re.search(r"HOUSE BILL \d\d-\d{4}\s+HOUSE SPONSORSHIP\s+(.+?)\s+(?:SENATE SPONSORSHIP|House Committees)", flat) or \
        re.search(r"HOUSE BILL \d\d-\d{4}\s+(.+?)\s+HOUSE SPONSORSHIP", flat) or \
        re.search(r"BY REPRESENTATIVES?\(?S?\)?\s+(.+?)(?:;|\s+also\s+SENATOR|\s+A BILL FOR|$)", flat)
    if not m:
        return "", ""
    names = m.group(1)
    return re.split(r",|\s+and\s+", names)[0].strip(), names[:300]


def reparse():
    """Rewrite the log's sponsor columns from the saved texts (after a parser change)."""
    log = os.path.join(CACHE, "sponsors.tsv")
    with open(log, encoding="utf-8") as f:
        rows = [line.rstrip("\n").split("\t") for line in f]
    out = []
    for year, num, ts, orig, *_ in rows:
        p = os.path.join(CACHE, "texts", year, f"HB{num}.txt")
        text = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        first, names = first_sponsor(text)
        out.append(f"{year}\t{num}\t{ts}\t{orig}\t{first}\t{names}\n")
    with open(log, "w", encoding="utf-8") as f:
        f.writelines(out)
    print(f"reparsed {len(out)} log rows")


def scan():
    log = os.path.join(CACHE, "sponsors.tsv")
    done = set()
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            done = {tuple(line.split("\t")[:2]) for line in f}
    todo = sorted((k, v) for k, v in files().items() if (str(k[0]), str(k[1])) not in done)
    print(f"{len(todo)} archived House introduced PDFs to read", flush=True)
    with open(log, "a", encoding="utf-8") as out:
        for i, ((year, num), (ts, orig)) in enumerate(todo, 1):
            raw = fetch(f"{WAYBACK}/web/{ts}id_/{orig}")
            if raw is None:
                continue
            text = pdf_text(raw) if raw[:4] == b"%PDF" else ""
            if text:
                p = os.path.join(CACHE, "texts", str(year), f"HB{num}.txt")
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text)
            first, names = first_sponsor(text)
            out.write(f"{year}\t{num}\t{ts}\t{orig}\t{first}\t{names}\n")
            out.flush()
            if i % 50 == 0:
                print(f"  {year} HB{num}: {i}/{len(todo)}", flush=True)


def crawl_texts():
    with open(NAMES, newline="", encoding="utf-8") as f:
        reviewed = {(r["year"], r["sponsor"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    out = []
    with open(os.path.join(CACHE, "sponsors.tsv"), encoding="utf-8") as f:
        for line in f:
            year, num, ts, orig, first, names = line.rstrip("\n").split("\t")
            r = reviewed.get((year, first))
            p = os.path.join(CACHE, "texts", year, f"HB{num}.txt")
            if not r or not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as tf:
                text = tf.read()
            # the title runs from 'A BILL FOR AN ACT' to 'Bill Summary', with the printed line numbers in between
            # some text layers print the title above 'A BILL FOR AN ACT' instead of below it
            t = re.search(r"A BILL FOR AN ACT\s+(CONCERNING.+?)\s+Bill Summary", re.sub(r"(?m)^\s*\d{3}\s*$", "", text), re.S) or \
                re.search(r"(CONCERNING.+?)\s+A BILL FOR AN ACT", text, re.S)
            out.append({"BioguideId": r["bioguide_id"], "Name": r["name"], "Session": f"{year} Regular Session",
                        "BillNumber": f"HB{num}", "BillId": f"CO-{year}A-HB{num}",
                        "Title": " ".join(t.group(1).split())[:300] if t else "", "IntroducedDate": "",
                        "House": "HOUSE", "AuthorName": first, "IntroducedBy": names[:200], "IntroducedByMatch": "Yes",
                        "TextVersion": "Introduced", "TextPath": p, "ArchivedPage": f"{orig} ({ts})"})
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["BioguideId"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdx", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--reparse", action="store_true", help="re-read the saved texts into the log")
    a = ap.parse_args()
    if a.reparse:
        reparse()
    if a.cdx:
        print(f"{len(files())} archived House introduced PDFs in scope")
    if a.scan:
        scan()
    if a.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
