#!/usr/bin/env python3
"""
Rhode Island House bills and resolutions, 1997-2002, from the Rhode Island General Assembly's bill
text archive (webserver.rilegislature.gov, 1997 on; no robots.txt), for David Cicilline (RI House
1995-2002), the only population member who served in the General Assembly after the archive begins
and before LegiScan's Rhode Island coverage. Rhode Island state-text pilot (2026-10-27). The bill
status site (status.rilegislature.gov) is closed to crawlers and is not used.

  --lists    The General Assembly's bill text search (billsearch.rilegislature.gov, /Billtext/ for one
             session year) lists every text that mentions "Cicilline"; the House texts' unsuffixed files
             (H5437.htm; lettered files are substitutes) are the introduced versions.
  --texts    Each text prints "Introduced By: Representatives Cicilline, ..." and "Date Introduced:";
             texts whose first-named introducer is Cicilline are kept (IntroducedByMatch), so bills he
             only co-sponsored, and texts that merely mention the name, drop out.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under ri_rilegislature_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/ri_rilegislature_bills.py --lists
    python3 replication/scripts/state/ri_rilegislature_bills.py --texts
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

SEARCH = "https://billsearch.rilegislature.gov/"
TEXTS = "https://webserver.rilegislature.gov/Billtext"
CACHE = "ri_rilegislature_cache"
YEARS = range(1997, 2003)
PERSON = {"bioguide_id": "C001084", "name": "David Cicilline", "surname": "Cicilline"}
LIST_OUT = "ri_cicilline_candidates.csv"
TEXT_OUT = "ri_state_legislation_sponsored.csv"
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


def crawl_lists():
    out, seen = [], set()
    for year in YEARS:
        page_no, pages = 1, 1
        while page_no <= pages:
            q = urllib.parse.urlencode({"SearchString": PERSON["surname"], "SearchDirectory": "/Billtext/",
                                        "SessionYear": year, "Sort": "DocTitle", "SortOrder": "Asc",
                                        "MaxRecords": 100, "CurrentPageIndex": page_no})
            page = cached(os.path.join(CACHE, "search", f"{year}_{page_no}.html"),
                          lambda: fetch(f"{SEARCH}?{q}")).decode("utf-8", "replace")
            pages = max([pages] + [int(p) for p in re.findall(r"PagerClick\((\d+)\)", page)])
            for url in re.findall(r'href="(https://webserver\.rilegislature\.gov/Billtext/[^"]+)"', page, re.I):
                m = re.search(r"/HouseText\d\d/[Hh](\d{4})[A-Za-z]*\.htm$", url)
                if not m:
                    continue  # Senate texts: Cicilline served in the House
                bill = f"H{m.group(1)}"
                if (year, bill) not in seen:
                    seen.add((year, bill))
                    yy = f"{year % 100:02d}"
                    out.append({"year": year, "bill": bill, "url": f"{TEXTS}/BillText{yy}/HouseText{yy}/{bill}.htm",
                                "found_as": url})
            page_no += 1
        print(f"{year}: {sum(1 for o in out if o['year'] == year)} House texts mention {PERSON['surname']}", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} candidates")


def html_text(raw):
    s = raw.decode("cp1252", "replace")
    s = re.sub(r"(?is)<(script|style|title)[^>]*>.*?</\1>", " ", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def crawl_texts():
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for b in items:
        year, bill = b["year"], b["bill"]
        raw = cached(os.path.join(CACHE, "html", year, f"{bill}.htm"), lambda: fetch(b["url"]))
        text = html_text(raw) if raw else ""
        by = re.search(r"Introduced By\s*:\s*(?:Representatives?|Reps?\.)?\s*(.+?)\s*Date Introduced", text[:3000], re.S)
        names = " ".join(by.group(1).split()) if by else ""
        first = re.split(r",| and ", names)[0].strip() if names else ""
        match = "" if not text else "Unavailable" if not names else "Yes" if sq(first).endswith(sq(PERSON["surname"])) else "No"
        if match != "Yes":
            continue  # co-sponsored, or a text that only mentions the name
        txt = os.path.join(CACHE, "texts", year, f"{bill}.txt")
        os.makedirs(os.path.dirname(txt), exist_ok=True)
        with open(txt, "w", encoding="utf-8") as f:
            f.write(text)
        d = re.search(r"Date Introduced\s*:\s*([A-Za-z]+ \d{1,2}, \d{4})", text)
        date = time.strftime("%Y-%m-%d", time.strptime(d.group(1), "%B %d, %Y")) if d else ""
        t = re.search(r"_{3,}\s*(.+?)\s*Introduced By\s*:", text[:3000], re.S)
        title = " ".join(t.group(1).split()) if t else ""
        title = re.sub(r"^(?:(?:[A-Z] ){2,}[A-Z]\b\s*)+", "", title)  # spaced-out "A N A C T" / "R E S O L U T I O N"
        out.append({"BioguideId": PERSON["bioguide_id"], "Name": PERSON["name"], "Session": f"{year} January Session",
                    "BillNumber": bill, "BillId": f"RI-{year}-{bill}", "Title": title[:300], "IntroducedDate": date,
                    "House": "HOUSE", "AuthorName": first, "IntroducedBy": names[:200], "IntroducedByMatch": match,
                    "TextVersion": "Introduced", "TextPath": txt})
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} texts with {PERSON['surname']} named first (of {len(items)} candidates)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    args = ap.parse_args()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
