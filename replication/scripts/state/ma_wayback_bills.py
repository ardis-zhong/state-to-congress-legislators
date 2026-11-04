#!/usr/bin/env python3
"""
Massachusetts House and Senate bills, 1999-2008, from the Internet Archive's copies (web.archive.org) of
the General Court's former bill text pages (www.mass.gov/legis/bills/..., earlier www.state.ma.us/legis/
bills/...), for population members who served in the General Court before LegiScan's Massachusetts
coverage (2009 on): Scott Brown (House 1999-2004, Senate 2004-2008) and Stephen Lynch (Senate 1999-2001).
Massachusetts state-text pilot (2026-10-28).

The General Court's current site and API start in 2009, and the archive kept no list of bills by
sponsor, so every archived bill text in scope is read. Each page is the bill as filed and prints its
sponsor and year: "SENATE, NO. 14 / By Mr. Morrissey, a petition (accompanied by bill, Senate, No. 14) of
Michael W. Morrissey ... / In the Year Two Thousand and Three." Many paths (bills/st00014.htm) were reused
by each session, so every distinct capture is read and the year comes from the text. The sponsor named
after "By" (the member who presented the petition) is matched to the person by session, chamber and the
exact "By ..." string in replication/data/reference/ma_sponsor_names_1999_2008.csv (IntroducedByMatch is
that match). Only HTML texts are read (the archive's PDF copies duplicate them).

  --cdx      The Wayback Machine's capture index for the bill folders (saved under ma_wayback_cache/cdx/).
  --scan     Reads every capture in scope; logs (capture, chamber, number, year, "By" string, petitioners)
             to ma_wayback_cache/bills.tsv (resumable); caches pages and texts.
  --texts    Writes ma_state_legislation_sponsored.csv from the log and the reviewed names.

Polite: one request at a time, at least 5 seconds apart, a User-Agent naming the project.

USAGE (from the repo root):
    python3 replication/scripts/state/ma_wayback_bills.py --cdx
    python3 replication/scripts/state/ma_wayback_bills.py --scan
    python3 replication/scripts/state/ma_wayback_bills.py --texts
"""

import argparse
import csv
import hashlib
import html
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

WAYBACK = "https://web.archive.org"
HOSTS = ["www.mass.gov", "www.state.ma.us"]
CACHE = "ma_wayback_cache"
NAMES = "replication/data/reference/ma_sponsor_names_1999_2008.csv"
TEXT_OUT = "ma_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 5
_last = [0.0]
# captures in scope: House texts until Brown left the House (2004), Senate texts through 2008
LAST_CAPTURE = {"H": "20050630", "S": "20090315"}
YEARS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}


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


def cdx(name, params):
    """Capture-index lines (cached; a gateway error page is retried, not kept)."""
    p = os.path.join(CACHE, "cdx", f"{name}.txt")
    if not os.path.exists(p):
        q = urllib.parse.urlencode({**params, "filter": "statuscode:200"})
        for attempt in range(4):
            raw = fetch(f"{WAYBACK}/cdx/search/cdx?{q}")
            if raw is not None and (raw == b"" or re.match(rb"\d{14} ", raw)):
                break
            time.sleep(120)
        else:
            raise SystemExit(f"capture index for {name} keeps failing; run --cdx again later")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(raw)
    with open(p, encoding="utf-8") as f:
        return [line.split(" ") for line in f.read().splitlines() if line.strip()]


def captures():
    """[(timestamp, original URL, chamber H/S)]: one per distinct version of each archived bill page."""
    out, seen = [], set()
    for host in HOSTS:
        for part in ("house", "senate", "st", "ht"):
            name = f"{host.split('.')[1]}_{part}"
            prefix = f"{host}/legis/bills/{part}/" if part in ("house", "senate") else f"{host}/legis/bills/{part}"
            for ts, orig, digest in cdx(name, {"url": prefix, "matchType": "prefix",
                                               "fl": "timestamp,original,digest", "collapse": "digest"}):
                m = re.search(r"/(ht|st)(\d+)\.html?$", orig, re.I)
                if not m or re.search(r"/(18[6-9]|19\d)/", orig):
                    continue
                chamber = "H" if m.group(1).lower() == "ht" else "S"
                if ts[:8] > LAST_CAPTURE[chamber] or digest in seen:
                    continue
                seen.add(digest)
                out.append((ts, orig, chamber))
    return sorted(out)


def plain(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())


def year_of(text):
    """'In the Year Two Thousand and Three' / 'IN THE YEAR TWO THOUSAND FIVE' -> 2003 / 2005 (1999: 'One Thousand
    Nine Hundred and Ninety-Nine'; lines may break inside the phrase)."""
    words = "|".join(YEARS)
    m = re.search(rf"In\s+the\s+Year\s+(Two\s+Thousand(?:\s+(?:and\s+)?({words})\b)?|One\s+Thousand\s+Nine\s+Hundred\s+and\s+Ninety[-\s]+Nine)",
                  text, re.I)
    if not m:
        return 0
    if m.group(1).lower().startswith("one"):
        return 1999
    return 2000 + YEARS.get((m.group(2) or "").lower(), 0)


def parse(text, orig=""):
    """(chamber, number, year, 'By ...' sponsor string, petitioners) from a bill page. 2005 House petitions
    ('PETITION -- HOUSE') print 'CHIEF SPONSOR:' and no 'HOUSE, No.' heading: the number comes from the URL."""
    h = re.search(r"\b(HOUSE|SENATE)\s*,?\s*(?:No|NO)\.\s*(\d+)", text[:600])
    u = re.search(r"/(ht|st)(\d+)\.html?$", orig, re.I)
    by = re.search(r"\bBy (M(?:r|rs|s|essrs)\.\s+[^,]+?)(?:,| and others| \(by request\)|\s+a petition)", text[:1500]) \
        or re.search(r"CHIEF SPONSOR:\s*\n(.+)", text[:600])
    pet = re.search(r"p[ae]tition(?:\s*\([^)]*\))?\s+of\s+(.+?)(?:\s+(?:for|relative to|that|to|providing|establishing)\b)", text[:1500], re.S)
    ch, num = (h.group(1)[0], int(h.group(2))) if h else ("H" if u.group(1).lower() == "ht" else "S", int(u.group(2))) if u else ("", 0)
    return (ch, num, year_of(text[:2500]), " ".join(by.group(1).split()) if by else "",
            " ".join(pet.group(1).split())[:200] if pet else "")


def session_of(year):
    """General Court number and years: 2003 -> 183, '2003-2004'."""
    gc = 181 + (year - 1999) // 2
    y0 = 1999 + 2 * (gc - 181)
    return gc, f"{gc}th General Court ({y0}-{y0 + 1})".replace("181th", "181st").replace("182th", "182nd").replace("183th", "183rd")


def scan():
    log = os.path.join(CACHE, "bills.tsv")
    done = set()
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            done = {tuple(line.split("\t")[:2]) for line in f}
    todo = [c for c in captures() if (c[0], c[1]) not in done]
    print(f"{len(todo)} archived bill pages to read", flush=True)
    with open(log, "a", encoding="utf-8") as out:
        for i, (ts, orig, chamber) in enumerate(todo):
            key = hashlib.md5(f"{ts} {orig}".encode()).hexdigest()
            raw = cached(os.path.join(CACHE, "pages", key[:2], f"{key}.htm"), lambda: fetch(f"{WAYBACK}/web/{ts}id_/{orig}"))
            if raw is None:
                continue  # retry on the next run
            text = plain(raw.decode("cp1252", "replace"))
            ch, num, year, by, pet = parse(text, orig)
            if text:
                os.makedirs(os.path.join(CACHE, "texts", key[:2]), exist_ok=True)
                with open(os.path.join(CACHE, "texts", key[:2], f"{key}.txt"), "w", encoding="utf-8") as f:
                    f.write(text)
            out.write(f"{ts}\t{orig}\t{chamber}\t{ch}\t{num}\t{year}\t{by}\t{pet}\t{key}\n")
            out.flush()
            if i % 500 == 0:
                print(f"  {ts[:8]} {orig.rsplit('/', 1)[-1]}: {i}/{len(todo)}", flush=True)


def crawl_texts():
    with open(NAMES, newline="", encoding="utf-8") as f:
        reviewed = {(r["general_court"], r["chamber"], r["by"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    with open(os.path.join(CACHE, "bills.tsv"), encoding="utf-8") as f:
        log = [line.rstrip("\n").split("\t") for line in f]
    out = {}
    for ts, orig, chamber, _, _, _, _, _, key in sorted(log):
        p = os.path.join(CACHE, "texts", key[:2], f"{key}.txt")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            text = f.read()
        ch, num, year, by, pet = parse(text, orig)  # re-read from the saved text, so parser fixes apply
        if not ch or not year:
            continue
        gc, label = session_of(int(year))
        r = reviewed.get((str(gc), ch, by))
        bill = f"{ch}{int(num)}"
        bill_id = f"MA-{gc}-{bill}"
        if not r or bill_id in out:  # earliest capture of each bill
            continue
        i = re.search(r"\b(?:HOUSE|SENATE)\s*,?\s*(?:No|NO)\.\s*\d+", text)
        text = text[i.start():] if i else text
        t = re.search(r"In\s+the\s+Year\s[^\n]+\n(.+?)\n\s*Be it enacted", text, re.S | re.I)
        out[bill_id] = {"BioguideId": r["bioguide_id"], "Name": r["name"], "Session": label, "BillNumber": bill,
                        "BillId": bill_id, "Title": " ".join(re.sub(r"_+|\bA N A CT\b", lambda x: "AN ACT" if x.group(0)[0] == "A" else " ", t.group(1)).split())[:300] if t else "",
                        "IntroducedDate": "", "House": "HOUSE" if ch == "H" else "SENATE", "AuthorName": by,
                        "IntroducedBy": pet, "IntroducedByMatch": "Yes", "TextVersion": "Introduced",
                        "TextPath": os.path.join(CACHE, "texts", key[:2], f"{key}.txt"), "ArchivedPage": f"{orig} ({ts})"}
        os.makedirs(os.path.join(CACHE, "final"), exist_ok=True)
        final = os.path.join(CACHE, "final", f"{bill_id}.txt")
        with open(final, "w", encoding="utf-8") as f:
            f.write(text)
        out[bill_id]["TextPath"] = final
    rows = sorted(out.values(), key=lambda o: o["BillId"])
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {TEXT_OUT}: {len(rows)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdx", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--texts", action="store_true")
    args = ap.parse_args()
    if args.cdx:
        cs = captures()
        print(f"{len(cs)} archived bill page versions in scope: House {sum(c[2] == 'H' for c in cs)}, "
              f"Senate {sum(c[2] == 'S' for c in cs)}")
    if args.scan:
        scan()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
