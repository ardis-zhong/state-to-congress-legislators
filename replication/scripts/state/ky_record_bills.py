#!/usr/bin/env python3
"""
Kentucky state bills and resolutions, 1998-2009, from the Kentucky General Assembly's online
Legislative Record (apps.legislature.ky.gov/record/), for population members who served in the
General Assembly before LegiScan's Kentucky coverage (2010 on). Kentucky state-text pilot (Ardis,
2026-10-26). The site has no robots.txt. Regular sessions 1998, 2000 (biennial until 2000) and
2001-2009, and the special sessions of those years.

  --members  Each session's sponsor pages (spon_H/spon_S.htm, from 2008 sponsors_house/senate.html)
             list every member with the bills and resolutions they sponsored or co-sponsored. Our
             people's entries are written as candidates for the reviewed list
             replication/data/reference/ky_sponsor_names_1998_2009.csv.
  --lists    For each reviewed (session, chamber, name): the items on the member's sponsor page;
             each item's record page lists its sponsors, the primary sponsor first ("SB 97 (BR 1084)
             - B. Guthrie"; from 2008 "Sponsors J. Westwood, ..."). Items whose first sponsor is the
             person are kept.
  --texts    The item's introduced text, the record's "bill.doc" (Word; committee substitutes and
             amendments are separate documents), converted to plain text with macOS textutil.
             Kentucky texts print no sponsor, so the record's sponsor order stands
             (IntroducedByMatch Unavailable).

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under ky_record_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/ky_record_bills.py --members
    python3 replication/scripts/state/ky_record_bills.py --lists
    python3 replication/scripts/state/ky_record_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

BASE = "https://apps.legislature.ky.gov/record"
CACHE = "ky_record_cache"
# session code -> (year, label); the 1998 and 2000 records are under /record/archived/ (the site redirects)
SESSIONS = {"98rs": (1998, "1998 Regular Session"), "00rs": (2000, "2000 Regular Session"),
            "01rs": (2001, "2001 Regular Session"), "02rs": (2002, "2002 Regular Session"),
            "02ss": (2002, "2002 Special Session"), "03rs": (2003, "2003 Regular Session"),
            "04rs": (2004, "2004 Regular Session"), "04ss": (2004, "2004 Special Session"),
            "05rs": (2005, "2005 Regular Session"), "06rs": (2006, "2006 Regular Session"),
            "06ss": (2006, "2006 Special Session"), "07rs": (2007, "2007 Regular Session"),
            "07ss": (2007, "2007 Special Session"), "08rs": (2008, "2008 Regular Session"),
            "08ss": (2008, "2008 Special Session"), "09rs": (2009, "2009 Regular Session"),
            "09ss": (2009, "2009 Special Session")}
NEW_LAYOUT = {"08rs", "08ss", "09rs", "09ss"}
PEOPLE = "replication/data/population/person_level.csv"
NAMES = "replication/data/reference/ky_sponsor_names_1998_2009.csv"
CANDIDATES = "ky_sponsor_name_candidates.csv"
LIST_OUT = "ky_primary_sponsored_bills.csv"
TEXT_OUT = "ky_state_legislation_sponsored.csv"
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


def plain(s):
    t = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return " ".join(t.split())


def sponsor_page(sess, chamber):
    """{member label: [item page names]} from a session's sponsor page for one chamber."""
    if sess in NEW_LAYOUT:
        name = "sponsors_house.html" if chamber == "H" else "sponsors_senate.html"
    else:
        name = "spon_H.htm" if chamber == "H" else "spon_S.htm"
    page = cached(os.path.join(CACHE, "sponsors", f"{sess}_{chamber}.html"),
                  lambda: fetch(f"{BASE}/{sess}/{name}")).decode("latin-1")
    out = {}
    if sess in NEW_LAYOUT:
        for label, block in re.findall(r"(?s)<h5>\s*([^<]+?)\s*</h5>\s*<p>(.*?)</p>", page):
            out[" ".join(label.split())] = re.findall(r'href="([^"]+\.html)"', block)
    else:
        # "<P>Guthrie, Brett<BR><A Href="SB97.htm">SB 97</A>*, ..." up to the next member
        for label, block in re.findall(r"(?is)<P>\s*([A-Z][^<]{2,60}?)\s*<BR>(.*?)(?=<P>|<A name=|$)", page):
            items = re.findall(r'(?i)href="([^"]+\.htm)"', block)
            if items and "," in label:
                out[" ".join(label.split())] = items
    return out


def surname(label):
    """'Comer Jr., James R.' -> 'comer'."""
    return re.sub(r"\s+(Jr|Sr|II|III)\.?$", "", label.split(",")[0].strip()).lower()


def ky_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Kentucky":
                continue
            ys = set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d)", r["StateLegYears"]):
                ys |= set(range(int(a), int(z) + 1))
            if any(1998 <= y <= 2009 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def find_members():
    rows = []
    people = ky_people()
    for sess, (year, _) in SESSIONS.items():
        for chamber in ("H", "S"):
            for label in sponsor_page(sess, chamber):
                for p in people:
                    if year in p["years"] and surname(label) == p["Name"].split()[-1].lower():
                        rows.append({"session": sess, "year": year, "chamber": chamber, "label": label,
                                     "bioguide_id": p["BioguideId"], "name": p["Name"],
                                     "state_leg_years": p["StateLegYears"], "state_leg_chamber": p["StateLegChamber"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {NAMES}")


def first_sponsor(sess, page):
    """The first-named sponsor on an item's record page, as printed ('B. Guthrie')."""
    if sess in NEW_LAYOUT:
        m = re.search(r"(?s)<th>\s*Sponsors?\s*</th>\s*<td>(.*?)</td>", page)
        names = plain(m.group(1)) if m else ""
    else:
        m = re.search(r"\(BR \d+\)\s*-\s*([^<\n]+)", plain(page).replace(" - ", " - "))
        names = m.group(1) if m else ""
        names = re.split(r"\s+(?:AN ACT|A RESOLUTION|A JOINT RESOLUTION|A CONCURRENT RESOLUTION)\b", names)[0]
    return re.split(r",", names)[0].strip(), names


def item_id(page_name):
    """'SB97.htm' / 'HJ13.htm' / 'SC71.htm' / 'SR29.html' -> 'SB97', 'HJR13', 'SCR71', 'SR29'."""
    m = re.match(r"(?i)([HS])([BRJC])(\d+)\.html?$", os.path.basename(page_name))
    if not m:
        return None
    body, kind, num = m.group(1).upper(), m.group(2).upper(), m.group(3)
    return body + {"B": "B", "R": "R", "J": "JR", "C": "CR"}[kind] + num


def crawl_lists():
    with open(NAMES, newline="", encoding="utf-8") as f:
        names = [r for r in csv.DictReader(f) if r["bioguide_id"]]
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for r in names:
        sess, chamber, label = r["session"], r["chamber"], r["label"]
        items = sponsor_page(sess, chamber).get(label, [])
        last, given = surname(label), label.partition(",")[2]
        n = 0
        for page_name in dict.fromkeys(items):
            bill = item_id(page_name)
            if not bill:
                continue
            page = cached(os.path.join(CACHE, "items", f"{sess}_{bill}.html"),
                          lambda: fetch(f"{BASE}/{sess}/{os.path.basename(page_name)}")).decode("latin-1")
            first, names_all = first_sponsor(sess, page)
            # 'B. Guthrie' / 'J. Comer Jr.' / 'E. Fletcher': surname, and the initial where printed
            f_last = re.sub(r"\b(Jr|Sr|II|III)\.?$", "", first).strip().split(" ")[-1]
            ok = sq(f_last) == sq(last) and (not re.match(r"[A-Z]\.", first) or first[0] == given.strip()[:1])
            if ok:
                title = re.search(r"(AN ACT|A RESOLUTION|A JOINT RESOLUTION|A CONCURRENT RESOLUTION)[^.]*\.", plain(page))
                doc = re.search(r'(?i)href="([^"]*/bill\.doc)"', page)
                out.append({"session": sess, "bioguide_id": r["bioguide_id"], "name": r["name"], "label": label,
                            "bill": bill, "title": title.group(0) if title else "", "sponsors": names_all[:300],
                            "doc": doc.group(1) if doc else ""})
                n += 1
        print(f"{sess} {chamber} {r['name']}: {len(set(items))} listed, {n} as first sponsor", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} items")


def doc_text(path):
    """Plain text of a Word .doc (macOS textutil), without the record's page footers."""
    r = subprocess.run(["textutil", "-convert", "txt", "-stdout", path], capture_output=True)
    if r.returncode != 0:
        return ""
    t = r.stdout.decode("utf-8", "replace")
    t = re.sub(r"(?m)^(UNOFFICIAL COPY AS OF .*|Page\s*page\s*\d+\s*of\s*numpages\s*\d+|Page \d+ of \d+|[HS][BRJC]\d{6}\.\d+.*)$", "", t)
    lines = [l.rstrip() for l in t.split("\n")]
    return "\n".join(l for l in lines if l.strip())


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    if limit:
        items = items[:limit]
    print(f"{len(items)} items to fetch", flush=True)
    out = []
    for i, b in enumerate(items, 1):
        sess, bill = b["session"], b["bill"]
        year, label = SESSIONS[sess]
        txt = os.path.join(CACHE, "texts", f"{sess}_{bill}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        elif b["doc"]:
            url = b["doc"] if b["doc"].startswith("http") else f"{BASE}/{sess}/{b['doc']}"
            local = os.path.join(CACHE, "docs", f"{sess}_{bill}.doc")
            raw = cached(local, lambda: fetch(url))
            if raw[:4] == b"\xd0\xcf\x11\xe0" or raw[:5] == b"{\\rtf":  # Word 97-2003, or RTF named .doc (2007 on)
                text = doc_text(local)
            if text:
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": label,
                    "BillNumber": bill, "BillId": f"KY-{sess.upper()}-{bill}", "Title": b["title"],
                    "IntroducedDate": "", "House": "HOUSE" if bill.startswith("H") else "SENATE",
                    "AuthorName": b["label"], "IntroducedBy": b["sponsors"][:200],
                    "IntroducedByMatch": "Unavailable" if text else "", "TextVersion": "Introduced",
                    "TextPath": txt if text else ""})
        if i % 100 == 0:
            print(f"  ...{i}/{len(items)}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text")


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
