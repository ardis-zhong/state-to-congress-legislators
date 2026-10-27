#!/usr/bin/env python3
"""
New Mexico state bills, memorials and resolutions, 1996-2010, from the New Mexico Legislature's
website (nmlegis.gov), for population members who served in the Legislature before LegiScan's New
Mexico coverage (2011 on). New Mexico state-text pilot (2026-10-26). robots.txt disallows only *.axd.

Only Steve Pearce (House 1997-2000) served in that window; his sponsor code is reviewed in
replication/data/reference/nm_sponsor_codes_1996_2010.csv.

  --lists    "Bill Finder by Sponsor" (/Legislation/BillFinder/Sponsor?SponCode=&YearStart=&YearEnd=)
             lists the legislation the member sponsored (co-sponsorships are recorded only from 2015).
  --texts    The item's page (/Legislation/Legislation?chamber=&legType=&legNo=&year=) links the
             introduced text (/Sessions/<session>/bills|memorials|resolutions/<house|senate>/HB0322.html;
             final versions are separate files; the printed line numbers are dropped). Its "INTRODUCED BY" line must name the person first.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under nm_nmlegis_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/nm_nmlegis_bills.py --lists
    python3 replication/scripts/state/nm_nmlegis_bills.py --texts
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://www.nmlegis.gov"
CACHE = "nm_nmlegis_cache"
CODES = "replication/data/reference/nm_sponsor_codes_1996_2010.csv"
LIST_OUT = "nm_sponsored_bills.csv"
TEXT_OUT = "nm_state_legislation_sponsored.csv"
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
    t = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return " ".join(t.split())


def session_code(label):
    """'1997 Regular' -> '1997R', '2000 2nd Special' -> '2000S2', '2000 Special' -> '2000S'."""
    year, kind = label.split(" ", 1)
    m = re.match(r"(\d)\w\w Special", kind)
    return year + ("R" if kind == "Regular" else f"S{m.group(1)}" if m else "S")


def crawl_lists():
    with open(CODES, newline="", encoding="utf-8") as f:
        codes = [r for r in csv.DictReader(f) if r["bioguide_id"]]
    out = []
    for r in codes:
        url = (f"{BASE}/Legislation/BillFinder/Sponsor?SponCode={r['spon_code']}"
               f"&YearStart={r['year_start_id']}&YearEnd={r['year_end_id']}&Type=")
        page = cached(os.path.join(CACHE, "lists", f"{r['spon_code']}.html"), lambda: fetch(url)).decode("utf-8", "replace")
        for row in re.split(r"<tr\b", page):
            link = re.search(r'href="\.\./Legislation\?chamber=([HS])&amp;legType=([A-Z]+)&amp;legNo=(\d+)&amp;year=(\w+)"', row)
            title = re.search(r'lblTitle_\d+">([^<]*)<', row)
            sess = re.search(r'lblSession_\d+">([^<]*)<', row)
            if not (link and sess):
                continue
            chamber, typ, num, ycode = link.groups()
            label = " ".join(sess.group(1).split())
            out.append({"bioguide_id": r["bioguide_id"], "name": r["name"], "label": r["label"], "session": label,
                        "code": session_code(label), "bill": f"{chamber}{typ}{num}", "chamber": chamber, "type": typ,
                        "num": num, "year_code": ycode, "title": plain(title.group(1)) if title else ""})
        print(f"{r['name']}: {len(out)} sponsored", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} items")


def html_text(raw):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", raw)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</tr>|</div>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    # the HTML prints a line number on each line ("0004| STEVAN E. PEARCE") and "|" between lines
    lines = [" ".join(re.sub(r"^\s*\d{4}\|", "", l).split()) for l in s.split("\n")]
    return "\n".join(l for l in lines if l and l != "|")


def crawl_texts():
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for b in items:
        key = f"{b['code']}_{b['bill']}"
        txt = os.path.join(CACHE, "texts", f"{key}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            page = cached(os.path.join(CACHE, "bills", f"{key}.html"),
                          lambda: fetch(f"{BASE}/Legislation/Legislation?chamber={b['chamber']}&legType={b['type']}"
                                        f"&legNo={b['num']}&year={b['year_code']}")).decode("utf-8", "replace")
            m = re.search(r'href="(/Sessions/[^"]+/(?:bills|memorials|resolutions)/(?:house|senate)/[^"]+\.html)"', page, re.I)
            if m:
                raw = cached(os.path.join(CACHE, "intro", f"{key}.html"), lambda: fetch(BASE + m.group(1)))
                text = html_text(raw.decode("cp1252", "replace")) if raw else ""
            if text:
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        m = re.search(r"INTRODUCED BY\s*\n([A-Z][A-Za-z.' \-]+)", text)
        first = " ".join(m.group(1).split()) if m else ""
        ok = bool(first) and sq(first.split()[-1]) == sq(b["label"])
        match = "" if not text else "Unavailable" if not first else "Yes" if ok else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": b["session"] + " Session",
                    "BillNumber": b["bill"], "BillId": f"NM-{b['code']}-{b['bill']}", "Title": b["title"],
                    "IntroducedDate": "", "House": "HOUSE" if b["chamber"] == "H" else "SENATE", "AuthorName": first or b["label"],
                    "IntroducedBy": first, "IntroducedByMatch": match, "TextVersion": "Introduced",
                    "TextPath": txt if text else ""})
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    args = ap.parse_args()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
