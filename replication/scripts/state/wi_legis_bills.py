#!/usr/bin/env python3
"""
Wisconsin state bills, 1995-2010, from the Wisconsin Legislature's document site
(docs.legis.wisconsin.gov), for population members who served in the Legislature before
LegiScan's Wisconsin coverage. Wisconsin state-text pilot (Ardis, 2026-10-25). Regular sessions
1995-2009; the site's proposals start with the 1995 session.

  --members  Each session's Author Index to Legislation (/document/authorindex/<year>/assembly
             and /senate) lists every member with a key (A78 = 78th Assembly district); our
             people's entries are written as candidates for the reviewed list
             replication/data/reference/wi_author_keys_1995_2010.csv.
  --lists    Each reviewed member's author index page (/document/authorindex/<year>/<key>) lists
             every proposal they authored or co-authored; the ones of their own house (AB, AJR,
             AR for Assembly members; SB, SJR, SR for senators) are kept as candidates.
  --texts    Each candidate as introduced (/<year>/related/proposals/<ab80>, else the PDF). Its
             heading names the authors ("January 31, 1995 - Introduced by Representatives
             BALDWIN, BLACK, ..."); a proposal counts when the person is named first
             (IntroducedByMatch), and the date there is the introduction date.

Polite: one request at a time, at least 2 seconds apart (robots.txt sets no crawl delay and
excludes only internal features), a User-Agent naming the project, every response cached under
wi_legis_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/wi_legis_bills.py --members
    python3 replication/scripts/state/wi_legis_bills.py --lists
    python3 replication/scripts/state/wi_legis_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import logging
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://docs.legis.wisconsin.gov"
CACHE = "wi_legis_cache"
SESSIONS = range(1995, 2011, 2)
PEOPLE = "replication/data/population/person_level.csv"
KEYS = "replication/data/reference/wi_author_keys_1995_2010.csv"
CANDIDATES = "wi_author_key_candidates.csv"
LIST_OUT = "wi_authored_candidates.csv"
TEXT_OUT = "wi_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
_last = [0.0]
MONTHS = {m: i for i, m in enumerate("January February March April May June July August September October "
                                     "November December".split(), 1)}


def get(path, cache_path, binary=False):
    """Fetch BASE+path once (cached). Returns the body, or empty for a 404; a page that keeps
    failing is skipped (not cached) so a re-run tries it again."""
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            data = f.read()
        return data if binary else data.decode("utf-8", errors="replace")
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"User-Agent": UA}), timeout=180) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = b""
                break
            time.sleep(30 * (attempt + 1))
        except Exception:
            time.sleep(30 * (attempt + 1))
    else:
        print(f"  could not fetch {path}", flush=True)
        return b"" if binary else ""
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(data)
    return data if binary else data.decode("utf-8", errors="replace")


def plain(s):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def pdf_text(path):
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text(x_tolerance=1.5) or "") for page in pdf.pages).strip()
    except Exception:
        return ""


def wi_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Wisconsin" and "Wisconsin" not in r["StateLegChamber"]:
                continue
            s, ys = re.sub(r"\bpresent\b", "2026", r["StateLegYears"], flags=re.I), set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–;]\s*(?:[A-Za-z]+\s+)?((?:19|20)\d\d)", s):
                ys |= set(range(int(a), int(z) + 1))
            if any(1995 <= y <= 2010 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def find_members():
    rows = []
    people = wi_people()
    for year in SESSIONS:
        for house in ("assembly", "senate"):
            page = get(f"/document/authorindex/{year}/{house}", os.path.join(CACHE, "index", f"{year}_{house}.html"))
            entries = re.findall(rf'href="/document/authorindex/{year}/([AS]\d+)"[^>]*>([^<]+)</a>', page)
            for p in people:
                if year not in p["years"] and year + 1 not in p["years"]:
                    continue
                last = p["Name"].split()[-1].lower()
                for key, label in entries:
                    if label.lower().startswith(last + ","):
                        rows.append({"session": year, "key": key, "label": " ".join(html.unescape(label).split()),
                                     "bioguide_id": p["BioguideId"], "name": p["Name"],
                                     "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {KEYS}")


def crawl_lists():
    with open(KEYS, newline="", encoding="utf-8") as f:
        keys = list(csv.DictReader(f))
    out = []
    for k in keys:
        page = get(f"/document/authorindex/{k['session']}/{k['key']}",
                   os.path.join(CACHE, "index", f"{k['session']}_{k['key']}.html"))
        body = plain(page)
        start = body.find(k["label"].split(" (")[0].split(",")[0])
        own = ("AB", "AJR", "AR") if k["key"].startswith("A") else ("SB", "SJR", "SR")
        found = []
        for typ, num in re.findall(r"\b(AJR|SJR|AB|SB|AR|SR)(\d+)\b", body[start:]):
            if typ in own and (typ, int(num)) not in found:
                found.append((typ, int(num)))
        for typ, num in found:
            out.append({"session": k["session"], "bioguide_id": k["bioguide_id"], "name": k["name"], "key": k["key"],
                        "label": k["label"], "type": typ, "number": num})
        print(f"{k['session']} {k['key']} {k['name']}: {len(found)} own-house proposals", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} candidates")


def heading(text):
    """(names after 'Introduced by', ISO date) from '<Month d, yyyy> - Introduced by Representatives X, Y'."""
    flat = " ".join(text[:5000].split())
    m = re.search(r"(?:(" + "|".join(MONTHS) + r") (\d{1,2}), (\d{4}))?\s*\W?\s*Introduced by (?:the )?"
                  r"(?:Representatives?|Senators?|Joint Legislative Council|Committee|Law Revision Committee)?\s*(.*?)"
                  r"(?:[,;]? cosponsored by|\. Referred|\. Report|(?<!\b[A-Z])\.\s|$)", flat)  # not at an initial
    if not m:
        return "", ""
    iso = f"{m.group(3)}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}" if m.group(1) else ""
    return m.group(4).strip(), iso


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} proposals to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        s, typ, num = b["session"], b["type"], int(b["number"])
        stem = f"{typ.lower()}{num}"
        txt = os.path.join(CACHE, "texts", f"{s}_{stem}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            pdf = os.path.join(CACHE, "texts", f"{s}_{stem}.pdf")
            if get(f"/{s}/related/proposals/{stem}.pdf", pdf, binary=True)[:4] == b"%PDF":
                text = pdf_text(pdf)
            if text:
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        names, iso = heading(text)
        first = re.split(r",|\band\b", names)[0].strip() if names else ""
        surname = b["label"].split(",")[0]
        sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
        # the surname, alone or after the person's own initial ("S. FITZGERALD" once a namesake served)
        given = b["label"].split(",", 1)[1].split()[1] if "," in b["label"] else ""
        ok = sq(first) == sq(surname) or (given and sq(first) == sq(given[0] + surname))
        match = "" if not text else "Unavailable" if not names else "Yes" if ok else "No"
        title = re.search(r"\bAN ACT\b(.*?)(?:\n\s*\n|Analysis by)", text, flags=re.S)
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{s}-{int(s) + 1} Regular Session",
                    "BillNumber": f"{typ}{num}", "BillId": f"WI-{s}-{typ}{num}",
                    "Title": " ".join(title.group(1).split())[:300] if title else "", "IntroducedDate": iso,
                    "House": "HOUSE" if typ.startswith("A") else "SENATE", "AuthorName": first,
                    "IntroducedBy": names[:200], "IntroducedByMatch": match, "TextVersion": "Introduced",
                    "TextPath": txt if text else ""})
        if i % 100 == 0:
            print(f"  ...{i}/{len(bills)}", flush=True)
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
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N proposals (smoke test)")
    args = ap.parse_args()
    if args.members:
        find_members()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
