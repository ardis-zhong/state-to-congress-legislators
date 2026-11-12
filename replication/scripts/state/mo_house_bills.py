#!/usr/bin/env python3
"""
Missouri House bills, 1996-1999, from the House's former bill-tracking flat files on documents.house.mo.gov
(billtracking/bills<yy>/...), for population members in the Missouri House before the archive.house.mo.gov
years. The House webmaster (webmaster@house.mo.gov, reply of 2026-11-10 to Ardis) allowed a slow, targeted
capture of these files and called them partial and possibly unreliable; documents.house.mo.gov's robots.txt
sets Crawl-delay 20, which this script keeps. (Old links /content.aspx?info=/bills99/... map to
/billtracking/bills99/....)

Per session year:
  member<yy>/MEMDIRD.HTM          member directory (district -> member page mem<NNN>.htm)
  spon<yy>/spn<NNN>.htm           bills listing the member (sponsored and co-sponsored)
  bills<yy>/<HB862>.htm           bill page: 'Sponsor: Akin, W. Todd (86)' and the introduced-text link
  biltxt<yy>/intro<yy>/HB0862I.htm  introduced text (1996-97: biltxt<yy>/HB1633I.HTM): 'INTRODUCED BY REPRESENTATIVES AKIN, ALTER, ...'
A bill counts when the bill page's Sponsor is the member (by district) and the first name in the introduced
text's INTRODUCED BY line is the member's surname.

Reviewed members: replication/data/reference/mo_house_members_1995_1999.csv (year, district, roster_name,
bioguide_id, name, note).

  --members  reads the directories and prints roster entries whose surname is one of ours (for review)
  --lists    reads the reviewed members' sponsor files and bill pages (mo_house_cache/bill_pages.tsv)
  --texts    fetches the introduced texts and writes mo_house_state_legislation_sponsored.csv

2000-2009 (before LegiScan's Missouri coverage, 2010 on) come from archive.house.mo.gov, whose robots.txt
disallows crawling but whose webmaster allowed a slow, targeted capture ("a slow scrape should be fine"); one
request every 120 seconds. MemberGridCluster.aspx gives each session's roster (district), MemberDetails.aspx
the member's 'Sponsored Bills' (sponsor only; co-sponsors are on a separate tab); the introduced texts are flat
files on documents.house.mo.gov (billtracking/bills<yy><n>/biltxt/intro/HB0071I.HTM, n = 1 for the regular
session; 20 seconds). Reviewed members: replication/data/reference/mo_house_members_2000_2009.csv (year, code,
district, roster_name, bioguide_id, name, check_surname, note).

  --archive-members  rosters 2000-2009 (regular sessions), printing our surnames for review
  --archive-lists    the reviewed members' Sponsored Bills (mo_house_cache/archive_bills.tsv)
  --archive-texts    introduced texts; writes mo_house_archive_state_legislation_sponsored.csv

USAGE (from the repo root):  python3 replication/scripts/state/mo_house_bills.py --members | --lists --texts
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://documents.house.mo.gov/billtracking"
CACHE = "mo_house_cache"
NAMES = "replication/data/reference/mo_house_members_1995_1999.csv"
OUT = "mo_house_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 20
YEARS = (1995, 1996, 1997, 1998, 1999)   # 1995: no files (error page)
SURNAMES = ("Burlison", "Akin", "Hartzler", "Luetkemeyer", "Carnahan", "Smith", "Onder", "Graves", "Talent", "McCaskill",
            "McCarthy", "Clay")
_last = [0.0]
ARCHIVE = "https://archive.house.mo.gov"
ARCHIVE_DELAY = 120
NAMES2 = "replication/data/reference/mo_house_members_2000_2009.csv"
OUT2 = "mo_house_archive_state_legislation_sponsored.csv"
ARCHIVE_YEARS = range(2000, 2010)
SESSIONS = {"R": "Regular Session", "S1": "Extraordinary Session", "S2": "2nd Extraordinary Session"}
_alast = [0.0]


def aget(path):
    """Cached GET of archive.house.mo.gov + path, one request per ARCHIVE_DELAY seconds."""
    local = os.path.join(CACHE, "archive", re.sub(r"[^A-Za-z0-9_.-]", "_", path.strip("/")))
    if os.path.exists(local):
        with open(local, encoding="utf-8", errors="replace") as f:
            return f.read()
    for attempt in range(3):
        wait = ARCHIVE_DELAY - (time.time() - _alast[0])
        if wait > 0:
            time.sleep(wait)
        _alast[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(ARCHIVE + path, headers={"User-Agent": UA}), timeout=120) as r:
                data = r.read()
            break
        except Exception:
            time.sleep(300 * (attempt + 1))
    else:
        print(f"  could not fetch {path}", flush=True)
        return None
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "wb") as f:
        f.write(data)
    return data.decode("utf-8", "replace")


def get(path):
    """Cached GET of BASE + path ('' for a missing page)."""
    local = os.path.join(CACHE, "raw", path.strip("/").replace("/", "_"))
    if os.path.exists(local):
        with open(local, "rb") as f:
            return f.read().decode("latin-1")
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = b""
                break
            time.sleep(60 * (attempt + 1))
        except Exception:
            time.sleep(60 * (attempt + 1))
    else:
        print(f"  could not fetch {path}", flush=True)
        return None
    if b"Missouri House of Representatives - Error" in data[:600]:
        data = b""   # the site answers missing files with an error page (e.g. no bills95 folder)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "wb") as f:
        f.write(data)
    return data.decode("latin-1")


def plain(t):
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</h\d>|</pre>", "\n", t)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " "))


def yy(year):
    return f"{year % 100:02d}"


def members():
    for year in YEARS:
        t = get(f"/bills{yy(year)}/member{yy(year)}/MEMDIRD.HTM")
        if not t:
            print(year, "no member directory")
            continue
        for num, name in re.findall(r"mem(\d+)\.htm\"?>\s*([^<]+)", t, re.I):
            if any(re.search(rf"\b{s}\b", name) for s in SURNAMES):
                print(f"{year},{int(num)},{' '.join(name.split())}")


def reviewed():
    with open(NAMES, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["bioguide_id"]]


def lists():
    log = os.path.join(CACHE, "bill_pages.tsv")
    out = []
    for r in reviewed():
        y, d = yy(int(r["year"])), int(r["district"])
        spn = get(f"/bills{y}/spon{y}/spn{d:03d}.htm")
        if not spn:
            print(f"  {r['year']} {r['name']}: no sponsor file")
            continue
        bills = sorted(set(re.findall(rf"/bills{y}/bills{y}/([A-Z]+\d+)\.htm", spn, re.I)),
                       key=lambda b: (re.match(r"[A-Z]+", b.upper()).group(0), int(re.search(r"\d+", b).group(0))))
        kept = 0
        for b in bills:
            page = get(f"/bills{y}/bills{y}/{b}.htm")
            if not page:
                continue
            flat = " ".join(plain(page).split())
            m = re.search(r"Sponsor:\s*(.+?)\s*\((\d+)\)", flat)
            intro = re.search(rf"/bills{y}/(biltxt{y}/(?:intro{y}/)?[A-Z0-9]+I\.htm)", page, re.I)  # 1996-97: no intro<yy>/
            title = re.search(rf"{b}\s+-.*?\s{b}\s+(.+?)\s+Sponsor:", flat) or re.search(rf"{b}\s+(.+?)\s+Sponsor:", flat)
            sponsor_ok = bool(m and int(m.group(2)) == d)
            kept += sponsor_ok
            out.append([r["year"], str(d), r["bioguide_id"], r["name"], b.upper(), m.group(1) if m else "",
                        "Yes" if sponsor_ok else "No", intro.group(1) if intro else "",
                        (title.group(1) if title else "")[:300]])
        print(f"  {r['year']} {r['name']}: {len(bills)} listed, {kept} sponsored", flush=True)
    with open(log, "w", encoding="utf-8") as f:
        for row in out:
            f.write("\t".join(row) + "\n")
    print(f"wrote {log}: {len(out)} bill pages, {sum(1 for o in out if o[6] == 'Yes')} with the member as Sponsor")


def first_introducer(text):
    flat = " ".join(text[:3000].split())
    m = re.search(r"INTRODUCED BY REPRESENTATIVE(?:\s?S)?\s+(.+?)(?:\.|\s+Read\s|$)", flat)
    if not m:
        return None
    first = re.split(r",|\s+AND\s+", m.group(1))[0].strip()
    return re.sub(r"\s*\((?:Sponsor|Co-?sponsors?)\)\s*$", "", first, flags=re.I)


def texts():
    with open(os.path.join(CACHE, "bill_pages.tsv"), encoding="utf-8") as f:
        log = [line.rstrip("\n").split("\t") for line in f]
    with open(NAMES, newline="", encoding="utf-8") as f:
        surname = {(r["year"], r["district"]): r["check_surname"] for r in csv.DictReader(f) if r["bioguide_id"]}
    out = []
    for year, d, bg, name, bill, sponsor, ok, intro, title in log:
        if ok != "Yes":
            continue
        y = yy(int(year))
        text = plain(get(f"/bills{y}/{intro}") or "").strip() if intro else ""
        p = os.path.join(CACHE, "texts", year, f"{bill}.txt")
        if text:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as tf:
                tf.write(text)
        first = first_introducer(text) if text else None
        if not first:
            check = "Unavailable"
        else:
            dist = re.search(r"\((\d+)\)", first)   # same-surname members print their district: 'HARTZLER (124)'
            same = re.sub(r"[^A-Z]", "", re.sub(r"\(.*", "", first).upper()) == surname[(year, d)].upper()
            check = "Yes" if same and (not dist or int(dist.group(1)) == int(d)) else "No"
        date = re.search(r"(?:Read 1\s*st time\s*|Pre-?filed\s+)([A-Za-z]+ \d{1,2},? \d{4})", " ".join(text[:3000].split()), re.I)
        idate = ""
        if date:
            try:
                idate = time.strftime("%Y-%m-%d", time.strptime(date.group(1).replace(",", "").title(), "%B %d %Y"))
            except ValueError:
                pass
        kind = re.match(r"[A-Z]+", bill).group(0)
        out.append({"BioguideId": bg, "Name": name, "Session": f"{year} Regular Session", "BillNumber": bill,
                    "BillId": f"MO-{year}-{bill}", "Title": " ".join(title.split()), "IntroducedDate": idate,
                    "House": "HOUSE", "AuthorName": sponsor, "IntroducedBy": first or "",
                    "IntroducedByMatch": check if text else "", "TextVersion": "Introduced",
                    "TextPath": p if text else "", "BillType": kind})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["BioguideId"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    print(f"Wrote {OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check "
          f"{dict(Counter(o['IntroducedByMatch'] for o in out))}")


def archive_members():
    for year in ARCHIVE_YEARS:
        t = aget(f"/MemberGridCluster.aspx?year={year}&code=R&filter=clear") or ""
        for d, last, first in re.findall(r"district=(\d+)\"[^>]*>([^<]+)</a></td><td[^>]*><a [^>]*>([^<]*)</a>", t):
            if any(re.search(rf"\b{x}\b", last) for x in SURNAMES):
                print(f"{year},R,{int(d)},{first.strip()} {last.strip()}", flush=True)


def archive_lists():
    with open(NAMES2, newline="", encoding="utf-8") as f:
        rev = [r for r in csv.DictReader(f) if r["bioguide_id"]]
    out = []
    for r in rev:
        t = aget(f"/MemberDetails.aspx?year={r['year']}&code={r['code']}&district={int(r['district']):03d}")
        if not t:
            continue
        flat = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<script.*?</script>", "", t))).split())
        name = (re.findall(r"Representative ([A-Z][\w.' -]{2,40}?) District (\d+)", flat) or [None])[-1]
        name = re.match(r"(.*)\|(\d+)$", f"{name[0]}|{name[1]}") if name else None
        sec = flat.split("Sponsored Bills", 1)[1] if "Sponsored Bills" in flat else ""
        sec = re.split(r"Co-Sponsored Bills|Amendments This Menu|Home Bill Search", sec, flags=re.I)[0]
        items = re.findall(r"\b([HS][BJRC]{1,2}R?) (\d+) - \(([0-9A-Z.]+)\) (.+?)(?= [HS][BJRC]{1,2}R? \d+ - \(|$)", sec)
        ok = bool(name and int(name.group(2)) == int(r["district"]) and r["check_surname"] in name.group(1).upper())
        print(f"  {r['year']} {r['code']} {r['name']}: page names {name.group(1) if name else '?'}; {len(items)} sponsored", flush=True)
        for kind, num, lr, title in items:
            out.append([r["year"], r["code"], r["district"], r["bioguide_id"], r["name"], f"{kind}{num}", lr,
                        title.strip()[:300], "Yes" if ok else "No"])
    with open(os.path.join(CACHE, "archive_bills.tsv"), "w", encoding="utf-8") as f:
        for row in out:
            f.write("\t".join(row) + "\n")
    print(f"wrote {len(out)} sponsored items")


WAYBACK = "https://web.archive.org"
_wlast = [0.0]


def wayback_intro(year, bill):
    """2000-2003 introduced texts are gone from both House hosts; the Internet Archive kept copies of the old site
    (www.house.state.mo.us/bills<yy>/biltxt<yy>/intro<yy>/HB0085I.htm). Capture lists are cached per year under
    mo_house_cache/wayback/cdx_<yy>.txt (CDX 'original' column); the capture nearest the session is read."""
    y = f"{year % 100:02d}"
    lst = os.path.join(CACHE, "wayback", f"cdx_{y}.txt")
    if not os.path.exists(lst):
        url = (f"{WAYBACK}/cdx/search/cdx?url=www.house.state.mo.us/bills{y}/*&output=txt&collapse=urlkey"
               f"&filter=statuscode:200&fl=original&limit=50000")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r:
                data = r.read().decode("utf-8", "replace")
        except Exception:
            return None
        if "Temporarily Offline" in data or "<html" in data[:200].lower():
            return None
        os.makedirs(os.path.dirname(lst), exist_ok=True)
        with open(lst, "w", encoding="utf-8") as f:
            f.write(data)
    kind, num = re.match(r"([A-Z]+)(\d+)", bill).groups()
    pat = re.compile(rf"/bills{y}/bil+txt(?:{y})?/intro(?:{y})?/{kind}0*{num}I?\.htm$", re.I)  # 2003: biltxt/intro/
    orig = next((u.strip() for u in open(lst, encoding="utf-8") if pat.search(u.strip())), None)
    if not orig:
        return None
    local = os.path.join(CACHE, "wayback", y, f"{bill}.htm")
    if os.path.exists(local):
        return open(local, "rb").read().decode("cp1252", "replace")
    for attempt in range(4):
        wait = 5 - (time.time() - _wlast[0])
        if wait > 0:
            time.sleep(wait)
        _wlast[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{WAYBACK}/web/{year + 1}id_/{orig}",
                                                               headers={"User-Agent": UA}), timeout=180) as r:
                raw = r.read()
            break
        except Exception:
            time.sleep(60 * (attempt + 1))
    else:
        return None
    if b"Temporarily Offline" in raw[:3000]:
        return None
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "wb") as f:
        f.write(raw)
    return raw.decode("cp1252", "replace")


def archive_texts():
    with open(NAMES2, newline="", encoding="utf-8") as f:
        surname = {(r["year"], r["code"], r["district"]): r["check_surname"] for r in csv.DictReader(f) if r["bioguide_id"]}
    with open(os.path.join(CACHE, "archive_bills.tsv"), encoding="utf-8") as f:
        log = [line.rstrip("\n").split("\t") for line in f]
    out = []
    for year, code, d, bg, name, bill, lr, title, ok in log:
        if ok != "Yes":
            continue
        kind, num = re.match(r"([A-Z]+)(\d+)", bill).groups()
        n = {"R": "1", "S1": "2", "S2": "3"}[code]
        p = os.path.join(CACHE, "texts", f"{year}{code}", f"{bill}.txt")
        text = plain(get(f"/bills{yy(int(year))}{n}/biltxt/intro/{kind}{int(num):04d}I.HTM") or "").strip()
        if not text and os.path.exists(p):
            text = open(p, encoding="utf-8").read()
        if not text and code == "R":
            text = plain(wayback_intro(int(year), bill) or "").strip()
        if re.search(r"\bWITHDRAWN\b", text[:600]) and "AN ACT" not in text:
            text = ""  # a withdrawn bill's placeholder page, not its text (2003 HB 123)
        if text:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as tf:
                tf.write(text)
        first = first_introducer(text) if text else None
        if not first:
            check = "Unavailable"
        else:
            dist = re.search(r"\((\d+)\)", first)
            same = re.sub(r"[^A-Z]", "", re.sub(r"\(.*", "", first).upper()) == surname[(year, code, d)].upper()
            check = "Yes" if same and (not dist or int(dist.group(1)) == int(d)) else "No"
        date = re.search(r"(?:Read 1\s*st time\s*|Pre-?filed\s+)([A-Za-z]+ \d{1,2},? \d{4})", " ".join(text[:3000].split()), re.I)
        idate = ""
        if date:
            try:
                idate = time.strftime("%Y-%m-%d", time.strptime(date.group(1).replace(",", "").title(), "%B %d %Y"))
            except ValueError:
                pass
        out.append({"BioguideId": bg, "Name": name, "Session": f"{year} {SESSIONS[code]}", "BillNumber": bill,
                    "BillId": f"MO-{year}{code}-{bill}", "Title": " ".join(title.split()), "IntroducedDate": idate,
                    "House": "HOUSE", "AuthorName": name, "IntroducedBy": first or "",
                    "IntroducedByMatch": check if text else "", "TextVersion": "Introduced",
                    "TextPath": p if text else "", "BillType": kind, "LRNumber": lr,
                    # 2000-2003 texts exist only as Internet Archive copies of www.house.state.mo.us
                    "TextSource": "Missouri House of Representatives (Internet Archive)" if int(year) <= 2003
                    else "Missouri House of Representatives"})
    with open(OUT2, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["BioguideId"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    print(f"Wrote {OUT2}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check "
          f"{dict(Counter(o['IntroducedByMatch'] for o in out))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--members", action="store_true")
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--archive-members", action="store_true")
    ap.add_argument("--archive-lists", action="store_true")
    ap.add_argument("--archive-texts", action="store_true")
    a = ap.parse_args()
    if a.archive_members:
        archive_members()
    if a.archive_lists:
        archive_lists()
    if a.archive_texts:
        archive_texts()
    if a.members:
        members()
    if a.lists:
        lists()
    if a.texts:
        texts()


if __name__ == "__main__":
    main()
