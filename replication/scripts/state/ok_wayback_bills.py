#!/usr/bin/env python3
"""
Oklahoma House bills 1999-2004 from the Internet Archive's copies of the Legislature's former website
(www.lsb.state.ok.us), for population members in the Oklahoma House before LegiScan (Oklahoma from 2009):
John Sullivan (House 1995-Feb 2002) and Dan Boren (House 2003-2004). The current sites (oklegislature.gov,
webserver1.lsb.state.ok.us) disallow all crawling in robots.txt, so only archived copies are read.

Who authored what:
  1999       the House Journal's daily first-reading lists (house/Journals/HJ1999/hjour<n>.rtf):
             'HB 1012  Sullivan (John) of the House.' -- the first name listed is the principal author.
  2000-2004  the House Journal's yearly Personal Index (e.g. house/Journals/HJ2001/2001 HPersonal _01.rtf):
             'SULLIVAN, JOHN , Tulsa County, District 71 ... Author: HBs 1004*, 1030*, ...' where '*' marks the
             principal author. House measures only (HB, HJR, HCR, HR); Senate bills carried in the House
             (SBs 637*) are the other chamber's bills and are left out; '(removed ...)' entries are dropped.
Texts: the archived introduced version <www.lsb.state.ok.us>/<biennium>HB/<HB1004>_int.rtf (RTF, converted
with macOS textutil); the text's 'By:' line must name the person first ('By: Sullivan (John) of the House').
Capture lists (CDX 'original timestamp') are cached in ok_wayback_cache/cdx/.

  --authors  read the indexes/journals -> ok_wayback_cache/authored.tsv
  --texts    fetch introduced texts -> ok_wayback_state_legislation_sponsored.csv

Polite: one request at a time, at least 6 seconds apart, a User-Agent naming the project.
USAGE (from the repo root):  python3 replication/scripts/state/ok_wayback_bills.py --authors --texts
"""

import argparse
import csv
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

WAYBACK = "https://web.archive.org"
CACHE = "ok_wayback_cache"
OUT = "ok_wayback_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 6
HOST = "http://www.lsb.state.ok.us"
# person: (bioguide, name, index heading, journal author string, sessions)
PEOPLE = [
    ("S001155", "John Sullivan", "SULLIVAN, JOHN ,", "Sullivan (John)", (1999, 2000, 2001, 2002)),
    ("B001254", "Dan Boren", "BOREN, DAN ,", "Boren", (2003, 2004)),
]
PERSONAL = {2000: "HOUSE/Journals/HJ2000/member%20personal%20_00.rtf",
            2001: "house/Journals/HJ2001/2001%20HPersonal%20_01.rtf",
            2002: "HOUSE/Journals/HJ2002/2002%20Personal.rtf",
            2003: "house/Journals/HJ2003/2003%20HPersonal.rtf",
            2004: "house/Journals/HJ2004/2004%20hpersonal.rtf"}
BIENNIUM = {1999: "1999-00HB", 2000: "1999-00HB", 2001: "2001-02HB", 2002: "2001-02HB",
            2003: "2003-04HB", 2004: "2003-04HB"}
LEGISLATURE = {1999: "47th Legislature, 1st Session", 2000: "47th Legislature, 2nd Session",
               2001: "48th Legislature, 1st Session", 2002: "48th Legislature, 2nd Session",
               2003: "49th Legislature, 1st Session", 2004: "49th Legislature, 2nd Session"}
_last = [0.0]


def fetch(url):
    for attempt in range(5):
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


def cached(local, url):
    """Archived file -> plain text (RTF via textutil), cached under ok_wayback_cache/."""
    txt = local + ".txt"
    if os.path.exists(txt):
        return open(txt, encoding="utf-8").read()
    raw = fetch(url)
    if not raw:
        return None
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "wb") as f:
        f.write(raw)
    if raw.lstrip()[:5] == b"{\\rtf":
        subprocess.run(["textutil", "-convert", "txt", "-output", txt, local], check=True)
    else:
        with open(txt, "w", encoding="utf-8") as f:
            f.write(raw.decode("cp1252", "replace"))
    return open(txt, encoding="utf-8").read()


def cdx(name):
    with open(os.path.join(CACHE, "cdx", f"{name}.txt"), encoding="utf-8") as f:
        return [line.split() for line in f if line.startswith("http")]


def personal_entries(text, heading):
    """'Author: HBs 1004*, 1727* (added p. 1692); HJRs 1023*; SBs 637*' -> [('HB', 1004, ''), ...] (principal only)."""
    i = text.find(heading)
    if i < 0:
        return []
    m = re.search(r"\nAuthor:(.*)", text[i:i + 3000])
    out = []
    for group in (m.group(1) if m else "").split(";"):
        g = re.match(r"\s*(HBs?|HJRs?|HCRs?|HRs?|SBs?|SJRs?|SCRs?|SRs?)\s+(.*)", group.strip())
        if not g:
            continue
        kind = g.group(1).rstrip("s")
        if kind[0] != "H":
            continue  # Senate measures the person carried in the House
        for item in g.group(2).split(","):
            n = re.match(r"\s*(\d+)(\*?)\s*(.*)", item)
            if n and n.group(2) == "*" and "removed" not in n.group(3):
                out.append((kind, int(n.group(1)), n.group(3).strip()))
    return out


def authors():
    rows = []
    for year, path in PERSONAL.items():
        text = cached(os.path.join(CACHE, "journals", f"personal_{year}.rtf"), f"{WAYBACK}/web/2006id_/{HOST}/{path}")
        for bg, name, heading, _, sessions in PEOPLE:
            if year in sessions:
                for kind, num, note in personal_entries(text or "", heading):
                    rows.append([year, bg, name, f"{kind}{num}", "Personal Index", note])
    # 1999: daily journals' first readings
    days = sorted({u for u, ts in cdx("house") if re.search(r"/Journals/HJ1999/hjour\d+(?:X|ex)?\.rtf$", u, re.I)},
                  key=lambda u: (len(u), u))
    seen = set()
    for u in days:
        day = re.search(r"hjour(\w+)\.rtf$", u, re.I).group(1)
        text = cached(os.path.join(CACHE, "journals", f"hj1999_{day}.rtf"), f"{WAYBACK}/web/2004id_/{u}") or ""
        for bg, name, _, jname, sessions in PEOPLE:
            if 1999 not in sessions:
                continue
            for m in re.finditer(r"^(HB|HJR|HCR|HR) (\d+)\s+(?:–|-)?\s*(?:By\s+)?([^\n]+)", text, re.M):
                first = re.split(r",| and | of the House", m.group(3))[0].strip()
                key = f"{m.group(1)}{m.group(2)}"
                if first == jname and key not in seen and int(m.group(2)) >= 1000:
                    seen.add(key)
                    rows.append([1999, bg, name, key, f"House Journal 1999 day {day}", ""])
    with open(os.path.join(CACHE, "authored.tsv"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write("\t".join(map(str, r)) + "\n")
    from collections import Counter
    print(f"{len(rows)} principal-author House measures: {dict(Counter((r[2], r[0]) for r in rows))}")


def by_line(text):
    flat = " ".join(text[:4000].split())
    # 2003-04 files print the authors after the measure number: 'HOUSE BILL HB1565: Boren AS INTRODUCED'
    h = re.search(r"\bHOUSE (?:BILL|JOINT RESOLUTION|CONCURRENT RESOLUTION|RESOLUTION)\s+H[A-Z]*\s?\d+:\s+(.+?)"
                  r"(?:\s+of the (?:House|Senate)|\s+and\s|,|\s+AS INTRODUCED|\s+<|$)", flat)
    if h:
        return h.group(1).strip()
    m = re.search(r"\bBy:?\s+(.+?)(?:\s+of the (?:House|Senate)|\s+and\s|,|\s+AS INTRODUCED|\s+<|$)", flat)
    return m.group(1).strip() if m else None


def texts():
    with open(os.path.join(CACHE, "authored.tsv"), encoding="utf-8") as f:
        rows = [line.rstrip("\n").split("\t") for line in f]
    caps = {}
    for b in set(BIENNIUM.values()):
        for u, ts in cdx(b):
            m = re.search(r"/(H[A-Z]+\d+)_int\.rtf$", u, re.I)
            if m:
                caps.setdefault((b, m.group(1).upper()), (ts, u))
    jname = {p[0]: p[3] for p in PEOPLE}
    out = []
    for year, bg, name, bill, source, note in rows:
        year = int(year)
        cap = caps.get((BIENNIUM[year], bill))
        text = ""
        if cap:
            text = cached(os.path.join(CACHE, "texts", BIENNIUM[year], f"{bill}_int.rtf"),
                          f"{WAYBACK}/web/{cap[0]}id_/{cap[1]}") or ""
        if text:
            # word-processor field markers in the RTF ('<StartFT>An Act ...<EndFT>', 'Section <6-502>')
            text = re.sub(r"<(?:StartFT|EndFT)>", "", text)
            text = re.sub(r"<([^<>\n]{1,40})>", r"\1", text)
            clean = os.path.join(CACHE, "texts", BIENNIUM[year], f"{bill}_int.clean.txt")
            with open(clean, "w", encoding="utf-8") as cf:
                cf.write(text)
        first = by_line(text) if text else None
        check = "" if not text else ("Unavailable" if not first else
                                     ("Yes" if first.replace(" ", "") == jname[bg].replace(" ", "") else "No"))
        t = re.search(r"\b(An Act relating to .+?)(?:;|\.)", " ".join(text.split()), re.I)
        out.append({"BioguideId": bg, "Name": name, "Session": f"{year} {LEGISLATURE[year]}",
                    "BillNumber": bill, "BillId": f"OK-{year}-{bill}", "Title": t.group(1)[:300] if t else "",
                    "IntroducedDate": "", "House": "HOUSE", "AuthorSource": source, "AuthorNote": note,
                    "IntroducedBy": first or "", "IntroducedByMatch": check, "TextVersion": "Introduced",
                    "TextPath": os.path.join(CACHE, "texts", BIENNIUM[year], f"{bill}_int.clean.txt") if text else ""})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    print(f"Wrote {OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; By-line check "
          f"{dict(Counter(o['IntroducedByMatch'] for o in out))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--authors", action="store_true")
    ap.add_argument("--texts", action="store_true")
    a = ap.parse_args()
    if a.authors:
        authors()
    if a.texts:
        texts()


if __name__ == "__main__":
    main()
