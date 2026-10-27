#!/usr/bin/env python3
"""
Nevada state bills and resolutions, 1997 session, from the Nevada Legislature's session archive
(archive.leg.state.nv.us), for population members who served in the Legislature before LegiScan's
Nevada coverage. Nevada state-text pilot (2026-10-26). robots.txt disallows */Reports/*, where the
archive keeps bill information for every pre-2011 session except 1997 (whose tracking pages are under
/Session/69th1997/tracking/), so only the 1997 session is covered here.

  --lists    The 1997 Senate and Assembly bill lists (tracking/sbResults.html, abResults.html) and
             resolution lists (json/Sres.json, ares.json) give each item's primary sponsor; items listed
             under a reviewed name (replication/data/reference/nv_sponsor_names_1997.csv) are kept.
  --texts    The item's detail page links its versions; "As Introduced" (97bills/SB/SB209.HTM) is
             used. Its heading names the sponsors ("Senate Bill No. 209-Senators Titus, Adler, ...");
             the person must be named first (IntroducedByMatch).

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under nv_leg_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/nv_leg_bills.py --lists
    python3 replication/scripts/state/nv_leg_bills.py --texts
"""

import argparse
import csv
import html
import json
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://archive.leg.state.nv.us/Session/69th1997"
CACHE = "nv_leg_cache"
LISTS = ["tracking/sbResults.html", "tracking/abResults.html"]
RESOLUTION_LISTS = ["json/Sres.json", "json/ares.json"]  # the resolution pages load these
NAMES = "replication/data/reference/nv_sponsor_names_1997.csv"
LIST_OUT = "nv_primary_sponsored_bills.csv"
TEXT_OUT = "nv_state_legislation_sponsored.csv"
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
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
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


def crawl_lists():
    with open(NAMES, newline="", encoding="utf-8") as f:
        names = {(r["chamber"], r["label"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    out = []
    for path in LISTS:
        page = cached(os.path.join(CACHE, "lists", os.path.basename(path)),
                      lambda: fetch(f"{BASE}/{path}")).decode("latin-1")
        for detail, bill, cells, title in re.findall(
                r'(?s)<A HREF="(Detail@[^"]+\.html)">\s*([A-Z]+\d+)\s*</td>(.*?)</tr>\s*<tr>.*?<i>(.*?)</i>', page):
            tds = [plain(c) for c in re.findall(r"(?s)<td[^>]*>(.*?)</td>", cells)]
            sponsor = tds[-1] if tds else ""
            r = names.get((bill[0], sponsor))
            if r:
                out.append({"bioguide_id": r["bioguide_id"], "name": r["name"], "label": sponsor, "bill": bill,
                            "intro": tds[1] if len(tds) > 1 else "", "title": plain(title), "detail": detail})
    for path in RESOLUTION_LISTS:
        data = json.loads(cached(os.path.join(CACHE, "lists", os.path.basename(path)),
                                 lambda: fetch(f"{BASE}/{path}")) or b"{}")
        for items in data.values():
            for x in items:
                r = names.get((x["Document"][0], " ".join(str(x["Sponsor"]).split())))
                if r:
                    out.append({"bioguide_id": r["bioguide_id"], "name": r["name"], "label": r["label"],
                                "bill": x["Document"], "intro": x["IntroDate"], "title": x["Summary"],
                                "detail": f"Detail@dbo_in_intro__introID={x['IntroID']}.html"})
    print(f"{len(out)} items: " + ", ".join(f"{n} {sum(1 for o in out if o['name'] == n)}" for n in sorted({o['name'] for o in out})))
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)


def html_text(raw):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", raw)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</tr>|</div>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    lines = [" ".join(l.split()) for l in s.split("\n")]
    return "\n".join(l for l in lines if l)


def crawl_texts():
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for b in items:
        bill = b["bill"]
        txt = os.path.join(CACHE, "texts", f"1997_{bill}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            page = cached(os.path.join(CACHE, "detail", f"{bill}.html"),
                          lambda: fetch(f"{BASE}/tracking/{b['detail']}")).decode("latin-1")
            m = re.search(r'href="(/Session/69th1997/97bills/[^"]+/[A-Z]+\d+\.HTM)"', page, re.I)
            if m:
                raw = cached(os.path.join(CACHE, "intro", f"{bill}.htm"),
                             lambda: fetch("https://archive.leg.state.nv.us" + m.group(1)))
                text = html_text(raw.decode("cp1252", "replace")) if raw else ""
            if text:
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        m = re.search(r"No\.\s*\d+\s*[-–]\s*(?:Senators?|Assemblym[ae]n|Assemblywom[ae]n|Assembly\s*members?)?\s*([^\n]+)", text)
        names = " ".join(m.group(1).split()) if m else ""
        first = re.split(r",| and ", names)[0].strip() if names else ""
        ok = sq(first) == sq(b["label"])
        match = "" if not text else "Unavailable" if not names else "Yes" if ok else "No"
        d = re.match(r"(\d+)-([A-Za-z]{3})-(\d\d)", b["intro"])
        date = time.strftime("%Y-%m-%d", time.strptime(d.group(0), "%d-%b-%y")) if d else ""
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": "1997 Regular Session (69th Session)",
                    "BillNumber": bill, "BillId": f"NV-69-{bill}", "Title": b["title"], "IntroducedDate": date,
                    "House": "SENATE" if bill.startswith("S") else "HOUSE", "AuthorName": first or b["label"],
                    "IntroducedBy": names[:200], "IntroducedByMatch": match, "TextVersion": "Introduced",
                    "TextPath": txt if text else ""})
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    args = ap.parse_args()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
