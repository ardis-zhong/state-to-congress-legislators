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

  --scan     Sessions 1999-2009 (70th-75th; the archive's bill information for them is under the closed
             "Reports" paths, but the bill texts are not): every introduced text is read by number
             (/Session/<n>/bills/<type>/<bill>.html for 1999-2003, .pdf for 2005-2009; AB, SB, AJR, SJR, ACR,
             SCR, AR, SR, until 25 numbers in a row are missing). An item is kept when the first sponsor
             in its heading ("Senate Bill No. 10-Senator Cegavske") is a reviewed (session, chamber,
             name) in replication/data/reference/nv_sponsor_names_1999_2009.csv. Output
             nv_scan_state_legislation_sponsored.csv. Regular sessions only.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under nv_leg_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/nv_leg_bills.py --lists
    python3 replication/scripts/state/nv_leg_bills.py --texts
    python3 replication/scripts/state/nv_leg_bills.py --scan
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


SCAN_SESSIONS = {"70th1999": (1999, "htm"), "71st2001": (2001, "htm"), "72nd2003": (2003, "htm"),
                 "73rd2005": (2005, "pdf"), "74th2007": (2007, "pdf"), "75th2009": (2009, "pdf")}
SCAN_TYPES = ["AB", "SB", "AJR", "SJR", "ACR", "SCR", "AR", "SR"]
SCAN_NAMES = "replication/data/reference/nv_sponsor_names_1999_2009.csv"
SCAN_OUT = "nv_scan_state_legislation_sponsored.csv"
HEADING = re.compile(r"(?is)(?:BILL|RESOLUTION)\s+NO\.\s*\d+\s*\S\s*(.+?)\s*(?:\(On Behalf|\(by request|Prefiled|"
                     r"(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d|_{3,}|$)")


def first_sponsor(text):
    """('Titus', 'Senators Titus, Adler and ...') from a text's heading; ('', '') if none."""
    m = HEADING.search(text[:1500])
    if not m:
        return "", ""
    names = " ".join(m.group(1).split())
    lead = re.sub(r"(?i)^(?:Senators?|Assemblym[ae]n|Assemblywom[ae]n|Assembly\s*members?|Speaker|President)\s+", "", names)
    return re.split(r",|;| and ", lead)[0].strip(), names


def intro_date(text):
    m = re.search(r"(?i)(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(\d{1,2}),\s*((?:19|20)\d\d)",
                  text[:2000])
    return time.strftime("%Y-%m-%d", time.strptime(" ".join(m.groups()).title(), "%B %d %Y")) if m else ""


def scan():
    import pdfplumber
    with open(SCAN_NAMES, newline="", encoding="utf-8") as f:
        names = {(r["session"], r["chamber"], r["label"].upper()): r for r in csv.DictReader(f) if r["bioguide_id"]}
    sq = lambda x: re.sub(r"[^A-Z]", "", x.upper())
    out = []
    for sess, (year, ext) in SCAN_SESSIONS.items():
        for typ in SCAN_TYPES:
            missing, num = 0, 0
            while missing < 25:
                num += 1
                bill = f"{typ}{num}"
                head_path = os.path.join(CACHE, "scan_heads", sess, f"{bill}.txt")
                if os.path.exists(head_path):
                    with open(head_path, encoding="utf-8") as f:
                        head = f.read()
                else:
                    url = f"https://archive.leg.state.nv.us/Session/{sess}/bills/{typ}/{bill}.{'html' if ext == 'htm' else 'pdf'}"
                    raw = fetch(url)
                    if raw is None:
                        continue
                    head = ""
                    if ext == "htm" and raw:
                        head = html_text(raw.decode("cp1252", "replace"))
                    elif raw[:4] == b"%PDF":
                        local = os.path.join(CACHE, "scan_pdf", sess, f"{bill}.pdf")
                        os.makedirs(os.path.dirname(local), exist_ok=True)
                        with open(local, "wb") as f:
                            f.write(raw)
                        with pdfplumber.open(local) as pdf:
                            head = "\n".join((pg.extract_text(x_tolerance=1.5) or "") for pg in pdf.pages)
                    os.makedirs(os.path.dirname(head_path), exist_ok=True)
                    with open(head_path, "w", encoding="utf-8") as f:
                        f.write(head)  # the whole text (kept for every item; small next to the PDFs)
                if not head.strip():
                    missing += 1
                    continue
                missing = 0
                first, all_names = first_sponsor(head)
                r = names.get((sess, typ[0], sq(first)))
                if r:
                    title = re.search(r"SUMMARY\W+(.+?)\(BDR", " ".join(head.split()))
                    out.append({"BioguideId": r["bioguide_id"], "Name": r["name"],
                                "Session": f"{year} Regular Session ({sess[:-4]} Session)", "BillNumber": bill,
                                "BillId": f"NV-{sess[:2]}-{bill}", "Title": title.group(1).strip() if title else "",
                                "IntroducedDate": intro_date(head), "House": "SENATE" if typ[0] == "S" else "HOUSE",
                                "AuthorName": first, "IntroducedBy": all_names[:200], "IntroducedByMatch": "Yes",
                                "TextVersion": "Introduced", "TextPath": head_path})
            kept = sum(1 for o in out if o["BillId"].split("-")[1] == sess[:2] and re.sub(r"\d", "", o["BillNumber"]) == typ)
            print(f"{sess} {typ}: up to {num - missing}, {kept} kept", flush=True)
    with open(SCAN_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {SCAN_OUT}: {len(out)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--scan", action="store_true")
    args = ap.parse_args()
    if args.scan:
        scan()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts()


if __name__ == "__main__":
    main()
