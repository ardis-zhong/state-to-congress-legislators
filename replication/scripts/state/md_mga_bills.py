#!/usr/bin/env python3
"""
Maryland state bills, 1996-2008, from the Maryland General Assembly's archived session pages
(mgaleg.maryland.gov/<year>rs/), for population members who served in the General Assembly
before LegiScan's Maryland coverage (2009 on). Maryland state-text pilot (Ardis, 2026-10-21).
The archive starts with the 1996 session (1995rs and earlier return 404).

  --members  For each person and regular session, the sponsor page /<year>rs/sponsors/<key>.htm
             (key = surname, lower case); its heading names the member ("Senator Andrew P.
             Harris District 9"). Candidates go to a reviewed list,
             replication/data/reference/md_sponsor_keys_1996_2008.csv.
  --lists    Each reviewed sponsor page lists every bill and joint resolution the member sponsored, with its
             "Sponsored By" line; a bill is kept when the person is named first (the primary
             sponsor). Bills first named "The President", "The Speaker", the Chair of a
             committee, or another member are left out.
  --texts    The bill as introduced (the "first reader", /<year>rs/bills/<hb|sb>/<bill>f.pdf),
             read with pdfplumber. Its heading names the sponsors ("By: Senators Harris, ...")
             and the introduction date ("Introduced and read first time: January 13, 1999");
             IntroducedByMatch says whether the first member named is the person.

Polite: one request at a time, at least 3 seconds apart, a User-Agent naming the project, every
response cached under md_mga_cache/. The site has no robots.txt (404).

USAGE (from the repo root):
    python3 replication/scripts/state/md_mga_bills.py --members
    python3 replication/scripts/state/md_mga_bills.py --lists
    python3 replication/scripts/state/md_mga_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import logging
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://mgaleg.maryland.gov/"
CACHE = "md_mga_cache"
YEARS = range(1996, 2009)
PEOPLE = "replication/data/population/person_level.csv"
KEYS = "replication/data/reference/md_sponsor_keys_1996_2008.csv"
CANDIDATES = "md_sponsor_key_candidates.csv"
LIST_OUT = "md_primary_sponsor_bills.csv"
TEXT_OUT = "md_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 3
_last = [0.0]
MONTHS = {m: i for i, m in enumerate("january february march april may june july august september october "
                                     "november december".split(), 1)}


def get(path, cache_path, binary=False):
    """Fetch BASE+path once (cached). Returns the body, or empty for a 404; a page that keeps
    failing is skipped (not cached) so a re-run tries it again."""
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            data = f.read()
        return data if binary else data.decode("latin-1", errors="replace")
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"User-Agent": UA}),
                                        timeout=120) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = b""
                break
            time.sleep(30 * (attempt + 1))
        except Exception:
            time.sleep(30 * (attempt + 1))
    else:
        print(f"  could not fetch {path}", flush=True)
        return b"" if binary else ""
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(data)
    return data if binary else data.decode("latin-1", errors="replace")


def plain(s):
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</td>|</h\d>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def pdf_text(path):
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text(x_tolerance=1.5) or "") for page in pdf.pages).strip()
    except Exception:
        return ""


def md_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if "Maryland" not in r["StateLegChamber"] and r["State"] != "Maryland":
                continue
            ys = set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d|present)", r["StateLegYears"]):
                ys |= set(range(int(a), (2026 if z == "present" else int(z)) + 1))
            if any(y in YEARS for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def sponsor_page(year, key):
    return get(f"{year}rs/sponsors/{key}.htm", os.path.join(CACHE, "sponsors", f"{year}_{key}.htm"))


def find_members():
    rows = []
    for p in md_people():
        last = p["Name"].split()[-1].lower().replace("'", "")
        for year in [y for y in YEARS if y in p["years"] or y - 1 in p["years"]]:
            for key in (last, f"{last}01", f"{last}02"):
                page = sponsor_page(year, key)
                head = re.search(r"(Senator|Delegate)\s+([^<\n]+?)\s+District\s+(\w+)", plain(page))
                if head:
                    rows.append({"year": year, "key": key, "bioguide_id": p["BioguideId"], "name": p["Name"],
                                 "page_member": f"{head.group(1)} {head.group(2)}", "district": head.group(3),
                                 "state_leg_years": p["StateLegYears"]})
                elif key != last:
                    break
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {KEYS}")


def squash(s):
    return re.sub(r"[^a-z]", "", s.lower())


def first_sponsor(sponsored_by):
    """'Senators Harris, Hoffman, and Stone' -> 'Harris'; 'The President and Senators ...' ->
    'The President'; 'Chairman, Judiciary Committee (By Request ...)' -> 'Chairman'."""
    s = " ".join(sponsored_by.split())
    s = re.sub(r"^(?:Senators?|Delegates?)\s+", "", s)
    return re.split(r",|\s+and\s+|\s+\(", s)[0].strip()


def crawl_lists():
    with open(KEYS, newline="", encoding="utf-8") as f:
        keys = list(csv.DictReader(f))
    out = []
    for k in keys:
        year = int(k["year"])
        t = plain(sponsor_page(year, k["key"]))
        total = re.search(r"Total Number of Bills:\s*(\d+)", t)
        blocks = re.split(r"\n?\s*(?=\b[HS][BJ] \d+\s+Status as of)", t)  # bills and joint resolutions
        n_bills, kept = 0, 0
        surname = re.sub(r"\d+$", "", k["key"])  # e.g. "vanhollen"
        for b in blocks:
            m = re.match(r"([HS][BJ]) (\d+)\s+Status as of.*?Sponsored By\s*(.*?)\s*Entitled\s*(.*?)\s*Committee", b, flags=re.S)
            if not m:
                continue
            n_bills += 1
            typ, num, by, title = m.groups()
            if squash(first_sponsor(by)) != surname:
                continue
            kept += 1
            out.append({"year": year, "bioguide_id": k["bioguide_id"], "name": k["name"], "key": k["key"],
                        "type": typ, "number": int(num), "title": " ".join(title.split())[:300],
                        "sponsored_by": " ".join(by.split())[:300]})
        if total and int(total.group(1)) != n_bills:
            print(f"  WARNING {year} {k['key']}: {total.group(1)} listed, {n_bills} parsed")
        print(f"{year} {k['name']}: {n_bills} sponsored, {kept} as first-named", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} bills")


def heading(text):
    """(names after 'By:', ISO introduction date) from the first reader's heading."""
    m = re.search(r"\bBy:\s*(?:The\s+)?(?:Senators?|Delegates?)?\s*(.*?)(?:\n\s*\n|Introduced and read|Read and Examined|Requested:|Constitutional Requirements|Assigned to)",
                  text[:3000], flags=re.S)
    names = " ".join(m.group(1).split()) if m else ""
    d = re.search(r"Introduced and read first time:\s*(\w+)\s+(\d{1,2}),\s*(\d{4})", text[:4000])
    iso = f"{d.group(3)}-{MONTHS[d.group(1).lower()]:02d}-{int(d.group(2)):02d}" if d and d.group(1).lower() in MONTHS else ""
    return names, iso


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        year, typ, num = b["year"], b["type"], int(b["number"])
        stem = f"{typ.lower()}{num:04d}"
        pdf_path = os.path.join(CACHE, "texts", f"{year}_{stem}f.pdf")
        txt_path = os.path.join(CACHE, "texts", f"{year}_{stem}f.txt")
        text = ""
        if os.path.exists(txt_path):
            with open(txt_path, encoding="utf-8") as f:
                text = f.read()
        elif get(f"{year}rs/bills/{typ.lower()}/{stem}f.pdf", pdf_path, binary=True):
            text = pdf_text(pdf_path)
            if text:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(text)
        names, iso = heading(text)
        first = first_sponsor(names) if names else ""
        surname = re.sub(r"\d+$", "", b["key"])
        match = "" if not text else "Unavailable" if not names else "Yes" if squash(first) == surname else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{year} Regular Session",
                    "BillNumber": f"{typ}{num}", "BillId": f"MD-{year}-{typ}{num}", "Title": b["title"],
                    "IntroducedDate": iso, "House": "HOUSE" if typ[0] == "H" else "SENATE", "AuthorName": b["sponsored_by"][:120],
                    "IntroducedBy": names[:200], "IntroducedByMatch": match, "TextVersion": "Introduced",
                    "TextPath": txt_path if text else ""})
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
