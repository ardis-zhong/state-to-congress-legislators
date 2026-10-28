#!/usr/bin/env python3
"""
Connecticut bills and resolutions, 2001-2009, from the Connecticut General Assembly's public bulk data
(ftp://ftp.cga.ct.gov/pub/data/archive/: <year>introducer.csv, <year>bill_info.csv) and bill text files
(www.cga.ct.gov/<year>/TOB/<H|S>/<year>HB-05329-R00-HB.htm; R00 = the bill as introduced), for population
members who served in the General Assembly before LegiScan's Connecticut coverage (2010 on for them).
Connecticut state-text pilot (2026-10-28).

introducer.csv lists every introducer and co-sponsor of every measure by district code ('81' = House
district 81, 'S16' = Senate district 16) with intro_type I (introducer) / C (co-sponsor) and sort_order;
the first introducer (I, sort_order 1) is the one printed first under 'Introduced by:' in the text.
Reviewed (year, district code) pairs are in replication/data/reference/ct_introducer_codes_2001_2009.csv.
Most Connecticut bills are raised by committees, so few are a member's own. The bill-status pages
(/asp/cgabillstatus/) are closed by robots.txt and are not used; the text files are allowed.

Introducer check: the first name under 'Introduced by:' must be the member (IntroducedByMatch).

Polite: one request at a time, at least 3 seconds apart, a User-Agent naming the project; everything is
cached under ct_cga_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/ct_cga_bills.py
"""

import csv
import html
import io
import os
import re
import subprocess
import time
import urllib.request

FTP = "ftp://ftp.cga.ct.gov/pub/data/archive"
SITE = "https://www.cga.ct.gov"
CACHE = "ct_cga_cache"
CODES = "replication/data/reference/ct_introducer_codes_2001_2009.csv"
TEXT_OUT = "ct_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 3
_last = [0.0]


def get(url, path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    if url.startswith("ftp:"):
        data = subprocess.run(["curl", "-s", "-f", "-m", "300", url], capture_output=True).stdout
    else:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            data = b""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return data


def table(year, name):
    raw = get(f"{FTP}/{year}{name}.csv", os.path.join(CACHE, "ftp", f"{year}{name}.csv"))
    return list(csv.DictReader(io.StringIO(raw.decode("cp1252", "replace"))))


def plain(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())


def text_url(year, bill):
    """HB05329 -> /2005/TOB/H/2005HB-05329-R00-HB.htm (HJ00030 -> .../2005HJ-00030-R00-HJ.htm)."""
    kind, num = bill[:2], bill[2:]
    return f"{SITE}/{year}/TOB/{kind[0]}/{year}{kind}-{num}-R00-{kind}.htm"


def main():
    with open(CODES, newline="", encoding="utf-8") as f:
        codes = {(r["year"], r["code"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    out = []
    for year in sorted({y for y, _ in codes}):
        info = {r["bill_num"]: r for r in table(year, "bill_info")}
        for r in table(year, "introducer"):
            p = codes.get((year, r["intro_code"].strip()))
            if not p or r["intro_type"] != "I" or r["sort_order"] != "1":
                continue
            bill = r["bill_num"]
            raw = get(text_url(year, bill), os.path.join(CACHE, "pages", year, f"{bill}.htm"))
            text = plain(raw.decode("cp1252", "replace")) if raw else ""
            i = text.find("General Assembly")
            text = text[i:].split("\nStatement of Purpose:")[0] if i >= 0 else ""
            by = re.search(r"Introduced by:\s*\n?(.+)", text)
            first = by.group(1).strip() if by else ""
            m = re.search(r"(?:REP|SEN)\.\s*([A-Z'\- ]+?),", first)
            match = "" if not text else "Unavailable" if not m else \
                "Yes" if m.group(1).replace(" ", "") == p["surname"].upper().replace(" ", "") else "No"
            txt = os.path.join(CACHE, "texts", year, f"{bill}.txt")
            if text:
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(plain(raw.decode("cp1252", "replace"))[i:])
            b = info.get(bill, {})
            d = re.match(r"(\d+)/(\d+)/(\d{4})", b.get("filed_date") or "")
            out.append({"BioguideId": p["bioguide_id"], "Name": p["name"], "Session": f"{year} Session",
                        "BillNumber": bill, "BillId": f"CT-{year}-{bill}", "Title": (b.get("bill_title") or "")[:300],
                        "IntroducedDate": f"{d.group(3)}-{int(d.group(1)):02d}-{int(d.group(2)):02d}" if d else "",
                        "House": "HOUSE" if bill[0] == "H" else "SENATE", "AuthorName": p["name"],
                        "IntroducedBy": first[:200], "IntroducedByMatch": match, "TextVersion": "Introduced",
                        "TextPath": txt if text else ""})
            print(f"{year} {bill} {p['name']}: {match or 'no text'}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable")))


if __name__ == "__main__":
    main()
