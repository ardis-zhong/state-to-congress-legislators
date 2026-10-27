#!/usr/bin/env python3
"""
South Dakota state bills and resolutions, 1997-2008, from the South Dakota Legislature's public API
(sdlegislature.gov/api, no key; robots.txt closes only the PDF viewer), for population members who
served in the Legislature between its online archive (1997 on) and LegiScan's South Dakota coverage
(2009 on): Mike Rounds (Senate 1997-2000) and Kristi Noem (House 2007-2008). South Dakota state-text
pilot (2026-10-27).

Each chamber names one prime sponsor per measure. A measure is kept when the person is the prime
sponsor (SponsorType "P" in /api/SessionMembers/Bills/<session member id>) and it began in the
person's own chamber, so the person is the first name on the text. Session member ids are reviewed in
replication/data/reference/sd_session_members_1997_2008.csv. The introduced text is the "Introduced"
version (/api/Bills/Versions/<bill id>) as HTML (/api/Documents/<document id>.html); its "Introduced
by: Senators Rounds, ..." line must name the person first (IntroducedByMatch).

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under sd_legis_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/sd_legis_bills.py
"""

import csv
import html
import json
import os
import re
import time
import urllib.error
import urllib.request

API = "https://sdlegislature.gov/api"
CACHE = "sd_legis_cache"
MEMBERS = "replication/data/reference/sd_session_members_1997_2008.csv"
TEXT_OUT = "sd_state_legislation_sponsored.csv"
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


def session_label(year):
    return f"{year[:4]} Special Session" if year.endswith("s") else f"{year} Regular Session"


def html_text(page):
    """The bill text from the document HTML: tags and the converter's stray '-->' lines removed."""
    s = re.sub(r"(?is)<(script|style|title)[^>]*>.*?</\1>", " ", page)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"(?m)^\s*-->\s*$", "", s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def main():
    with open(MEMBERS, newline="", encoding="utf-8") as f:
        members = [r for r in csv.DictReader(f) if r["bioguide_id"]]
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for m in members:
        smid = m["session_member_id"]
        bills = json.loads(cached(os.path.join(CACHE, "member_bills", f"{smid}.json"),
                                  lambda: fetch(f"{API}/SessionMembers/Bills/{smid}")) or b"{}").get("Bills", [])
        surname = m["name"].split()[-1]
        n = 0
        for b in bills:
            bill = b["Bill"]
            num = bill["BillNumber"] if not bill["BillNumber"][0].isalpha() else re.sub(r"^[A-Z]+", "", bill["BillNumber"])
            code = f"{bill['BillType']}{num}"
            if b["SponsorType"] != "P" or not code.startswith(m["chamber"]):
                continue
            versions = json.loads(cached(os.path.join(CACHE, "versions", f"{bill['BillId']}.json"),
                                         lambda: fetch(f"{API}/Bills/Versions/{bill['BillId']}")) or b"[]")
            intro = [v for v in versions if v["BillVersion"] == "Introduced"]
            text, date = "", ""
            if intro:
                doc = intro[0]["DocumentId"]
                page = cached(os.path.join(CACHE, "documents", f"{doc}.html"),
                              lambda: fetch(f"{API}/Documents/{doc}.html")).decode("utf-8", "replace")
                text = html_text(page)
                date = (intro[0]["DocumentDate"] or "")[:10]
            txt = os.path.join(CACHE, "texts", f"{m['year']}_{code}.txt")
            if text:
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
            by = re.search(r"Introduced by:\s*(?:Representatives?|Senators?)\s+([^\n]+)", text[:2000])
            names = " ".join(by.group(1).split()) if by else ""
            first = re.split(r",| and ", names)[0].strip() if names else ""
            match = "" if not text else "Unavailable" if not names else "Yes" if sq(first).startswith(sq(surname)) else "No"
            out.append({"BioguideId": m["bioguide_id"], "Name": m["name"], "Session": session_label(m["year"]),
                        "BillNumber": code, "BillId": f"SD-{m['year']}-{code}", "Title": bill["Title"],
                        "IntroducedDate": date, "House": "SENATE" if m["chamber"] == "S" else "HOUSE",
                        "AuthorName": first or surname, "IntroducedBy": names[:200], "IntroducedByMatch": match,
                        "TextVersion": "Introduced", "TextPath": txt if text else ""})
            n += 1
        print(f"{m['year']} {m['name']}: {n} prime-sponsored measures from their own chamber", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable")))


if __name__ == "__main__":
    main()
