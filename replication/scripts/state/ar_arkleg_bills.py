#!/usr/bin/env python3
"""
Arkansas state bills and resolutions, 1991-2010, from the Arkansas State Legislature's website
(arkleg.state.ar.us), for population members who served in the General Assembly before LegiScan's
Arkansas coverage (2011 on). Arkansas state-text pilot (2026-10-26). robots.txt allows all agents
except ChatGPT.

  --members  Each session's legislator list (/Legislators/List?ddBienniumSession=<code>) links every
             member's page by a key (usually the surname). Our people's keys are written as
             candidates for the reviewed list replication/data/reference/ar_member_keys_1991_2010.csv.
  --lists    Each reviewed (session, key): the member page's "Primary Sponsor" section lists the
             bills and resolutions the person sponsored as lead sponsor.
  --texts    Each item's page (/Bills/Detail) links the bill PDF; its heading names the sponsors
             ("By: Senator Ross"; "By: Representatives Pryor, Smith"), which must name the person
             first (IntroducedByMatch). A PDF headed "As Engrossed: ..." is a later printing
             (text_version Engrossed); otherwise it is the bill as filed.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under ar_arkleg_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/ar_arkleg_bills.py --members
    python3 replication/scripts/state/ar_arkleg_bills.py --lists
    python3 replication/scripts/state/ar_arkleg_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import subprocess
import time
import urllib.parse

BASE = "https://arkleg.state.ar.us"
CACHE = "ar_arkleg_cache"
FIRST, LAST = 1991, 2010
PEOPLE = "replication/data/population/person_level.csv"
KEYS = "replication/data/reference/ar_member_keys_1991_2010.csv"
CANDIDATES = "ar_member_key_candidates.csv"
LIST_OUT = "ar_primary_sponsored_bills.csv"
TEXT_OUT = "ar_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
_last = [0.0]


def fetch(url):
    """One polite request (no cache) through curl (the site needs TLS 1.3, which this Python's LibreSSL
    lacks): the body as bytes, b'' for a 404, None if it keeps failing."""
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = subprocess.run(["curl", "-s", "-L", "-A", UA, "-m", "180", "-w", "\n%{http_code}", url], capture_output=True)
        body, _, code = r.stdout.rpartition(b"\n")
        if r.returncode == 0 and code == b"200":
            return body
        if r.returncode == 0 and code == b"404":
            return b""
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


def slug(code):
    return code.replace("/", "")


def sessions():
    """{code: (year met, label)} for 1991-2010, from a member page's "View Bills by Session" selector
    (Mike Ross's, whose Senate service, 1991-2000, spans every session our people served in here;
    nobody in the population served 2001-2010)."""
    page = cached(os.path.join(CACHE, "sessions_ross.html"),
                  lambda: fetch(f"{BASE}/Legislators/Detail?member=Ross&ddBienniumSession=1995%2FR")).decode("utf-8", "replace")
    out = {}
    for code, label in re.findall(r'<option[^>]*value="(\d{4}/[A-Z]\d?)"[^>]*>([^<]+)', page):
        label = " ".join(html.unescape(label).split())
        met = int(re.findall(r"(?:19|20)\d\d", label)[-1])  # "1991 - First Extraordinary Session, 1992" met in 1992
        if FIRST <= met <= LAST:
            out[code] = (met, label)
    return out


def ar_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Arkansas":
                continue
            ys = set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d)", r["StateLegYears"]):
                ys |= set(range(int(a), int(z) + 1))
            if any(FIRST <= y <= LAST for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def find_members():
    rows = []
    people = ar_people()
    for code, (met, label) in sorted(sessions().items()):
        page = cached(os.path.join(CACHE, "members", f"{slug(code)}.html"),
                      lambda: fetch(f"{BASE}/Legislators/List?ddBienniumSession={urllib.parse.quote(code, safe='')}"))
        keys = sorted(set(re.findall(r"Detail\?member=([^&\"]+)&amp;ddBienniumSession", page.decode("utf-8", "replace"))))
        for p in people:
            if met not in p["years"]:
                continue
            last = p["Name"].split()[-1].lower()
            for key in keys:
                k = urllib.parse.unquote_plus(html.unescape(key))
                if re.sub(r"^[A-Z]\.\s*", "", k).lower() == last:
                    rows.append({"session": code, "year": met, "label": label, "key": k, "bioguide_id": p["BioguideId"],
                                 "name": p["Name"], "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {KEYS}")


def crawl_lists():
    with open(KEYS, newline="", encoding="utf-8") as f:
        keys = [r for r in csv.DictReader(f) if r["bioguide_id"]]
    out = []
    for r in keys:
        code, key = r["session"], r["key"]
        url = (f"{BASE}/Legislators/Detail?member={urllib.parse.quote(key)}"
               f"&ddBienniumSession={urllib.parse.quote(code, safe='')}")
        page = cached(os.path.join(CACHE, "lists", f"{slug(code)}_{re.sub(r'[^A-Za-z]', '', key)}.html"),
                      lambda: fetch(url)).decode("utf-8", "replace")
        sections = re.split(r'(?s)<div class="row tableSectionHeader"[^>]*>\s*<div[^>]*>\s*', page)
        n = 0
        for sec in sections[1:]:
            if not sec.startswith("Primary Sponsor"):
                continue
            for bill, title in re.findall(r'(?s)aria-label="Bill Number ([A-Z]+\d+)" href="[^"]*">.*?'
                                          r'<div class="col-md-8"[^>]*>(.*?)</div>', sec):
                out.append({"session": code, "year": r["year"], "label": r["label"], "bioguide_id": r["bioguide_id"],
                            "name": r["name"], "key": key, "bill": bill, "title": plain(title)})
                n += 1
        print(f"{code} {r['name']}: {n} as primary sponsor", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} items")


def session_name(label):
    """'1991 - First Extraordinary Session, 1992' -> '1992 First Extraordinary Session (1991 General Assembly)'."""
    ga, kind, met = re.match(r"(\d{4}) - (.*?), (\d{4})", label).groups()
    return f"{met} {kind}" + (f" ({ga} General Assembly)" if ga != met else "")


def pdf_text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text(x_tolerance=1.5) or "") for p in pdf.pages)


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    if limit:
        items = items[:limit]
    print(f"{len(items)} items to fetch", flush=True)
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for i, b in enumerate(items, 1):
        code, bill = b["session"], b["bill"]
        txt = os.path.join(CACHE, "texts", f"{slug(code)}_{bill}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            page = cached(os.path.join(CACHE, "bills", f"{slug(code)}_{bill}.html"),
                          lambda: fetch(f"{BASE}/Bills/Detail?id={bill}"
                                        f"&ddBienniumSession={urllib.parse.quote(code, safe='')}")).decode("utf-8", "replace")
            m = re.search(r'href="(/Home/FTPDocument\?path=[^"]*%2FBills%2F[^"]*?\.pdf)"', page, re.I)
            if m:
                local = os.path.join(CACHE, "pdf", f"{slug(code)}_{bill}.pdf")
                raw = cached(local, lambda: fetch(BASE + html.unescape(m.group(1))))
                if raw[:4] == b"%PDF":
                    text = pdf_text(local)
            if text:
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        # the heading without the printed line numbers ("4 By: Senator Ross"; the name can follow on the next line)
        head = " ".join(re.sub(r"^\d+\s*", "", l) for l in text.split("\n")[:12])
        m = re.search(r"By:\s*(?:Senat\w*|Sens?\.|Representatives?|Reps?\.)?\s*"
                      r"(.*?)(?=\s+By:|\s+For An Act|\s+A Bill|\s+(?i:(?:senate|house) (?:concurrent |joint )?resolution)|$)",
                      head)
        names = " ".join(m.group(1).split()) if m else ""
        first = re.split(r",| and ", names)[0].strip() if names else ""
        last = b["name"].split()[-1]
        ok = sq(first) == sq(last) or sq(first) == sq(b["key"])
        match = "" if not text else "Unavailable" if not names else "Yes" if ok else "No"
        version = "Engrossed" if re.search(r"As Engrossed", head) else "Introduced"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": session_name(b["label"]),
                    "BillNumber": bill, "BillId": f"AR-{slug(code)}-{bill}", "Title": b["title"], "IntroducedDate": "",
                    "House": "HOUSE" if bill.startswith("H") else "SENATE", "AuthorName": first or b["key"],
                    "IntroducedBy": names[:200], "IntroducedByMatch": match, "TextVersion": version,
                    "TextPath": txt if text else ""})
        if i % 100 == 0:
            print(f"  ...{i}/{len(items)}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable"))
          + f"; Engrossed {sum(1 for o in out if o['TextVersion'] == 'Engrossed' and o['TextPath'])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--members", action="store_true")
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N items (smoke test)")
    args = ap.parse_args()
    if args.members:
        find_members()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
