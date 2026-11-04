#!/usr/bin/env python3
"""
Oregon bills and resolutions, 1997-2005 regular sessions, from the Internet Archive's copies
(web.archive.org) of the Legislature's former website (www.leg.state.or.us), for population members
who served in the Legislative Assembly before the OData service's coverage (2007 on; see
or_olis_bills.py): Jeff Merkley (House 1999-2006) and Kurt Schrader (House 1997-2002, Senate
2003-2006). Oregon pre-2007 state-text pilot (2026-11-03).

Each session's House and Senate Measure History (<yy>reg/pubs/hsemh.txt|html, senmh.txt|html) lists every
measure with its sponsors: "HB 2013 By Representatives MERKLEY, BECK, RASMUSSEN; Representative X --
Relating to ..." (chief sponsors before the ';', regular sponsors after it). Measures whose first chief
sponsor is a reviewed (session, chamber, name) in replication/data/reference/or_sponsor_names_1997_2005.csv
are kept, and only their introduced texts are read (<yy>reg/measures/hb2000.dir/hb2013.int.html, from
2001 .intro.html). The text's "Sponsored by Representative MERKLEY ..." line must name the person first
(IntroducedByMatch). Special sessions are not read.

  --lists    The latest archived copy of each Measure History; writes or_wayback_measures.csv (kept measures).
  --texts    Each kept measure's introduced text (earliest archived copy); writes
             or_wayback_state_legislation_sponsored.csv.

Polite: one request at a time, at least 5 seconds apart, a User-Agent naming the project; everything is
cached under or_wayback_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/or_wayback_bills.py --lists
    python3 replication/scripts/state/or_wayback_bills.py --texts
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
HOST = "www.leg.state.or.us"
CACHE = "or_wayback_cache"
NAMES = "replication/data/reference/or_sponsor_names_1997_2005.csv"
LIST_OUT = "or_wayback_measures.csv"
TEXT_OUT = "or_wayback_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 5
_last = [0.0]
SESSIONS = {"1997": "97reg", "1999": "99reg", "2001": "01reg", "2003": "03reg", "2005": "05reg"}
HISTORIES = ["hsemh", "hsemh1", "hsemh2", "senmh", "senmh1", "senmh2"]
TYPES = r"HB|SB|HJR|SJR|HCR|SCR|HJM|SJM|HR|SR|HM|SM"


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


def cached(path, make):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    data = make()
    if data is None:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return data


def cdx(name, params):
    """Capture-index lines [timestamp, original] (cached; the archive's 'offline' page is retried, not kept)."""
    p = os.path.join(CACHE, "cdx", f"{name}.txt")
    if not os.path.exists(p):
        q = urllib.parse.urlencode({**params, "filter": "statuscode:200", "fl": "timestamp,original"})
        for attempt in range(4):
            raw = fetch(f"{WAYBACK}/cdx/search/cdx?{q}")
            if raw is not None and (raw == b"" or re.match(rb"\d{14} ", raw)):
                break
            time.sleep(120)
        else:
            raise SystemExit(f"capture index for {name} keeps failing; run again later")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(raw)
    with open(p, encoding="utf-8") as f:
        return [line.split(" ") for line in f.read().splitlines() if line.strip()]


def plain(raw):
    s = raw.decode("latin-1")
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


def entries(text, year):
    """[(measure 'HB 2013', 'By ...' sponsor string, title, first-reading date)] from a Measure History."""
    flat = " ".join(text.split())
    out = []
    for m in re.finditer(rf"\b((?:{TYPES}) \d+) By (.+?) -- (Relating to .+?|.+?)(?= \d{{1,2}}-\d{{1,2}}\s*\((?:H|S)\)|$)", flat):
        d = re.match(r"\s*(\d{1,2})-(\d{1,2})\s*\(", flat[m.end():m.end() + 20])
        date = f"{year}-{int(d.group(1)):02d}-{int(d.group(2)):02d}" if d else ""
        out.append((m.group(1), m.group(2).strip(), m.group(3).strip()[:300], date))
    return out


def first_chief(by):
    """'Representatives MERKLEY, BECK; Representative X' -> 'MERKLEY'; 'COMMITTEE ON ...' -> 'COMMITTEE ON ...'."""
    chief = re.sub(r"\(at the request of[^)]*\)", "", by.split(";")[0])
    chief = re.sub(r"^(?:Representatives?|Senators?)\s+", "", chief.strip())
    return re.split(r",| and ", chief)[0].strip()


def lists():
    out = []
    for year, folder in SESSIONS.items():
        pubs = []
        for host in (HOST, HOST + ":80"):
            pubs += cdx(f"{folder}_pubs_{host.replace(':', '_')}", {"url": f"{host}/{folder}/pubs/", "matchType": "prefix"})
        for h in HISTORIES:
            caps = [(ts, orig) for ts, orig in pubs if re.search(rf"/pubs/{h}\.(?:txt|html)$", orig)]
            if not caps:
                continue
            ts, orig = max(caps)  # the latest copy: the whole session
            raw = cached(os.path.join(CACHE, "histories", f"{folder}_{h}_{ts}.{orig.rsplit('.', 1)[1]}"),
                         lambda: fetch(f"{WAYBACK}/web/{ts}id_/{orig}"))
            if not raw:
                print(f"  no copy of {orig}", flush=True)
                continue
            es = entries(plain(raw), year)
            print(f"{year} {h}: {len(es)} measures ({orig} {ts})", flush=True)
            for measure, by, title, date in es:
                out.append({"Year": year, "Measure": measure, "FirstChief": first_chief(by), "By": by[:300],
                            "Title": title, "FirstReading": date, "History": f"{orig} ({ts})"})
    with open(NAMES, newline="", encoding="utf-8") as f:
        reviewed = {(r["session"], r["chamber"], r["sponsor"]) for r in csv.DictReader(f) if r["bioguide_id"]}
    # every measure is listed once per history; keep the first listing
    seen, kept = set(), []
    for o in out:
        key = (o["Year"], o["Measure"])
        if key in seen:
            continue
        seen.add(key)
        if (o["Year"], o["Measure"][0], o["FirstChief"]) in reviewed:
            kept.append(o)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(kept)
    print(f"Wrote {LIST_OUT}: {len(kept)} measures of {len(seen)} listed")
    with open(os.path.join(CACHE, "all_first_chiefs.tsv"), "w", encoding="utf-8") as f:
        for o in out:
            f.write(f"{o['Year']}\t{o['Measure']}\t{o['FirstChief']}\n")


def text_urls(folder):
    """{('hb', 2013): (timestamp, url)} for each introduced text archived for the session (earliest copy)."""
    found = {}
    for host in (HOST, HOST + ":80"):
        for ts, orig in cdx(f"{folder}_measures_{host.replace(':', '_')}", {"url": f"{host}/{folder}/measures/",
                                                                            "matchType": "prefix"}):
            m = re.search(r"/([a-z]+)(\d+)\.(?:int|intro)\.html$", orig)
            if m:
                key = (m.group(1), int(m.group(2)))
                if key not in found or ts < found[key][0]:
                    found[key] = (ts, orig)
    return found


def crawl_texts():
    with open(NAMES, newline="", encoding="utf-8") as f:
        reviewed = {(r["session"], r["chamber"], r["sponsor"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        kept = list(csv.DictReader(f))
    urls = {}
    out, excluded = [], []
    for o in kept:
        r = reviewed[(o["Year"], o["Measure"][0], o["FirstChief"])]
        folder = SESSIONS[o["Year"]]
        if folder not in urls:
            urls[folder] = text_urls(folder)
        kind, num = o["Measure"].split()
        hit = urls[folder].get((kind.lower(), int(num)))
        text, match = "", ""
        if hit:
            ts, orig = hit
            raw = cached(os.path.join(CACHE, "texts_raw", folder, f"{kind}{num}.html"),
                         lambda: fetch(f"{WAYBACK}/web/{ts}id_/{orig}"))
            if raw:
                text = plain(raw)
                i = re.search(r"\d+(?:st|nd|rd|th) OREGON LEGISLATIVE ASSEMBLY", text)
                text = text[i.start():] if i else text
                text = re.sub(r"[ \t\xa0]+", " ", text)
                text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if text:
            sp = re.search(r"Sponsored\s+by\s+(?:Representatives?|Senators?)?\s*(.+?)(?:\n|\(at the request|$)", text[:3000])
            first = re.split(r",|;| and ", sp.group(1))[0].strip() if sp else ""
            match = "Unavailable" if not first else "Yes" if first.upper() == r["sponsor"].upper() else "No"
            if match == "No":
                excluded.append(f"{o['Year']} {o['Measure']}: {first}")
                continue
            p = os.path.join(CACHE, "texts", folder, f"{kind}{num}.txt")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
        out.append({"BioguideId": r["bioguide_id"], "Name": r["name"], "Session": f"{o['Year']} Regular Session",
                    "BillNumber": f"{kind}{num}", "BillId": f"OR-{o['Year']}R1-{kind}{num}", "Title": o["Title"],
                    "IntroducedDate": o["FirstReading"], "House": "HOUSE" if kind[0] == "H" else "SENATE",
                    "AuthorName": o["FirstChief"], "IntroducedBy": o["By"][:200], "IntroducedByMatch": match,
                    "TextVersion": "Introduced", "TextPath": p if text else "",
                    "ArchivedPage": f"{hit[1]} ({hit[0]})" if hit else ""})
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "Unavailable", ""))
          + f"; {len(excluded)} excluded (text names someone else first): {excluded[:10]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    args = ap.parse_args()
    if args.lists:
        lists()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
