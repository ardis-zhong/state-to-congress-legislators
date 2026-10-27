#!/usr/bin/env python3
"""
Iowa state bills and resolutions, 1995-2010, from the Iowa Legislature's website (legis.iowa.gov),
for population members who served in the General Assembly before their first LegiScan bills with a
lead-sponsor role (2011 on). Iowa state-text pilot (2026-10-26). robots.txt disallows only
/chambers/.

  --members  Each General Assembly's Senate and House member lists (/legislators/senate|house?ga=)
             link every member's page by a person id. Our people's ids are written as candidates for
             the reviewed list replication/data/reference/ia_person_ids_1995_2010.csv.
  --lists    For each reviewed (ga, person id): "Find a Bill by Sponsor" (/legislation/findLegislation/
             findBillBySponsorOrManager?ga=&pid=) lists the bills and resolutions the person sponsored.
  --texts    The Bill Book's document for the item (/docs/publications/LGI/<ga>/<bill>.pdf): for 1995-2002
             a scan of the bill jacket (cover, the bill as introduced, then the amendments filed to it
             and sometimes the enrolled act), for 2009-2010 the printed bill. The pages before the first
             amendment page ("S-3204", "H-1554", clip sheets) are kept, read with pdfplumber (the scans'
             text layer is OCR). The cover's "BY KING, ..." line must name the person first.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under ia_legis_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/ia_legis_bills.py --members
    python3 replication/scripts/state/ia_legis_bills.py --lists
    python3 replication/scripts/state/ia_legis_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://www.legis.iowa.gov"
CACHE = "ia_legis_cache"
GAS = {76: (1995, 1996), 77: (1997, 1998), 78: (1999, 2000), 79: (2001, 2002), 80: (2003, 2004),
       81: (2005, 2006), 82: (2007, 2008), 83: (2009, 2010)}
PEOPLE = "replication/data/population/person_level.csv"
IDS = "replication/data/reference/ia_person_ids_1995_2010.csv"
CANDIDATES = "ia_person_id_candidates.csv"
LIST_OUT = "ia_sponsored_bills.csv"
TEXT_OUT = "ia_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
AMENDMENT_PAGE = re.compile(r"(?m)^\s*[SH]-\s?\d{4}\b|CLIP SHEET|AMENDMENT TO|^\s*\S{0,3}\s*Amend (?:Senate|House)\s+(?:File|Joint|Concurrent)",
                            re.I)
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


def plain(s):
    t = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return " ".join(t.split())


def ia_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Iowa":
                continue
            ys = set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d)", r["StateLegYears"]):
                ys |= set(range(int(a), int(z) + 1))
            if any(1995 <= y <= 2010 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def find_members():
    rows = []
    people = ia_people()
    for ga, years in GAS.items():
        for chamber in ("senate", "house"):
            page = cached(os.path.join(CACHE, "members", f"{ga}_{chamber}.html"),
                          lambda: fetch(f"{BASE}/legislators/{chamber}?ga={ga}")).decode("utf-8", "replace")
            for pid, name in re.findall(r'href="/legislators/legislator\?ga=\d+&(?:amp;)?personID=(\d+)"[^>]*>(.*?)</a>',
                                        page, re.S):
                name = re.sub(r"\s*\([^)]*\)\s*$", "", plain(name))  # "Leonard L. Boswell (01/09/1995 - 01/01/1997)"
                for p in people:
                    if set(years) & p["years"] and name and name.split()[-1].lower() == p["Name"].split()[-1].lower():
                        rows.append({"ga": ga, "years": f"{years[0]}-{years[1]}", "chamber": chamber, "person_id": pid,
                                     "label": name, "bioguide_id": p["BioguideId"], "name": p["Name"],
                                     "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {IDS}")


def crawl_lists():
    with open(IDS, newline="", encoding="utf-8") as f:
        ids = [r for r in csv.DictReader(f) if r["bioguide_id"]]
    out = []
    for r in ids:
        ga, pid = r["ga"], r["person_id"]
        page = cached(os.path.join(CACHE, "lists", f"{ga}_{pid}.html"),
                      lambda: fetch(f"{BASE}/legislation/findLegislation/findBillBySponsorOrManager?ga={ga}&pid={pid}"))
        page = page.decode("utf-8", "replace")
        sec = page[page.find('id="sponsoredLegislation"'):]
        n = 0
        for m in re.finditer(r'(?s)BillBook\?[^"]*?ba=([A-Z]+\d+)[^"]*"[^>]*>[^<]*</a></td>\s*<td[^>]*>(.*?)</td>', sec):
            out.append({"ga": ga, "years": r["years"], "bioguide_id": r["bioguide_id"], "name": r["name"],
                        "label": r["label"], "bill": m.group(1), "title": plain(m.group(2))})
            n += 1
        print(f"GA {ga} {r['name']}: {n} sponsored", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} items")


def bill_pages(path):
    """Text of the jacket's pages before the first amendment page (the cover and the bill as introduced)."""
    import pdfplumber
    keep = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            t = page.extract_text(x_tolerance=1.5) or ""
            if AMENDMENT_PAGE.search("\n".join(t.split("\n")[:6])):
                break  # an amendment page (if the jacket starts with one, it holds no introduced text)
            keep.append(t)
    return "\n".join(keep)


def close(a, b):
    """Equal, or one OCR error apart ('l<ING' read as 'ling' for KING) when the name has 4+ letters."""
    if a == b:
        return True
    if len(b) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    s, t = (a, b) if len(a) < len(b) else (b, a)
    return any(t[:k] + t[k + 1:] == s for k in range(len(t)))


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    if limit:
        items = items[:limit]
    print(f"{len(items)} items to fetch", flush=True)
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for i, b in enumerate(items, 1):
        ga, bill = b["ga"], b["bill"]
        txt = os.path.join(CACHE, "texts", f"{ga}_{bill}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            local = os.path.join(CACHE, "pdf", f"{ga}_{bill}.pdf")
            raw = cached(local, lambda: fetch(f"{BASE}/docs/publications/LGI/{ga}/{bill}.pdf"))
            if raw[:4] == b"%PDF":
                text = bill_pages(local)
            if text.strip():
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        # "BY KING, SMITH, and JONES" on the cover (a resolution's line may start with its line number)
        m = re.search(r"(?m)^\s*(?:\d{1,2}\s+){0,2}BY\s+(?!THE GENERAL|THE SENATE|THE HOUSE)(\S[^\n]*)$", text[:2500])
        names = " ".join(m.group(1).split()) if m else ""
        first = re.split(r",|\s+(?i:and)\s+", names)[0].strip() if names else ""
        last = b["name"].split()[-1]
        ok = bool(first) and close(sq(first), sq(last))
        garbled = bool(re.search(r"[^A-Za-z.' \-]", first))  # OCR noise ('i<I :\G'): unreadable, not a mismatch
        match = "" if not text else "Unavailable" if not names else "Yes" if ok else "Unavailable" if garbled else "No"
        y0, y1 = b["years"].split("-")
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{y0}-{y1} Session ({ga}th General Assembly)",
                    "BillNumber": bill, "BillId": f"IA-GA{ga}-{bill}", "Title": b["title"], "IntroducedDate": "",
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
