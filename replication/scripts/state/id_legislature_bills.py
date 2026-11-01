#!/usr/bin/env python3
"""
Idaho bills, resolutions and memorials, 1998-2014, from the Idaho Legislature's website
(legislature.idaho.gov/sessioninfo/<year>/legislation/), for population members who served in the
Legislature from 1998 on: Mike Simpson (House 1998), Bill Sali (House 1998-2006), Jim Risch (Senate
1998-2002), Russ Fulcher (Senate 2005-2014) and Raul Labrador (House 2007-2010). Idaho state-text pilot
(2026-10-29). LegiScan's Idaho data names almost no sponsors for 2010-2011 and only committees from
2012, so Fulcher's 2010-2014 bills are read here too.

Most Idaho measures are introduced by committees ("BY STATE AFFAIRS COMMITTEE"); a member's own
measure prints the member's name instead ("BY CLARK", "BY SALI AND BARRETT"). The session lists give
no sponsors, so every measure page of each session is read (one page holds the daily history and the
bill as introduced; in some older sessions an amended bill's page holds only the amended
text, headed 'As Amended', and is marked TextVersion Amended). From 2009 the page prints the sponsor
('by SCHROEDER') and links the bill as introduced as a PDF (/wp-content/uploads/sessioninfo/<year>/
legislation/S1001.pdf); the PDF is read only for measures whose page names a member in KEEP. The "BY ..."
line of the introduced text is logged for every measure (the page's 'by' line from 2009); measures
whose first named sponsor is a reviewed (session, chamber, name) in
replication/data/reference/id_sponsor_names_1998_2014.csv are kept (IntroducedByMatch = Yes: the
introduced text itself names the person first).

  --scan     Reads every measure page (resumable; log id_legislature_cache/sponsors.tsv; the bill
             text section of each page is kept under id_legislature_cache/texts/).
  --texts    Writes id_state_legislation_sponsored.csv from the log and the reviewed names.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project (robots.txt
closes only WordPress admin and calendar paths).

USAGE (from the repo root):
    python3 replication/scripts/state/id_legislature_bills.py --scan
    python3 replication/scripts/state/id_legislature_bills.py --texts
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

SITE = "https://legislature.idaho.gov/sessioninfo"
SESSIONS = ["1998", "1999", "2000", "2000extra1", "2001", "2002", "2003", "2004", "2005", "2006", "2006extra1",
            "2007", "2008", "2009", "2010", "2011", "2012", "2013", "2014"]
CACHE = "id_legislature_cache"
NAMES = "replication/data/reference/id_sponsor_names_1998_2014.csv"
TEXT_OUT = "id_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
_last = [0.0]
KEEP = ("SIMPSON", "SALI", "RISCH", "FULCHER", "LABRADOR")  # surnames whose 2009+ PDFs are read
KINDS = r"BILL|CONCURRENT RESOLUTION|JOINT MEMORIAL|JOINT RESOLUTION|JOINT PROCLAMATION|RESOLUTION|PROCLAMATION"


def fetch(url):
    """One polite request (no cache): the body as bytes, b'' for a 404, None if it keeps failing."""
    for attempt in range(5):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            time.sleep(30 * (attempt + 1))
        except Exception:
            time.sleep(30 * (attempt + 1))
    print(f"  could not fetch {url}", flush=True)
    return None


def plain(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())


def measures(session):
    """Measure numbers on the session's legislation list (H0001, S1001, HCR001, ...)."""
    p = os.path.join(CACHE, "lists", f"{session}.html")
    if not os.path.exists(p):
        raw = fetch(f"{SITE}/{session}/legislation/")
        if not raw:
            raise SystemExit(f"no legislation list for {session}")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(raw)
    with open(p, encoding="utf-8", errors="replace") as f:
        s = f.read()
    return sorted(set(re.findall(rf"/sessioninfo/{session}/legislation/([A-Z]+\d+)", s)))


def bill_text(page):
    """The 'Bill Text' section (the measure as introduced), as plain text."""
    m = re.search(r'(?i)name="billtext"', page)
    if not m:
        return ""
    rest = page[m.end():]
    end = re.search(r'(?i)<a\s+name="', rest)
    text = plain(rest[:end.start()] if end else rest)
    i = text.find("LEGISLATURE OF THE STATE OF IDAHO")
    return text[i:] if i >= 0 else text


def page_by(page, m):
    """The sponsor printed on a 2009+ measure page ('S1001' / 'by SCHROEDER'; amended 'H0014aa,aaS')."""
    b = re.search(rf"(?m)^{m}[a-zA-Z,]*\n[bB][yY] (.+)$", plain(page))
    return " ".join(b.group(1).split()) if b else ""


def pdf_text(raw):
    """Text of a bill PDF without its line-number column (the numbers come out as lines of their own)."""
    import io
    import logging
    from pdfminer.high_level import extract_text
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    t = extract_text(io.BytesIO(raw)).replace("\xad", "-")
    t = "\n".join(line.strip() for line in t.splitlines() if line.strip() and not re.fullmatch(r"\d+", line.strip()))
    i = t.find("LEGISLATURE OF THE STATE OF IDAHO")
    return t[i:] if i >= 0 else t


def by_line(text):
    """The 'BY ...' sponsor string under the heading, e.g. 'SALI AND BARRETT', 'STATE AFFAIRS COMMITTEE'."""
    m = re.search(rf"\b(?:HOUSE|SENATE) (?:{KINDS}) NO\. \d+[^\n]*\n\s*BY (.+?)\s*\n\s*(?:Requested by|1 |AN ACT|A (?:CONCURRENT|JOINT|RESOLUTION|PROCLAMATION))", text[:3000], re.S)
    return " ".join(m.group(1).split()) if m else ""


def version_of(text):
    """The text section is the bill as introduced unless its heading says 'As Amended' (older sessions)."""
    m = re.search(rf"\b(?:HOUSE|SENATE) (?:{KINDS}) NO\. \d+([^\n]*)", text[:1500])
    return "Amended" if m and "amended" in m.group(1).lower() else "Introduced"


def first_named(by):
    return re.split(r",| AND ", by)[0].strip()


def scan():
    log = os.path.join(CACHE, "sponsors.tsv")
    done = set()
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            done = {tuple(line.split("\t")[:2]) for line in f}
    os.makedirs(CACHE, exist_ok=True)
    with open(log, "a", encoding="utf-8") as out:
        for session in SESSIONS:
            ms = measures(session)
            todo = [m for m in ms if (session, m) not in done]
            print(f"{session}: {len(ms)} measures, {len(todo)} to read", flush=True)
            for i, m in enumerate(todo):
                raw = fetch(f"{SITE}/{session}/legislation/{m}/")
                if raw is None:
                    continue  # retry on the next run
                page = raw.decode("utf-8", "replace")
                text = bill_text(page)
                by = by_line(text)
                if not text and session >= "2009":
                    by = page_by(page, m)
                    if any(k in by.upper() for k in KEEP):
                        pdf = fetch(f"https://legislature.idaho.gov/wp-content/uploads/sessioninfo/{session}/legislation/{m}.pdf")
                        text = pdf_text(pdf) if pdf else ""
                if text:
                    p = os.path.join(CACHE, "texts", session, f"{m}.txt")
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(text)
                out.write(f"{session}\t{m}\t{by}\n")
                out.flush()
                if i % 200 == 0:
                    print(f"  {session} {m}: {i}/{len(todo)}", flush=True)


def crawl_texts():
    with open(NAMES, newline="", encoding="utf-8") as f:
        reviewed = {(r["session"], r["chamber"], r["sponsor"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    with open(os.path.join(CACHE, "sponsors.tsv"), encoding="utf-8") as f:
        log = [line.rstrip("\n").split("\t") for line in f]
    out = []
    for session, m, _ in log:
        p = os.path.join(CACHE, "texts", session, f"{m}.txt")
        if not os.path.exists(p):
            continue  # no bill text on the site
        with open(p, encoding="utf-8") as f:
            text = f.read()
        by = by_line(text)  # re-read from the saved text, so parser fixes apply to pages already scanned
        first = first_named(by)
        r = reviewed.get((session, m[0], first))
        if not r:
            continue
        t = re.search(r"\n\s*(?:1 )?(AN ACT|A (?:CONCURRENT|JOINT) (?:RESOLUTION|MEMORIAL)|A (?:SENATE |HOUSE )?RESOLUTION|A PROCLAMATION)\b(.+?)(?:\n\s*(?:\d+ )?Be It|\n\s*(?:\d+ )?WHEREAS|\n\s*(?:\d+ )?We,|$)",
                      text, re.S)
        title = re.sub(r"\s\d+\s", " ", " ".join((t.group(1) + t.group(2)).split())) if t else ""
        kind, num = re.match(r"([A-Z]+?)(\d+)$", m).groups()
        year = session[:4]
        out.append({"BioguideId": r["bioguide_id"], "Name": r["name"],
                    "Session": f"{year} {'First Extraordinary' if 'extra' in session else 'Regular'} Session",
                    "BillNumber": f"{kind}{int(num)}", "BillId": f"ID-{session.replace('extra', 'E')}-{kind}{int(num)}",
                    "Title": title[:300], "IntroducedDate": "", "House": "HOUSE" if m[0] == "H" else "SENATE",
                    "AuthorName": first, "IntroducedBy": by[:200], "IntroducedByMatch": "Yes",
                    "TextVersion": version_of(text), "TextPath": p})
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--texts", action="store_true")
    args = ap.parse_args()
    if args.scan:
        scan()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
