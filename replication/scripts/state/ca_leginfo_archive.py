#!/usr/bin/env python3
"""
California state bills, 1993-1998, from the Legislature's older public website
(www.leginfo.ca.gov), for population members who served in the California
Legislature in those years. Part of the California state-text pilot (Ardis,
2026-10-17); 1999-2008 comes from ca_pubinfo_bills.py, 2009 on from LegiScan.
The Legislature's database downloads for 1993-1998 hold only chaptered bills,
which is why this uses the website.

STEPS (no model in the loop):
  1. Per-session bill indexes (one per house), which list every bill with its
     author: pub/<93-94|95-96|97-98>/bill/index_<assembly|senate>_bill_author_topic.
  2. Bills whose index author is one of our people, per the reviewed list
     replication/data/reference/ca_index_authors_1993_1998.csv (author name as
     printed, by session and house; e.g. Juanita Millender-McDonald is "McDonald").
     The index author is the bill's author (sponsor).
  3. For each bill, the site's bill listing (cgi-bin/postquery) gives the introduced
     version: a link for 1995-1998; for 1993-1994 the version is listed with its
     date but not linked, and the file is fetched from its standard path
     (<dir>/<bill>_bill_<yymmdd>_introduced).
  4. The introduced text, with HTML markup removed.
  5. The index lists a bill's final author, and California authorship can be transferred
     after introduction. To match the 1999-2008 rule (primary author of the introduced
     version), IntroducedByMatch = Yes only when the person's name appears in the text's
     "INTRODUCED BY" block; build_tables.py keeps only those rows.

Polite crawling: one request at a time, at least 1.5 seconds apart, with a User-Agent
naming the project. Every response is cached under ca_leginfo_cache/, so a re-run
only fetches what is missing.

OUTPUT (local, gitignored):
    ca_leginfo_cache/                       raw indexes, listings and texts
    ca_leginfo_state_legislation_sponsored.csv   one row per (person, bill)

USAGE (from the repo root):
    python3 replication/scripts/state/ca_leginfo_archive.py [--limit N]
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.leginfo.ca.gov"
CACHE = "ca_leginfo_cache"
AUTHORS = "replication/data/reference/ca_index_authors_1993_1998.csv"
OUT = "ca_leginfo_state_legislation_sponsored.csv"
SESSIONS = {"93-94": "9394", "95-96": "9596", "97-98": "9798"}
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
MIN_GAP = 1.5
_last = [0.0]


def get(path, cache_path):
    """Fetch BASE+path once; cached on disk. Returns text, or None for 404."""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="latin-1") as f:
            return f.read()
    for attempt in range(5):
        wait = MIN_GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read().decode("latin-1")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = None
                break
            time.sleep(10 * (attempt + 1))
        except Exception:
            time.sleep(10 * (attempt + 1))
    else:
        raise SystemExit(f"giving up on {path}")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="latin-1") as f:
        f.write(data if data is not None else "")
    return data


def index_rows(session, house):
    text = get(f"/pub/{session}/bill/index_{house}_bill_author_topic",
               os.path.join(CACHE, session, f"index_{house}.txt"))
    rows, cur = [], None
    for ln in text.split("\n"):
        m = re.match(r"^([A-Z]{2,4}(?:X\d+)?)\s+(\d+)\s+(\S.*?)\s{2,}(\S.*)$", ln.rstrip())
        if m:
            cur = {"type": m.group(1), "num": int(m.group(2)), "author": m.group(3).strip(), "topic": m.group(4).strip()}
            rows.append(cur)
        elif cur and ln.startswith(" " * 20) and ln.strip():
            cur["topic"] += " " + ln.strip()
    return rows


def strip_html(s):
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</pre>|</h\d>|</tr>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    s = re.sub(r"[ \t]+\n", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def introduced(session, bill_type, num):
    """(text, date, url) of the introduced version, or (None, None, reason)."""
    key = f"{bill_type.lower()}_{num}"
    listing = get("/cgi-bin/postquery?" + urllib.parse.urlencode(
        {"bill_number": key, "sess": SESSIONS[session], "house": "B", "author": ""}),
        os.path.join(CACHE, session, "listing", key + ".html"))
    hrefs = re.findall(r'href="(/pub/[^"]+)"', listing or "", flags=re.I)
    link = next((h for h in hrefs if re.search(r"_introduced(\.html?)?$", h)), None)
    if not link:
        # 1993-94: "Introduced - 03/01/93" is listed but not linked; the file sits next to the others
        m = re.search(r"Introduced\s*-\s*(\d\d)/(\d\d)/(\d\d)", re.sub(r"<[^>]+>", " ", listing or ""))
        folder = next((h.rsplit("/", 1)[0] for h in hrefs if f"/{key}_" in h), None)
        if not (m and folder):
            return None, None, "no introduced version listed"
        link = f"{folder}/{key}_bill_{m.group(3)}{m.group(1)}{m.group(2)}_introduced"
    raw = get(link, os.path.join(CACHE, session, "text", link.rsplit("/", 1)[1]))
    if not raw:
        return None, None, f"introduced file not found: {link}"
    text = strip_html(raw) if "<" in raw[:500] else raw.strip()
    d = re.search(r"_(\d{6}|\d{8})_introduced", link).group(1)
    date = (f"19{d[0:2]}-{d[2:4]}-{d[4:6]}" if len(d) == 6 else f"{d[0:4]}-{d[4:6]}-{d[6:8]}")
    return text, date, BASE + link


def introduced_by_match(text, author):
    """Yes if the author's name is in the text's INTRODUCED BY block (introducers and coauthors,
    up to the date line), No if not, '' when there is no text or no such block."""
    if not text:
        return ""
    m = re.search(r"INTRODUCED BY(.*?)(?:\n\s*[A-Z]+ \d{1,2}, \d{4}|An act|Assembly Concurrent|Senate Concurrent|"
                  r"Assembly Joint|Senate Joint|Assembly Constitutional|Senate Constitutional)", text, flags=re.S)
    if not m:
        return ""
    block = m.group(1)
    introducers = re.split(r"\(\s*(?:Principal\s+)?[Cc]oauthors?", block)[0]  # lead introducers only
    return "Yes" if author.rstrip(".") in introducers else "No"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the first N bills (smoke test)")
    args = ap.parse_args()
    with open(AUTHORS, newline="", encoding="utf-8") as f:
        authors = {(r["session"], r["house"], r["author_name"]): r for r in csv.DictReader(f)}

    todo = []
    for session in SESSIONS:
        for house in ("assembly", "senate"):
            for b in index_rows(session, house):
                a = authors.get((session, house, b["author"]))
                if a:
                    todo.append((session, house, b, a))
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} bills to process")

    out = []
    for i, (session, house, b, a) in enumerate(todo, 1):
        text, date, url = introduced(session, b["type"], b["num"])
        text_path = ""
        if text:
            text_path = os.path.join(CACHE, session, "text", f"{b['type'].lower()}_{b['num']}.txt")
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text)
        x = re.match(r"([A-Z]+?)(?:X(\d+))?$", b["type"])
        year = 1900 + int(session[:2])
        out.append({
            "BioguideId": a["bioguide_id"], "Name": a["name"],
            "Session": f"{year}-{year + 1} " + (f"Extraordinary Session {x.group(2)}" if x.group(2) else "Regular Session"),
            "BillNumber": f"{x.group(1)}{b['num']}", "MeasureType": x.group(1), "SessionNum": x.group(2) or "0",
            "BillId": f"CA-{year}-{x.group(1)}{b['num']}" + (f"X{x.group(2)}" if x.group(2) else ""),
            "Title": b["topic"], "IntroducedDate": date or "", "House": house.upper(),
            "AuthorName": b["author"], "IntroducedByMatch": introduced_by_match(text, b["author"]),
            "SourceUrl": url if text else "", "Error": "" if text else url,
            "TextPath": text_path,
        })
        if i % 100 == 0:
            print(f"  ...{i}/{len(todo)}", flush=True)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text")


if __name__ == "__main__":
    main()
