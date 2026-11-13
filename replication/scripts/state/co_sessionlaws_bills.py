#!/usr/bin/env python3
"""
Colorado enacted bills 1993-2006 from the Internet Archive's copies of the Session Laws on the state's former
website (www.state.co.us/gov_dir/leg_dir/olls/sl<year>[a]/sl.<chapter>.htm), for population members in the
General Assembly before LegiScan (Colorado from 2010) whose bills are not otherwise online: the current site
(leg.colorado.gov) has bills only from about 2014 and disallows its bill files in robots.txt, and the old
bill site (leg.state.co.us) is behind a Cloudflare challenge.

The Session Laws print every act passed in a session, one chapter per file, with its sponsors:
  'HOUSE BILL 98-1055  BY REPRESENTATIVE T. Williams; also SENATORS Dennis, Norton, ...'
The first member named is the prime sponsor in the house of origin (the other house's sponsors follow 'also').
So these rows are enacted bills only, in their enacted form (text_version = Chaptered), like California
1989-1992 and South Carolina 1985-1990. The archive kept nearly every chapter for 1993-2004 and a small share
for 2005-2006 (Cory Gardner's first House years; his 2007-2008 introduced bills come from co_wayback_bills.py).
A chapter counts when its first-named sponsor is the member: reviewed names in
replication/data/reference/co_sessionlaw_sponsors_1993_2006.csv (year, chamber H/S, sponsor = printed name,
bioguide_id, name, note); same-surname members print an initial ('T. Williams').

  --cdx    capture list of the session-law folders (cached)
  --scan   read every archived chapter -> co_sessionlaws_cache/chapters.tsv (resumable; texts cached)
  --texts  write co_sessionlaws_state_legislation_sponsored.csv

Polite: one request at a time, at least 5 seconds apart, a User-Agent naming the project.
USAGE (from the repo root):  python3 replication/scripts/state/co_sessionlaws_bills.py --cdx --scan --texts
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

WAYBACK = "https://web.archive.org"
CACHE = "co_sessionlaws_cache"
NAMES = "replication/data/reference/co_sessionlaw_sponsors_1993_2006.csv"
OUT = "co_sessionlaws_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 5
YEARS = range(1993, 2007)
_last = [0.0]


def fetch(url):
    for attempt in range(6):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r:
                data = r.read()
            if b"Temporarily Offline" in data[:3000]:
                raise IOError("archive offline")
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            time.sleep(60 * (attempt + 1))
        except Exception:
            time.sleep(60 * (attempt + 1))
    print(f"  could not fetch {url}", flush=True)
    return None


def cdx():
    path = os.path.join(CACHE, "cdx.txt")
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        url = (f"{WAYBACK}/cdx/search/cdx?url=www.state.co.us/gov_dir/leg_dir/olls/&matchType=prefix&output=txt"
               f"&collapse=urlkey&fl=original,timestamp&filter=statuscode:200&limit=200000")
        data = fetch(url).decode("utf-8", "replace")
        assert data.startswith("http"), data[:200]
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
    caps = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            p = line.split()
            m = re.search(r"/olls/sl(\d{4})a?/sl[._](\d+)\.htm$", p[0], re.I) if len(p) == 2 else None
            if m and int(m.group(1)) in YEARS:
                k = (int(m.group(1)), int(m.group(2)))
                if k not in caps or p[1] < caps[k][0]:
                    caps[k] = (p[1], p[0])
    return caps


def plain(raw):
    t = raw.decode("cp1252", "replace")
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", t).strip()


def heading(text):
    """-> (bill 'HB98-1055', chamber 'H', first sponsor 'T. Williams', title) or None."""
    flat = " ".join(text[:5000].split())
    # 'BY REPRESENTATIVES Kaufman, ...'; some headings repeat 'BY REPRESENTATIVES', print 'By', or omit 'BY'
    # from 2001 'BY REPRESENTATIVE(S) Romanoff, ..., and Williams, S.;' (initial after the surname)
    m = re.search(r"\b(HOUSE|SENATE) (BILL|JOINT RESOLUTION|CONCURRENT RESOLUTION) (\d\d)-(\d+)\b(?:\s*\[Digest\])?\s*"
                  r"(?:(?:[Bb][Yy]\s+)?(?:REPRESENTATIVES?|SENATORS?)(?:\(S\))?\s+)+"
                  r"(.+?(?:,\s*[A-Z]\.(?=[,;\s]|$))?)(?:;|,|\s+and\s|\s+AN ACT|$)", flat)
    if not m:
        return None
    kind = {"BILL": "B", "JOINT RESOLUTION": "JR", "CONCURRENT RESOLUTION": "CR"}[m.group(2)]
    t = re.search(r"\bAN ACT\s+(.+?)\.\s", flat)
    return (f"{m.group(1)[0]}{kind}{m.group(3)}-{m.group(4)}", m.group(1)[0], m.group(5).strip(),
            t.group(1)[:300] if t else "")


def scan():
    log = os.path.join(CACHE, "chapters.tsv")
    done = set()
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            done = {tuple(line.split("\t")[:2]) for line in f}
    caps = cdx()
    todo = sorted(k for k in caps if (str(k[0]), str(k[1])) not in done)
    print(f"{len(caps)} archived chapters, {len(todo)} to read", flush=True)
    with open(log, "a", encoding="utf-8") as out:
        for i, (year, ch) in enumerate(todo, 1):
            ts, url = caps[(year, ch)]
            raw = fetch(f"{WAYBACK}/web/{ts}id_/{url}")
            if raw is None:
                continue
            text = plain(raw) if raw else ""
            if text:
                p = os.path.join(CACHE, "texts", str(year), f"ch{ch:03d}.txt")
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as tf:
                    tf.write(text)
            h = heading(text) if text else None
            out.write(f"{year}\t{ch}\t" + ("\t".join(h) if h else "#none\t\t\t") + "\n")
            out.flush()
            if i % 100 == 0:
                print(f"  {year} ch {ch}: {i}/{len(todo)}", flush=True)


def texts():
    with open(NAMES, newline="", encoding="utf-8") as f:
        reviewed = {(r["year"], r["chamber"], r["sponsor"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    rows, seen = [], set()
    with open(os.path.join(CACHE, "chapters.tsv"), encoding="utf-8") as f:
        for line in f:
            year, ch, bill, chamber, sponsor, title = (line.rstrip("\n").split("\t") + [""] * 6)[:6]
            tp = os.path.join(CACHE, "texts", year, f"ch{int(ch):03d}.txt")
            if os.path.exists(tp):  # re-read the heading with the current parser
                h = heading(open(tp, encoding="utf-8").read())
                if not h:
                    continue
                bill, chamber, sponsor, title = h
            r = reviewed.get((year, chamber, sponsor))
            if not r or (year, bill) in seen:
                continue
            seen.add((year, bill))
            kind, num = re.match(r"([HS](?:B|JR|CR))\d\d-(\d+)", bill).groups()
            rows.append({"BioguideId": r["bioguide_id"], "Name": r["name"], "Session": f"{year} Regular Session",
                         "BillNumber": f"{kind}{num}", "BillId": f"CO-{year}A-{kind}{num}", "Title": title,
                         "IntroducedDate": "", "House": "HOUSE" if chamber == "H" else "SENATE",
                         "IntroducedBy": sponsor, "IntroducedByMatch": "Yes", "TextVersion": "Chaptered",
                         "Chapter": ch, "TextPath": os.path.join(CACHE, "texts", year, f"ch{int(ch):03d}.txt")})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["BioguideId", "TextPath"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(f"Wrote {OUT}: {len(rows)} rows {dict(Counter(r['Name'] for r in rows))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdx", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--texts", action="store_true")
    a = ap.parse_args()
    if a.cdx:
        print(f"{len(cdx())} chapters")
    if a.scan:
        scan()
    if a.texts:
        texts()


if __name__ == "__main__":
    main()
