#!/usr/bin/env python3
"""
Minnesota state bills, 1995-2008, from the Minnesota Revisor of Statutes' bill status system
(revisor.mn.gov), for population members who served in the Legislature before LegiScan's Minnesota
coverage (2009 on). Minnesota state-text pilot (Ardis, 2026-10-25). Regular sessions of the 79th
(1995-96) to 85th (2007-08) Legislatures; the Revisor's bill status starts with the 1995 session.

  --members  Each session's status search page (/bills/status_search.php?body=<House|Senate>
             &session=<code>) lists the chief authors ("author1", first-named authors) with ids;
             our people's entries are written as candidates for the reviewed list
             replication/data/reference/mn_author_ids_1995_2008.csv.
  --lists    For each reviewed (session, body, id): the bills of the person's own house on which the
             person is chief author (/bills/status_result.php?...&author1[]=<id>&submit_author1=GO).
             Bills only, not resolutions.
  --texts    Each bill's status page (/bills/<leg>/<year>/0/<HF|SF>/<n>) and its introduction text
             (/bills/<leg>/<year>/0/<HF|SF>/<n>/versions/0/). Minnesota's bill texts print no
             authors, so the chief author comes from the Revisor's record; IntroducedByMatch is
             "Unchanged" when the status history has no "Author(s) stricken/changed" action and
             "AuthorsChanged" when it has one (the chief author may then have changed after
             introduction).

Polite: one request at a time, at least 2 seconds apart (robots.txt excludes only /alpha/ and
/beta/), a User-Agent naming the project, every response cached under mn_revisor_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/mn_revisor_bills.py --members
    python3 replication/scripts/state/mn_revisor_bills.py --lists
    python3 replication/scripts/state/mn_revisor_bills.py --texts [--limit N]
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

BASE = "https://www.revisor.mn.gov"
CACHE = "mn_revisor_cache"
SESSIONS = {"0791995": (79, 1995), "0801997": (80, 1997), "0811999": (81, 1999), "0822001": (82, 2001),
            "0832003": (83, 2003), "0842005": (84, 2005), "0852007": (85, 2007)}
PEOPLE = "replication/data/population/person_level.csv"
IDS = "replication/data/reference/mn_author_ids_1995_2008.csv"
CANDIDATES = "mn_author_id_candidates.csv"
LIST_OUT = "mn_chief_author_bills.csv"
TEXT_OUT = "mn_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
_last = [0.0]


def get(path, cache_path):
    """Fetch BASE+path once (cached). Returns the text, or '' for a 404; a page that keeps failing
    is skipped (not cached) so a re-run tries it again."""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8", errors="replace") as f:
            return f.read()
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"User-Agent": UA}), timeout=180) as r:
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
        print(f"  could not fetch {path}", flush=True)
        return ""
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(data)
    return data


def plain(s):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def mn_people():
    out = []
    with open(PEOPLE, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["State"] != "Minnesota" and "Minnesota" not in r["StateLegChamber"]:
                continue
            s, ys = re.sub(r"\bpresent\b", "2026", r["StateLegYears"], flags=re.I), set()
            for a, z in re.findall(r"((?:19|20)\d\d)\s*[-–]\s*(?:[A-Za-z]+\s+)?((?:19|20)\d\d)", s):
                ys |= set(range(int(a), int(z) + 1))
            if any(1995 <= y <= 2008 for y in ys):
                r["years"] = ys
                out.append(r)
    return out


def author_ids(code, body):
    page = get(f"/bills/status_search.php?body={body}&session={code}", os.path.join(CACHE, "search", f"{code}_{body}.html"))
    sel = re.search(r'(?is)<select[^>]*name="author1\[\]"[^>]*>(.*?)</select>', page)
    return re.findall(r'value="(\d+)"[^>]*>([^<(]+)\((\d+)\)', sel.group(1)) if sel else []


def find_members():
    rows = []
    people = mn_people()
    for code, (leg, year) in SESSIONS.items():
        for body in ("House", "Senate"):
            for aid, label, n in author_ids(code, body):
                for p in people:
                    if year in p["years"] or year + 1 in p["years"]:
                        if label.strip().lower() == p["Name"].split()[-1].lower():
                            rows.append({"session": code, "year": year, "body": body, "author_id": aid,
                                         "label": label.strip(), "chief_authored": n, "bioguide_id": p["BioguideId"],
                                         "name": p["Name"], "state_leg_years": p["StateLegYears"]})
    with open(CANDIDATES, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {CANDIDATES}: {len(rows)} candidates; review into {IDS}")


def crawl_lists():
    with open(IDS, newline="", encoding="utf-8") as f:
        ids = list(csv.DictReader(f))
    out = []
    for k in ids:
        q = urllib.parse.urlencode({"body": k["body"], "search": "basic", "session": k["session"], "location": k["body"],
                                    "bill_type": "bill", "author1[]": k["author_id"], "submit_author1": "GO"})
        page = get(f"/bills/status_result.php?{q}", os.path.join(CACHE, "lists", f"{k['session']}_{k['body']}_{k['author_id']}.html"))
        leg, year = SESSIONS[k["session"]]
        bills = []
        for row in re.findall(r"(?is)<tr>(.*?)</tr>", page):
            m = re.search(rf'href="/bills/{leg}/(\d{{4}})/0/(HF|SF)/(\d+)\?', row)
            if not m:
                continue
            cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split()) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)]
            date = next((c for c in cells if re.fullmatch(r"\d\d/\d\d/\d{4}", c)), "")
            key = (m.group(2), int(m.group(3)))
            own = "HF" if k["body"] == "House" else "SF"  # a member's own house; other-house files are companions
            if key[0] == own and key not in [(b["type"], b["number"]) for b in bills]:
                bills.append({"session": k["session"], "leg": leg, "year": m.group(1), "bioguide_id": k["bioguide_id"],
                              "name": k["name"], "body": k["body"], "type": m.group(2), "number": int(m.group(3)),
                              "first_action_date": date, "title": cells[-1][:300] if cells else ""})
        # the search page's count also covers resolutions and other-house companions, so it is not checked here
        out.extend(bills)
        print(f"{year} {k['body']} {k['name']}: {len(bills)} chief-authored bills", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} bills")


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        bills = list(csv.DictReader(f))
    if limit:
        bills = bills[:limit]
    print(f"{len(bills)} bills to fetch", flush=True)
    out = []
    for i, b in enumerate(bills, 1):
        leg, year, typ, num = b["leg"], b["year"], b["type"], b["number"]
        base = f"/bills/{leg}/{year}/0/{typ}/{num}"
        status = plain(get(f"{base}?body={b['body']}", os.path.join(CACHE, "status", f"{leg}_{typ}{num}.html")))
        changed = bool(re.search(r"Authors? (?:stricken|changed)", status))
        txt = os.path.join(CACHE, "texts", f"{leg}_{typ}{num}_v0.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            page = plain(get(f"{base}/versions/0/", os.path.join(CACHE, "texts", f"{leg}_{typ}{num}_v0.html")))
            start = page.find("A bill for an act")
            start = start if start >= 0 else page.find("A resolution")
            text = page[start:] if start >= 0 else ""
            if text:
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        m, d, y = (b["first_action_date"].split("/") + ["", "", ""])[:3]
        iso = f"{y}-{m}-{d}" if y else ""
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{leg}{dict(zip('123', ['st', 'nd', 'rd'])).get(str(leg)[-1], 'th')} Legislature "
                               f"({SESSIONS[b['session']][1]}-{SESSIONS[b['session']][1] + 1})",
                    "BillNumber": f"{typ}{num}", "BillId": f"MN-{leg}-{typ}{num}", "Title": b["title"], "IntroducedDate": iso,
                    "House": b["body"].upper(), "AuthorName": b["name"],
                    "IntroducedByMatch": ("AuthorsChanged" if changed else "Unchanged") if text else "",
                    "TextVersion": "Introduced", "TextPath": txt if text else ""})
        if i % 100 == 0:
            print(f"  ...{i}/{len(bills)}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Unchanged", "AuthorsChanged")))


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
