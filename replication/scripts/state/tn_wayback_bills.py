#!/usr/bin/env python3
"""
Tennessee House and Senate bills and joint resolutions, 1997-2002 and 2007-2008, from the Internet
Archive's copies (web.archive.org) of the General Assembly's old bill text files on
www.legislature.state.tn.us, for population members who served in the General Assembly before
LegiScan's Tennessee coverage (2009 on). Tennessee state-text pilot (2026-10-28).

The General Assembly's sites (capitol.tn.gov, wapp.capitol.tn.gov) close robots.txt to every crawler
but the Internet Archive's, so only the archive's copies are read. What it kept:
  - 100th General Assembly (1997-1998): bills/100gahtm/100_bill/HB0902.htm (HTML),
  - 101st (1999-2000): bills/101gahtm/101_bill/SB0330.pdf,
  - 102nd (2001-2002) and 105th (2007-2008): bills/currentga/BILL/SB0113.pdf, a path reused by each
    General Assembly, so the capture date says which one (2001-2002 thin; 2003-2006 almost nothing).
Each file is the bill as filed ("Filed for intro on 02/08/99", printed 1997-2000 only) and names each
chamber's bill and prime sponsor: "SENATE BILL 360 By Cooper / HOUSE BILL 902 By Fitzhugh" (Tennessee
bills are filed in House/Senate pairs; a file may show one or both). Every archived file in scope is
read and its (chamber, bill, first sponsor) headings logged; a heading whose first sponsor is a
reviewed (General Assembly, chamber, sponsor) in replication/data/reference/tn_sponsor_names_1997_2008.csv
gives a row for that chamber's bill number, with the file's text.

  --cdx      The Wayback Machine's capture index for those folders (saved under tn_wayback_cache/cdx/).
  --scan     Reads every archived file in scope; logs (GA, file, capture, headings, filed date) to
             tn_wayback_cache/headings.tsv (resumable); caches pages and extracted texts.
  --texts    Writes tn_state_legislation_sponsored.csv from the log and the reviewed names.

Polite: one request at a time, at least 5 seconds apart, a User-Agent naming the project.

USAGE (from the repo root):
    python3 replication/scripts/state/tn_wayback_bills.py --cdx
    python3 replication/scripts/state/tn_wayback_bills.py --scan
    python3 replication/scripts/state/tn_wayback_bills.py --texts
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
HOST = "www.legislature.state.tn.us"
CACHE = "tn_wayback_cache"
NAMES = "replication/data/reference/tn_sponsor_names_1997_2008.csv"
TEXT_OUT = "tn_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 5
_last = [0.0]
GA_YEARS = {100: 1997, 101: 1999, 102: 2001, 105: 2007}
# currentga captures: the General Assembly in session (from a few days after it convened)
CURRENT_WINDOWS = {102: ("20010115", "20021231"), 105: ("20070115", "20081231")}
CURRENT_PREFIXES = ["HB0", "HB1", "HB2", "HB3", "HB4", "SB0", "SB1", "SB2", "SB3", "SB4", "HJR", "SJR"]
SENATE_ONLY = {105}  # only senators in scope in 2007-2008 (Black, Burchett)
KINDS = {("HOUSE", "BILL"): "HB", ("SENATE", "BILL"): "SB", ("HOUSE", "JOINT RESOLUTION"): "HJR",
         ("SENATE", "JOINT RESOLUTION"): "SJR"}


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


def cached(cache_path, make):
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()
    data = make()
    if data is None:
        return None
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(data)
    return data


def cdx(name, params):
    """Capture-index lines [timestamp, original, ...] (cached; a gateway error page is retried, not kept)."""
    p = os.path.join(CACHE, "cdx", f"{name}.txt")
    if not os.path.exists(p):
        q = urllib.parse.urlencode({**params, "filter": "statuscode:200"})
        for attempt in range(4):
            raw = fetch(f"{WAYBACK}/cdx/search/cdx?{q}")
            if raw is not None and (raw == b"" or re.match(rb"\d{14} ", raw)):
                break
            time.sleep(120)
        else:
            raise SystemExit(f"capture index for {name} keeps failing; run --cdx again later")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(raw)
    with open(p, encoding="utf-8") as f:
        return [line.split(" ") for line in f.read().splitlines() if line.strip()]


def files():
    """[(GA, KIND, number, timestamp, original URL)] for archived bill files in scope."""
    out = {}
    for ga in (100, 101):
        for ts, orig in cdx(f"ga{ga}", {"url": f"{HOST}/bills/{ga}gahtm/{ga}_bill/", "matchType": "prefix",
                                        "fl": "timestamp,original", "collapse": "urlkey"}):
            m = re.search(r"/((?:H|S)J?[BR])(\d+)\.(?:htm|pdf)$", orig, re.I)
            if m and ((ga, m.group(1).upper(), int(m.group(2))) not in out or ts < out[(ga, m.group(1).upper(), int(m.group(2)))][0]):
                out[(ga, m.group(1).upper(), int(m.group(2)))] = (ts, orig)
    for prefix in CURRENT_PREFIXES:
        for ts, orig, _digest in cdx(f"currentga_{prefix}", {"url": f"{HOST}/bills/currentga/bill/{prefix}",
                                                             "matchType": "prefix", "fl": "timestamp,original,digest",
                                                             "collapse": "digest"}):
            m = re.search(r"/((?:H|S)J?[BR])(\d+)\.pdf$", orig, re.I)
            if not m:
                continue
            for ga, (lo, hi) in CURRENT_WINDOWS.items():
                key = (ga, m.group(1).upper(), int(m.group(2)))
                if lo <= ts[:8] <= hi and not (ga in SENATE_ONLY and key[1][0] == "H") and \
                        (key not in out or ts < out[key][0]):
                    out[key] = (ts, orig)
    return sorted((g, k, n, ts, o) for (g, k, n), (ts, o) in out.items())


def plain(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())


def page_text(raw, orig):
    """The bill's text: from the PDF's text layer, or the HTML page from 'Filed for intro' / the first heading."""
    if orig.lower().endswith(".pdf"):
        if not raw.startswith(b"%PDF"):
            return ""
        import pdfplumber
        try:
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            return ""
        # page footers: 'SENATE BILL 330' / '001752' / '-1-'
        text = re.sub(r"(?m)^(?:(?:HOUSE|SENATE) (?:BILL|JOINT RESOLUTION) \d+\s*\n)?\d{6}\s*\n-\s*\d+\s*-\s*$\n?", "", text)
        text = re.sub(r"(?m)^-\s*\d+\s*-\s*$\n?", "", text)
    else:
        text = plain(raw.decode("cp1252", "replace"))
        text = re.sub(r"^Bill Text for \S+\n", "", text)
    m = re.search(r"Filed for intro|(?:HOUSE|SENATE) (?:BILL|JOINT RESOLUTION)", text)
    text = text[m.start():] if m else ""
    return re.sub(r"[ \t]+", " ", text).strip()


def headings(text):
    """[(KIND, number, first sponsor)] from 'SENATE BILL 330 By Rochelle' headings."""
    out = []
    for m in re.finditer(r"(HOUSE|SENATE) (BILL|JOINT RESOLUTION) (\d+)\s*\n?\s*By\s+([^\n]+)", text[:1500]):
        first = re.split(r",| and ", m.group(4))[0].strip()
        out.append((KINDS[(m.group(1), m.group(2))], int(m.group(3)), first))
    return out


def text_path(ga, kind, num):
    return os.path.join(CACHE, "texts", str(ga), f"{kind}{num:04d}.txt")


def scan():
    log = os.path.join(CACHE, "headings.tsv")
    done, seen = set(), set()  # files read; (GA, bill) already named in a read file's headings
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                done.add(tuple(p[:3]))
                seen.update((p[0], h.split("|")[0], h.split("|")[1]) for h in p[5].split(";") if h)
    todo = [f for f in files() if (str(f[0]), f[1], str(f[2])) not in done]
    print(f"{len(todo)} archived files to read", flush=True)
    with open(log, "a", encoding="utf-8") as out:
        for i, (ga, kind, num, ts, orig) in enumerate(todo):
            if (str(ga), kind, str(num)) in seen:
                continue  # its companion's file already printed this bill and its sponsor (same text)
            ext = ".pdf" if orig.lower().endswith(".pdf") else ".htm"
            raw = cached(os.path.join(CACHE, "pages", str(ga), f"{kind}{num:04d}{ext}"),
                         lambda: fetch(f"{WAYBACK}/web/{ts}id_/{orig}"))
            if raw is None:
                continue  # retry on the next run
            text = page_text(raw, orig)
            if text:
                os.makedirs(os.path.dirname(text_path(ga, kind, num)), exist_ok=True)
                with open(text_path(ga, kind, num), "w", encoding="utf-8") as f:
                    f.write(text)
            date = filed_date(text, ga)
            heads = ";".join(f"{k}|{n}|{s}" for k, n, s in headings(text))
            seen.update((str(ga), k, str(n)) for k, n, _ in headings(text))
            out.write(f"{ga}\t{kind}\t{num}\t{ts}\t{date}\t{heads}\n")
            out.flush()
            if i % 500 == 0:
                print(f"  GA{ga} {kind}{num}: {i}/{len(todo)}", flush=True)


def title_of(text):
    t = re.search(r"\b(AN ACT|A RESOLUTION)(.+?)(?:BE IT ENACTED|BE IT RESOLVED|WHEREAS|$)", text[:4000], re.S)  # 'AN ACTto'
    return " ".join((t.group(1) + " " + t.group(2)).split())[:300] if t else ""


def filed_date(text, ga):
    """'Filed for intro on 02/08/99' (or '02/05/2001') -> '1999-02-08'; blank when the printed year does not fit the
    General Assembly (a 1997 file prints '02/06/14')."""
    d = re.search(r"Filed for intro on (\d\d?)/(\d\d?)/(\d{4}|\d\d)\b", text[:300])
    if not d:
        return ""
    y = int(d.group(3))
    y = y if y > 1900 else 1900 + y if y > 50 else 2000 + y
    y0 = GA_YEARS[int(ga)]
    return f"{y}-{int(d.group(1)):02d}-{int(d.group(2)):02d}" if y0 - 1 <= y <= y0 + 1 else ""


def crawl_texts():
    with open(NAMES, newline="", encoding="utf-8") as f:
        reviewed = {(r["ga"], r["chamber"], r["sponsor"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    with open(os.path.join(CACHE, "headings.tsv"), encoding="utf-8") as f:
        log = [line.rstrip("\n").split("\t") for line in f]
    out = {}
    for ga, kind, num, ts, date, heads in log:
        if not heads:
            continue
        for h in heads.split(";"):
            hk, hn, first = h.split("|", 2)
            r = reviewed.get((ga, hk[0], first))
            if not r:
                continue
            bill = f"{hk}{hn}"
            bill_id = f"TN-{ga}-{bill}"
            own = (hk, int(hn)) == (kind, int(num))  # the file of the bill itself, not of its companion
            if bill_id in out and not own:
                continue
            with open(text_path(int(ga), kind, int(num)), encoding="utf-8") as f:
                text = f.read()
            y0 = GA_YEARS[int(ga)]
            out[bill_id] = {"BioguideId": r["bioguide_id"], "Name": r["name"],
                            "Session": f"{ga}th General Assembly ({y0}-{y0 + 1})".replace("101th", "101st").replace("102th", "102nd"),
                            "BillNumber": bill, "BillId": bill_id, "Title": title_of(text), "IntroducedDate": filed_date(text, ga),
                            "House": "HOUSE" if hk[0] == "H" else "SENATE", "AuthorName": first,
                            "IntroducedBy": first, "IntroducedByMatch": "Yes", "TextVersion": "Introduced",
                            "TextPath": text_path(int(ga), kind, int(num)), "ArchivedFile": f"{kind}{num} ({ts})"}
    rows = sorted(out.values(), key=lambda o: o["BillId"])
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
        print(f"{len(fs)} archived bill files in scope:",
              ", ".join(f"GA{g} {sum(1 for f in fs if f[0] == g)}" for g in sorted({f[0] for f in fs})))
    if args.scan:
        scan()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
