#!/usr/bin/env python3
"""
Arizona bills and resolutions, 1999-2009 (44th-49th Legislatures), from the Internet Archive's copies
(web.archive.org) of the Legislature's bill texts (www.azleg.gov/legtext/<n>leg/<session>/bills/), for
population members who served in the Legislature before LegiScan's Arizona coverage (2010 on):
Harry Mitchell (Senate 1999-2006), Gabby Giffords (House 2001-2002, Senate 2003-2005), Tom O'Halleran
(House 2001-2006, Senate 2007-2008), Andy Biggs (House 2003-2010), Ann Kirkpatrick (House 2005-2007),
Kyrsten Sinema (House 2005-2010) and Debbie Lesko (House 2009-2010). Arizona state-text pilot (2026-11-03).

azleg.gov asks crawlers to wait 120 seconds between requests and closes its bill-document and search
pages to them, and has no list of bills by sponsor for past Legislatures, so only the archive's copies
are read. The introduced version of each measure is the file ending in "p" (hb2059p.htm / .pdf); it
prints "Introduced by Representative Huffman" (or "Representatives Biggs, Kavanagh, ..."), the first
named being the prime sponsor (on the cover page; the 1999-2000 HTML copies omit it, so the PDF is read
where both were kept, and a measure archived only as such HTML cannot be attributed). Every archived
introduced file in scope is read (not House measures of the 44th Legislature, when no one in scope sat in
the House, nor 2010 sessions); measures whose first named sponsor is a reviewed (Legislature, chamber,
name) in replication/data/reference/az_sponsor_names_1999_2010.csv are kept.

  --cdx      The Wayback Machine's capture index for each Legislature's legtext folder (cached under
             az_wayback_cache/cdx/); prints the number of introduced files in scope.
  --scan     Reads every introduced file; logs (Legislature, session, measure, "Introduced by" names) to
             az_wayback_cache/sponsors.tsv (resumable) and keeps the texts.
  --texts    Writes az_state_legislation_sponsored.csv from the log and the reviewed names.

Polite: one request at a time, at least 5 seconds apart, a User-Agent naming the project.

USAGE (from the repo root):
    python3 replication/scripts/state/az_wayback_bills.py --cdx
    python3 replication/scripts/state/az_wayback_bills.py --scan
    python3 replication/scripts/state/az_wayback_bills.py --texts
"""

import argparse
import csv
import html
import io
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

WAYBACK = "https://web.archive.org"
CACHE = "az_wayback_cache"
NAMES = "replication/data/reference/az_sponsor_names_1999_2010.csv"
TEXT_OUT = "az_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 5
_last = [0.0]
LEGISLATURES = {44: 1999, 45: 2001, 46: 2003, 47: 2005, 48: 2007, 49: 2009}
ORDINALS = {"forty-fourth": 44, "forty-fifth": 45, "forty-sixth": 46, "forty-seventh": 47, "forty-eighth": 48,
            "forty-ninth": 49}
FILE = re.compile(r"/legtext/(\d+)leg/(\d[rs])/bills/((?:hb|sb|hcr|scr|hjr|sjr|hm|sm|hr|sr)\d+)p\.(htm|pdf)$", re.I)


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
            time.sleep(60 * (attempt + 1))
        except Exception:
            time.sleep(60 * (attempt + 1))
    print(f"  could not fetch {url}", flush=True)
    return None


def cdx(name, params):
    """Capture-index lines (cached; the archive's 'offline' or gateway error page is retried, not kept)."""
    p = os.path.join(CACHE, "cdx", f"{name}.txt")
    if not os.path.exists(p):
        q = urllib.parse.urlencode({**params, "filter": "statuscode:200", "fl": "timestamp,original"})
        for attempt in range(6):
            raw = fetch(f"{WAYBACK}/cdx/search/cdx?{q}")
            if raw is not None and (raw == b"" or re.match(rb"\d{14} ", raw)):
                break
            time.sleep(180)
        else:
            raise SystemExit(f"capture index for {name} keeps failing; run --cdx again later")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(raw)
    with open(p, encoding="utf-8") as f:
        return [line.split(" ") for line in f.read().splitlines() if line.strip()]


def files():
    """{(legislature, session '1r', measure 'hb2059'): (timestamp, url)}: one copy per introduced file,
    the PDF where the archive kept it (the 1999-2000 HTML copies omit the 'Introduced by' cover), else the
    HTML (earliest capture)."""
    best = {}
    for leg in LEGISLATURES:
        for host in ("www.azleg.gov", "azleg.gov", "www.azleg.state.az.us"):
            for ts, orig in cdx(f"{leg}leg_{host}", {"url": f"{host}/legtext/{leg}leg/", "matchType": "prefix"}):
                m = FILE.search(orig)
                if not m:
                    continue
                key = (int(m.group(1)), m.group(2).lower(), m.group(3).lower())
                if (key[0] == 44 and key[2][0] == "h") or (key[0], key[1]) == (49, "2r"):
                    continue  # no one in scope in the 1999-2000 House; LegiScan has 2010 on
                rank = (m.group(4).lower() != "pdf", ts)
                if key not in best or rank < best[key][0]:
                    best[key] = (rank, ts, orig)
    return {k: (v[1], v[2]) for k, v in best.items()}


def page_text(raw):
    if raw[:4] == b"%PDF":
        import logging
        from pdfminer.high_level import extract_text
        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        try:
            t = extract_text(io.BytesIO(raw))
        except Exception:
            return ""
        t = re.sub(r"\(cid:(\d+)\)", lambda c: chr(int(c.group(1))), t)  # some 2003-2004 PDFs map glyphs to char codes
        t = "\n".join(line.strip() for line in t.splitlines() if line.strip() and not re.fullmatch(r"\d+", line.strip()))
    else:
        s = raw.decode("cp1252", "replace")
        s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
        t = html.unescape(re.sub(r"<[^>]+>", " ", s))
        t = re.sub(r"[ \t\xa0]+", " ", t)
        t = t.replace("\u00a6", " ")  # the 2003-2004 HTML covers are drawn in box characters
        t = "\n".join(line.strip() for line in t.splitlines() if line.strip() and not re.fullmatch(r"\s*-+\s*", line))
    i = t.find("REFERENCE TITLE")
    return t[i:] if i >= 0 else t


def introduced_by(text):
    """'Introduced by Representatives Biggs, Kavanagh: ...' -> 'Biggs, Kavanagh ...' (names only)."""
    m = re.search(r"Introduced\s+by\s+((?:Representatives?|Senators?)\s.+?)(?=\n\s*(?:AN ACT|A (?:CONCURRENT|JOINT)|A (?:HOUSE |SENATE )?"
                  r"(?:RESOLUTION|MEMORIAL))|\(TEXT OF|$)", text[:4000], re.S)
    return " ".join(m.group(1).split())[:400] if m else ""


def first_named(by):
    names = re.sub(r"^(?:Representatives?|Senators?)\s+", "", by)
    names = re.sub(r"\s*\(with permission[^)]*\)", "", names)
    # a sole sponsor can run into the measure's title ('Biggs AMENDING SECTION 15-1803'): names never hold an
    # all-capitals word of two or more letters (initials are single letters: 'Rios P', 'Gardner W')
    names = re.split(r"\s+(?=[A-Z]{2,}\b)", names)[0]
    return re.split(r",|:|;| and |\s+(?:Representatives?|Senators?)\s", names)[0].strip()


def scan():
    log = os.path.join(CACHE, "sponsors.tsv")
    done = set()
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            done = {tuple(line.split("\t")[:3]) for line in f}
    todo = sorted((k, v) for k, v in files().items() if (str(k[0]), k[1], k[2]) not in done)
    print(f"{len(todo)} archived introduced files to read", flush=True)
    with open(log, "a", encoding="utf-8") as out:
        for i, ((leg, sess, measure), (ts, orig)) in enumerate(todo):
            raw = fetch(f"{WAYBACK}/web/{ts}id_/{orig}")
            if raw is None:
                continue  # retry on the next run
            text = page_text(raw) if raw else ""
            if text:
                p = os.path.join(CACHE, "texts", f"{leg}{sess}", f"{measure}.txt")
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text)
            by = introduced_by(text)
            out.write(f"{leg}\t{sess}\t{measure}\t{ts}\t{orig}\t{by}\n")
            out.flush()
            if i % 500 == 0:
                print(f"  {leg} {sess} {measure}: {i}/{len(todo)}", flush=True)


def session_label(leg, sess):
    n = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth"][int(sess[0]) - 1]
    year = LEGISLATURES[leg] + (1 if sess[0] == "2" and sess[1] == "r" else 0)
    kind = "Regular" if sess[1] == "r" else "Special"
    return f"{leg}th Legislature, {n} {kind} Session", year


def crawl_texts():
    with open(NAMES, newline="", encoding="utf-8") as f:
        reviewed = {(r["legislature"], r["chamber"], r["sponsor"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    with open(os.path.join(CACHE, "sponsors.tsv"), encoding="utf-8") as f:
        log = [line.rstrip("\n").split("\t") for line in f]
    out = []
    for leg, sess, measure, ts, orig, by in log:
        first = first_named(by)
        r = reviewed.get((leg, measure[0].upper(), first))
        if not r:
            continue
        p = os.path.join(CACHE, "texts", f"{leg}{sess}", f"{measure}.txt")
        with open(p, encoding="utf-8") as f:
            text = f.read()
        t = re.search(r"REFERENCE TITLE:\s*(.+?)\n", text)
        label, year = session_label(int(leg), sess)
        if sess[1] == "s":  # special sessions: the year printed in the heading ('Third Special Session 2002')
            y = re.search(r"Special Session\s+((?:19|20)\d\d)", text[:1500])
            year = int(y.group(1)) if y else year
        if year >= 2010:
            continue  # LegiScan's Arizona data covers 2010 on
        kind, num = re.match(r"([a-z]+)(\d+)$", measure).groups()
        out.append({"BioguideId": r["bioguide_id"], "Name": r["name"], "Session": f"{label} ({year})",
                    "BillNumber": f"{kind.upper()}{num}", "BillId": f"AZ-{leg}{sess.upper()}-{kind.upper()}{num}",
                    "Title": " ".join(t.group(1).split())[:300] if t else "", "IntroducedDate": "",
                    "House": "HOUSE" if kind[0] == "h" else "SENATE", "AuthorName": first, "IntroducedBy": by[:200],
                    "IntroducedByMatch": "Yes", "TextVersion": "Introduced", "TextPath": p,
                    "ArchivedPage": f"{orig} ({ts})"})
    rows = sorted(out, key=lambda o: o["BillId"])
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {TEXT_OUT}: {len(rows)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdx", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--texts", action="store_true")
    args = ap.parse_args()
    if args.cdx:
        fs = files()
        print(f"{len(fs)} archived introduced files in scope:",
              ", ".join(f"{leg}th {sum(1 for k in fs if k[0] == leg)}" for leg in LEGISLATURES))
        for leg in LEGISLATURES:
            for s in sorted({k[1] for k in fs if k[0] == leg}):
                print(f"  {leg} {s}: {sum(1 for k in fs if k[:2] == (leg, s))}")
    if args.scan:
        scan()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
