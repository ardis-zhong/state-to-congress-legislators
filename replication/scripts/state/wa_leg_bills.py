#!/usr/bin/env python3
"""
Washington state bills, 1991-2008, from the Washington Legislature's website, for population
members who served in the Legislature before LegiScan's Washington coverage (2009-10 on).
Washington state-text pilot (Ardis, 2026-10-24). The online archive starts with the 1991-92
biennium.

  --members  Each biennium's sponsor lists (app.leg.wa.gov/bi/BillsBySponsor/
             _getSponsorsByBiennium/?bienniumYear=1991-92, as used by the "Bills by sponsor"
             report) give every House and Senate member's id; our people's entries are written
             as candidates for the reviewed list
             replication/data/reference/wa_sponsor_ids_1991_2008.csv.
  --lists    The "Bills by sponsor" report, primary bills only
             (/bi/report/billsbysponsor/?biennium=..&<house|senate>SponsorId=..&sponsorType=..
             &billsBySponsorReportType=primarybills), lists each person's primary-sponsored
             bills, joint memorials and resolutions, with their original sponsor.
  --texts    Each one as introduced: the unsuffixed file in the Legislature's document archive
             (lawfilesext.leg.wa.gov/biennium/<biennium>/Htm/Bills/<House Bills>/<number>.htm,
             else the PDF). Its heading names the sponsors ("By Representatives Locke, Ballard,
             ..."); IntroducedByMatch says whether the first member named is the person, and
             the reading date ("Read first time 01/14/91.") gives the introduction date.

Polite: one request at a time, at least 3 seconds apart, a User-Agent naming the project, every
response cached under wa_leg_cache/. Neither app.leg.wa.gov nor lawfilesext.leg.wa.gov has a
robots.txt (404).

USAGE (from the repo root):
    python3 replication/scripts/state/wa_leg_bills.py --members
    python3 replication/scripts/state/wa_leg_bills.py --lists
    python3 replication/scripts/state/wa_leg_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

APP = "https://app.leg.wa.gov"
FILES = "https://lawfilesext.leg.wa.gov"
CACHE = "wa_leg_cache"
BIENNIA = [f"{y}-{str(y + 1)[2:]}" for y in range(1991, 2009, 2)]
PEOPLE = "replication/data/population/person_level.csv"
IDS = "replication/data/reference/wa_sponsor_ids_1991_2008.csv"
CANDIDATES = "wa_sponsor_id_candidates.csv"
LIST_OUT = "wa_primary_sponsor_bills.csv"
TEXT_OUT = "wa_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 3
_last = [0.0]
MONTHS = {m: i for i, m in enumerate("January February March April May June July August September October "
                                     "November December".split(), 1)}
FOLDERS = {"HB": "House Bills", "SB": "Senate Bills", "HJR": "House Joint Resolutions",
           "SJR": "Senate Joint Resolutions", "HJM": "House Joint Memorials", "SJM": "Senate Joint Memorials",
           "HCR": "House Concurrent Resolutions", "SCR": "Senate Concurrent Resolutions",
           "HR": "House Resolutions", "SR": "Senate Resolutions"}


def get(url, cache_path, binary=False):
    """Fetch url once (cached). Returns the body, or empty for a 404; a page that keeps failing
    is skipped (not cached) so a re-run tries it again."""
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            data = f.read()
        return data if binary else data.decode("utf-8", errors="replace")
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
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
        print(f"  could not fetch {url}", flush=True)
        return b"" if binary else ""
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(data)
    return data if binary else data.decode("utf-8", errors="replace")


def plain(s):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def pdf_text(path):
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text(x_tolerance=1.5) or "") for page in pdf.pages).strip()
    except Exception:
        return ""


def wa_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Washington" and "Washington" not in r["StateLegChamber"]:
                continue
            s, ys = re.sub(r"\bpresent\b", "2026", r["StateLegYears"], flags=re.I), set()
            # ranges such as "1994-2005" or "January 1989-January 1993"
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*(?:[A-Za-z]+\s+)?((?:19|20)\d\d)", s):
                ys |= set(range(int(a), int(z) + 1))
            if any(1991 <= y <= 2009 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def sponsors(biennium):
    data = get(f"{APP}/bi/BillsBySponsor/_getSponsorsByBiennium/?bienniumYear={biennium}",
               os.path.join(CACHE, "sponsors", f"{biennium}.json"))
    return json.loads(data) if data else {}


def find_members():
    rows = []
    for p in wa_people():
        last = {"Cathy McMorris Rodgers": "mcmorris", "Jaime Herrera Beutler": "herrera"}.get(p["Name"], p["Name"].split()[-1].lower())  # name in the Legislature
        for b in BIENNIA:
            y = int(b[:4])
            if y not in p["years"] and y + 1 not in p["years"]:
                continue
            for key, chamber in (("sponsorsHouse", "House"), ("sponsorsSenate", "Senate")):
                for s in sponsors(b).get(key, []):
                    if last in s["text"].lower():
                        rows.append({"biennium": b, "chamber": chamber, "sponsor_id": s["value"], "sponsor_text": s["text"],
                                     "bioguide_id": p["BioguideId"], "name": p["Name"],
                                     "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {IDS}")


def report(biennium, chamber, sponsor_id):
    t = chamber.lower()
    q = urllib.parse.urlencode({"biennium": biennium, f"{t}SponsorId": sponsor_id, "sponsorType": t,
                                "billsBySponsorReportType": "primarybills", "hasCompanionBills": "false"})
    return get(f"{APP}/bi/report/billsbysponsor/?{q}", os.path.join(CACHE, "reports", f"{biennium}_{t}_{sponsor_id}.html"))


def crawl_lists():
    with open(IDS, newline="", encoding="utf-8") as f:
        ids = list(csv.DictReader(f))
    out = []
    for k in ids:
        page = report(k["biennium"], k["chamber"], k["sponsor_id"])
        total = re.search(r"Total count:\s*(\d+)", page)
        n = 0
        for m in re.finditer(r'(?s)<tr[^>]*data-leg-type="([A-Z]+)"[^>]*data-bill-number="(\d+)"(.*?)</tr>', page):
            typ, num, body = m.groups()
            cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
                     for c in re.findall(r"(?s)<td[^>]*>(.*?)</td>", body)]
            original = cells[-2] if len(cells) >= 2 else ""
            title = cells[4] if len(cells) > 4 else ""
            out.append({"biennium": k["biennium"], "bioguide_id": k["bioguide_id"], "name": k["name"],
                        "chamber": k["chamber"], "sponsor_text": k["sponsor_text"], "type": typ, "number": int(num),
                        "title": title[:300], "original_sponsor": original})
            n += 1
        if total and int(total.group(1)) != n:
            print(f"  WARNING {k['biennium']} {k['name']}: {total.group(1)} listed, {n} parsed")
        print(f"{k['biennium']} {k['chamber']} {k['name']}: {n} primary-sponsored", flush=True)
    seen, uniq = set(), []
    for o in out:
        key = (o["bioguide_id"], o["biennium"], o["type"], o["number"])
        if key not in seen:
            seen.add(key)
            uniq.append(o)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(uniq[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(uniq)
    print(f"Wrote {LIST_OUT}: {len(uniq)} bills")


def heading(text):
    """(names as printed after 'By', ISO date read first) from the introduced text."""
    flat = " ".join(text[:5000].split())
    # "By Representatives Locke, ..." (some resolutions omit the title: "By Kilmer, Schoesler, ...")
    m = re.search(r"\bBy (?:(?:Representatives?|Senators?) )?([A-Z].*?)(?:\.\s*Read first time|Read first time|Prefiled|$)", flat)
    names = m.group(1).strip() if m else ""
    iso = ""
    d = re.search(r"Read first time (\d{1,2})/(\d{1,2})/(\d{2,4})", flat)
    if d:
        y = int(d.group(3))
        y = y + (1900 if y > 50 else 2000) if y < 100 else y
        iso = f"{y}-{int(d.group(1)):02d}-{int(d.group(2)):02d}"
    d = d or re.search(r"Read first time (" + "|".join(MONTHS) + r") (\d{1,2}), (\d{4})", flat)
    if d and not iso:
        iso = f"{d.group(3)}-{MONTHS[d.group(1)]:02d}-{int(d.group(2)):02d}"
    return names, iso


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        bien, typ, num = b["biennium"], b["type"], int(b["number"])
        folder = urllib.parse.quote(FOLDERS.get(typ, ""))
        txt_path = os.path.join(CACHE, "texts", f"{bien}_{typ}{num}.txt")
        text = ""
        if os.path.exists(txt_path):
            with open(txt_path, encoding="utf-8") as f:
                text = f.read()
        elif folder:
            raw = get(f"{FILES}/biennium/{bien}/Htm/Bills/{folder}/{num}.htm", os.path.join(CACHE, "texts", f"{bien}_{typ}{num}.htm"),
                      binary=True)
            text = plain(raw.decode("cp1252", errors="replace")) if raw else ""  # Word-exported HTML, windows-1252
            if not text:
                pdf = os.path.join(CACHE, "texts", f"{bien}_{typ}{num}.pdf")
                if get(f"{FILES}/biennium/{bien}/Pdf/Bills/{folder}/{num}.pdf", pdf, binary=True)[:4] == b"%PDF":
                    text = pdf_text(pdf)
            if text:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(text)
        names, iso = heading(text)
        first = re.split(r"[,;]|\band\b", names)[0].strip() if names else ""
        # the sponsor list's label, e.g. "Smith, A." when two members share a surname: the text then
        # prints the initial too ("A. Smith")
        surname, _, initial = (x.strip() for x in b["sponsor_text"].partition(","))
        squash = lambda s: re.sub(r"[^a-z]", "", s.lower())
        want = squash(initial + surname) if initial else squash(surname)
        match = "" if not text else "Unavailable" if not names else "Yes" if squash(first).endswith(want) else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{bien} Regular Session",
                    "BillNumber": f"{typ}{num}", "BillId": f"WA-{bien[:4]}-{typ}{num}", "Title": b["title"],
                    "IntroducedDate": iso, "House": b["chamber"].upper(), "AuthorName": b["original_sponsor"],
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
