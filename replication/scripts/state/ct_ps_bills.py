#!/usr/bin/env python3
"""
Connecticut bills 1993-2000 from the General Assembly's own bill-text files, for population members who served
before the introducer files that ct_cga_bills.py uses (2001 on): Rob Simmons (House 1991-2001), Chris Murphy
(House 1999-2002), Joe Courtney (House to 1994), John Larson and James Maloney (Senate to 1994).

The General Assembly's website still serves each session's bill texts as introduced (robots.txt allows them;
the bill-status pages /asp/cgabillstatus/ are closed and are not used):
  1993-1998  www.cga.ct.gov/ps<yy>/tob/h/hb-5005.htm, /tob/s/sb-0005.htm
  1999       www.cga.ct.gov/ps99/TOB/H/1999HB-05001-R00-HB.htm (R00 = as introduced)
  2000       www.cga.ct.gov/2000/TOB/H/2000HB-05001-R00-HB.htm
Texts before 1993 are not online. There is no index of bills by introducer for these years, so every House
bill 1993-2000 (and every Senate bill 1993-1994) is read in number order until 400 numbers in a row are
missing; each text prints 'Introduced by REP. STRIPP, 135th DIST.' (1999 on 'Introduced by: REP. FRITZ, 90th
Dist.'), committee bills name the committee. A bill counts when the first introducer is the member (surname
and district, reviewed in DISTRICTS below).

  --scan   read every text -> ct_ps_cache/introducers.tsv (resumable; texts cached)
  --texts  write ct_ps_state_legislation_sponsored.csv

Polite: one request at a time, at least 3 seconds apart, a User-Agent naming the project.
USAGE (from the repo root):  python3 replication/scripts/state/ct_ps_bills.py --scan --texts
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

SITE = "https://www.cga.ct.gov"
CACHE = "ct_ps_cache"
OUT = "ct_ps_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 3
MAX_MISSING = 400
# (chamber, years) to read; Senate only while Larson and Maloney served
SCOPE = [("H", y) for y in range(1993, 2001)] + [("S", 1993), ("S", 1994)]
# (chamber, surname, district) -> (bioguide, name, years); districts from the members' Wikipedia pages / CGA rosters
DISTRICTS = {
    ("H", "SIMMONS", 43): ("S001152", "Rob Simmons", range(1993, 2001)),
    ("H", "MURPHY", 81): ("M001169", "Chris Murphy", range(1999, 2001)),
    ("H", "COURTNEY", 56): ("C001069", "Joe Courtney", range(1993, 1995)),
    ("S", "LARSON", 3): ("L000557", "John B. Larson", range(1993, 1995)),
    ("S", "MALONEY", 24): ("M000090", "James H. Maloney", range(1993, 1995)),
}
_last = [0.0]


def url(ch, year, num):
    if year <= 1998:
        return f"{SITE}/ps{year % 100:02d}/tob/{ch.lower()}/{ch.lower()}b-{num:04d}.htm"
    folder = "ps99" if year == 1999 else str(year)
    return f"{SITE}/{folder}/TOB/{ch}/{year}{ch}B-{num:05d}-R00-{ch}B.htm"


def fetch(u):
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            time.sleep(30 * (attempt + 1))
        except Exception:
            time.sleep(30 * (attempt + 1))
    print(f"  could not fetch {u}", flush=True)
    return None


def plain(raw):
    t = raw.decode("cp1252", "replace")
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", t).strip()


def first_introducer(text):
    """'Introduced by REP. STRIPP, 135th DIST.' -> ('REP', 'STRIPP', 135); a committee -> ('', '<text>', 0)."""
    flat = " ".join(text[:4000].split())
    m = re.search(r"Introduced by:?\s+(.{0,120})", flat)
    if not m:
        return None
    p = re.match(r"(REP|SEN)\.\s+([A-Z][A-Z'. \-]+?),\s*(\d+)\s*(?:st|nd|rd|th)\b", m.group(1), re.I)
    if not p:
        return ("", m.group(1)[:60], 0)
    return (p.group(1).upper(), p.group(2).upper().strip(), int(p.group(3)))


def scan():
    log = os.path.join(CACHE, "introducers.tsv")
    os.makedirs(CACHE, exist_ok=True)
    done = {}
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                done.setdefault((p[0], int(p[1])), {})[int(p[2])] = p[3]
    with open(log, "a", encoding="utf-8") as out:
        for ch, year in SCOPE:
            seen = done.get((ch, year), {})
            num, miss = (5001 if ch == "H" else 1), 0
            while miss < MAX_MISSING:
                if num in seen:
                    miss = 0 if seen[num] != "#missing" else miss + 1
                    num += 1
                    continue
                raw = fetch(url(ch, year, num))
                if raw is None:
                    num += 1
                    continue
                if not raw:
                    out.write(f"{ch}\t{year}\t{num}\t#missing\n")
                    miss += 1
                else:
                    text = plain(raw)
                    p = os.path.join(CACHE, "texts", str(year), f"{ch}B{num}.txt")
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "w", encoding="utf-8") as tf:
                        tf.write(text)
                    fi = first_introducer(text)
                    out.write(f"{ch}\t{year}\t{num}\t{'#none' if fi is None else '|'.join(map(str, fi))}\n")
                    miss = 0
                out.flush()
                num += 1
            print(f"  {ch} {year}: through {num - 1}", flush=True)


def texts():
    rows = []
    with open(os.path.join(CACHE, "introducers.tsv"), encoding="utf-8") as f:
        for line in f:
            ch, year, num, fi = line.rstrip("\n").split("\t")
            if fi.startswith("#"):
                continue
            title, surname, dist = fi.split("|")
            hit = DISTRICTS.get((ch, surname, int(dist)))
            if not hit or int(year) not in hit[2] or title != ("REP" if ch == "H" else "SEN"):
                continue
            p = os.path.join(CACHE, "texts", year, f"{ch}B{num}.txt")
            text = open(p, encoding="utf-8").read()
            t = re.search(r"\b(AN ACT .+?)\.", " ".join(text.split()), re.I)
            rows.append({"BioguideId": hit[0], "Name": hit[1], "Session": f"{year} Regular Session",
                         "BillNumber": f"{ch}B{num}", "BillId": f"CT-{year}-{ch}B{int(num):05d}",
                         "Title": t.group(1)[:300] if t else "", "IntroducedDate": "",
                         "House": "HOUSE" if ch == "H" else "SENATE", "IntroducedBy": f"{title}. {surname}, {dist}",
                         "IntroducedByMatch": "Yes", "TextVersion": "Introduced", "TextPath": p})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["BioguideId", "TextPath"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(f"Wrote {OUT}: {len(rows)} rows {dict(Counter((r['Name'], r['Session'][:4]) for r in rows))}")


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
