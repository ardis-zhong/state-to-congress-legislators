#!/usr/bin/env python3
"""
Louisiana state bills, 1997-2009, from the Louisiana Legislature's website (legis.la.gov), for
population members who served in the Legislature before LegiScan's Louisiana coverage (2010 on).
Louisiana state-text pilot (Ardis, 2026-10-25). Regular, extraordinary and organizational
sessions from 1997 (the site's first session) to 2009.

  --members  Each session's bill search (/legis/BillSearch.aspx?sid=<session>, "Author" section)
             lists the authors with ids; our people's entries are written as candidates for the
             reviewed list replication/data/reference/la_author_ids_1997_2009.csv.
  --lists    For each reviewed (session, id): the author search (/legis/BillSearchList.aspx?srch=a),
             which lists every instrument with its primary author; the ones whose author is the
             person are kept.
  --texts    Each instrument's page (/legis/BillInfo.aspx?i=<id>) and its original version (the
             document labelled "<session> - <type> <number>", a PDF). Its heading names the authors
             ("BY REPRESENTATIVES SCALISE AND HEBERT"); an instrument counts when the person is
             named first (IntroducedByMatch). Many of the PDFs' fonts map every character 29 code
             points too low ("%<" for "BY"); such text is shifted back.

Polite: one request at a time, at least 2 seconds apart (legis.la.gov has no robots.txt), a
User-Agent naming the project, every response cached under la_legis_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/la_legis_bills.py --members
    python3 replication/scripts/state/la_legis_bills.py --lists
    python3 replication/scripts/state/la_legis_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import http.cookiejar
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://legis.la.gov/legis/"
CACHE = "la_legis_cache"
SESSIONS = {"97RS": "1997 Regular Session", "98RS": "1998 Regular Session", "981ES": "1998 First Extraordinary Session",
            "99RS": "1999 Regular Session", "00OS": "2000 Organizational Session",
            "001ES": "2000 First Extraordinary Session", "00RS": "2000 Regular Session",
            "002ES": "2000 Second Extraordinary Session", "011ES": "2001 First Extraordinary Session",
            "01RS": "2001 Regular Session", "012ES": "2001 Second Extraordinary Session",
            "021ES": "2002 First Extraordinary Session", "02RS": "2002 Regular Session", "03RS": "2003 Regular Session",
            "04OS": "2004 Organizational Session", "041ES": "2004 First Extraordinary Session",
            "04RS": "2004 Regular Session", "05RS": "2005 Regular Session", "051ES": "2005 First Extraordinary Session",
            "061ES": "2006 First Extraordinary Session", "06RS": "2006 Regular Session",
            "062ES": "2006 Second Extraordinary Session", "07RS": "2007 Regular Session",
            "08OS": "2008 Organizational Session", "081ES": "2008 First Extraordinary Session",
            "082ES": "2008 Second Extraordinary Session", "08RS": "2008 Regular Session", "09RS": "2009 Regular Session"}
PEOPLE = "replication/data/population/person_level.csv"
IDS = "replication/data/reference/la_author_ids_1997_2009.csv"
CANDIDATES = "la_author_id_candidates.csv"
LIST_OUT = "la_authored_bills.csv"
TEXT_OUT = "la_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
P = "ctl00$ctl00$PageBody$PageContent$"
_last = [0.0]
_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))
_opener.cookiejar = _jar


def fetch(url, data=None):
    """One polite request (no cache): the body as bytes, b'' for a 404, None if it keeps failing."""
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            body = urllib.parse.urlencode(data).encode() if data else None
            with _opener.open(urllib.request.Request(url, data=body, headers={"User-Agent": UA}), timeout=180) as r:
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


def form_fields(page):
    return {n: html.unescape(v) for n, v in re.findall(r'<input[^>]*name="(__[^"]+)"[^>]*value="([^"]*)"', page)}


def author_section(sid):
    """The bill search page with its Author section open (fresh, for its form state)."""
    url = f"{BASE}BillSearch.aspx?sid={sid}"
    page = (fetch(url) or b"").decode("utf-8", "replace")
    d = form_fields(page)
    d[P + "btnHeadAuthor"] = "Author"
    return (fetch(url, d) or b"").decode("utf-8", "replace")


def plain(s):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", s)
    t = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return " ".join(t.split())


def la_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Louisiana" and "Louisiana" not in r["StateLegChamber"]:
                continue
            s, ys = re.sub(r"\bpresent\b", "2026", r["StateLegYears"], flags=re.I), set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*(?:[A-Za-z]+\s+)?((?:19|20)\d\d)", s):
                ys |= set(range(int(a), int(z) + 1))
            if any(1997 <= y <= 2009 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def find_members():
    rows = []
    people = la_people()
    for sid, label in SESSIONS.items():
        year = int(label[:4])
        page = cached(os.path.join(CACHE, "search", f"{sid}.html"), lambda: author_section(sid).encode()).decode()
        sel = re.search(r'(?is)<select[^>]*name="[^"]*ddlAuthors"[^>]*>(.*?)</select>', page)
        authors = re.findall(r'value="(\d+)"[^>]*>([^<]+)<', sel.group(1)) if sel else []
        for p in people:
            if year not in p["years"]:
                continue
            last = p["Name"].split()[-1].lower()
            for aid, name in authors:
                name = " ".join(html.unescape(name).split())
                if name.lower().startswith(last + ","):
                    rows.append({"session": sid, "year": year, "author_id": aid, "label": name,
                                 "bioguide_id": p["BioguideId"], "name": p["Name"], "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {IDS}")


def search_author(sid, aid):
    _opener.cookiejar.clear()  # the site keeps the last search in the session; start each search afresh
    page = author_section(sid)
    d = form_fields(page)
    d[P + "ddlAuthors"] = aid
    d[P + "btnSearchByAuthor"] = "Search"
    res = (fetch(f"{BASE}BillSearchList.aspx?srch=a", d) or b"").decode("utf-8", "replace")
    total = re.search(r"There (?:are|is) (\d+) Instruments? in this List", res)
    if total and int(total.group(1)) > len(set(re.findall(r'href="BillInfo\.aspx\?i=(\d+)"', res))):
        d = form_fields(res)  # "Show 100 Items"
        d["__EVENTTARGET"] = P + "LinkBtnDisplayCount"
        res = (fetch(f"{BASE}BillSearchList.aspx?srch=a", d) or b"").decode("utf-8", "replace")
    if "Search Results" not in res and "ctl00_PageBody_LabelBillID" not in res:
        # bounced back to the search form: don't cache, a re-run tries again (a search with a single
        # result goes straight to that instrument's page, which is kept)
        print(f"  no results page for {sid} author {aid}", flush=True)
        return None
    return res.encode()


def crawl_lists():
    with open(IDS, newline="", encoding="utf-8") as f:
        ids = list(csv.DictReader(f))
    out = []
    for k in ids:
        res = cached(os.path.join(CACHE, "lists", f"{k['session']}_{k['author_id']}.html"),
                     lambda: search_author(k["session"], k["author_id"])).decode("utf-8", "replace")
        total = re.search(r"There (?:are|is) (\d+) Instruments? in this List", res)
        rows = re.findall(r'(?s)href="BillInfo\.aspx\?i=(\d+)"[^>]*>([A-Z]+\d+)</a>.*?_LinkAuthor"[^>]*>([^<]*)</a>'
                          r'.*?_LabelKWordAndSTitle">(.*?)</span>', res)
        one = re.search(r'BillInfo\.aspx\?i=(\d+)', "".join(re.findall(r'<form[^>]*action="([^"]*)"', res)))
        if one and "ctl00_PageBody_LabelBillID" in res:  # single result: the instrument's own page
            span = lambda n: (re.search(rf'id="ctl00_PageBody_{n}"[^>]*>([^<]*)<', res) or [None, ""])[1]
            full = html.unescape(span("LinkAuthor")).split()
            rows = [(one.group(1), span("LabelBillID"), full[-1] if full else "", span("LabelShortTitle"))]
            total = None
        if total and int(total.group(1)) != len(rows):
            print(f"  WARNING {k['session']} {k['name']}: {total.group(1)} listed, {len(rows)} parsed")
        sq = lambda x: re.sub(r"[^A-Z]", "", html.unescape(x).upper())
        surname = sq(k["label"].split(",")[0])
        given = k["label"].split(",", 1)[1].strip() if "," in k["label"] else ""
        # the author column prints the surname, with the initial when a namesake serves ("RALEXANDER")
        own = [r for r in rows if sq(r[2]) in (surname, sq(given[:1]) + surname)]
        for i, bill, author, title in own:
            out.append({"session": k["session"], "year": k["year"], "bioguide_id": k["bioguide_id"], "name": k["name"],
                        "label": k["label"], "bill_info_id": i, "bill": bill, "author": author.strip(),
                        "title": " ".join(html.unescape(re.sub(r"<[^>]+>", " ", title)).split())[:300]})
        print(f"{k['session']} {k['name']}: {len(rows)} listed, {len(own)} as author", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} instruments")


INV = {"’": 0x27, "‘": 0x60}  # pdfminer's StandardEncoding names for codes 0x27 and 0x60


def unshift(t):
    """Undo the 29-code-point font shift ('%<' -> 'BY'); spaces and line breaks added by the
    extractor stay as they are."""
    out = []
    for tok in re.split(r"(\(cid:\d+\))", t):
        m = re.fullmatch(r"\(cid:(\d+)\)", tok)
        if m:
            out.append(chr(int(m.group(1)) + 29))
            continue
        for c in tok:
            out.append(c if c in " \n" else chr(INV.get(c, ord(c)) + 29) if c in INV or ord(c) < 0x2000 else c)
    return "".join(out)


def english(t):
    return len(re.findall(r"\b(?:the|of|and|to|in|for|by)\b", t, flags=re.I))


def pdf_text(path):
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    try:
        with pdfplumber.open(path) as pdf:
            raw = "\n".join((page.extract_text(x_tolerance=1.5) or "") for page in pdf.pages).strip()
    except Exception:
        return ""
    fixed = unshift(raw)
    return fixed if english(fixed) > english(raw) else raw


def heading(text):
    """The names after 'BY REPRESENTATIVE(S)/SENATOR(S)' in the heading: that line plus wrapped
    continuation lines (upper case, before the subject line 'KEYWORD: ...')."""
    lines = [ln.strip() for ln in text[:4000].splitlines()]
    for n, ln in enumerate(lines):
        m = re.match(r"BY\s+(?:REPRESENTATIVES?|SENATORS?)\s+(.*)", ln)
        if m:
            names = m.group(1)
            for nxt in lines[n + 1:n + 4]:
                if not nxt or ":" in nxt or re.match(r"\d", nxt) or nxt != nxt.upper() or not names.rstrip().endswith((",", "AND")):
                    break
                names += " " + nxt
            return " ".join(names.split())
    return ""


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} instruments to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        s, bill = b["session"], b["bill"]
        txt = os.path.join(CACHE, "texts", f"{s}_{bill}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            info = cached(os.path.join(CACHE, "info", f"{b['bill_info_id']}.html"),
                          lambda: fetch(f"{BASE}BillInfo.aspx?i={b['bill_info_id']}")).decode("utf-8", "replace")
            typ, num = re.match(r"([A-Z]+)(\d+)", bill).groups()
            docs = re.findall(r'href="ViewDocument\.aspx\?d=(\d+)"[^>]*>([^<]*)</a>', info)
            # "97RS - HB 70" through 2003, "HB199 Original" from 2004 (study requests: "SCS1 Original")
            want = {f"{s} - {typ} {num}", f"{typ}{num} Original", f"{typ.removesuffix('R')}{num} Original"}
            orig = next((d for d, lab in docs if " ".join(html.unescape(lab).split()) in want), None)
            if orig:
                pdf = os.path.join(CACHE, "texts", f"{s}_{bill}.pdf")
                if cached(pdf, lambda: fetch(f"{BASE}ViewDocument.aspx?d={orig}"))[:4] == b"%PDF":
                    text = pdf_text(pdf)
            if text:
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        names = heading(text)
        first = re.split(r",|\bAND\b", names)[0] if names else ""
        first = re.sub(r"\(BY REQUEST\)", "", first).strip()
        sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
        surname = b["label"].split(",")[0]
        given = b["label"].split(",", 1)[1].strip() if "," in b["label"] else ""
        # the surname, or the person's own initial and surname ("R. ALEXANDER" once a namesake served)
        ok = sq(first) == sq(surname) or bool(given) and sq(first) == sq(given[0] + surname)
        match = "" if not text else "Unavailable" if not names else "Yes" if ok else "No"
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": SESSIONS[s],
                    "BillNumber": bill, "BillId": f"LA-{s}-{bill}", "Title": b["title"], "IntroducedDate": "",
                    "House": "HOUSE" if bill.startswith("H") else "SENATE", "AuthorName": first,
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
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N instruments (smoke test)")
    args = ap.parse_args()
    if args.members:
        find_members()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
