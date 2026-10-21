#!/usr/bin/env python3
"""
Illinois state bills, 1997-2008, from the Illinois General Assembly's own archives, for
population members who served in the General Assembly before LegiScan's Illinois coverage
(2009 on). Illinois state-text pilot (Ardis, 2026-10-20).

90th-92nd General Assemblies (1997-2002): the legacy "Legisnet" archive on ilga.gov
    (/documents/legislation/legisnet<GA>/). Each member has a sponsor page
    (sponsor/<KEY>.html) listing every bill they sponsored in any role, each with its chief
    sponsor's key; a bill counts when the person is its chief sponsor in its house of origin
    (the archive labels members with their latest title, so the bill's prefix gives the
    chamber, e.g. Peter Roskam's 1997-99 House bills). The introduced text is
    <type>groups/<type>/<GA>0<TYPE><number>.html.
93rd-95th General Assemblies (2003-2008): the member pages on ilga.gov, with the General
    Assembly chosen by its cookie (ILGA.Web.GAId), list the bills on which the member is a
    primary (chief) sponsor (/<Chamber>/Members/Details/<id>?Primary=True), again with the
    chief sponsor's name; the introduced text is the unsuffixed file in the General
    Assembly's file repository (ftp.ilga.gov/legislation/<GA>/<TYPE>/0<GA>00<TYPE><number>.htm),
    which ilga.gov's robots.txt names as the place for automated retrieval.
The lists give the chief sponsor the Legislature records at the end of the session. As for the
other state archives, a bill counts only when the person introduced it: each bill's status
history gives the introduction date, the filer (2003-2008: "Filed with Secretary by Sen. ...";
2005-2008 texts also print "Introduced ..., by Rep. ...") and any change of chief sponsor in the
house of origin (Illinois leaders often file placeholder bills that a member takes over);
bills introduced by someone else get IntroducedByMatch = No and are left out of Table 4. Members' keys and ids are in the reviewed list
replication/data/reference/il_member_keys_1997_2008.csv (--members writes candidates for it).

Polite: ilga.gov's robots.txt asks for Crawl-delay 10, so one request at a time, at least 10
seconds apart, a User-Agent naming the project, and every response cached under
il_ilga_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/il_ilga_bills.py --members   # candidate keys/ids to review
    python3 replication/scripts/state/il_ilga_bills.py --lists     # chief-sponsored bills
    python3 replication/scripts/state/il_ilga_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

WWW = "https://www.ilga.gov"
FTP = "https://ftp.ilga.gov"
CACHE = "il_ilga_cache"
LEGISNET = {90: 1997, 91: 1999, 92: 2001}
NEW_SITE = {93: (3, 2003), 94: (8, 2005), 95: (9, 2007)}  # GA -> (ILGA.Web.GAId, first year)
PEOPLE = "replication/data/population/person_level.csv"
KEYS = "replication/data/reference/il_member_keys_1997_2008.csv"
CANDIDATES = "il_member_key_candidates.csv"
LIST_OUT = "il_chief_sponsor_bills.csv"
TEXT_OUT = "il_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
CRAWL_DELAY = 10
_last = [0.0]


def get(url, cache_path, cookie=""):
    """Fetch url once (cached). Returns the text, or '' for a 404."""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8", errors="replace") as f:
            return f.read()
    headers = {"User-Agent": UA}
    if cookie:
        headers["Cookie"] = cookie
    for attempt in range(5):
        wait = CRAWL_DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
                data = r.read().decode(r.headers.get_content_charset() or "latin-1", errors="replace")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = ""
                break
            time.sleep(30 * (attempt + 1))
        except Exception:
            time.sleep(30 * (attempt + 1))
    else:
        raise SystemExit(f"giving up on {url}")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(data)
    return data


def plain(s):
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def il_people():
    """Population members with Illinois General Assembly service in 1997-2008."""
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Illinois":
                continue
            ys = set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d|present)", r["StateLegYears"]):
                ys |= set(range(int(a), (2026 if z == "present" else int(z)) + 1))
            ys |= {int(y) for y in re.findall(r"(?:19|20)\d\d", r["StateLegYears"])}
            if any(1997 <= y <= 2008 for y in ys):
                out.append(r)
    return out


def legisnet_url(ga, path):
    return f"{WWW}/documents/legislation/legisnet{ga}/{path}"


def find_members():
    """Candidate sponsor keys (1997-2002) and member ids (2003-2008) for our people, to review."""
    people = il_people()
    rows = []
    for ga, y in LEGISNET.items():
        for p in people:
            first, last = p["Name"].replace('"', "").split()[0], p["Name"].split()[-1]
            for key in (last.upper(), f"{last.upper()},{first.upper()}"):
                page = get(legisnet_url(ga, f"sponsor/{key}.html"),
                           os.path.join(CACHE, "legisnet", f"{ga}_sponsor_{key}.html"))
                head = re.search(r"(Senator|Representative)\s+([^<\n]+)", page)
                if head:
                    rows.append({"ga": ga, "bioguide_id": p["BioguideId"], "name": p["Name"], "key": key,
                                 "member_id": "", "chamber": "Senate" if head.group(1) == "Senator" else "House",
                                 "page_name": head.group(2).strip()})
    for ga, (gaid, y) in NEW_SITE.items():
        for chamber in ("House", "Senate"):
            page = get(f"{WWW}/{chamber}/Members/List", os.path.join(CACHE, "members", f"{ga}_{chamber}.html"),
                       cookie=f"ILGA.Web.GAId={gaid}; ILGA.Web.GANum={ga}")
            members = set(re.findall(rf'href="/{chamber}/Members/Details/(\d+)"[^>]*>\s*([^<]+?)\s*<', page))
            for p in people:
                last = p["Name"].split()[-1].lower()
                for mid, name in members:
                    if last in name.lower():
                        rows.append({"ga": ga, "bioguide_id": p["BioguideId"], "name": p["Name"], "key": "",
                                     "member_id": mid, "chamber": chamber, "page_name": name})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates for {len(people)} people; review into {KEYS}")


def chamber_types(chamber):
    return "H" if chamber == "House" else "S"


def crawl_lists():
    with open(KEYS, newline="", encoding="utf-8") as f:
        keys = list(csv.DictReader(f))
    out = []
    for k in keys:
        ga = int(k["ga"])
        prefix = chamber_types(k["chamber"])
        if ga in LEGISNET:
            page = get(legisnet_url(ga, f"sponsor/{k['key']}.html"),
                       os.path.join(CACHE, "legisnet", f"{ga}_sponsor_{k['key']}.html"))
            for m in re.finditer(r'summary/\d+0([A-Z]+)(\d{4})\.html">[^<]*</a>\s*<a href="[^"]*sponsor/([^".]+)\.html">'
                                 r'[^<]*</a>\s*([^\n]*)', page):
                typ, num, chief, rest = m.groups()
                if chief == k["key"]:  # the chief sponsor; Legisnet's title is the member's latest one
                    title = re.split(r"\s{2,}", rest.strip())[0]
                    out.append({"ga": ga, "bioguide_id": k["bioguide_id"], "name": k["name"],
                                "chamber": "House" if typ.startswith("H") else "Senate",
                                "type": typ, "number": int(num), "title": title, "chief_sponsor": chief})
        else:
            gaid = NEW_SITE[ga][0]
            page = get(f"{WWW}/{k['chamber']}/Members/Details/{k['member_id']}?Primary=True",
                       os.path.join(CACHE, "members", f"{ga}_{k['chamber']}_{k['member_id']}_primary.html"),
                       cookie=f"ILGA.Web.GAId={gaid}; ILGA.Web.GANum={ga}")
            page = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", page)
            for row in re.findall(r'(?is)<tr>\s*<th scope="row">.*?</tr>', page):
                cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", "", c)).split())
                         for c in re.findall(r"(?is)<t[hd][^>]*>(.*?)</t[hd]>", row)]
                bill = re.fullmatch(r"([A-Z]+)(\d{4})", cells[0]) if cells else None
                if bill and len(cells) >= 3 and cells[1] == k["page_name"] and bill.group(1).startswith(prefix):
                    out.append({"ga": ga, "bioguide_id": k["bioguide_id"], "name": k["name"], "chamber": k["chamber"],
                                "type": bill.group(1), "number": int(bill.group(2)), "title": cells[2],
                                "chief_sponsor": cells[1]})
        print(f"GA {ga} {k['name']}: {sum(1 for o in out if o['ga'] == ga and o['bioguide_id'] == k['bioguide_id'])} "
              f"chief-sponsored", flush=True)
    seen, unique = set(), []
    for o in out:  # a member listed in both chambers in one General Assembly (Hultgren, 2005-06)
        if (o["bioguide_id"], o["ga"], o["type"], o["number"]) not in seen:
            seen.add((o["bioguide_id"], o["ga"], o["type"], o["number"]))
            unique.append(o)
    out = unique
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} bills")


FILE_CODE = {"HJR": "HJ", "SJR": "SJ", "HJRCA": "HC", "SJRCA": "SC", "JSR": "JS"}  # file names abbreviate these
MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}


def introduced_text(ga, typ, num):
    """The bill as introduced: Legisnet's unsuffixed page (from its '<GA>_<TYPE><number>' line on, past the
    links to later versions), or the repository's unsuffixed file."""
    code = FILE_CODE.get(typ, typ)
    if ga in LEGISNET:
        group = "hb" if typ.startswith("H") and typ != "HR" else "hr" if typ == "HR" else \
                "sb" if typ == "SB" else "sr"
        if typ in ("HJR", "HJRCA"):
            group = "hr"
        page = get(legisnet_url(ga, f"{group}groups/{group[:2]}/{ga}0{code}{num:04d}.html"),
                   os.path.join(CACHE, "texts", f"{ga}_{typ}{num}.html"))
        if not page:  # joint resolutions' files use SJ, SC (constitutional amendments) etc.: follow the summary
            summary = get(legisnet_url(ga, f"summary/{ga}0{typ}{num:04d}.html"),
                          os.path.join(CACHE, "summary", f"{ga}_{typ}{num}.html"))
            link = re.search(r"([a-z]+groups/[a-z]+/\d+0[A-Z]+\d{4})(?:LV)?\.html", summary)
            if link:
                page = get(legisnet_url(ga, link.group(1) + ".html"),
                           os.path.join(CACHE, "texts", f"{ga}_{typ}{num}_via_summary.html"))
        text = plain(page)
        start = re.search(rf"\b{ga}_[A-Z]{{2,5}}{num:04d}\b", text)  # e.g. 90_HB0378 (SJRCA pages print SC)
        return (text[start.start():] if start else text), "Introduced"
    page = get(f"{FTP}/legislation/{ga}/{typ}/0{ga}00{code}{num:04d}.htm",
               os.path.join(CACHE, "texts", f"{ga}_{typ}{num}.htm"))
    return plain(page), "Introduced"


def status(ga, typ, num):
    """(introduced date, filer, sponsor changes in the house of origin) from the bill's status history:
    Legisnet's status page (1997-2002; 'FILED WITH CLERK' names no one, but some bills record
    'CHIEF SPONSOR <KEY>' with the filing; changes read 'PRIMARY SPONSOR CHANGED TO' or
    'CHIEF SPONSOR CHANGED TO') or the
    repository's bill-status XML (2003-2008; 'Filed with Secretary by Sen. ...')."""
    origin, code = typ[0], FILE_CODE.get(typ, typ)
    if ga in LEGISNET:
        page = get(legisnet_url(ga, f"status/{ga}0{typ}{num:04d}.html"),
                   os.path.join(CACHE, "status", f"{ga}_{typ}{num}.html"))
        date, filer, changes = "", "", []
        for line in plain(page).splitlines():
            m = re.match(r"\s*(\d\d-\d\d-\d\d|[A-Z]{3}-\d\d-\d{4})\s+([HS])\s+(.*)", line)
            if not m:
                continue
            d, chamber, action = m.group(1), m.group(2), " ".join(m.group(3).split())
            if not date:  # the first entry: filed (House) or first reading (Senate, which records no filing)
                if re.fullmatch(r"\d\d-\d\d-\d\d", d):
                    y = int(d[:2])
                    date = f"{1900 + y if y > 50 else 2000 + y}-{d[3:5]}-{d[6:8]}"
                else:
                    date = f"{d[7:]}-{MONTHS[d[:3]]:02d}-{d[4:6]}"
            if chamber != origin or "ALTERNATE" in action:
                continue
            first = re.fullmatch(r"CHIEF SPONSOR ([A-Z',.\- ]+)", action)  # recorded with the filing
            if first and not filer and not changes:
                filer = first.group(1)
            elif re.match(r"(?:PRIMARY|CHIEF) SPONSOR CHANGED TO", action):
                changes.append(action)
        return date, filer, changes
    page = get(f"{FTP}/legislation/{ga}/BillStatus/XML/0{ga}00{code}{num:04d}.xml",
               os.path.join(CACHE, "status", f"{ga}_{typ}{num}.xml"))
    acts = re.findall(r"<statusdate>([^<]*)</statusdate><chamber>([^<]*)</chamber><action>([^<]*)</action>",
                      page.split("<actions>", 1)[-1])  # skip the <lastaction> summary
    date, filer, changes = "", "", []
    for d, chamber, action in acts:
        action = " ".join(html.unescape(action).split())
        if not date:
            mo, dy, yr = d.split("/")
            date = f"{yr}-{int(mo):02d}-{int(dy):02d}"
        f = re.match(r"(?:Pre)?[Ff]iled with (?:the )?(?:Clerk|Secretary) by (?:Rep\.|Sen\.|Representative|Senator) (.+)", action)
        if f and not filer:
            filer = f.group(1)
        if chamber[:1] == origin and re.match(r"Chief Sponsor Changed", action):
            changes.append(action)
    return date, filer, changes


def squash(s):
    return re.sub(r"[^a-z]", "", s.lower())


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        ga, typ, num = int(b["ga"]), b["type"], int(b["number"])
        date, filer, changes = status(ga, typ, num)
        text, version = introduced_text(ga, typ, num)
        text_path = ""
        if text and not re.search(rf"[A-Z]{{2,5}}0*{num}\b", text[:800].replace(" ", "")):
            text = ""  # an error or index page, not the bill
        if text:
            text_path = os.path.join(CACHE, "texts", f"{ga}_{typ}{num}.txt")
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text)
        surname = squash(b["name"].split()[-1])
        byline = re.search(r"Introduced\s+[\d/]+,\s+by\s+(?:Rep\.|Sen\.)\s+(.+?)\s*(?:SYNOPSIS|\n\s*\n)", text[:1500], re.S)
        # who introduced it: the filer (2003-2008), the 2005-2008 text's "Introduced ..., by" line, and no
        # change of chief sponsor in the house of origin; Legisnet (1997-2002) records no filer, so there a
        # bill counts when its chief sponsor never changed ("Unchanged"), as for resolutions filed without a name
        named = [n for n in (filer, byline.group(1) if byline else "") if n]
        if named:  # the filer decides, whatever changed later
            match = "Yes" if all(surname in squash(n) for n in named) else "No"
        elif changes:
            match = "No"
        else:
            match = "Unchanged"  # no filer named (1997-2002, and resolutions) and no change of chief sponsor
        y = LEGISNET.get(ga) or NEW_SITE[ga][1]
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(ga % 10 if ga % 100 not in (11, 12, 13) else 0, "th")
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"],
                    "Session": f"{ga}{suffix} General Assembly ({y}-{y + 1})",
                    "BillNumber": f"{typ}{num}", "BillId": f"IL-GA{ga}-{typ}{num}", "Title": b["title"],
                    "IntroducedDate": date, "House": b["chamber"].upper(), "AuthorName": b["chief_sponsor"],
                    "FiledBy": filer or (" ".join(byline.group(1).split()) if byline else ""),
                    "SponsorChanges": " | ".join(changes)[:300], "IntroducedByMatch": match,
                    "TextVersion": version, "TextPath": text_path})
        if i % 100 == 0:
            print(f"  ...{i}/{len(bills)}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}"
                      for k in ("Yes", "Unchanged", "No")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--members", action="store_true")
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N bills (smoke test)")
    args = ap.parse_args()
    if args.members:
        find_members()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
