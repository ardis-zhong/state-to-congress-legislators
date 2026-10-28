#!/usr/bin/env python3
"""
Georgia House and Senate bills and resolutions, 1995-2008 (the 1995-96 to 2007-08 sessions), from the
Internet Archive's copies (web.archive.org) of the General Assembly's old website, www.legis.state.ga.us,
for population members who served in the General Assembly before LegiScan's Georgia coverage (2009 on).
Georgia state-text pilot (2026-10-28). The old site no longer exists; the current site (legis.ga.gov)
serves 2001 on only through a private, token-protected API, which is not used.

  --cdx      The Wayback Machine's capture index (CDX API) for each session folder: the latest capture with
             status 200 of every archived page (saved under ga_wayback_cache/cdx/).
  --lists    Each session's bill lists in number order (list/hb0100l.htm 1995-2002, list/hb0100.htm
             2003-2008; 100 measures a page, HB/SB/HR/SR) name every measure's first sponsor; for 2003-2008
             the archived member pages of our people ("Legislation Sponsored By ...", each measure with the
             member's position "(1)") fill in list pages the archive lacks. Writes ga_bill_list.csv (every
             measure seen); sponsors are matched to people through the reviewed
             replication/data/reference/ga_sponsor_names_1995_2008.csv (session, chamber, list name, district).
  --texts    The text of each of our people's measures: 1995-2000 the bill page (leg/fulltext/<bill>.htm),
             which carries the latest printing only (text_version from its heading: "(AS PASSED HOUSE AND
             SENATE)" = Enrolled, "(AS PASSED HOUSE)" = Engrossed, substitutes = Amended); 2001-2008 the
             earliest archived LC version (versions/<bill>_LC_.._a_<n>.htm "as introduced"; "_pf_" =
             prefiled). The text's "By: Representatives Graves of the 12th, ..." line must name the person
             first, with the right district where the line gives one (IntroducedByMatch).

Polite: one request at a time, at least 4 seconds apart, a User-Agent naming the project, every response
cached under ga_wayback_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/ga_wayback_bills.py --cdx
    python3 replication/scripts/state/ga_wayback_bills.py --lists
    python3 replication/scripts/state/ga_wayback_bills.py --texts
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

WAYBACK = "https://web.archive.org"
HOST = "www.legis.state.ga.us"
CACHE = "ga_wayback_cache"
SESSIONS = ["1995_96", "1997_98", "1999_00", "2001_02", "2003_04", "2005_06", "2007_08"]
NAMES = "replication/data/reference/ga_sponsor_names_1995_2008.csv"
LIST_OUT = "ga_bill_list.csv"
TEXT_OUT = "ga_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 4
_last = [0.0]


def fetch(url):
    """One polite request (no cache): the body as bytes, b'' for a 404, None if it keeps failing."""
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
            time.sleep(60 * (attempt + 1))  # 429/5xx: the archive asks for patience
        except Exception:
            time.sleep(60 * (attempt + 1))
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


def cdx_index(session):
    """{lower-case path below legis/<session>/: (timestamp, original URL)} for the latest 200 capture."""
    q = urllib.parse.urlencode({"url": f"{HOST}/legis/{session}/", "matchType": "prefix",
                                "fl": "urlkey,timestamp,original", "filter": "statuscode:200"})
    raw = cached(os.path.join(CACHE, "cdx", f"{session}.txt"), lambda: fetch(f"{WAYBACK}/cdx/search/cdx?{q}"))
    index = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        parts = line.split(" ")
        if len(parts) != 3:
            continue
        _, ts, orig = parts
        m = re.search(r"/legis/\d{4}_\d\d/(.+)$", orig, re.I)
        if not m:
            continue
        key = urllib.parse.unquote(m.group(1)).lower()
        if key not in index or ts > index[key][0]:
            index[key] = (ts, orig)
    return index


def page(session, key, index):
    """The archived page (decoded) for a path below legis/<session>/, or '' when not archived."""
    if key not in index:
        return ""
    ts, orig = index[key]
    local = os.path.join(CACHE, "pages", session, re.sub(r"[^a-z0-9_.-]", "_", key))
    raw = cached(local, lambda: fetch(f"{WAYBACK}/web/{ts}id_/{orig}"))
    return raw.decode("cp1252", "replace")


def plain(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())


BILL_HEAD = re.compile(r"^(HB|SB|HR|SR)\s*0*(\d+)(?:\s+(\D.*))?$")


def parse_list(text):
    """[(bill, title, first sponsor)] from a bill list page: blocks start at an 'HB 100' line, the title
    follows (on the same line from 2005), and the first sponsor is the '(1) Surname,First 12th' line
    (2003-08) or the next line (1995-2002: 'Henson, Steve')."""
    if len(text.splitlines()) < 20:  # some 2007-08 pages have no line breaks
        text = re.sub(r"\s+(?=(?:HB|SB|HR|SR) \d+ |\(\d+\) |HC:|SC:|Status:)", "\n", text)
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = BILL_HEAD.match(line)
        if not m or i + 2 >= len(lines):
            continue
        same = bool(m.group(3))
        title, sponsor = (m.group(3) if same else lines[i + 1]), ""
        for nxt in lines[i + (1 if same else 2):i + 8]:
            if BILL_HEAD.match(nxt) or re.match(r"^(HC|SC):", nxt):
                break
            sm = re.match(r"^\(1\)\s*(.+)$", nxt)
            if sm:
                sponsor = sm.group(1)
                break
            if not re.match(r"^\(\d+\)", nxt) and "," in nxt:
                sponsor = nxt
                break
        out.append((f"{m.group(1)}{m.group(2)}", title, " ".join(sponsor.split())))
    return out


def crawl_lists():
    rows = {}
    for session in SESSIONS:
        index = cdx_index(session)
        lists = sorted(k for k in index if re.fullmatch(r"(?:leg/)?list/(?:hb|sb|hr|sr)\d{4}l?\.htm", k))
        n0 = len(rows)
        for key in lists:
            for bill, title, sponsor in parse_list(plain(page(session, key, index))):
                rows.setdefault((session, bill), {"session": session, "bill": bill, "title": title,
                                                  "sponsor": sponsor, "source": key})
        # 2003-2008: our people's member pages ("(1) Graves,Tom 12th" = first sponsor)
        member_pages = []
        if os.path.exists(NAMES):
            with open(NAMES, newline="", encoding="utf-8") as f:
                member_pages = [r["member_page"] for r in csv.DictReader(f)
                                if r["session"] == session and r.get("member_page")]
        for key in sorted(set(member_pages)):
            text = plain(page(session, key, index))
            for m in re.finditer(r"^(HB|SB|HR|SR) (\d+) (.+)\n\((\d+)\) (.+)$", text, re.M):
                if m.group(4) == "1":
                    rows.setdefault((session, f"{m.group(1)}{m.group(2)}"),
                                    {"session": session, "bill": f"{m.group(1)}{m.group(2)}", "title": m.group(3),
                                     "sponsor": " ".join(m.group(5).split()), "source": key})
        print(f"{session}: {len(lists)} list pages, {len(rows) - n0} measures", flush=True)
    out = sorted(rows.values(), key=lambda r: (r["session"], r["bill"][:2], int(r["bill"][2:])))
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} measures")


def text_page(session, bill, index):
    """(key, html) of the earliest text: an LC version for 2001-2008, else the bill page."""
    b = bill.lower()
    versions = []
    for k in index:
        m = re.fullmatch(rf"versions/{b}_(.+)_(\d+)\.htm", k)
        if m:
            tag = m.group(1)
            versions.append((0 if re.search(r"(?:^|_)a$|as_introduced", tag) else 1 if re.search(r"(?:^|_)pf$", tag)
                             else 2, int(m.group(2)), k))
    for _, _, k in sorted(versions):
        s = page(session, k, index)
        if s:
            return k, s
    for k in (f"leg/fulltext/{b}.htm", f"fulltext/{b}.htm"):
        s = page(session, k, index)
        if s:
            return k, s
    return "", ""


def bill_text(session, key, s):
    """The printed bill from an archived page: from its heading line ('HB 159 LC 9 7911' or
    'HB 101 HB 101/AP' on the 1995-2000 bill pages, '02 LC 25 2228' on 2001-2008 pages) to the
    page footer."""
    t = plain(s)
    if session >= "2001":
        i = re.search(r"(?m)^(?:\d\d\s+)?LC\s+\d+\s+\d+", t)
    else:
        i = (re.search(r"(?m)^(?:HB|SB|HR|SR)\s+\d+\s+(?:(?:\d\d\s+)?LC\s+\d|(?:HB|SB|HR|SR)\s*\d+/)", t)
             or re.search(r"[HS]\.\s*[BR]\.\s*No\.\s*\d+", t))
    if not i:
        return ""
    t = t[i.start():]
    j = re.search(r"(?m)^(?:Office of the Clerk|Office of the Secretary|Clerk of the House|Secretary of the Senate|"
                  r"Top of Page|Last Updated)", t)
    return (t[:j.start()] if j else t).strip()


def version_of(key, text):
    """text_version from the archived file name (2001-2008 LC versions) or the printing's heading."""
    head = " ".join(text[:400].split())
    tag = re.sub(r"_\d+\.htm$", "", key.split("/")[-1]) if key.startswith("versions/") else ""
    if re.search(r"(?:^|_)a$|as_introduced", tag):
        return "Introduced"
    if re.search(r"(?:^|_)pf$", tag):
        return "Prefiled"
    if "adopted" in tag:
        return "Adopted"
    if re.search(r"AS PASSED HOUSE AND SENATE|AS PASSED SENATE AND HOUSE", head):
        return "Enrolled"
    if re.search(r"AS PASSED|/AP\b|(?:^|_)ap$", head + " " + tag):
        return "Engrossed"
    if tag or re.search(r"SUBSTITUTE|/CS|/FA|/SCS|/HCS|LC\s+\d+\s+\d+S\b", head):
        return "Amended"
    return "Introduced"


def crawl_texts():
    with open(NAMES, newline="", encoding="utf-8") as f:
        names = list(csv.DictReader(f))
    reviewed = {(r["session"], r["chamber"], r["list_name"].lower()): r for r in names if r["bioguide_id"]}
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    indexes = {}
    for b in items:
        session, bill = b["session"], b["bill"]
        r = reviewed.get((session, bill[0], b["sponsor"].lower()))
        if not r:
            continue
        index = indexes.setdefault(session, cdx_index(session))
        key, s = text_page(session, bill, index)
        text = bill_text(session, key, s) if s else ""
        txt = os.path.join(CACHE, "texts", session, f"{bill}.txt")
        if text:
            os.makedirs(os.path.dirname(txt), exist_ok=True)
            with open(txt, "w", encoding="utf-8") as f:
                f.write(text)
        flat = " ".join(text[:3000].split())
        by = re.search(r"By:\s*(?:Representatives?|Senators?|Reps?\.|Sens?\.)\s+(.+?)\s+(?:A\s+(?:BILL|RESOLUTION)|AN\s+ACT|$)",
                       flat)
        names_ = by.group(1) if by else ""
        first = re.split(r",(?!\s*Post)| and ", re.sub(r"\s+(?:rd|st|nd|th)\b", lambda m: m.group(0).strip(), names_))[0].strip()
        fm = re.match(r"(.+?)\s+of\s+the\s+(\d+)", first)
        surname = sq(fm.group(1) if fm else first)
        district = fm.group(2) if fm else ""
        ok = surname.endswith(sq(r["surname"])) and (not district or not r["district"] or district == r["district"])
        match = "" if not text else "Unavailable" if not names_ else "Yes" if ok else "No"
        version = version_of(key, text) if text else ""
        d = (re.search(r"(\d{1,2}/\d{1,2}/\d\d)\s+Read 1st [Tt]ime|FR:\s*(\d\d/\d\d/\d\d)", plain(s))
             if s and session < "2001" else None)
        date = time.strftime("%Y-%m-%d", time.strptime(d.group(1) or d.group(2), "%m/%d/%y")) if d else ""
        y0 = int(session[:4])
        out.append({"BioguideId": r["bioguide_id"], "Name": r["name"],
                    "Session": f"{y0}-{y0 + 1} Regular Session", "BillNumber": bill,
                    "BillId": f"GA-{y0}-{bill}", "Title": b["title"][:300], "IntroducedDate": date,
                    "House": "HOUSE" if bill[0] == "H" else "SENATE", "AuthorName": first or b["sponsor"],
                    "IntroducedBy": names_[:200], "IntroducedByMatch": match, "TextVersion": version,
                    "TextPath": txt if text else "", "ArchivedPage": key})
        print(f"  {session} {bill}: {key or 'no text'} {match} {version}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdx", action="store_true")
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    args = ap.parse_args()
    if args.cdx:
        for s in SESSIONS:
            print(f"{s}: {len(cdx_index(s))} archived pages", flush=True)
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
