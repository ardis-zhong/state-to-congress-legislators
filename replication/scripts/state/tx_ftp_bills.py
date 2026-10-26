#!/usr/bin/env python3
"""
Texas state bills, 1993-2009, from the Texas Legislature's anonymous FTP site
(ftp://ftp.legis.state.tx.us), for population members who served in the Legislature before
LegiScan's Texas coverage (2011 on for our people). Texas state-text pilot (Ardis, 2026-10-25).
The FTP site is the route the Texas Legislative Council asks data users to take instead of the
website (its Acceptable_Use_FTP_Public_Site.txt; the website's robots.txt also disallows the bill
pages). Bill text starts with the 73rd Legislature (1993); regular and special sessions 73R-81R.

  --members  Each session's author report index (/bills/<session>/reports/author/index.htm) lists
             every member with a code ("Turner, Sylvester (H-A4685)"); our people's entries are
             written as candidates for the reviewed list
             replication/data/reference/tx_author_codes_1993_2009.csv.
  --lists    Each reviewed member's author report (/bills/<session>/reports/author/<code>.htm)
             lists the bills they authored or joint-authored with all authors in order; bills on
             which the person is listed first are kept.
  --texts    Each bill as introduced (/bills/<session>/billtext/html/<house_bills>/<HB00600_HB00699>/
             HB00663I.htm). Its heading names the authors ("By: Turner, Sylvester H.B. No. 663");
             a bill counts when the person is named first (IntroducedByMatch).

Polite: one request at a time, at least 2 seconds apart, every response cached under
tx_ftp_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/tx_ftp_bills.py --members
    python3 replication/scripts/state/tx_ftp_bills.py --lists
    python3 replication/scripts/state/tx_ftp_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

FTP = "ftp://ftp.legis.state.tx.us"
CACHE = "tx_ftp_cache"
SESSIONS = {"73R": 1993, "74R": 1995, "75R": 1997, "76R": 1999, "77R": 2001, "78R": 2003, "781": 2003, "782": 2003,
            "783": 2003, "784": 2004, "79R": 2005, "791": 2005, "792": 2005, "793": 2006, "80R": 2007, "81R": 2009,
            "811": 2009}
PEOPLE = "replication/data/population/person_level.csv"
CODES = "replication/data/reference/tx_author_codes_1993_2009.csv"
CANDIDATES = "tx_author_code_candidates.csv"
LIST_OUT = "tx_first_author_bills.csv"
TEXT_OUT = "tx_state_legislation_sponsored.csv"
DELAY = 2
_last = [0.0]
FOLDERS = {"HB": "house_bills", "SB": "senate_bills", "HJR": "house_joint_resolutions", "SJR": "senate_joint_resolutions",
           "HCR": "house_concurrent_resolutions", "SCR": "senate_concurrent_resolutions", "HR": "house_resolutions",
           "SR": "senate_resolutions"}
CODE_LETTERS = {"HB": "HB", "SB": "SB", "HJR": "HJ", "SJR": "SJ", "HCR": "HC", "SCR": "SC", "HR": "HR", "SR": "SR"}


def get(path, cache_path):
    """Fetch FTP+path once (cached) as text. Returns '' when the file is missing; a fetch that keeps
    failing is skipped (not cached) so a re-run tries it again."""
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read().decode("cp1252", errors="replace")
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(FTP + path, timeout=180) as r:
                data = r.read()
            break
        except urllib.error.URLError as e:
            if "550" in str(e) or "No such file" in str(e):
                data = b""
                break
            time.sleep(20 * (attempt + 1))
        except Exception:
            time.sleep(20 * (attempt + 1))
    else:
        print(f"  could not fetch {path}", flush=True)
        return ""
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(data)
    return data.decode("cp1252", errors="replace")


def plain(s):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def tx_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Texas" and "Texas" not in r["StateLegChamber"]:
                continue
            s, ys = re.sub(r"\bpresent\b", "2026", r["StateLegYears"], flags=re.I), set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*(?:[A-Za-z]+\s+)?((?:19|20)\d\d)", s):
                ys |= set(range(int(a), int(z) + 1))
            if any(1993 <= y <= 2009 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def author_index(session):
    page = get(f"/bills/{session}/reports/author/index.htm", os.path.join(CACHE, "authors", f"{session}_index.htm"))
    return re.findall(r'href="([A-Z]\d+)\.htm"[^>]*>([^<]+)', page, flags=re.I)


def find_members():
    rows = []
    people = tx_people()
    for session, year in SESSIONS.items():
        for code, label in author_index(session):
            name = " ".join(html.unescape(label).split())
            for p in people:
                if year not in p["years"] and year - 1 not in p["years"]:
                    continue
                last = p["Name"].split()[-1].lower()
                if name.lower().startswith(last + " ") or name.lower().startswith(last + ","):
                    rows.append({"session": session, "code": code, "label": name, "bioguide_id": p["BioguideId"],
                                 "name": p["Name"], "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {CODES}")


def author_page(session, code):
    for name in (f"{code}.htm", f"{code}.HTM"):
        page = get(f"/bills/{session}/reports/author/{name}", os.path.join(CACHE, "authors", f"{session}_{name}"))
        if page:
            return page
    return ""


def crawl_lists():
    with open(CODES, newline="", encoding="utf-8") as f:
        codes = list(csv.DictReader(f))
    out = []
    for k in codes:
        t = plain(author_page(k["session"], k["code"]))
        n_total = re.search(r"Number of Bills:\s*(\d+)", t)
        entries = re.findall(r"\b(HB|SB|HJR|SJR|HCR|SCR|HR|SR) (\d+)\s+Author:\s*(.*?)\s*(?:\n|Sponsor:|Last Action:)", t)
        captions = dict(re.findall(r"\b((?:HB|SB|HJR|SJR|HCR|SCR|HR|SR) \d+)\s+Author:.*?Caption:\s*(.*?)\n", t, flags=re.S))
        first = []
        for typ, num, authors in entries:
            lead = authors.split("|")[0].strip()
            if lead.lower() == k["author_label"].lower():
                first.append((typ, int(num)))
        if n_total and int(n_total.group(1)) != len(entries):
            print(f"  WARNING {k['session']} {k['name']}: {n_total.group(1)} listed, {len(entries)} parsed")
        for typ, num in first:
            out.append({"session": k["session"], "year": SESSIONS[k["session"]], "bioguide_id": k["bioguide_id"],
                        "name": k["name"], "author_label": k["author_label"], "type": typ, "number": num,
                        "caption": " ".join(captions.get(f"{typ} {num}", "").split())[:300]})
        print(f"{k['session']} {k['name']}: {len(entries)} authored, {len(first)} as first author", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} bills")


def folder_listing(session, typ, num):
    lo = num // 100 * 100
    group = f"{CODE_LETTERS[typ]}{max(lo, 1 if lo == 0 else lo):05d}_{CODE_LETTERS[typ]}{lo + 99:05d}"
    path = f"/bills/{session}/billtext/html/{FOLDERS[typ]}/{group}/"
    listing = get(path, os.path.join(CACHE, "listings", f"{session}_{typ}_{lo}.txt"))
    names = re.findall(r"(\S+\.html?)\s*$", listing, flags=re.I | re.M)
    return path, names


# Texas bylines tell same-surname members apart by county ("Turner of Harris") or initial ("Cuellar, H.").
COUNTY = {"T000489": "harris", "C001063": "webb"}  # Sylvester Turner, Henry Cuellar


def close(a, b):
    """Equal, or one typo apart (substitution, insertion or deletion): 'Rodriquez', 'Culburson'."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1 or min(len(a), len(b)) < 5:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def byline_ok(names, label, bioguide, name):
    """The first name in the byline is the person: their surname (one typo allowed), and any county or
    initial printed with it is theirs."""
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    first = re.sub(r",?\s*et al\.?$", "", names.strip(), flags=re.I)
    first, _, initial = first.partition(",")
    surname, _, county = re.sub(r"(?i)of\s*", " of ", first).partition(" of ")
    if not close(sq(surname), sq(label.split(",")[0])):
        return False
    if county and sq(county) != COUNTY.get(bioguide, ""):
        return False
    # after the comma: an initial ("B.") or given name ("Pete") qualifies the surname; anything else is a co-author
    qual = sq(initial.split(",")[0])
    given = sq(name.split()[0])
    if re.fullmatch(r"\s*[A-Z]\.?\s*", initial.split(",")[0]):
        return given.startswith(qual)
    return True


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        s, typ, num = b["session"], b["type"], int(b["number"])
        stem = f"{CODE_LETTERS[typ]}{num:05d}I"
        txt = os.path.join(CACHE, "texts", f"{s}_{stem}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            path, names = folder_listing(s, typ, num)
            name = next((n for n in names if n.upper().startswith(stem + ".")), None)
            if name:
                text = plain(get(path + name, os.path.join(CACHE, "texts", f"{s}_{name}")))
            if text:
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        flat = " ".join(text[:3000].split())
        m = re.search(r"\bBy:?\s+(.*?)\s+(?:H|S)\.\s*(?:B|J\.?\s*R|C\.?\s*R|R)\.\s*No\.", flat)  # "By: Carter" / "By Marchant"
        names = m.group(1) if m else ""
        names = "" if re.fullmatch(r"_+", names) else names  # blank byline in a few drafts
        ok = bool(names) and byline_ok(names, b["author_label"], b["bioguide_id"], b["name"])
        match = "" if not text else "Unavailable" if not names else "Yes" if ok else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{s} ({b['year']})",
                    "BillNumber": f"{typ}{num}", "BillId": f"TX-{s}-{typ}{num}", "Title": b.get("caption", ""), "IntroducedDate": "",
                    "House": "HOUSE" if typ.startswith("H") else "SENATE", "AuthorName": names[:120],
                    "IntroducedByMatch": match, "TextVersion": "Introduced", "TextPath": txt if text else ""})
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
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N bills (smoke test)")
    args = ap.parse_args()
    if args.members:
        find_members()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
