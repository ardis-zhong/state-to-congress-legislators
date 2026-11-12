#!/usr/bin/env python3
"""
Florida bills before 1998 from the Internet Archive's copies of the Legislature's former Online Sunshine
website (www.leg.state.fl.us/session/<year>/...), for population members in the Florida Legislature before
the flsenate.gov archive used by fl_senate_bills.py (1998 on). The live Online Sunshine paths answer 403 and
the Legislature's own sites have no older bill text.

Each archived bill-information page (session/<year>/<senate|house>/bills/billinfo/html/sb0002.html) prints
the bill's filers: "S 2 GENERAL BILL/CS/1ST ENG by Ways and Means; Meadows; (CO-SPONSORS) Casas; Dyer".
Committees (committee substitutes) come first, then the members who filed it, then co-sponsors. As in
fl_senate_bills.py, a bill counts when its sole individual filer is the person (reviewed list
replication/data/reference/fl_filer_names_1995_1997.csv: year, chamber H/S, filer, bioguide_id, name, note),
and the introduced text's "By Senator X" / "By Representative X" line must name the person.

  --cdx    capture index per session year (cached under fl_wayback_cache/cdx/)
  --scan   reads every archived bill-information page (earliest capture); logs (year, chamber, number, filers)
           to fl_wayback_cache/filers.tsv (resumable)
  --texts  fetches the introduced text (archived billtext/<sb0002>.html, else the PDF) for reviewed filers and
           writes fl_wayback_state_legislation_sponsored.csv

Polite: one request at a time, at least 5 seconds apart, a User-Agent naming the project.
USAGE (from the repo root):  python3 replication/scripts/state/fl_wayback_bills.py --cdx --scan --texts
"""

import argparse
import csv
import html
import io
import os
import re
import time
import urllib.error
import urllib.request

WAYBACK = "https://web.archive.org"
CACHE = "fl_wayback_cache"
NAMES = "replication/data/reference/fl_filer_names_1995_1997.csv"
TEXT_OUT = "fl_wayback_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 5
YEARS = (1995, 1996, 1997)
INFO = re.compile(r"/session/(\d{4})/(senate|house)/bills/billinfo/html/(sb|hb|s|h)(\d+)\.html$", re.I)  # 1995-96: h0001
TEXT = re.compile(r"/session/(\d{4})/(senate|house)/bills/(?:billinfo/html/(?:\.\.%5c\.\.%5c)?)?billtext"
                  r"(?:%5c|/)(?:(html)(?:%5c|/)billtext(?:%5c|/)(sb|hb)(\d+)\.html|(pdf)(?:%5c|/)(s|h)(\d+)\.pdf)$", re.I)
COMMITTEE_WORDS = re.compile(r"&|\(|\b(?:and|Committee|Appropriations|Judiciary|Rules|Finance|Commerce|Education|"
                             r"Transportation|Agriculture|Ethics|Health|Governmental|Criminal|Regulat\w*|Banking|"
                             r"Natural Resources|Community|Children|Elder|Insurance|Tourism|Utilities|Corrections|"
                             r"Ways|Means|Environmental|Fiscal|Select|Joint|Executive|Business|Real Property|"
                             r"Military|Veterans|Water|Housing|Law Enforcement|Juvenile|Family|Tax|Claims)\b", re.I)
_last = [0.0]


def fetch(url):
    for attempt in range(5):
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
            time.sleep(60 * (attempt + 1))
        except Exception:
            time.sleep(60 * (attempt + 1))
    print(f"  could not fetch {url}", flush=True)
    return None


def cdx(year):
    path = os.path.join(CACHE, "cdx", f"{year}.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return [line.split(" ") for line in f.read().splitlines() if line]
    url = (f"{WAYBACK}/cdx/search/cdx?url=www.leg.state.fl.us/session/{year}/*&output=txt&fl=timestamp,original"
           f"&filter=statuscode:200&limit=200000")
    raw = fetch(url)
    if raw is None or b"Temporarily Offline" in raw or b"<html" in raw[:300].lower():
        print(f"  capture index for {year} unavailable (archive offline?); retry later", flush=True)
        return []
    lines = [line.split(" ") for line in raw.decode("utf-8", "replace").splitlines() if line]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(" ".join(x) for x in lines) + "\n")
    return lines


def index():
    """({(year, H|S, number): (ts, url)} for bill-information pages, {(year, H|S, number): [(kind, ts, url)]} for
    unsuffixed bill texts), earliest capture first."""
    info, texts = {}, {}
    for year in YEARS:
        for ts, orig in cdx(year):
            m = INFO.search(orig)
            if m:
                key = (int(m.group(1)), m.group(3)[0].upper(), int(m.group(4)))
                if key not in info or ts < info[key][0]:
                    info[key] = (ts, orig)
                continue
            m = TEXT.search(orig)
            if m:
                if m.group(3):
                    key, kind = (int(m.group(1)), m.group(4)[0].upper(), int(m.group(5))), "html"
                else:
                    key, kind = (int(m.group(1)), m.group(7).upper(), int(m.group(8))), "pdf"
                texts.setdefault(key, []).append((kind, ts, orig))
    for v in texts.values():
        v.sort(key=lambda x: (x[0] != "html", x[1]))
    return info, texts


def plain(raw):
    t = raw.decode("cp1252", "replace")
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</pre>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", t)


def filers(page_text):
    """'... by Ways and Means; Meadows; (CO-SPONSORS) Casas' -> ['Meadows'] (committees dropped)."""
    flat = " ".join(page_text.split())
    m = re.search(r"\b(?:GENERAL BILL|LOCAL BILL|JOINT RESOLUTION|CONCURRENT RESOLUTION|RESOLUTION|MEMORIAL|BILL)\b"
                  r"[^;]*?\sby\s+(.+?)(?:\(CO-SPONSORS\)|\((?:Compare|Similar|Identical|Linked)|$)", flat)
    if not m:
        return None
    seg = m.group(1)
    # Without a co-sponsor or companion marker the filers run straight into the short title, which the page
    # header prints first ('General Bill S100: Radio Station WFLZ, 93.3 FM Click here ...' / 1997
    # 'S200: Condominium Association Liens Florida Legislature ...'): cut the filer list there.
    t = re.search(r"\b[SH]\s?0*\d+:\s+(.+?)\s+(?:Click here|Florida Legislature)", flat)
    if t:
        k = seg.find(" " + t.group(1).strip())
        if k >= 0:
            seg = seg[:k]
    parts = [p.strip() for p in seg.split(";") if p.strip()]
    return [p for p in parts if not COMMITTEE_WORDS.search(p)]


def suspect(fl):
    """A filers.tsv entry written before the short-title cut that may have lost or garbled the filer."""
    if fl in ("#none", ""):
        return True
    return any(len(p.split()) > 3 or p[:1].islower() or re.search(r"\d", p) for p in fl.split(";"))


def scan():
    log = os.path.join(CACHE, "filers.tsv")
    done = set()
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                # rows from the first parser (5 columns) are re-read when they look garbled; 'v2' rows are final
                if len(p) > 5 or not suspect(p[4]):
                    done.add(tuple(p[:3]))
    info, _ = index()
    todo = sorted((k, v) for k, v in info.items() if (str(k[0]), k[1], str(k[2])) not in done)
    print(f"{len(todo)} archived bill-information pages to read", flush=True)
    with open(log, "a", encoding="utf-8") as out:
        for i, ((year, ch, num), (ts, orig)) in enumerate(todo, 1):
            page = os.path.join(CACHE, "pages", str(year), f"{ch}{num}.html")
            if os.path.exists(page):
                raw = open(page, "rb").read()
            else:
                raw = fetch(f"{WAYBACK}/web/{ts}id_/{orig}")
                if raw is None:
                    continue
                os.makedirs(os.path.dirname(page), exist_ok=True)
                with open(page, "wb") as pf:
                    pf.write(raw)
            fl = filers(plain(raw)) if raw else None
            out.write(f"{year}\t{ch}\t{num}\t{ts}\t{'#none' if fl is None else ';'.join(fl)}\tv2\n")
            out.flush()
            if i % 100 == 0:
                print(f"  {year} {ch}{num}: {i}/{len(todo)}", flush=True)


def by_line_ok(text, surname):
    flat = " ".join(text[:3000].split())
    m = re.search(r"\bBy\s+(?:the\s+)?(?:Committee on .{3,90}?\s+and\s+)?(?:Senators?|Representatives?)\s+([A-Z][A-Za-z.' \-]+?)(?:[,;]|\s+and\s|\s{2}|\s+[a-z]|\s+\d|$)", flat)
    if not m:
        return "Unavailable"
    return "Yes" if re.sub(r"[^a-z]", "", m.group(1).lower()).startswith(re.sub(r"[^a-z]", "", surname.lower())) else "No"


def crawl_texts():
    with open(NAMES, newline="", encoding="utf-8") as f:
        reviewed = {(r["year"], r["chamber"], r["filer"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    _, texts = index()
    out = []
    with open(os.path.join(CACHE, "filers.tsv"), encoding="utf-8") as f:
        latest = {}  # a page re-read with the v2 parser replaces its earlier row
        for line in f:
            p = line.rstrip("\n").split("\t")
            latest[tuple(p[:3])] = p[:5]
        log = list(latest.values())
    for year, ch, num, ts, fl in log:
        names = [n for n in fl.split(";") if not COMMITTEE_WORDS.search(n)] if fl and fl != "#none" else []
        if len(names) == 1 and (year, ch, names[0]) not in reviewed:
            # pages without a '(CO-SPONSORS)' or 'Compare' marker run the filer into the title:
            # 'Crist Habitual Felony Offender/Sentencing provides ...' -> 'Crist'
            run_on = [k[2] for k in reviewed if k[:2] == (year, ch) and names[0].startswith(k[2] + " ")]
            if run_on:
                names = [max(run_on, key=len)]
        if len(names) != 1 or (year, ch, names[0]) not in reviewed:
            continue
        r = reviewed[(year, ch, names[0])]
        p = os.path.join(CACHE, "texts", year, f"{ch}B{num}.txt")
        text = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        for kind, tts, orig in ([] if text else texts.get((int(year), ch, int(num)), [])):
            raw = fetch(f"{WAYBACK}/web/{tts}id_/{orig}")
            if not raw:
                continue
            if kind == "pdf" and raw[:4] == b"%PDF":
                from pdfminer.high_level import extract_text
                try:
                    text = extract_text(io.BytesIO(raw)) or ""
                except Exception:
                    text = ""
            elif kind == "html":
                text = plain(raw).strip()
            if text:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as tf:
                    tf.write(text)
                break
        t = re.search(r"\bA bill to be entitled\s+(An act .+?)(?:;|\.)", " ".join(text.split()), re.I)
        out.append({"BioguideId": r["bioguide_id"], "Name": r["name"], "Session": f"{year} Regular Session",
                    "BillNumber": f"{ch}B{num}", "BillId": f"FL-{year}-{ch}B{num}",
                    "Title": t.group(1)[:300] if t else "", "IntroducedDate": "",
                    "House": "SENATE" if ch == "S" else "HOUSE", "AuthorName": names[0], "IntroducedBy": names[0],
                    "IntroducedByMatch": by_line_ok(text, names[0]) if text else "",
                    "TextVersion": "Introduced", "TextPath": p if text else ""})
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["BioguideId"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; By-line check "
          f"{dict(Counter(o['IntroducedByMatch'] for o in out))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdx", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--texts", action="store_true")
    a = ap.parse_args()
    if a.cdx:
        info, texts = index()
        print(f"{len(info)} bill-information pages, {len(texts)} bills with an archived unsuffixed text")
    if a.scan:
        scan()
    if a.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
