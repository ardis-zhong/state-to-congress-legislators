#!/usr/bin/env python3
"""
New York Assembly and Senate bills, 1999-2008 (the 1999-2000 to 2007-2008 terms), from the New York
State Assembly's bill pages (nyassembly.gov/leg/, from the 1999 term on; robots.txt closes the site only
to GPTBot), for population members who served in the Legislature before LegiScan's New York coverage
(2009 on). New York state-text pilot (2026-10-27).

The site has no list of bills by sponsor for past terms, so every bill is read by number:
/leg/?bn=A00100&term=1999&Summary=Y&Text=Y gives the bill's SPONSOR and its text in one page. Assembly
bills (A) are read for every term; Senate bills (S) only for the terms in which a population member sat
in the Senate. A term's numbers are read until 1,000 in a row are missing (the numbering has gaps of a few
hundred, e.g. 1999 A07716-A07999). Bills whose SPONSOR is a
reviewed (term, chamber, sponsor) in replication/data/reference/ny_sponsors_1999_2008.csv are kept, and
their text's "Introduced by M. of A. MORELLE, ..." / "Introduced by Sen. KUHL" line must name the person
first (IntroducedByMatch). Bills introduced by the Rules Committee "at request of" a member are not the
member's. Resolutions (K, J, B) are not read.

The site shows only a bill's latest printing, so an amended bill (BILL NO A09999A) has its amended text
(text_version Amended); the printing still names the original introducers.

Polite: one request at a time, at least 1 second apart (about a day in all), a User-Agent naming the
project; every bill's sponsor is logged to ny_assembly_cache/sponsors/<term>_<chamber>.tsv (so the scan
resumes where it stopped) and the pages of candidate bills are cached under ny_assembly_cache/pages/.

USAGE (from the repo root):
    python3 replication/scripts/state/ny_assembly_bills.py --scan [--limit N]
    python3 replication/scripts/state/ny_assembly_bills.py --texts
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://nyassembly.gov/leg/"
CACHE = "ny_assembly_cache"
SPONSORS = "replication/data/reference/ny_sponsors_1999_2008.csv"
TERMS = [1999, 2001, 2003, 2005, 2007]
SENATE_TERMS = [1999, 2001, 2003]  # Randy Kuhl (State Senate 1987-2004)
TEXT_OUT = "ny_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 1
MAX_MISSING = 1000  # consecutive missing numbers that end a term
_last = [0.0]


def fetch(url):
    """One polite request (no cache): the body as bytes, None if it keeps failing."""
    for attempt in range(5):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                return r.read()
        except Exception:
            time.sleep(30 * (attempt + 1))
    print(f"  could not fetch {url}", flush=True)
    return None


def plain(page):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


def surnames():
    """Upper-case surnames worth caching pages for (reviewed afterwards against the sponsor log)."""
    with open(SPONSORS, newline="", encoding="utf-8") as f:
        return {r["sponsor"].upper() for r in csv.DictReader(f)}


def scan(limit=0):
    keep = surnames()
    done_total = 0
    for chamber, terms in (("A", TERMS), ("S", SENATE_TERMS)):
        for term in terms:
            log = os.path.join(CACHE, "sponsors", f"{term}_{chamber}.tsv")
            os.makedirs(os.path.dirname(log), exist_ok=True)
            seen = {}
            if os.path.exists(log):
                with open(log, encoding="utf-8") as f:
                    for line in f:
                        num, bill_no, sponsor = line.rstrip("\n").split("\t")
                        seen[int(num)] = (bill_no, sponsor)
            if seen.get(-1):
                continue  # term finished
            num = max(seen) if seen else 0
            missing = 0
            for n in sorted(seen, reverse=True):  # trailing misses already logged
                if seen[n][0]:
                    break
                missing += 1
            with open(log, "a", encoding="utf-8") as out:
                while missing < MAX_MISSING:
                    num += 1
                    bn = f"{chamber}{num:05d}"
                    page = fetch(f"{BASE}?bn={bn}&term={term}&Summary=Y&Text=Y")
                    if page is None:
                        num -= 1
                        time.sleep(300)
                        continue
                    page = page.decode("utf-8", "replace")
                    s = " ".join(plain(page).split())
                    m = re.search(r"BILL NO (\S+) SAME AS .*? SPONSOR (.*?) COSPNSR", s)
                    if not m:
                        missing += 1
                        out.write(f"{num}\t\t\n")
                        out.flush()
                        continue
                    missing = 0
                    bill_no, sponsor = m.group(1), m.group(2).strip()
                    out.write(f"{num}\t{bill_no}\t{sponsor}\n")
                    out.flush()
                    if any(k in sponsor.upper() for k in keep):
                        p = os.path.join(CACHE, "pages", str(term), f"{bn}.html")
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                        with open(p, "w", encoding="utf-8") as f:
                            f.write(page)
                    done_total += 1
                    if limit and done_total >= limit:
                        return
                    if num % 500 == 0:
                        print(f"  {term} {chamber}: up to {bn}", flush=True)
                out.write("-1\tdone\t\n")
            print(f"{term} {chamber}: {num - missing} numbers read", flush=True)


def crawl_texts():
    with open(SPONSORS, newline="", encoding="utf-8") as f:
        reviewed = {(int(r["term"]), r["chamber"], r["sponsor"].upper()): r for r in csv.DictReader(f) if r["bioguide_id"]}
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for chamber, terms in (("A", TERMS), ("S", SENATE_TERMS)):
        for term in terms:
            log = os.path.join(CACHE, "sponsors", f"{term}_{chamber}.tsv")
            if not os.path.exists(log):
                continue
            with open(log, encoding="utf-8") as f:
                rows = [line.rstrip("\n").split("\t") for line in f]
            for num, bill_no, sponsor in rows:
                r = reviewed.get((term, chamber, re.sub(r"\s*\(MS\)$", "", sponsor).upper()))  # (MS) = multi-sponsored
                if not r or int(num) < 0:
                    continue
                bn = f"{chamber}{int(num):05d}"
                p = os.path.join(CACHE, "pages", str(term), f"{bn}.html")
                with open(p, encoding="utf-8") as f:
                    page = f.read()
                text = plain(page)
                i = text.find("STATE OF NEW YORK")
                text = text[i:] if i >= 0 else ""
                text = re.split(r"\n\s*(?:Go to top|Sitemap)\b", text)[0]
                text = re.sub(r"[ \t\xa0]+", " ", text)
                text = re.sub(r"\n\s*\n+", "\n", text).strip()
                # uni-bills ('SENATE - ASSEMBLY') print both chambers' introducers: read this chamber's line
                intro = r"M\.\s*of\s*A\." if chamber == "A" else r"Sens?\."
                by = re.search(r"Introduced\s+by\s+" + intro + r"\s*(.+?)\s+--", text[:3000], re.S)
                names = " ".join(by.group(1).split()) if by else ""
                first = re.split(r",| and ", names)[0].strip() if names else ""
                match = "" if not text else "Unavailable" if not names else "Yes" if sq(first).endswith(sq(r["surname"])) else "No"
                d = re.search(r"(?:IN (?:ASSEMBLY|SENATE)|SENATE - ASSEMBLY)\s*(?:\(Prefiled\))?\s*([A-Z][a-z]+ \d{1,2}, \d{4})", text[:1500])
                date = time.strftime("%Y-%m-%d", time.strptime(d.group(1), "%B %d, %Y")) if d else ""
                title = ""
                t = re.search(r"\b(AN ACT|CONCURRENT RESOLUTION)\b(.+?)(?:The People of the State|Section 1|$)", text, re.S)
                if t:
                    title = " ".join((t.group(1) + t.group(2)).split())[:300]
                txt = os.path.join(CACHE, "texts", str(term), f"{bn}.txt")
                if text:
                    os.makedirs(os.path.dirname(txt), exist_ok=True)
                    with open(txt, "w", encoding="utf-8") as f:
                        f.write(text)
                out.append({"BioguideId": r["bioguide_id"], "Name": r["name"],
                            "Session": f"{term}-{term + 1} Regular Sessions", "BillNumber": bill_no,
                            "BillId": f"NY-{term}-{bn}", "Title": title, "IntroducedDate": date,
                            "House": "HOUSE" if chamber == "A" else "SENATE", "AuthorName": first or sponsor,
                            "IntroducedBy": names[:200], "IntroducedByMatch": match,
                            "TextVersion": "Amended" if re.search(r"\d[A-Z]$", bill_no) else "Introduced",
                            "TextPath": txt if text else ""})
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="--scan: stop after N bills (smoke test)")
    args = ap.parse_args()
    if args.scan:
        scan(args.limit)
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
