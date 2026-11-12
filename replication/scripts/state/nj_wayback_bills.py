#!/usr/bin/env python3
"""
New Jersey bills 1996-1999 from the Internet Archive's copies of the Legislature's former website
(www.njleg.state.nj.us/9697/Bills/..., /9899/Bills/...). The Legislature's current site has data only from the
2000-01 session (nj_njleg_bills.py), and the archive kept only a small share of the earlier introduced texts
(about 15 for 1996-97 and 333 for 1998-99), so these rows are a sample.

Every archived introduced text (<number>_i1.htm) is read; its 'Sponsored by:' block lists the prime sponsors,
first named first ('Assemblyman PAUL DIGAETANO District 36 ...'). A bill counts when the first prime sponsor is
one of the population members serving then (reviewed list below, matched on the printed name and chamber).

  --scan   reads every archived introduced text -> nj_wayback_cache/sponsors.tsv (resumable)
  --texts  writes nj_wayback_state_legislation_sponsored.csv for reviewed sponsors

Polite: one request at a time, at least 5 seconds apart, a User-Agent naming the project.
USAGE (from the repo root):  python3 replication/scripts/state/nj_wayback_bills.py --scan --texts
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.request

WAYBACK = "https://web.archive.org"
CACHE = "nj_wayback_cache"
OUT = "nj_wayback_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 5
SESSIONS = {"9697": 1996, "9899": 1998}
# printed first-sponsor name (upper case, title word dropped) -> (bioguide, name, chamber). Reviewed against the
# members serving 1996-1999: Adler (Senate 1992-2009), Garrett (Assembly 1990-2003), Lance (Assembly 1991-2002),
# Pascrell (Assembly to 1997), Pou (Assembly 1997-), Conaway and Watson Coleman (Assembly 1998-).
NAMES = {
    "JOHN H. ADLER": ("A000364", "John Adler", "S"),
    "SCOTT GARRETT": ("G000548", "Scott Garrett", "A"),
    "E. SCOTT GARRETT": ("G000548", "Scott Garrett", "A"),
    "LEONARD LANCE": ("L000567", "Leonard Lance", "A"),
    "WILLIAM J. PASCRELL, JR.": ("P000096", "Bill Pascrell", "A"),
    "WILLIAM J. PASCRELL": ("P000096", "Bill Pascrell", "A"),
    "NELLIE POU": ("P000621", "Nellie Pou", "A"),
    "HERB CONAWAY, JR.": ("C001136", "Herb Conaway", "A"),
    "HERB CONAWAY": ("C001136", "Herb Conaway", "A"),
    "BONNIE WATSON COLEMAN": ("W000822", "Bonnie Watson Coleman", "A"),
}
_last = [0.0]


def fetch(url):
    for attempt in range(5):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
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


def plain(raw):
    t = raw.decode("cp1252", "replace")
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", t).strip()


def captures():
    """(session, house, number) -> (timestamp, url) of the earliest archived introduced HTML."""
    out = {}
    with open(os.path.join(CACHE, "cdx.txt"), encoding="utf-8") as f:
        for line in f:
            p = line.split()
            if len(p) < 2:
                continue
            m = re.search(r"/(9697|9899)/bills/([as])\d+/(\d+)_i1\.htm$", p[0], re.I)
            if m:
                k = (m.group(1), m.group(2).upper(), int(m.group(3)))
                if k not in out or p[1] < out[k][0]:
                    out[k] = (p[1], p[0])
    return out


def first_sponsor(text):
    flat = " ".join(text[:3000].split())
    m = re.search(r"Sponsored by:\s*(?:Assembly(?:man|woman)|Senator)\s+(.+?)\s+District\s+\d+", flat)
    return m.group(1).strip() if m else None


def scan():
    log = os.path.join(CACHE, "sponsors.tsv")
    done = set()
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            done = {tuple(line.split("\t")[:3]) for line in f}
    caps = captures()
    todo = sorted(k for k in caps if (k[0], k[1], str(k[2])) not in done)
    print(f"{len(caps)} archived introduced texts, {len(todo)} to read", flush=True)
    with open(log, "a", encoding="utf-8") as out:
        for sess, house, num in todo:
            ts, url = caps[(sess, house, num)]
            raw = fetch(f"{WAYBACK}/web/{ts}id_/{url}")
            if raw is None:
                continue
            text = plain(raw) if raw else ""
            if text:
                p = os.path.join(CACHE, "texts", sess, f"{house}{num}.txt")
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as tf:
                    tf.write(text)
            intro = re.search(r"INTRODUCED ([A-Z]+ \d{1,2}, \d{4})", text)
            out.write(f"{sess}\t{house}\t{num}\t{first_sponsor(text) or ''}\t{intro.group(1) if intro else ''}\n")
            out.flush()


def texts():
    rows = []
    with open(os.path.join(CACHE, "sponsors.tsv"), encoding="utf-8") as f:
        for line in f:
            sess, house, num, sponsor, intro = line.rstrip("\n").split("\t")
            hit = NAMES.get(sponsor.upper())
            if not hit or hit[2] != house:
                continue
            p = os.path.join(CACHE, "texts", sess, f"{house}{num}.txt")
            text = open(p, encoding="utf-8").read()
            t = re.search(r"\b(An Act .+?)(?:\.|;)\s", " ".join(text.split()))
            d = ""
            if intro:
                try:
                    d = time.strftime("%Y-%m-%d", time.strptime(intro.title(), "%B %d, %Y"))
                except ValueError:
                    pass
            y = SESSIONS[sess]
            rows.append({"BioguideId": hit[0], "Name": hit[1], "Session": f"{y}-{y + 1} Regular Session",
                         "BillNumber": f"{house}{num}", "BillId": f"NJ-{y}-{house}{num}",
                         "Title": t.group(1)[:300] if t else "", "IntroducedDate": d,
                         "House": "SENATE" if house == "S" else "ASSEMBLY", "IntroducedBy": sponsor,
                         "IntroducedByMatch": "Yes", "TextVersion": "Introduced", "TextPath": p})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["BioguideId", "TextPath"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(f"Wrote {OUT}: {len(rows)} rows {dict(Counter(r['Name'] for r in rows))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--texts", action="store_true")
    a = ap.parse_args()
    if a.scan:
        scan()
    if a.texts:
        texts()


if __name__ == "__main__":
    main()
