#!/usr/bin/env python3
"""
West Virginia state bills, 1993-2009, from the West Virginia Legislature's bill status
archive (wvlegislature.gov/Bill_Status/), for population members who served in the
Legislature before LegiScan's West Virginia coverage (2010 on). West Virginia state-text
pilot (Ardis, 2026-10-21). Bills only: the archive's sponsor search covers bills, not
resolutions.

  --members  Each year's "Bills by Sponsor" page lists the delegates and senators who
             sponsored bills that session; our people's entries are written as candidates for
             the reviewed list replication/data/reference/wv_sponsor_names_1993_2009.csv.
  --lists    For each reviewed (year, session, chamber, name): the bills the person sponsored
             (POST to Bills_Sponsors.cfm, which lists lead and co-sponsored bills alike), then
             each bill's history page, which names the LEAD SPONSOR and links the introduced
             text. A bill is kept when the person is its lead sponsor.
  --texts    The introduced version ("Introduced Version" link on the history page). Its
             heading names who introduced the bill, lead sponsor first ("(By Delegates
             Walters, Webb, ...)", "[Introduced February 26, 1997; ...]"); IntroducedByMatch
             says whether the first member named is the person.

Polite: one request at a time, at least 6 seconds apart (robots.txt sets no crawl delay and
does not exclude /Bill_Status/), a User-Agent naming the project, every response cached under
wv_legislature_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/wv_legislature_bills.py --members
    python3 replication/scripts/state/wv_legislature_bills.py --lists
    python3 replication/scripts/state/wv_legislature_bills.py --texts [--limit N]
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

BASE = "https://www.wvlegislature.gov/Bill_Status/"
CACHE = "wv_legislature_cache"
YEARS = range(1993, 2010)
SESSION_TYPES = ["RS", "1X", "2X", "3X", "4X", "5X", "6X", "7X"]
PEOPLE = "replication/data/population/person_level.csv"
NAMES = "replication/data/reference/wv_sponsor_names_1993_2009.csv"
CANDIDATES = "wv_sponsor_name_candidates.csv"
LIST_OUT = "wv_lead_sponsor_bills.csv"
TEXT_OUT = "wv_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 6
_last = [0.0]
MONTHS = {m: i for i, m in enumerate("january february march april may june july august september october "
                                     "november december".split(), 1)}


def get(path, cache_path, data=None, soft=False):
    """Fetch BASE+path once (cached; POST when data is given). Returns the text, or '' for a 404
    (and, with soft=True, for a page that keeps failing, which is then not cached)."""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8", errors="replace") as f:
            return f.read()
    body = urllib.parse.urlencode(data).encode() if data else None
    for attempt in range(5):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + path, data=body, headers={"User-Agent": UA}),
                                        timeout=120) as r:
                text = r.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                text = ""
                break
            time.sleep(30 * (attempt + 1))
        except Exception:
            time.sleep(30 * (attempt + 1))
    else:
        if soft:
            print(f"  could not fetch {path}", flush=True)
            return ""
        raise SystemExit(f"giving up on {path}")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def plain(s):
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def wv_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "West Virginia" or "West Virginia" not in r["StateLegChamber"]:
                continue
            ys = set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d|present)", r["StateLegYears"]):
                ys |= set(range(int(a), (2026 if z == "present" else int(z)) + 1))
            if any(y in YEARS for y in ys):
                out.append(r)
    return out


def sponsor_page(year, st):
    return get(f"Bills_Sponsors.cfm?year={year}&sessiontype={st}&btype=bill",
               os.path.join(CACHE, "sponsors", f"{year}_{st}.html"))


def find_members():
    people = wv_people()
    rows = []
    for year in YEARS:
        for st in SESSION_TYPES:
            page = sponsor_page(year, st)
            for field, chamber in (("Input2", "House"), ("Input1", "Senate")):
                sel = re.search(rf'(?is)<select name="{field}".*?</select>', page)
                names = [html.unescape(v) for v in re.findall(r'<option value="([^"]*)"', sel.group(0))] if sel else []
                for p in people:
                    last = p["Name"].split()[-1].lower()
                    for n in names:
                        if n and last in n.lower():
                            rows.append({"year": year, "session": st, "chamber": chamber, "field": field, "sponsor": n,
                                         "bioguide_id": p["BioguideId"], "name": p["Name"],
                                         "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates for {len(people)} people; review into {NAMES}")


def history(year, st, num, btype="bill"):
    return get(f"Bills_history.cfm?input={num}&year={year}&sessiontype={st}&btype={btype}",
               os.path.join(CACHE, "history", f"{year}_{st}_{num}.html"))


def lead_sponsor(page):
    t = plain(page)
    m = re.search(r"LEAD SPONSOR:\s*(.*?)\s*(?:SPONSORS:|BILL TEXT:|CODE AFFECTED:)", t, flags=re.S)
    return " ".join(m.group(1).split()) if m else ""


def crawl_lists():
    with open(NAMES, newline="", encoding="utf-8") as f:
        names = list(csv.DictReader(f))
    out = []
    for n in names:
        year, st = int(n["year"]), n["session"]
        page = get(f"bills_sponsors.cfm?year={year}&sessiontype={st}&btype=bill",
                   os.path.join(CACHE, "lists", f"{year}_{st}_{n['field']}_{re.sub(r'[^A-Za-z]', '', n['sponsor'])}.html"),
                   data={n["field"]: n["sponsor"], ("Input1" if n["field"] == "Input2" else "Input2"): "",
                         "btn_get_sponsored_bills": "Submit"})
        found = re.search(r"sponsored (\d+) bills", page)
        nums = list(dict.fromkeys(re.findall(rf"Bills_history\.cfm\?input=(\d+)&(?:amp;)?year={year}&(?:amp;)?sessiontype={st}",
                                             page, flags=re.I)))
        if found and int(found.group(1)) != len(nums):
            print(f"  WARNING {year} {st} {n['sponsor']}: {found.group(1)} sponsored, {len(nums)} parsed")
        lead = 0
        for num in nums:
            hp = history(year, st, num)
            ls = lead_sponsor(hp)
            if ls.lower() != n["sponsor"].lower():
                continue
            lead += 1
            t = plain(hp)
            title = re.search(r"SUMMARY:\s*(.*?)\s*LEAD SPONSOR:", t, flags=re.S)
            link = re.search(r'href="(bills_text\.cfm\?billdoc=[^"]*intr[^"]*)"', hp, flags=re.I)
            out.append({"year": year, "session": st, "bioguide_id": n["bioguide_id"], "name": n["name"],
                        "chamber": n["chamber"], "sponsor": n["sponsor"],
                        "type": "HB" if int(num) >= 2000 else "SB", "number": int(num),
                        "title": " ".join(title.group(1).split())[:300] if title else "",
                        "text_link": html.unescape(link.group(1)) if link else ""})
        print(f"{year} {st} {n['chamber']} {n['sponsor']}: {len(nums)} sponsored, {lead} as lead", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} bills")


def by_line(text):
    """(names as printed, ISO date) from the heading '(By Delegates Walters, Webb, ...)' /
    '(By Senator Manchin)' and '[Introduced February 26, 1997; ...]'."""
    m = re.search(r"\(\s*By\s+(?:Delegates?|Senators?|Mr\.|Ms\.|Mrs\.)?\s*(.*?)\)", text[:3000], flags=re.S | re.I)
    names = " ".join(m.group(1).split()) if m else ""
    d = re.search(r"\[\s*(?:(?:Introduced|Originating)\s+)?(\w+)\s+(\d{1,2})[.,]\s*(\d{4})", text[:4000], flags=re.I)
    iso = f"{d.group(3)}-{MONTHS[d.group(1).lower()]:02d}-{int(d.group(2)):02d}" \
        if d and d.group(1).lower() in MONTHS else ""
    return names, iso


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        year, st, num = b["year"], b["session"], b["number"]
        text = ""
        if b["text_link"]:
            page = get(b["text_link"], os.path.join(CACHE, "texts", f"{year}_{st}_{num}.html"), soft=True)
            body = page.split("Introduced Version", 1)[-1] if page else ""
            text = plain(body)
            start = re.search(r"[HS]\.\s*B\.\s*\d+|(?:Senate|House) Bill No\.\s*\d+", text)
            text = text[start.start():] if start else ""  # no bill heading: an empty page, not the bill
        txt_path = ""
        if text:
            txt_path = os.path.join(CACHE, "texts", f"{year}_{st}_{num}.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
        names, iso = by_line(text)
        first = re.split(r",|\band\b", names)[0].strip() if names else ""
        surname = b["sponsor"].split(",")[0].split()[0]
        match = "" if not text else "Unavailable" if not names else \
            "Yes" if surname.lower() in first.lower() else "No"
        sess = "Regular Session" if st == "RS" else f"{st[0]}{dict(zip('1234567', ['st', 'nd', 'rd', 'th', 'th', 'th', 'th']))[st[0]]} Special Session"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{year} {sess}",
                    "BillNumber": f"{b['type']}{num}", "BillId": f"WV-{year}{'' if st == 'RS' else st}-{b['type']}{num}",
                    "Title": b["title"], "IntroducedDate": iso, "House": b["chamber"].upper(), "AuthorName": b["sponsor"],
                    "IntroducedBy": names[:200], "IntroducedByMatch": match, "TextVersion": "Introduced",
                    "TextPath": txt_path})
        if i % 100 == 0:
            print(f"  ...{i}/{len(bills)}", flush=True)
    # a bill introduced in the first year of a Legislature can carry over into the second; the archive then
    # lists it under both years with the same text: keep the year it was introduced
    texts = {}
    for o in out:
        if o["TextPath"]:
            with open(o["TextPath"], encoding="utf-8") as f:
                texts[o["BillId"]] = f.read()
    carried = {o["BillId"] for o in out for p in out
               if o["TextPath"] and p["TextPath"] and o["BioguideId"] == p["BioguideId"]
               and o["BillNumber"] == p["BillNumber"] and o["Session"][:4] == str(int(p["Session"][:4]) + 1)
               and "Regular" in o["Session"] and "Regular" in p["Session"] and texts[o["BillId"]] == texts[p["BillId"]]}
    if carried:
        print(f"  {len(carried)} carried-over bills listed again in the second year dropped: {sorted(carried)}")
    out = [o for o in out if o["BillId"] not in carried]
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
