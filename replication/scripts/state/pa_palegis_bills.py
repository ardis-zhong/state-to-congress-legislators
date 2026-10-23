#!/usr/bin/env python3
"""
Pennsylvania state bills, 1969-2008, from the Pennsylvania General Assembly's website
(palegis.us), for population members who served in the General Assembly before LegiScan's
Pennsylvania coverage (2009 on). Pennsylvania state-text pilot (Ardis, 2026-10-21). Regular
sessions only.

  --members  Each session's bill search page (/legislation/bills?sessYr=<year>&sessInd=0)
             lists that session's sponsors with their member ids ("301|H"); our people's
             entries are written as candidates for the reviewed list
             replication/data/reference/pa_member_ids_1969_2008.csv. --members also records
             each candidate's full name and result count from the first page of their sponsor
             listing ("Bills Sponsored By Representative Joseph R. Pitts ... returned 332
             results"), to review namesakes and to size the crawl.
  --lists    Each reviewed member's sponsor listing, 20 per page
             (/legislation/bills/by-sponsor?sessind=0&memberid=..&billbody=h|s&sessyr=..
             &pagenumber=N), lists every bill and resolution they sponsored and marks each
             "Prime Sponsor" or "Co-Sponsor"; the prime-sponsored ones are kept.
  --texts    Each bill's page (/legislation/bills/<year>/<hb100>) lists its printings by
             printer's number; the lowest one is the bill as introduced (HTM when available,
             else the PDF, which for older sessions is a scan with a text layer). Its heading
             names who introduced it ("INTRODUCED BY MESSRS HOPKINS, DWYER, ..., JANUARY 28,
             1969"); IntroducedByMatch says whether the first member named is the person.

Polite: one request at a time, at least 4 seconds apart (palegis.us's robots.txt sets no
rule for general crawlers; the older legis.state.pa.us asks for Crawl-delay 5 and its paths
are not used), a User-Agent naming the project, every response cached under pa_palegis_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/pa_palegis_bills.py --members
    python3 replication/scripts/state/pa_palegis_bills.py --lists
    python3 replication/scripts/state/pa_palegis_bills.py --texts [--limit N]
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

BASE = "https://www.palegis.us"
CACHE = "pa_palegis_cache"
SESSIONS = range(1969, 2009, 2)
PEOPLE = "replication/data/population/person_level.csv"
IDS = "replication/data/reference/pa_member_ids_1969_2008.csv"
CANDIDATES = "pa_member_id_candidates.csv"
LIST_OUT = "pa_prime_sponsor_bills.csv"
# 1971-1977 Senate: the website's prime sponsors are wrong for whole member-sessions (e.g. Zemprelli's
# bills listed under Dougherty), and many bills have no prime sponsor at all (--senate-map samples every
# senator's listing and shows this). --senate-scan therefore reads every Senate bill of those sessions as
# introduced and keeps the ones whose "Introduced by" line names one of our senators first.
SENATE_FIX_SESSIONS = (1971, 1973, 1975, 1977)
MAP_OUT = "pa_senate_listing_map_1971_1977.csv"
SCAN_OUT = "pa_senate_scan_1971_1977.csv"
TEXT_OUT = "pa_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 4
_last = [0.0]
MONTHS = {m: i for i, m in enumerate("january february march april may june july august september october "
                                     "november december".split(), 1)}


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
            with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"User-Agent": UA}),
                                        timeout=120) as r:
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
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def pdf_text(path):
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text(x_tolerance=1.5) or "") for page in pdf.pages).strip()
    except Exception:
        return ""


def pa_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Pennsylvania" and "Pennsylvania" not in r["StateLegChamber"]:
                continue
            s = re.sub(r"\bpresent\b", "2026", r["StateLegYears"], flags=re.I)
            ys = set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d)", s):
                ys |= set(range(int(a), int(z) + 1))
            if any(1969 <= y <= 2008 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def listing(year, member_id, body, page=1):
    q = f"sessind=0&memberid={member_id}&billbody={body}&sessyr={year}" + (f"&pagenumber={page}" if page > 1 else "")
    return get(f"/legislation/bills/by-sponsor?{q}", os.path.join(CACHE, "lists", f"{year}_{body}{member_id}_p{page}.html"))


def find_members():
    rows = []
    people = pa_people()
    for p in people:
        p["last"] = p["Name"].split()[-1].upper().replace(".", "")
    for year in SESSIONS:
        page = get(f"/legislation/bills?sessYr={year}&sessInd=0", os.path.join(CACHE, "sessions", f"{year}.html"))
        i = page.find('id="member-select"')
        opts = re.findall(r'<option value="(\d+)\|([HS])"[^>]*>\s*(?:Representative|Senator)\s+([^<]+)',
                          page[i:page.find("</select>", i)])
        for p in people:
            if year not in p["years"] and year + 1 not in p["years"]:
                continue
            for mid, body, label in opts:
                # later sessions add an initial when two members share a surname ("D. EVANS")
                if re.sub(r"[^A-Z]", "", label.split(",")[0].split()[-1].upper()) == re.sub(r"[^A-Z]", "", p["last"]):
                    first = listing(year, mid, body.lower())
                    title = re.search(r"Bills Sponsored By\s+(?:Representative|Senator)\s+([^|<]+?)\s*(?:\||<)", first)
                    n = re.search(r"returned\s*(?:<[^>]+>\s*)?([\d,]+)", first)
                    rows.append({"session": year, "member_id": mid, "body": body, "label": " ".join(label.split()),
                                 "page_name": title.group(1).strip() if title else "",
                                 "results": n.group(1).replace(",", "") if n else "0",
                                 "bioguide_id": p["BioguideId"], "name": p["Name"],
                                 "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {IDS}")


def items(page):
    """(bill, prime?) for each result on a sponsor-listing page, e.g. ('HB0001', False)."""
    out = []
    parts = re.split(r'(?=<a[^>]+href="/legislation/bills/\d{4}/[a-z]+\d+")', page)
    for part in parts:
        m = re.match(r'<a[^>]+href="/legislation/bills/\d{4}/([a-z]+)(\d+)"', part)
        if not m:
            continue
        t = plain(part[:4000])
        role = re.search(r"\b(Prime Sponsor|Co-Sponsor)\b", t)
        title = re.search(r"Short Title:\s*(.*?)\s*Last Action:", t, flags=re.S)
        out.append((m.group(1).upper(), int(m.group(2)), bool(role and role.group(1) == "Prime Sponsor"),
                    " ".join(title.group(1).split()) if title else ""))
    seen, uniq = set(), []
    for typ, num, prime, title in out:
        if (typ, num) not in seen:
            seen.add((typ, num))
            uniq.append((typ, num, prime, title))
        elif prime:
            uniq = [(a, b, c or (a, b) == (typ, num), d) for a, b, c, d in uniq]
    return uniq


def crawl_lists():
    with open(IDS, newline="", encoding="utf-8") as f:
        ids = list(csv.DictReader(f))
    out, seen = [], set()
    for k in ids:
        year, mid, body = int(k["session"]), k["member_id"], k["body"].lower()
        first = listing(year, mid, body)
        n = re.search(r"returned\s*(?:<[^>]+>\s*)?([\d,]+)", first)
        total = int(n.group(1).replace(",", "")) if n else 0
        found = items(first)
        for page in range(2, (total + 19) // 20 + 1):
            found += items(listing(year, mid, body, page))
        if len(found) != total:
            print(f"  WARNING {year} {k['name']}: {total} results, {len(found)} parsed")
        prime = [f for f in found if f[2]]
        for typ, num, _, title in prime:
            if (k["bioguide_id"], year, typ, num) in seen:
                continue
            seen.add((k["bioguide_id"], year, typ, num))
            out.append({"session": year, "bioguide_id": k["bioguide_id"], "name": k["name"], "member_id": mid,
                        "body": k["body"], "page_name": k["page_name"], "type": typ, "number": num, "title": title[:300]})
        print(f"{year} {k['name']}: {total} sponsored, {len(prime)} as prime sponsor", flush=True)
    if os.path.exists(SCAN_OUT):  # 1971-1977 Senate bills found by --senate-scan
        with open(SCAN_OUT, newline="", encoding="utf-8") as f:
            for b in csv.DictReader(f):
                key = (b["bioguide_id"], int(b["session"]), b["type"], int(b["number"]))
                if key not in seen:
                    seen.add(key)
                    out.append({k: b[k] for k in out[0]})
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} bills")


def senate_map():
    """For each 1971-1977 senator's listing, the introducers named first in up to three of its
    prime-sponsored bills: shows whose bills the website files under that senator's id."""
    rows = []
    for year in SENATE_FIX_SESSIONS:
        page = get(f"/legislation/bills?sessYr={year}&sessInd=0", os.path.join(CACHE, "sessions", f"{year}.html"))
        i = page.find('id="member-select"')
        opts = re.findall(r'<option value="(\d+)\|S"[^>]*>\s*Senator\s+([^<]+)', page[i:page.find("</select>", i)])
        for mid, label in opts:
            prime = [it for it in items(listing(year, mid, "s")) if it[2]][:3]
            firsts = []
            for typ, num, _, _ in prime:
                text, _, _ = introduced_text(year, typ, num)
                names, _ = introduced_line(text)
                firsts.append(re.split(r",|AND", names)[0][:20] if names else "?")
            rows.append({"session": year, "member_id": mid, "label": " ".join(label.split()),
                         "sampled_bills": " ".join(f"{t}{n}" for t, n, _, _ in prime), "first_named": " ".join(firsts)})
            print(year, mid, label.strip(), firsts, flush=True)
    with open(MAP_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {MAP_OUT}: {len(rows)} senator listings")


def senate_scan():
    """Every Senate bill of the 1971-1977 sessions as introduced (SB 1 upward until 40 numbers in a
    row have no printing), kept when its "Introduced by" line names one of our senators in that
    session first (reviewed ids, body S). Writes SCAN_OUT in the LIST_OUT format."""
    with open(IDS, newline="", encoding="utf-8") as f:
        senators = [r for r in csv.DictReader(f) if r["body"] == "S" and int(r["session"]) in SENATE_FIX_SESSIONS]
    out = []
    for year in SENATE_FIX_SESSIONS:
        ours = [r for r in senators if int(r["session"]) == year]
        num, misses = 0, 0
        while misses < 40:
            num += 1
            text, _, pns = introduced_text(year, "SB", num)
            misses = 0 if pns else misses + 1
            names, _ = introduced_line(text)
            for r in ours:
                surname = re.sub(r"[^A-Z]", "", r["name"].split()[-1].upper())
                if names and first_named(names, surname):
                    page = plain(get(f"/legislation/bills/{year}/sb{num}", os.path.join(CACHE, "bills", f"{year}_SB{num}.html")))
                    title = re.search(r"Meetings\s*\n?\s*((?:An Act|A Joint Resolution|A Resolution|A Concurrent Resolution).*?)\n", page)
                    out.append({"session": year, "bioguide_id": r["bioguide_id"], "name": r["name"],
                                "member_id": r["member_id"], "body": "S", "page_name": r["page_name"],
                                "type": "SB", "number": num, "title": " ".join(title.group(1).split())[:300] if title else "",
                                "found_by": "senate scan"})
            if num % 100 == 0:
                print(f"  {year} SB{num}: {sum(1 for o in out if o['session'] == year)} found", flush=True)
        print(f"{year}: scanned SB1-SB{num - misses}, {sum(1 for o in out if o['session'] == year)} bills by our senators",
              flush=True)
    with open(SCAN_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {SCAN_OUT}: {len(out)} bills")


def introduced_line(text):
    """(names, ISO date) from 'INTRODUCED BY MESSRS HOPKINS, DWYER, ..., JANUARY 28, 1969' (or
    'INTRODUCED BY PITTS, ...' / 'BY SENATOR SCHWARTZ'), matched on the text with spaces removed
    because older scans print it letter-spaced."""
    sq = re.sub(r"[^A-Z0-9,]", "", text[:4000].upper())
    m = re.search(r"[IL1]NTRODUCEDBY(?:MESSRS|MESSRS\.|MRS|MR|MS|MISS|SENATORS?|REPRESENTATIVES?)*(.*?)"
                  r"(" + "|".join(m.upper() for m in MONTHS) + r")(\d{1,2}),?(\d{4})", sq)
    if not m:
        return "", ""
    iso = f"{m.group(4)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(3)):02d}"
    return m.group(1).strip(","), iso


def first_named(names, surname):
    """Whether the squashed sponsor list ("SCHWARTZANDJONES", "M,URPHY,RYAN") names the person first:
    it starts with the surname after at most three stray OCR letters or initials, or after an
    OCR-garbled "MESSRS" ("ME5SRSMURPHY"), or its first name is the surname with one OCR error
    ("CHULZE" for Schulze)."""
    import difflib
    sq = re.sub(r"[^A-Z0-9]", "", names)
    if re.match(rf"[A-Z0-9]{{0,3}}{surname}", sq) or re.match(rf"M[A-Z0-9]{{3,6}}{surname}", sq):
        return True
    first = re.split(r",|AND", names)[0]
    first = re.sub(r"[^A-Z]", "", first)[:len(surname) + 1]
    return len(surname) >= 5 and difflib.SequenceMatcher(None, first, surname).ratio() >= 0.8


def introduced_text(year, typ, num):
    """(text, txt_path, printer's numbers) for the bill as introduced: its lowest printer's
    number, as HTM when the bill page links it, else the PDF."""
    bill_page = get(f"/legislation/bills/{year}/{typ.lower()}{num}", os.path.join(CACHE, "bills", f"{year}_{typ}{num}.html"))
    pns = sorted({int(p) for p in re.findall(rf"/legislation/bills/text/(?:PDF|HTM)/{year}/0/{typ}{num:04d}/PN(\d+)",
                                            bill_page)})
    text, txt_path = "", ""
    if pns:
        pn = f"PN{pns[0]:04d}"
        txt_path = os.path.join(CACHE, "texts", f"{year}_{typ}{num}_{pn}.txt")
        if os.path.exists(txt_path):
            with open(txt_path, encoding="utf-8") as f:
                text = f.read()
        else:
            if f"/HTM/{year}/0/{typ}{num:04d}/{pn}" in bill_page:
                page = get(f"/legislation/bills/text/HTM/{year}/0/{typ}{num:04d}/{pn}",
                           os.path.join(CACHE, "texts", f"{year}_{typ}{num}_{pn}.htm"))
                text = plain(page) if page else ""
            if not text:
                pdf_path = os.path.join(CACHE, "texts", f"{year}_{typ}{num}_{pn}.pdf")
                data = get(f"/legislation/bills/text/PDF/{year}/0/{typ}{num:04d}/{pn}", pdf_path, binary=True)
                text = pdf_text(pdf_path) if data[:4] == b"%PDF" else ""
            if text:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(text)
    return text, (txt_path if text else ""), pns


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        year, typ, num = b["session"], b["type"], int(b["number"])
        text, txt_path, pns = introduced_text(year, typ, num)
        names, iso = introduced_line(text)
        if iso and not int(year) <= int(iso[:4]) <= int(year) + 1:
            iso = ""  # an OCR misread (e.g. "1363" for 1969)
        surname = re.sub(r"[^A-Z]", "", b["name"].split()[-1].upper())
        match = "" if not text else "Unavailable" if not names else \
            "Yes" if first_named(names, surname) else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{year}-{int(year) + 1} Regular Session",
                    "BillNumber": f"{typ}{num}", "BillId": f"PA-{year}-{typ}{num}", "Title": b["title"],
                    "IntroducedDate": iso, "House": "HOUSE" if typ.startswith("H") else "SENATE",
                    "AuthorName": b["page_name"], "PrintersNumber": f"PN{pns[0]:04d}" if pns else "",
                    "IntroducedBy": names[:200], "IntroducedByMatch": match, "TextVersion": "Introduced",
                    "TextPath": txt_path})
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
    ap.add_argument("--senate-map", action="store_true")
    ap.add_argument("--senate-scan", action="store_true")
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N bills (smoke test)")
    args = ap.parse_args()
    if args.members:
        find_members()
    if args.senate_map:
        senate_map()
    if args.senate_scan:
        senate_scan()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
