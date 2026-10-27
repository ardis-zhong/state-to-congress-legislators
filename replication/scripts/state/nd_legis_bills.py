#!/usr/bin/env python3
"""
North Dakota House bills and resolutions, 1997-2010 (55th-61st Legislative Assemblies), from the
North Dakota Legislative Branch website (ndlegis.gov), for Rick Berg (ND House 1985-2010), the only
population member who served in the Legislative Assembly in its online archive (1997 on) without
LegiScan rows. North Dakota state-text pilot (2026-10-27). robots.txt allows /assembly/.

  --lists    Each regular session's House journals (/assembly/<asm>/regular/journals/HR<nn>.pdf, from
             journal-index.html) print every first reading as "Reps. Klemin, Berg, Carlson and Sen.
             Wardner introduced: HB 1204: ..."; measures whose first-named introducer is Berg are kept.
             The site's bill index names no sponsors before 2005, so the journals are used for every year.
  --texts    The measure's versions page (regular/bill-index/bi<n>.html) links its PDFs; the
             introduced version is the first one numbered .xx00 (.0100, or .0200 or later when the draft
             was revised before filing; engrossments print "ENGROSSMENT").
             pdfplumber cannot open these PDFs, so pdfminer reads them. The text's "Introduced by ...
             Representatives Berg, ..." line must name Berg first (IntroducedByMatch).

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under nd_legis_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/nd_legis_bills.py --lists
    python3 replication/scripts/state/nd_legis_bills.py --texts
"""

import argparse
import csv
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://ndlegis.gov/assembly"
CACHE = "nd_legis_cache"
ASSEMBLIES = {"55-1997": 55, "56-1999": 56, "57-2001": 57, "58-2003": 58, "59-2005": 59, "60-2007": 60, "61-2009": 61}
PERSON = {"bioguide_id": "B001272", "name": "Rick Berg", "surname": "Berg"}
LIST_OUT = "nd_berg_introduced_measures.csv"
TEXT_OUT = "nd_state_legislation_sponsored.csv"
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


def pdf_text(path):
    from pdfminer.high_level import extract_text
    try:
        return extract_text(path)
    except Exception:
        return ""


def first_name(names):
    """'Klemin, Berg, Carlson and Sen. Wardner' -> 'Klemin'."""
    return re.split(r",| and ", names)[0].strip()


def parse_first_readings(text):
    """(introducers, bill match) for every member-introduced first reading in a journal. The introducer
    list ("Reps. Klemin, Berg and Sen. Wardner") ends at "introduced:"; the bill ("HB 1204: ...") follows,
    sometimes after an "(At the request of ...)" line or a page header."""
    out = []
    for m in re.finditer(r"introduced:", text):
        before = text[max(0, m.start() - 600):m.start()]
        starts = [x.start() for x in re.finditer(r"(?m)^\s*(?:Reps?|Representatives?)\.?\s", before)]
        if not starts or re.search(r"introduced:|Was read", before[starts[-1]:]):
            continue  # a committee, the Legislative Council or an agency introduced it
        who = re.sub(r"\x0c.*?(?:DAY|\d{4})\n", " ", before[starts[-1]:], flags=re.S)
        names = re.sub(r"^\s*(?:Reps?|Representatives?)\.?\s+", "", " ".join(who.split()))
        bill = re.search(r"\b(HB|HCR|HR|HJR)\s+(\d{4})\s*:\s*(.{0,400})", text[m.end():m.end() + 700], re.S)
        if bill:
            out.append((names, bill))
    return out


def crawl_lists():
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for asm, num in ASSEMBLIES.items():
        index = cached(os.path.join(CACHE, "journals", asm, "journal-index.html"),
                       lambda: fetch(f"{BASE}/{asm}/regular/journals/journal-index.html")).decode("utf-8", "replace")
        days = sorted(set(re.findall(r"\./(HR\d+)\.pdf", index)), key=lambda d: int(d[2:]))
        n = 0
        for day in days:
            local = os.path.join(CACHE, "journals", asm, f"{day}.pdf")
            raw = cached(local, lambda: fetch(f"{BASE}/{asm}/regular/journals/{day}.pdf"))
            if raw[:4] != b"%PDF":
                continue
            txt = local[:-4] + ".txt"
            if not os.path.exists(txt):
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(pdf_text(local))
            with open(txt, encoding="utf-8") as f:
                text = f.read()
            for intro in parse_first_readings(text):
                names, m = intro
                if sq(first_name(names)) != sq(PERSON["surname"]):
                    continue
                bill = f"{m.group(1)}{m.group(2)}"
                if any(o["assembly"] == asm and o["bill"] == bill for o in out):
                    continue
                title = " ".join(m.group(3).split())
                title = re.split(r"\s+Was read the first time", title)[0]
                out.append({"assembly": asm, "bill": bill, "number": m.group(2), "journal": day,
                            "introducers": names[:200], "title": title[:300]})
                n += 1
        print(f"{asm}: {len(days)} House journals, {n} measures with Berg first", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} measures")


def crawl_texts():
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for b in items:
        asm, bill, number = b["assembly"], b["bill"], b["number"]
        page = cached(os.path.join(CACHE, "versions", asm, f"bi{number}.html"),
                      lambda: fetch(f"{BASE}/{asm}/regular/bill-index/bi{number}.html")).decode("utf-8", "replace")
        pdfs = list(dict.fromkeys(re.findall(r"\.\./bill-text/(\w+?\d{4})\.pdf", page)))
        # drafts revised before filing are introduced as .0200 or later; amendments end in 01-99
        doc = ([p for p in pdfs if p.endswith("00")] or pdfs or [""])[0]
        txt = os.path.join(CACHE, "texts", asm, f"{bill}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        elif doc:
            local = os.path.join(CACHE, "pdf", asm, f"{doc}.pdf")
            raw = cached(local, lambda: fetch(f"{BASE}/{asm}/regular/bill-text/{doc}.pdf"))
            if raw[:4] == b"%PDF":
                text = pdf_text(local)
                # drop the margin line numbers, which pdfminer prints as lines of their own
                text = re.sub(r"(?m)^\s*\d{1,2}\s*$\n?", "", text)
                text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if text:
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        m = re.search(r"Representatives?\s+([^\n]+)", text[:1500])
        names = " ".join(m.group(1).split()) if m else ""
        first = first_name(names) if names else ""
        match = "" if not text else "Unavailable" if not names else "Yes" if sq(first) == sq(PERSON["surname"]) else "No"
        year = int(asm[3:])
        version = ("Engrossed" if "ENGROSS" in text[:300] else "Enrolled" if "In Regular Session Commencing" in text[:400]
                   else "Introduced") if text else ""
        out.append({"BioguideId": PERSON["bioguide_id"], "Name": PERSON["name"],
                    "Session": f"{year} Regular Session ({ASSEMBLIES[asm]}{'st' if ASSEMBLIES[asm] == 61 else 'th'} Legislative Assembly)",
                    "BillNumber": bill, "BillId": f"ND-{ASSEMBLIES[asm]}-{bill}", "Title": b["title"],
                    "IntroducedDate": "", "House": "HOUSE", "AuthorName": first or PERSON["surname"],
                    "IntroducedBy": names[:200], "IntroducedByMatch": match,
                    "TextVersion": version,
                    "TextPath": txt if text else ""})
        print(f"  {asm} {bill}: {doc or 'no PDF'} {match}", flush=True)
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
    args = ap.parse_args()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
