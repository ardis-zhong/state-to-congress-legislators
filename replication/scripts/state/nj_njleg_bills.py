#!/usr/bin/env python3
"""
New Jersey state bills, 2000-2009, from the New Jersey Legislature's website (njleg.state.nj.us),
for population members who served in the Legislature before LegiScan's New Jersey coverage
(2010 on). New Jersey state-text pilot (Ardis, 2026-10-25). The website's bill data (the JSON
service its pages use) covers the 2000-01 session on; for 1996-99 it holds only bill-tracking
databases without text.

  --members  The bill-search page's data lists every session's sponsors with a roster key
             ("Lance, Leonard (As Asm)", 71); our people's entries are written as candidates for the
             reviewed list replication/data/reference/nj_roster_keys_2000_2009.csv.
  --lists    For each reviewed (session, roster key): the sponsor search
             (/api/billSearchHist/combinedSponsorSearch/.../<key>/.../<session>), which gives each
             bill with the person's sponsor type and order; bills on which the person is the first
             prime sponsor (Type_of_Sponsor P, Sponsor_Key 1) are kept.
  --texts    Each bill's documents (/api/billDetailHist/billText/<bill>/<session>), and the
             "Introduced" one (pub.njleg.state.nj.us/Bills/...). Its heading names the sponsors
             ("INTRODUCED JANUARY 20, 2000 Sponsored by: Assemblyman LEONARD LANCE ..."); a bill
             counts when the person is named first (IntroducedByMatch).

Polite: one request at a time, at least 2 seconds apart (robots.txt allows all), a User-Agent
naming the project, every response cached under nj_njleg_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/nj_njleg_bills.py --members
    python3 replication/scripts/state/nj_njleg_bills.py --lists
    python3 replication/scripts/state/nj_njleg_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import json
import os
import re
import time
import urllib.error
import urllib.request

SITE = "https://www.njleg.state.nj.us"
PUB = "https://pub.njleg.state.nj.us"
CACHE = "nj_njleg_cache"
SESSIONS = (2000, 2002, 2004, 2006, 2008)
PEOPLE = "replication/data/population/person_level.csv"
KEYS = "replication/data/reference/nj_roster_keys_2000_2009.csv"
CANDIDATES = "nj_roster_key_candidates.csv"
LIST_OUT = "nj_first_prime_bills.csv"
TEXT_OUT = "nj_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
_last = [0.0]
MONTHS = {m: i for i, m in enumerate("JANUARY FEBRUARY MARCH APRIL MAY JUNE JULY AUGUST SEPTEMBER OCTOBER "
                                     "NOVEMBER DECEMBER".split(), 1)}


def get(url, cache_path):
    """Fetch url once (cached) as bytes. Returns b'' for a 404; a page that keeps failing is skipped
    (not cached) so a re-run tries it again."""
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
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
        return b""
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(data)
    return data


def plain(s):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def nj_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "New Jersey" and "New Jersey" not in r["StateLegChamber"]:
                continue
            s, ys = re.sub(r"\bpresent\b", "2026", r["StateLegYears"], flags=re.I), set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*(?:[A-Za-z]+\s+)?((?:19|20)\d\d)", s):
                ys |= set(range(int(a), int(z) + 1))
            if any(2000 <= y <= 2009 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def roster():
    page = get(f"{SITE}/bill-search", os.path.join(CACHE, "bill-search.html")).decode("utf-8", "replace")
    data = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S).group(1))
    return data["props"]["pageProps"]["sponsors"]


def find_members():
    rows = []
    sponsors = roster()
    for p in nj_people():
        last = {"Bonnie Watson Coleman": "watson coleman", "Jeff Van Drew": "van drew",
                "Thomas Kean Jr.": "kean"}.get(p["Name"], p["Name"].split()[-1].lower())
        for s in SESSIONS:
            if s not in p["years"] and s + 1 not in p["years"]:
                continue
            for x in sponsors:
                if x["SessionYear"] == s and x["Full_Name"].lower().startswith(last + ","):
                    rows.append({"session": s, "roster_key": x["Roster_Key"], "full_name": x["Full_Name"],
                                 "bioguide_id": p["BioguideId"], "name": p["Name"], "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {KEYS}")


def crawl_lists():
    with open(KEYS, newline="", encoding="utf-8") as f:
        keys = list(csv.DictReader(f))
    out = []
    for k in keys:
        url = f"{SITE}/api/billSearchHist/combinedSponsorSearch/empty/{k['roster_key']}/empty/empty/empty/empty/empty/{k['session']}"
        data = json.loads(get(url, os.path.join(CACHE, "sponsor", f"{k['session']}_{k['roster_key']}.json")) or b"[[]]")
        rows = data[0] if data and isinstance(data[0], list) else []
        total = data[1][0]["BillCount"] if len(data) > 1 and data[1] else None
        if total is not None and total != len(rows):
            print(f"  WARNING {k['session']} {k['name']}: {total} listed, {len(rows)} returned")
        first = [r for r in rows if r.get("Type_of_Sponsor") == "P" and r.get("Sponsor_Key") == 1]
        for r in first:
            out.append({"session": k["session"], "bioguide_id": k["bioguide_id"], "name": k["name"],
                        "full_name": k["full_name"], "bill": r["Bill"].strip(), "synopsis": " ".join((r.get("Synopsis") or "").split())[:300]})
        print(f"{k['session']} {k['name']}: {len(rows)} sponsored, {len(first)} as first prime sponsor", flush=True)
    seen, uniq = set(), []
    for o in out:  # a member with two roster keys in one session (Assembly, then Senate)
        if (o["bioguide_id"], o["session"], o["bill"]) not in seen:
            seen.add((o["bioguide_id"], o["session"], o["bill"]))
            uniq.append(o)
    out = uniq
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} bills")


def heading(text):
    """(first sponsor as printed, ISO date) from 'INTRODUCED JANUARY 20, 2000 Sponsored by:
    Assemblyman LEONARD LANCE District 23 ...' (appropriations acts: 'By Assemblymen LANCE and MALONE')."""
    flat = " ".join(text[:4000].split())
    d = re.search(r"(?:INTRODUCED|PRE-FILED FOR INTRODUCTION IN THE \d{4} SESSION|DATED:?)\s+(" + "|".join(MONTHS) +
                  r")\s+(\d{1,2}),\s*(\d{4})", flat)
    iso = f"{d.group(3)}-{MONTHS[d.group(1)]:02d}-{int(d.group(2)):02d}" if d else ""
    m = (re.search(r"Sponsored by:\s*(?:Assemblyman|Assemblywoman|Senator|Assembly Member)\s+(.*?)\s+(?:District\b|Co-Sponsored)", flat)
         or re.search(r"\bBy (?:Assemblym[ae]n|Assemblywom[ae]n|Senators?)\s+([A-Z][A-Z.' -]*?)(?:,| and\b| AN ACT)", flat))
    return (m.group(1).strip() if m else ""), iso


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        s, bill = b["session"], b["bill"]
        txt = os.path.join(CACHE, "texts", f"{s}_{bill}_I1.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            docs = json.loads(get(f"{SITE}/api/billDetailHist/billText/{bill}/{s}", os.path.join(CACHE, "docs", f"{s}_{bill}.json")) or b"[]")
            intro = next((d for d in docs if d.get("Description") == "Introduced" and d.get("HTML_Link")), None)
            if intro:
                raw = get(PUB + intro["HTML_Link"], os.path.join(CACHE, "texts", f"{s}_{bill}_I1.htm"))
                text = plain(raw.decode("cp1252", "replace")) if raw else ""
            if text:
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        first, iso = heading(text)
        surname = b["full_name"].split(",")[0]
        sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
        bare = re.sub(r",?\s+(JR\.?|SR\.?|III|II|M\.D\.)\s*$", "", first, flags=re.I)  # "HERBERT CONAWAY, JR."
        match = "" if not text else "Unavailable" if not first else "Yes" if sq(bare).endswith(sq(surname)) else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{s}-{int(s) + 1} Regular Session",
                    "BillNumber": bill, "BillId": f"NJ-{s}-{bill}", "Title": b["synopsis"], "IntroducedDate": iso,
                    "House": "HOUSE" if bill.startswith("A") else "SENATE", "AuthorName": first,
                    "IntroducedByMatch": match, "TextVersion": "Introduced", "TextPath": txt if text else ""})
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
