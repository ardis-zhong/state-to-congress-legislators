#!/usr/bin/env python3
"""
South Carolina state bills, 1993-2008, from the South Carolina Legislature's website
(scstatehouse.gov), for population members who served in the General Assembly before LegiScan's
South Carolina coverage (2009-2010 session on). South Carolina state-text pilot (Ardis, 2026-10-26).
Sessions 110 (1993-1994) to 117 (2007-2008); robots.txt allows these pages.

  --members  Each session's sponsor pulldowns (POST /sponsorsearch.php GETMEMBERS=H|S) list the
             members with their permanent sponsor codes; our people's entries are written as
             candidates for the reviewed list replication/data/reference/sc_sponsor_codes_1993_2008.csv.
  --lists    For each reviewed (session, chamber, code): the sponsor search with "Primary Sponsored
             Bills ONLY", which lists every bill and resolution with its sponsors ("By H. Brown,
             Allison"); items whose first sponsor is the person are kept.
  --texts    Each item's page (/sess<n>_<years>/bills/<number>.htm). It holds the latest printed
             version; from 1999 earlier printings are linked as "Versions of This Bill" (prever/),
             but the introduced printing of an amended bill is not among them. The earliest version
             online is used: its heading ("COMMITTEE REPORT", "AMENDED", ...) gives text_version, and
             a page with no heading is the bill as introduced. Printed later versions name the
             sponsors ("Introduced by Reps. Wilkins, Hawkins, ..."); an item counts when the person
             is named first (IntroducedByMatch). Introduced-only pages print no sponsor line
             (Unavailable: the site's primary-sponsor record is kept).

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under sc_statehouse_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/sc_statehouse_bills.py --members
    python3 replication/scripts/state/sc_statehouse_bills.py --lists
    python3 replication/scripts/state/sc_statehouse_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import subprocess
import time
import urllib.parse

BASE = "https://www.scstatehouse.gov"
CACHE = "sc_statehouse_cache"
SESSIONS = {n: f"{1993 + 2 * (n - 110)}-{1994 + 2 * (n - 110)}" for n in range(110, 118)}
PEOPLE = "replication/data/population/person_level.csv"
CODES = "replication/data/reference/sc_sponsor_codes_1993_2008.csv"
CANDIDATES = "sc_sponsor_code_candidates.csv"
LIST_OUT = "sc_primary_sponsored_bills.csv"
TEXT_OUT = "sc_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
TYPES = {"General Bill": "", "Joint Resolution": "JR", "Concurrent Resolution": "CR", "Resolution": "R"}
# a printed version's heading (its first line) -> text_version; a text that starts with the bill itself
# ("A BILL", "A CONCURRENT RESOLUTION") is the bill as introduced
VERSIONS = [("INTRODUCED", "Introduced"), ("COMMITTEE REPORT", "Reported"), ("POLLED OUT OF COMMITTEE", "Reported"),
            ("COMMITTEE AMENDMENT ADOPTED", "Amended"), ("AMENDED", "Amended"), ("RECALLED", "Amended"),
            ("REVISED", "Amended"), ("RECOMMITTED", "Amended")]
NOTE = re.compile(r"Text(?:</a>)?\s+matches\s+printed\s+bills")
_last = [0.0]


def fetch(url, data=None):
    """One polite request (no cache) through curl (the site needs TLS 1.3, which this Python's
    LibreSSL lacks): the body as bytes, b'' for a 404, None if it keeps failing."""
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        cmd = ["curl", "-s", "-A", UA, "-m", "180", "-w", "\n%{http_code}", url]
        if data:
            cmd[1:1] = ["--data", urllib.parse.urlencode(data)]
        r = subprocess.run(cmd, capture_output=True)
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
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", s)
    t = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return " ".join(t.split())


def sc_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "South Carolina" and "South Carolina" not in r["StateLegChamber"]:
                continue
            s, ys = re.sub(r"\bpresent\b", "2026", r["StateLegYears"], flags=re.I), set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*(?:[A-Za-z]+\s+)?((?:19|20)\d\d)", s):
                ys |= set(range(int(a), int(z) + 1))
            if any(1993 <= y <= 2008 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def members(sess, chamber):
    page = cached(os.path.join(CACHE, "members", f"{sess}_{chamber}.html"),
                  lambda: fetch(f"{BASE}/sponsorsearch.php", {"GETMEMBERS": chamber, "SESSION": sess,
                                                               "PERM_SPONSOR_CODE": 0, "PAGETYPE": 0}))
    page = page.decode("latin-1")
    return [(c, " ".join(html.unescape(n).split())) for c, n in
            re.findall(r'value="(\d+)"\s*>\s*(?:Representative|Senator)\s+([^<\n]+)', page)]


def find_members():
    rows = []
    people = sc_people()
    for sess, years in SESSIONS.items():
        y0, y1 = map(int, years.split("-"))
        for chamber in ("H", "S"):
            listed = members(sess, chamber)
            for p in people:
                if not ({y0, y1} & p["years"]):
                    continue
                last = re.sub(r",?\s+(Jr|Sr|II|III)\.?$", "", p["Name"]).split()[-1].lower()
                for code, label in listed:
                    if label.lower().split()[-1] == last:
                        rows.append({"session": sess, "years": years, "chamber": chamber, "code": code,
                                     "label": label, "bioguide_id": p["BioguideId"], "name": p["Name"],
                                     "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {CODES}")


def crawl_lists():
    with open(CODES, newline="", encoding="utf-8") as f:
        codes = [r for r in csv.DictReader(f) if r["bioguide_id"]]
    out = []
    for c in codes:
        sess, chamber, code = int(c["session"]), c["chamber"], c["code"]
        form = {"session": sess, "Senator": code if chamber == "S" else 0,
                "Representative": code if chamber == "H" else 0, "prime": "Y", "summary": "T", "headerfooter": 1}
        page = cached(os.path.join(CACHE, "lists", f"{sess}_{chamber}_{code}.html"),
                      lambda: fetch(f"{BASE}/sponsorsearch.php", form)).decode("latin-1")
        n = 0
        for block in re.split(r'<a name="\d+"></a>', page)[1:]:
            # "H 3629 Joint Resolution, By ...", "H*4244 ..." (passed), "S*0017 (Rat #0001, Act #0215 of 1993) ..."
            m = re.match(r'\s*<span[^>]*>([HS])\*?\s*(\d+)\s*(?:\([^)]*\)\s*)?([A-Za-z ]+?), By (.*?)<br></span>',
                         block, re.S)
            if not m:
                continue
            body, num, typ, by = m.groups()
            num = str(int(num))
            first = re.search(r'member\.php\?code=(\d+)', by)
            if not first or first.group(1) != code:
                continue
            link = re.search(r'HREF="(/sess\d+_[\d-]+/bills/\d+\.htm)"', block)
            title = plain(block[m.end():block.find("<A class") if "<A class" in block else None])
            title = re.sub(r"^(?:Similar \([^)]*\)\s*)+", "", title)
            out.append({"session": sess, "years": c["years"], "bioguide_id": c["bioguide_id"], "name": c["name"],
                        "label": c["label"], "bill": f"{body}{TYPES.get(typ, '')}{num}", "type": typ,
                        "sponsors": plain(by), "title": title, "url": link.group(1) if link else ""})
            n += 1
        print(f"{sess} {chamber} {c['name']}: {n} primary-sponsored", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} items")


def bill_text(page):
    """The printed text after the 'Text matches printed bills' note, as plain lines."""
    m = NOTE.search(page)
    if not m:
        return ""
    s = page[page.find("</center>", m.start()) + 9:]
    s = s.split("-----XX-----")[0]
    s = re.sub(r"(?i)<br\s*/?>|<p>|</p>|</center>|</h\d>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    lines = [" ".join(l.split()) for l in s.split("\n")]
    s = "\n".join(l for l in lines if l)
    return re.sub(r"^Indicates Matter Stricken\nIndicates New Matter\n", "", s)


def version_of(text):
    """text_version from the printed heading; ratified acts start "(A215, R1, S17)"."""
    first = text.split("\n")[0].upper()
    if re.match(r"\(A\d+, R\d+", first):
        return "Enrolled"
    if first.startswith("A "):
        return "Introduced"
    for key, v in VERSIONS:
        if first.startswith(key):
            return v
    return "Unknown: " + first[:40]


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} items to fetch", flush=True)
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for i, b in enumerate(bills, 1):
        sess, num = b["session"], re.sub(r"\D", "", b["bill"])
        text = date = ""
        if b["url"]:
            page = cached(os.path.join(CACHE, "bills", f"{sess}_{num}.htm"),
                          lambda: fetch(BASE + b["url"])).decode("latin-1")
            dates = re.findall(r"\b((?:19|20)\d\d)(\d\d)(\d\d)\b", page[:(NOTE.search(page) or re.search("$", page)).start()])
            dates = sorted(d for d in dates if 1 <= int(d[1]) <= 12)
            date = "-".join(dates[0]) if dates else ""
            prev = sorted(set(re.findall(r'href="\.\./prever/(\d+_\d{8})\.htm"', page)), key=lambda p: p[-8:])
            src = page
            if prev:
                folder = b["url"].split("/bills/")[0]
                src = cached(os.path.join(CACHE, "prever", f"{sess}_{prev[0]}.htm"),
                             lambda: fetch(f"{BASE}{folder}/prever/{prev[0]}.htm")).decode("latin-1")
            text = bill_text(src)
        txt = os.path.join(CACHE, "texts", f"{sess}_{num}.txt")
        if text:
            os.makedirs(os.path.dirname(txt), exist_ok=True)
            with open(txt, "w", encoding="utf-8") as f:
                f.write(text)
        version = version_of(text) if text else ""
        m = re.search(r"Introduced by (?i:Reps?|Sens?|Senators?|Representatives?)\.?\s+(.*?)(?:\n(?!.*,\s*$)|$)",
                      text, re.S)
        names = " ".join(m.group(1).split()) if m else ""
        first = re.split(r",| and ", names)[0].strip() if names else ""
        label = b["label"]
        # the label ("H. Brown", "L.O. Graham"), or the bare surname when no other member of the
        # chamber that session shares it
        chamber = "H" if b["bill"].startswith("H") else "S"
        alone = sum(1 for _, l in members(int(sess), chamber) if sq(l.split()[-1]) == sq(label.split()[-1])) == 1
        ok = sq(first) == sq(label) or (sq(first) == sq(label.split()[-1]) and alone)
        match = "" if not text else "Unavailable" if not names else "Yes" if ok else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"],
                    "Session": f"{b['years']} Session ({sess}th General Assembly)", "BillNumber": b["bill"],
                    "BillId": f"SC-{sess}-{b['bill']}", "Title": b["title"], "IntroducedDate": date,
                    "House": "HOUSE" if b["bill"].startswith("H") else "SENATE", "AuthorName": first or label,
                    "IntroducedBy": names[:200], "IntroducedByMatch": match, "TextVersion": version,
                    "TextPath": txt if text else ""})
        if i % 100 == 0:
            print(f"  ...{i}/{len(bills)}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable"))
          + "; versions: " + ", ".join(f"{v} {sum(1 for o in out if o['TextVersion'] == v)}"
                                       for v in sorted({o['TextVersion'] for o in out if o['TextVersion']})))


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
