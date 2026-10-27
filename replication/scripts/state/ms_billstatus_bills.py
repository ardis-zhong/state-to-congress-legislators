#!/usr/bin/env python3
"""
Mississippi state bills and resolutions, 1999-2009, from the Mississippi Legislature's Bill Status
System (billstatus.ls.state.ms.us), for population members who served in the Legislature before
LegiScan's Mississippi coverage (2010 on). Mississippi state-text pilot (2026-10-27). The site has no
robots.txt. Regular sessions 1999-2009 and the extraordinary sessions listed on sessions.htm.

  --members  Each session's "List of Measures by Author" (/<session>/pdf/h_auth.htm, s_auth.htm; .xml from 2008) links a
             page per member; our people's pages are written as candidates for the reviewed list
             replication/data/reference/ms_author_pages_1999_2009.csv.
  --lists    Each reviewed author page lists the measures the member authored; their document links give
             the PDF folder, and the introduced version is <bill>IN.pdf.
  --texts    The introduced PDF, read with pdfplumber. Its "By: Senator(s) Nunnelee, ..." line must name
             the person first (IntroducedByMatch); co-authored measures are dropped that way.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under ms_billstatus_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/ms_billstatus_bills.py --members
    python3 replication/scripts/state/ms_billstatus_bills.py --lists
    python3 replication/scripts/state/ms_billstatus_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://billstatus.ls.state.ms.us"
CACHE = "ms_billstatus_cache"
PEOPLE = "replication/data/population/person_level.csv"
PAGES = "replication/data/reference/ms_author_pages_1999_2009.csv"
CANDIDATES = "ms_author_page_candidates.csv"
LIST_OUT = "ms_authored_measures.csv"
TEXT_OUT = "ms_state_legislation_sponsored.csv"
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


def sessions():
    """['1999', '2000', ..., '20051E', ...] for 1999-2009."""
    page = cached(os.path.join(CACHE, "sessions.htm"), lambda: fetch(f"{BASE}/sessions.htm")).decode("latin-1")
    return sorted({s for s in re.findall(r"/(\d{4}\w*)/pdf/mainmenu\.htm", page) if 1999 <= int(s[:4]) <= 2009})


def session_label(code):
    year, extra = code[:4], code[4:]
    return f"{year} Regular Session" if not extra else f"{year} {'First Second Third Fourth Fifth'.split()[int(extra[0]) - 1]} Extraordinary Session"


def ms_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Mississippi":
                continue
            ys = set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d)", r["StateLegYears"]):
                ys |= set(range(int(a), int(z) + 1))
            if any(1999 <= y <= 2009 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def find_members():
    rows = []
    people = ms_people()
    for code in sessions():
        for chamber in ("H", "S"):
            ext = "xml" if int(code[:4]) >= 2008 else "htm"  # 2008 on: XML lists (h_auth.xml)
            page = cached(os.path.join(CACHE, "authors", f"{code}_{chamber}.{ext}"),
                          lambda: fetch(f"{BASE}/{code}/pdf/{chamber.lower()}_auth.{ext}")).decode("latin-1")
            links = re.findall(r'(?i)<A HREF="((?:House|Senate)_authors/[^"]+)">([^<]+)</A>', page)
            links += [(h, n) for n, h in re.findall(r"<M\d_NAME>([^<]+)</M\d_NAME>\s*<M\d_LINK>([^<]+)</M\d_LINK>", page)]
            for href, label in links:
                label = " ".join(html.unescape(label).split())
                for p in people:
                    last = p["Name"].split()[-1].lower()
                    if int(code[:4]) in p["years"] and re.sub(r"[^a-z]", "", label.lower()).endswith(re.sub(r"[^a-z]", "", last)):
                        rows.append({"session": code, "chamber": chamber, "page": href, "label": label,
                                     "bioguide_id": p["BioguideId"], "name": p["Name"], "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {PAGES}")


def crawl_lists():
    with open(PAGES, newline="", encoding="utf-8") as f:
        pages = [r for r in csv.DictReader(f) if r["bioguide_id"]]
    out = []
    for r in pages:
        code = r["session"]
        page = cached(os.path.join(CACHE, "author_pages", f"{code}_{os.path.basename(r['page'])}"),
                      lambda: fetch(f"{BASE}/{code}/pdf/{r['page']}")).decode("latin-1")
        n = 0
        seen = set()
        docs = re.findall(r'(?i)HREF="[./]*(documents/[^"]+/([A-Z]+\d+)[A-Z]{2}\d?\.pdf)"', page)
        docs += re.findall(r"<MEASURELINK>[./]*(documents/[^<]+/([A-Z]+\d+)[A-Z]{2}\d?\.pdf)</MEASURELINK>", page)
        for doc, bill in docs:
            if bill in seen:
                continue
            seen.add(bill)
            title = (re.search(re.escape(bill) + r"\s*</A>.*?<TD[^>]*>(.*?)</TD>", page, re.S | re.I)
                     or re.search(r"<MEASURE>" + re.escape(bill) + r"</MEASURE>.*?<SHORTTITLE>(.*?)</SHORTTITLE>", page, re.S))
            folder = doc.rsplit("/", 1)[0]
            out.append({"session": code, "bioguide_id": r["bioguide_id"], "name": r["name"], "label": r["label"],
                        "bill": bill, "title": " ".join(html.unescape(re.sub(r"<[^>]+>", " ", title.group(1))).split()) if title else "",
                        "intro_url": f"{BASE}/{folder}/{bill}IN.pdf"})
            n += 1
        print(f"{code} {r['name']}: {n} measures", flush=True)
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
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for i, b in enumerate(items, 1):
        code, bill = b["session"], b["bill"]
        txt = os.path.join(CACHE, "texts", f"{code}_{bill}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            local = os.path.join(CACHE, "pdf", f"{code}_{bill}IN.pdf")
            raw = cached(local, lambda: fetch(b["intro_url"]))
            if raw[:4] == b"%PDF":
                text = pdf_text(local)
            if text.strip():
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        m = re.search(r"By:\s*(?:Senators?\(s\)|Representatives?\(s\)|Senators?|Representatives?)?\s*(.+?)(?:\s+To:|\n)", text[:800])
        names = " ".join(m.group(1).split()) if m else ""
        first = re.sub(r"\(By Request\)", "", re.split(r",| and ", names)[0], flags=re.I).strip() if names else ""
        last = b["name"].split()[-1]
        ok = bool(first) and sq(first).endswith(sq(last))
        match = "" if not text.strip() else "Unavailable" if not names else "Yes" if ok else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": session_label(code), "BillNumber": bill,
                    "BillId": f"MS-{code}-{bill}", "Title": b["title"], "IntroducedDate": "",
                    "House": "HOUSE" if bill.startswith("H") else "SENATE", "AuthorName": first or b["label"],
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
    ap.add_argument("--members", action="store_true")
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N measures (smoke test)")
    args = ap.parse_args()
    if args.members:
        find_members()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
