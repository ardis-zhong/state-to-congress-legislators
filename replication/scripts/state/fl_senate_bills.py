#!/usr/bin/env python3
"""
Florida state bills, 1998-2009, from the Florida Senate's website (flsenate.gov), which
hosts both chambers' bills (Senate numbers even, House numbers odd) for sessions before
LegiScan's Florida coverage (2010 on). Florida state-text pilot (Ardis, 2026-10-18).

STEP 1 (--lists): every bill in every 1998-2009 session (regular, special, organization),
    from the paged session lists /Session/Bills/<session>?Chamber=<house|senate>&PageNumber=N,
    which give the bill number, title, and "Filed By" sponsor. Output: fl_bill_list.csv.
STEP 2 (--texts): for the bills filed by our people (reviewed list
    replication/data/reference/fl_filer_names_1998_2009.csv), the bill as filed (the
    introduced version): /Session/Bill/<session>/<number>/BillText/Filed/HTML.
    Output: fl_state_legislation_sponsored.csv.

Polite crawling per flsenate.gov's robots.txt (Crawl-delay: 10): one request at a time, at
least 10 seconds apart, with a User-Agent naming the project. Every response is cached
under fl_senate_cache/, so a re-run only fetches what is missing.

USAGE (from the repo root):
    python3 replication/scripts/state/fl_senate_bills.py --lists
    python3 replication/scripts/state/fl_senate_bills.py --texts
"""

import argparse
import urllib.error
import csv
import html
import os
import re
import time
import urllib.parse
import urllib.request

BASE = "https://www.flsenate.gov"
CACHE = "fl_senate_cache"
SESSIONS = ["1998", "1998O", "1999", "2000", "2000A", "2000O", "2001", "2001A", "2001B", "2001C",
            "2002", "2002D", "2002E", "2002O", "2003", "2003A", "2003B", "2003C", "2003D", "2003E",
            "2004", "2004A", "2004O", "2005", "2005B", "2006", "2006O", "2007", "2007A", "2007B",
            "2007C", "2007D", "2008", "2008O", "2009", "2009A", "2009B"]
LIST_OUT = "fl_bill_list.csv"
FILERS = "replication/data/reference/fl_filer_names_1998_2009.csv"
TEXT_OUT = "fl_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
CRAWL_DELAY = 10
_last = [0.0]


def get(path, cache_path):
    """Fetch BASE+path once (cached). Returns the text, or '' for a 404."""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8", errors="replace") as f:
            return f.read()
    for attempt in range(5):
        wait = CRAWL_DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"User-Agent": UA}),
                                        timeout=90) as r:
                data = r.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = ""
                break
            time.sleep(30 * (attempt + 1))
        except Exception:
            time.sleep(30 * (attempt + 1))
    else:
        raise SystemExit(f"giving up on {path}")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(data)
    return data


def clean(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def list_rows(page_html):
    rows = []
    for m in re.finditer(r'<tr[^>]*>\s*<th scope="row"><a href="/Session/Bill/([^/"]+)/([^/"]+)">(.*?)</a></th>'
                         r'\s*<td>(.*?)</td>\s*<td>(.*?)</td>', page_html, flags=re.S):
        rows.append({"session": m.group(1), "number": m.group(2), "label": clean(m.group(3)),
                     "title": clean(m.group(4)), "filed_by": clean(m.group(5))})
    return rows


def crawl_lists():
    out = []
    for session in SESSIONS:
        for chamber in ("senate", "house"):
            page = 1
            while True:
                q = urllib.parse.urlencode({"LegislativeSessionTitle": session, "Chamber": chamber,
                                            "SearchOnlyCurrentVersion": "True", "IsIncludeAmendments": "False",
                                            "IsFirstReference": "True", "HasInputError": "False",
                                            "PageNumber": page, "ExpandedView": "False"})
                body = get(f"/Session/Bills/{session}?{q}", os.path.join(CACHE, "lists", f"{session}_{chamber}_{page}.html"))
                rows = list_rows(body)
                for r in rows:
                    r["chamber"] = chamber.title()
                out.extend(rows)
                more = f"PageNumber={page + 1}" in body.replace("&amp;", "&")
                if not rows or not more:
                    break
                page += 1
            print(f"{session} {chamber}: {sum(1 for r in out if r['session'] == session and r['chamber'] == chamber.title())} bills, "
                  f"{page} page(s)", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["session", "chamber", "number", "label", "title", "filed_by"],
                           lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} bills")


def filed_text(html_text):
    """The filed bill's HTML page -> plain text (the bill itself, without site navigation)."""
    body = re.search(r"(?is)<pre[^>]*>(.*?)</pre>", html_text) or re.search(r"(?is)<body[^>]*>(.*?)</body>", html_text)
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", body.group(1) if body else html_text)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def by_check(text, must):
    """The filed text's "By ..." block names who filed the bill. Returns (by_line, match):
    match = "Yes" when the first individual named is our person (e.g. "By Senator Crist",
    "By the Committee on Governmental Operations and Representative Posey"); "No" when someone
    else is named first (a later sponsor in the session list, or a committee bill led by another
    member); "Unavailable" when the text has no "By" line (House bills 2003-2009 are printed
    without one), in which case the session list's "Filed By" is the only record."""
    head = text[:2500]
    m = re.search(r"\bBy\s+(.*?)(?=\n\s*(?:\d+\s*)?A bill to be entitled|\n\s*\d+-\d+[A-Z]?-\d+|\n\s*\n\s*\d)", head, flags=re.S)
    if not m:
        return "", "Unavailable"
    by_line = " ".join(m.group(1).split())
    people = re.search(r"(?:Senators?|Representatives?)\s+(.*)", by_line)
    if not people:
        return by_line, "No"  # a committee alone
    first = re.split(r",|\band\b", people.group(1))[0].strip()
    return by_line, "Yes" if first == must or first.endswith(" " + must) else "No"


def crawl_texts(limit=0):
    with open(FILERS, newline="", encoding="utf-8") as f:
        filers = list(csv.DictReader(f))
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    todo = []
    for b in bills:
        year = int(b["session"][:4])
        for r in filers:
            if b["chamber"] == r["chamber"] and int(r["first_year"]) <= year <= int(r["last_year"]) \
                    and [n.strip() for n in b["filed_by"].split(",")] == [r["filer_name"]]:
                todo.append((b, r))  # sole filer only, as for LegiScan's role-less sessions
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} bills to fetch", flush=True)
    out = []
    for i, (b, r) in enumerate(todo, 1):
        raw = get(f"/Session/Bill/{b['session']}/{b['number']}/BillText/Filed/HTML",
                  os.path.join(CACHE, "texts", f"{b['session']}_{b['number']}_filed.html"))
        text = filed_text(raw) if raw else ""
        by_line, match = by_check(text, r["text_must_name"] or r["filer_name"])
        text_path = ""
        if text:
            text_path = os.path.join(CACHE, "texts", f"{b['session']}_{b['number']}_filed.txt")
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text)
        kind = re.match(r"(?:[A-Z]+/)*([A-Z]+)\s*(\d+)", b["label"])
        bill_type = kind.group(1) if kind else ""
        sess = b["session"]
        sess_name = (f"{sess[:4]} Regular Session" if sess.isdigit() else
                     f"{sess[:4]} Organization Session" if sess.endswith("O") else
                     f"{sess[:4]} Special Session {sess[4:]}")
        out.append({"BioguideId": r["bioguide_id"], "Name": r["name"], "Session": sess_name,
                    "BillNumber": f"{bill_type}{b['number']}", "BillId": f"FL-{sess}-{bill_type}{b['number']}",
                    "Title": b["title"], "IntroducedDate": "", "House": b["chamber"].upper(),
                    "AuthorName": b["filed_by"], "ByLine": by_line[:200], "IntroducedByMatch": match,
                    "TextVersion": "Introduced", "TextPath": text_path})
        if i % 100 == 0:
            print(f"  ...{i}/{len(todo)}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; By-line check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N bills (smoke test)")
    args = ap.parse_args()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
