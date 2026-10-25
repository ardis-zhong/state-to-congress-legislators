#!/usr/bin/env python3
"""
North Carolina state bills, 1989-2008, from the North Carolina General Assembly's website
(ncleg.gov), for population members who served in the General Assembly before LegiScan's North
Carolina coverage (2009 on). North Carolina state-text pilot (Ardis, 2026-10-25). Regular
sessions 1989-2007; the website's bill text starts with the 1989 session.

North Carolina's introduced texts print the sponsors with the primary sponsors first, before a
semicolon ("Sponsors: Representatives Edwards; Culp, Gardner, ..."). The member pages that list
primary-sponsored bills cover 2001 on only, and the site lists no ids for former members, so:

  --lists    For each reviewed (person, session, chamber) in
             replication/data/reference/nc_sponsor_names_1989_2008.csv, the website's bill-text
             search (/Search/BillText, all editions) for the phrases "Representatives <Surname>"
             and "Representative <Surname>" (or "Senators"/"Senator"), also with the person's
             initial ("A. Adams", used when members share a surname), which match where the
             person is named first in a sponsor line.
  --texts    Each candidate as introduced (Edition 1:
             /Sessions/<year>/Bills/<House|Senate>/PDF/<H100>v1.pdf, read with pdfplumber). A bill
             counts when its "Sponsors:" line names the person first (IntroducedByMatch); the date
             under the sponsor block is the introduction date.

Polite: robots.txt asks for Crawl-delay 2; one request at a time, at least 2 seconds apart, a
User-Agent naming the project, every response cached under nc_ncleg_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/nc_ncleg_bills.py --lists
    python3 replication/scripts/state/nc_ncleg_bills.py --texts [--limit N]
"""

import argparse
import csv
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.ncleg.gov"
CACHE = "nc_ncleg_cache"
NAMES = "replication/data/reference/nc_sponsor_names_1989_2008.csv"
LIST_OUT = "nc_first_sponsor_candidates.csv"
TEXT_OUT = "nc_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
_last = [0.0]
MONTHS = {m: i for i, m in enumerate("January February March April May June July August September October "
                                     "November December".split(), 1)}


def get(path, cache_path, binary=False):
    """Fetch BASE+path once (cached). Returns the body, or empty for a 404; a page that keeps
    failing is skipped (not cached) so a re-run tries it again."""
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
            with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"User-Agent": UA}), timeout=180) as r:
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
    return data if binary else data.decode("utf-8", errors="replace")


def pdf_text(path):
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text(x_tolerance=1.5) or "") for page in pdf.pages).strip()
    except Exception:
        return ""


def search(session, chamber, phrase):
    q = urllib.parse.urlencode({"sSearchText": phrase, "sSession": session,
                                "sBillChamber": "1" if chamber == "House" else "2", "sBillType": "3"})
    page = get(f"/Search/BillText?{q}", os.path.join(CACHE, "search", f"{session}_{chamber}_{re.sub(r'[^A-Za-z]', '_', phrase)}.html"))
    return sorted(set(re.findall(rf"/BillLookUp/{session}/([HS]\d+)", page)), key=lambda b: int(b[1:]))


def crawl_lists():
    with open(NAMES, newline="", encoding="utf-8") as f:
        names = list(csv.DictReader(f))
    out, seen = [], set()
    for n in names:
        title = "Representative" if n["chamber"] == "House" else "Senator"
        found = set()
        initial = f"{n['name'][0]}. {n['printed_surname']}"  # members sharing a surname are printed with an initial
        for phrase in (f"{title}s {n['printed_surname']}", f"{title} {n['printed_surname']}",
                       f"{title}s {initial}", f"{title} {initial}"):
            found |= set(search(n["session"], n["chamber"], phrase))
        prefix = "H" if n["chamber"] == "House" else "S"
        for bill in sorted(found, key=lambda b: int(b[1:])):
            if bill.startswith(prefix) and (n["bioguide_id"], n["session"], bill) not in seen:
                seen.add((n["bioguide_id"], n["session"], bill))
                out.append({"session": n["session"], "bioguide_id": n["bioguide_id"], "name": n["name"],
                            "chamber": n["chamber"], "printed_surname": n["printed_surname"], "initial": n["name"][0],
                            "bill": bill})
        print(f"{n['session']} {n['chamber']} {n['name']}: {len(found)} candidates", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} candidate bills")


def sponsors_line(text):
    """(names after 'Sponsors: Representatives', primary sponsors only (before ';'), ISO date)."""
    flat = " ".join(text[:8000].split())
    # the sponsor block ends at its period before a rule (─, – or - repeated) or "Referred to"
    m = re.search(r"Sponsors?:\s*(?:Representatives?|Senators?)\s+(.*?)\.\s*(?:[─–\-]{3,}|Referred|\(Primary|$)", flat)
    names = m.group(1) if m else ""
    primary = names.split(";")[0] if names else ""
    d = re.search(r"(" + "|".join(MONTHS) + r") (\d{1,2}), (\d{4})", flat[m.end():] if m else flat)
    iso = f"{d.group(3)}-{MONTHS[d.group(1)]:02d}-{int(d.group(2)):02d}" if d else ""
    return names, primary, iso


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        s, bill = b["session"], b["bill"]
        folder = "House" if bill.startswith("H") else "Senate"
        pdf = os.path.join(CACHE, "texts", f"{s}_{bill}v1.pdf")
        txt = os.path.join(CACHE, "texts", f"{s}_{bill}v1.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        elif get(f"/Sessions/{s}/Bills/{folder}/PDF/{bill}v1.pdf", pdf, binary=True)[:4] == b"%PDF":
            text = pdf_text(pdf)
            if text:
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        names, primary, iso = sponsors_line(text)
        primary = re.sub(r"\s*\(by request\)", "", primary, flags=re.I)  # introduced on someone's behalf
        first = re.split(r",|\band\b|─", primary)[0].strip().rstrip(".") if primary else ""
        sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
        # the surname alone, or with the person's own initial ("A. Adams"); another member's initial fails
        match = "" if not text else "Unavailable" if not names else \
            "Yes" if sq(first) in (sq(b["printed_surname"]), sq(b["initial"] + b["printed_surname"])) else "No"
        title = re.search(r"Short Title:\s*(.*?)\s*\((?:Public|Local)\)", " ".join(text[:2000].split()))
        kind = re.search(r"(HOUSE|SENATE) (BILL|JOINT RESOLUTION|RESOLUTION) \d+", " ".join(text[:600].split()))
        typ = (bill[0] + {"BILL": "B", "JOINT RESOLUTION": "JR", "RESOLUTION": "R"}[kind.group(2)]) if kind else bill[0]
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{s} Regular Session",
                    "BillNumber": f"{typ}{bill[1:]}", "BillId": f"NC-{s}-{bill}", "Title": title.group(1) if title else "",
                    "IntroducedDate": iso, "House": folder.upper(), "AuthorName": first,
                    "IntroducedBy": names[:200], "IntroducedByMatch": match, "TextVersion": "Introduced",
                    "TextPath": txt if text else ""})
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
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N bills (smoke test)")
    args = ap.parse_args()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
