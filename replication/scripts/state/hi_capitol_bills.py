#!/usr/bin/env python3
"""
Hawaii state bills and resolutions, 1999-2008, from the Hawaii State Legislature's public data
website (data.capitol.hawaii.gov, which the Legislature's Reference Bureau library pointed us to for
bulk retrieval), for population members who served in the Legislature before LegiScan's Hawaii
coverage (2009-2010 on). Hawaii state-text pilot (Ardis, 2026-10-26). robots.txt sets no limits.

  --members  Each year's measures-introduced lists (/sessions/session<year>/Lists/...) name the
             introducers of every measure, the lead introducer first (1999-2000 lists name one
             member per measure). Our people's names are written as candidates for the reviewed list
             replication/data/reference/hi_introducer_names_1999_2008.csv.
  --lists    Measures whose first-named introducer is a reviewed (year, chamber, name). Bills keep
             their number for the two-year Legislature and the even-year folders repeat the odd
             year's bills, so a bill is taken from the year it was introduced. 2008 has a House and
             a Senate bill list (as of January 28, 2008, after the bill introduction deadline) but no
             resolution lists.
  --texts    The measure's introduced version, the unsuffixed file in the year's Bills folder
             (HB228_.htm; HD1/SD1/CD1 are later drafts), HTML or else PDF. Hawaii's introduced texts
             end with a blank "INTRODUCED BY: ____" signature line, so no introducer check is
             possible (IntroducedByMatch Unavailable): the Legislature's introducer lists stand.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under hi_capitol_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/hi_capitol_bills.py --members
    python3 replication/scripts/state/hi_capitol_bills.py --lists
    python3 replication/scripts/state/hi_capitol_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://data.capitol.hawaii.gov"
CACHE = "hi_capitol_cache"
YEARS = range(1999, 2009)
LISTS = {
    1999: ["Lists/all_measures.htm"],
    2000: ["Lists/hb.htm", "Lists/sb.htm", "Lists/hreso.htm", "Lists/sreso.htm"],
    2001: ["Lists/intro_list.htm"],
    2002: ["Lists/intro_list.htm"],
    2003: ["Lists/intro_list" + t + ".htm" for t in ("HB", "SB", "HCR", "HR", "SCR", "SR")],
    2004: ["Lists/intro_list" + t + ".htm" for t in ("hb", "sb", "HCR", "HR", "SCR", "SR")],
    2005: ["Lists/hb_intro.htm", "Lists/sb_intro.htm"] + ["Lists/intro_list" + t + ".htm" for t in ("HCR", "HR", "SCR", "SR")],
    2006: ["Lists/intro_list" + t + ".htm" for t in ("HB", "SB", "HCR", "HR", "SCR", "SR")],
    2007: ["Lists/intro_list" + t + ".htm" for t in ("hb", "sb", "HCR", "HR", "scr", "sr")],
    2008: ["Lists/Backup/intro_listHB_pf_all.htm", "Lists/Backup/intro_listSB_pf_all.htm"],
}
MEASURE = re.compile(r"\b(HB|SB|HCR|HR|SCR|SR)0*(\d+)\b")
TITLES = r"(?:House Speaker|Senate President|Speaker|President|Vice Speaker|Vice President|Representative|Senator)\s+"
PEOPLE = "replication/data/population/person_level.csv"
NAMES = "replication/data/reference/hi_introducer_names_1999_2008.csv"
CANDIDATES = "hi_introducer_name_candidates.csv"
LIST_OUT = "hi_introduced_measures.csv"
TEXT_OUT = "hi_state_legislation_sponsored.csv"
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
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r:
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


def parse_list(page):
    """[(measure, title, introducers)] from one measures-introduced page."""
    out = []
    if re.search(r"(?i)<td", page):
        # 2001-2008 tables: [measure, title, introducers] or (2008) [links, measure + title, introducers]
        for row in re.split(r"(?i)<tr\b", page):
            cells = [plain(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)]
            if len(cells) < 3:
                continue
            for i in (0, 1):
                m = MEASURE.match(cells[i])
                if m:
                    title = cells[i + 1] if i == 0 else cells[i][m.end():]
                    title = re.sub(r"^(?:\s*[HSC]D\d+)+\s*", "", title)
                    out.append((m.group(1) + m.group(2), title.strip(), cells[i + 2] if i == 0 else cells[2]))
                    break
        return out
    # 1999-2000 paragraphs: "HB0228&nbsp; TITLE.&nbsp; Case E (586-8475)" / "HCR001 <tab>TITLE.   Representative Case (586-8475)"
    for para in re.split(r"(?i)<p\b", page):
        text = html.unescape(re.sub(r"<[^>]+>", "", para[para.find(">") + 1:]))
        m = MEASURE.match(text.strip())
        if not m:
            continue
        rest = text.strip()[m.end():]
        parts = [p.strip() for p in re.split(r"\xa0|\t| {2,}|\s{3,}", rest) if p.strip()]
        intro = next((p for p in reversed(parts) if re.search(r"\(\d{3}-\d{4}\)", p)), "")
        title = " ".join(" ".join(p.split()) for p in parts if p != intro)
        out.append((m.group(1) + m.group(2), title, " ".join(intro.split())))
    return out


def first_introducer(intro):
    """The lead introducer's name as printed: 'TAKAI', 'B. OSHIRO', 'Case E', 'Representative Case'."""
    first = re.split(r",| and ", intro)[0]
    first = re.sub(r"\(\d{3}-\d{4}\)", "", first)
    first = re.sub(r"\((?:BR|by request)\)", "", first, flags=re.I)
    return " ".join(re.sub(r"^" + TITLES, "", first.strip()).split())


def year_lists(year):
    rows = []
    for path in LISTS[year]:
        page = cached(os.path.join(CACHE, "lists", f"session{year}_" + path.replace("/", "_")),
                      lambda: fetch(f"{BASE}/sessions/session{year}/{path}")).decode("latin-1")
        rows += parse_list(page)
    return rows


def surname_key(label):
    """'Case E' / 'CASE' / 'Representative Case' -> 'CASE'; keeps a leading initial ('B. OSHIRO')."""
    label = re.sub(r"\s+[A-Z]\.?$", "", label.strip()) if not re.match(r"^[A-Z]\.", label) else label
    return label.upper()


def hi_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Hawaii":
                continue
            ys = set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d)", r["StateLegYears"]):
                ys |= set(range(int(a), int(z) + 1))
            if ys & set(YEARS):
                r["years"] = ys
                out.append(r)
    return out


def find_members():
    rows = []
    people = hi_people()
    for year in YEARS:
        labels = {}
        for measure, _, intro in year_lists(year):
            lab = first_introducer(intro)
            labels.setdefault((measure[0], surname_key(lab)), set()).add(lab)
        for p in people:
            if year not in p["years"]:
                continue
            last = p["Name"].split()[-1].upper()
            for (chamber, key), labs in sorted(labels.items()):
                if key and key.split()[-1] == last:
                    rows.append({"year": year, "chamber": chamber, "name_key": key, "labels": "; ".join(sorted(labs)),
                                 "bioguide_id": p["BioguideId"], "name": p["Name"], "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {NAMES}")


def crawl_lists():
    with open(NAMES, newline="", encoding="utf-8") as f:
        names = {(int(r["year"]), r["chamber"], r["name_key"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    out, seen = [], set()
    for year in YEARS:
        n = 0
        for measure, title, intro in year_lists(year):
            biennium = year - (year + 1) % 2  # 1999-2000, 2001-2002, ...
            if measure[1] == "B":  # bills keep their number across the biennium
                if (biennium, measure) in seen:
                    continue
                seen.add((biennium, measure))
            r = names.get((year, measure[0], surname_key(first_introducer(intro))))
            if r:
                out.append({"year": year, "bioguide_id": r["bioguide_id"], "name": r["name"], "measure": measure,
                            "title": title, "introducers": intro})
                n += 1
        print(f"{year}: {n} measures", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} measures")


def files_of(year):
    page = cached(os.path.join(CACHE, "dirs", f"bills_{year}.html"),
                  lambda: fetch(f"{BASE}/sessions/session{year}/Bills/")).decode("latin-1")
    return re.findall(r'(?i)href="([^"]+/([^"/]+\.(?:htm|html|pdf)))"', page)


def html_text(raw):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", raw)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</tr>|</div>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    lines = [" ".join(l.split()) for l in s.split("\n")]
    return "\n".join(l for l in lines if l)


def pdf_text(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text(x_tolerance=1.5) or "") for p in pdf.pages)


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    if limit:
        items = items[:limit]
    print(f"{len(items)} measures to fetch", flush=True)
    index = {}
    out = []
    for i, b in enumerate(items, 1):
        year, measure = int(b["year"]), b["measure"]
        if year not in index:
            index[year] = {name.lower(): href for href, name in files_of(year)}
        txt = os.path.join(CACHE, "texts", f"{year}_{measure}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            for ext in ("htm", "html", "pdf"):
                href = index[year].get(f"{measure}_.{ext}".lower()) or index[year].get(f"{measure}.{ext}".lower())
                if not href:
                    continue
                url = href if href.startswith("http") else BASE + href
                local = os.path.join(CACHE, "bills", f"{year}_{measure}.{ext}")
                raw = cached(local, lambda: fetch(url))
                if ext == "pdf" and raw[:4] == b"%PDF":
                    text = pdf_text(local)
                elif ext != "pdf" and raw:
                    text = html_text(raw.decode("cp1252", "replace"))
                if "Only the PDF version of this document is available" in text:
                    text = ""  # a placeholder page: use the PDF
                if text.strip():
                    break
            if text:
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{year} Regular Session",
                    "BillNumber": measure, "BillId": f"HI-{year}-{measure}", "Title": b["title"], "IntroducedDate": "",
                    "House": "HOUSE" if measure.startswith("H") else "SENATE",
                    "AuthorName": first_introducer(b["introducers"]), "IntroducedBy": b["introducers"][:200],
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
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N measures (smoke test)")
    args = ap.parse_args()
    if args.members:
        find_members()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
