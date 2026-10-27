#!/usr/bin/env python3
"""
Oregon state bills and resolutions, 2007-2009, from the Oregon Legislature's public OData service
(api.oregonlegislature.gov) and OLIS (olis.oregonlegislature.gov), for population members who
served in the Legislature before LegiScan's Oregon coverage (2010 special session on). Oregon
state-text pilot (2026-10-26). Neither host has a robots.txt. The OData service starts with the
2007 session; earlier sessions have no sponsor or document records online.

  --lists    Each session's MeasureSponsors (SponsorLevel Chief/Regular with a PrintOrder). A measure's
             first chief sponsor is its chief sponsor with the lowest print order; measures whose first
             chief sponsor is a reviewed legislator code
             (replication/data/reference/or_legislator_codes_2007_2009.csv) are kept.
  --texts    The measure's "Introduced" document (MeasureDocuments -> OLIS PDF), read with pdfplumber.
             Its heading ("Sponsored by Representative MERKLEY ...") must name the person first.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under or_olis_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/or_olis_bills.py --lists
    python3 replication/scripts/state/or_olis_bills.py --texts [--limit N]
"""

import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ODATA = "https://api.oregonlegislature.gov/odata/odataservice.svc"
CACHE = "or_olis_cache"
SESSIONS = {"2007R1": "2007 Regular Session", "2008S1": "2008 Special Session", "2009R1": "2009 Regular Session"}
CODES = "replication/data/reference/or_legislator_codes_2007_2009.csv"
LIST_OUT = "or_chief_sponsored_measures.csv"
TEXT_OUT = "or_state_legislation_sponsored.csv"
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


def odata(table, session, page=1000):
    """All rows of an OData table for a session, a page at a time (cached per page)."""
    rows, skip = [], 0
    while True:
        q = urllib.parse.urlencode({"$filter": f"SessionKey eq '{session}'", "$top": page, "$skip": skip,
                                    "$format": "json"}, quote_via=urllib.parse.quote)
        body = cached(os.path.join(CACHE, "odata", f"{table}_{session}_{skip}.json"),
                      lambda: fetch(f"{ODATA}/{table}?{q}"))
        batch = json.loads(body or b"{}").get("value", [])
        rows += batch
        if len(batch) < page:
            return rows
        skip += page


def crawl_lists():
    with open(CODES, newline="", encoding="utf-8") as f:
        codes = {(r["session"], r["code"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    out = []
    for session, label in SESSIONS.items():
        chiefs = {}
        for s in odata("MeasureSponsors", session):
            if s["SponsorLevel"] == "Chief" and (s["LegislatoreCode"] or s["CommitteeCode"]):
                key = (s["MeasurePrefix"], s["MeasureNumber"])
                chiefs.setdefault(key, []).append((int(s["PrintOrder"] or 0), s["LegislatoreCode"] or s["CommitteeCode"]))
        titles = {(m["MeasurePrefix"], m["MeasureNumber"]): m for m in odata("Measures", session)}
        n = 0
        for (prefix, num), lst in sorted(chiefs.items()):
            first = sorted(lst)[0][1]
            r = codes.get((session, first))
            if r:
                m = titles.get((prefix, num), {})
                out.append({"session": session, "label": label, "bioguide_id": r["bioguide_id"], "name": r["name"],
                            "code": first, "surname": r["surname"], "bill": f"{prefix}{num}",
                            "title": m.get("RelatingTo") or m.get("CatchLine") or "",
                            "chief_sponsors": "; ".join(c for _, c in sorted(lst))})
                n += 1
        print(f"{session}: {n} measures", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} measures")


def pdf_text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text(x_tolerance=1.5) or "") for p in pdf.pages)


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    if limit:
        items = items[:limit]
    docs = {}
    for session in SESSIONS:
        for d in odata("MeasureDocuments", session):
            if d["VersionDescription"] == "Introduced":
                docs[(session, f"{d['MeasurePrefix']}{d['MeasureNumber']}")] = d["DocumentUrl"]
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for i, b in enumerate(items, 1):
        session, bill = b["session"], b["bill"]
        txt = os.path.join(CACHE, "texts", f"{session}_{bill}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        elif (session, bill) in docs:
            local = os.path.join(CACHE, "pdf", f"{session}_{bill}.pdf")
            raw = cached(local, lambda: fetch(docs[(session, bill)]))
            if raw[:4] == b"%PDF":
                text = pdf_text(local)
            if text.strip():
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        head = " ".join(text.split("\n")[:25])
        m = re.search(r"Sponsored by\s+(?:Representatives?|Senators?|Speaker|President)?\s*(.*?)(?:;|\(|\s{2}|SUMMARY|$)", head)
        names = " ".join(m.group(1).split()) if m else ""
        first = re.split(r",| and ", names)[0].strip() if names else ""
        ok = sq(first).endswith(sq(b["surname"])) if first else False
        match = "" if not text else "Unavailable" if not names else "Yes" if ok else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": b["label"], "BillNumber": bill,
                    "BillId": f"OR-{session}-{bill}", "Title": b["title"], "IntroducedDate": "",
                    "House": "HOUSE" if bill.startswith("H") else "SENATE", "AuthorName": first or b["code"],
                    "IntroducedBy": names[:200], "IntroducedByMatch": match, "TextVersion": "Introduced",
                    "TextPath": txt if text.strip() else ""})
        if i % 100 == 0:
            print(f"  ...{i}/{len(items)}", flush=True)
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
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N measures (smoke test)")
    args = ap.parse_args()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
