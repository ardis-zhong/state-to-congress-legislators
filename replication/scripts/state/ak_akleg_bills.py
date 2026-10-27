#!/usr/bin/env python3
"""
Alaska state bills and resolutions, 1999-2008, from the Alaska Legislature's BASIS system
(akleg.gov/basis), for population members who served in the Legislature before LegiScan's Alaska
coverage. Alaska state-text pilot (2026-10-26). robots.txt allows /basis/ (it disallows /PDF/, so
texts come from BASIS's plain-text view).

People and the names they served under (reviewed list replication/data/reference/ak_member_codes_1999_2008.csv):
Lisa Murkowski (MUR, 21st-22nd Legislatures) and Mary Peltola, who served as Mary Kapsner (KAP,
21st-24th) and Mary Nelson (NEL, 25th).

  --lists    Each reviewed (Legislature, member code): /basis/Member/Sponsorship/<leg>?code= lists the
             bills and resolutions the member prime-sponsored, with all prime sponsors; items whose
             first-named prime sponsor is the person are kept.
  --texts    The item's version A (the bill as introduced) from /basis/Bill/Plaintext/<leg>?Hsid=
             (e.g. HB0077A), which keeps the printed line numbers. The plain text prints no sponsor, so
             the sponsorship record stands (IntroducedByMatch Unavailable).

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under ak_akleg_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/ak_akleg_bills.py --lists
    python3 replication/scripts/state/ak_akleg_bills.py --texts [--limit N]
"""

import argparse
import csv
import html
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://www.akleg.gov/basis"
CACHE = "ak_akleg_cache"
LEGS = {21: (1999, 2000), 22: (2001, 2002), 23: (2003, 2004), 24: (2005, 2006), 25: (2007, 2008)}
CODES = "replication/data/reference/ak_member_codes_1999_2008.csv"
LIST_OUT = "ak_prime_sponsored_bills.csv"
TEXT_OUT = "ak_state_legislation_sponsored.csv"
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
    with open(CODES, newline="", encoding="utf-8") as f:
        codes = [r for r in csv.DictReader(f) if r["bioguide_id"]]
    sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
    out = []
    for r in codes:
        leg, code = int(r["legislature"]), r["code"]
        page = cached(os.path.join(CACHE, "sponsorship", f"{leg}_{code}.html"),
                      lambda: fetch(f"{BASE}/Member/Sponsorship/{leg}?code={code}")).decode("utf-8", "replace")
        prime = page.split("Prime Sponsorship", 1)[1] if "Prime Sponsorship" in page else ""
        prime = re.split(r"Cosponsorship|Co-Sponsorship|Cosponsor", prime)[0]
        n = listed = 0
        for root, title, sponsors in re.findall(
                r'(?s)<td class="billRoot">.*?Root=([A-Z]+ *\d+)".*?<td class="col02">(.*?)</td>\s*<td class="col03">(.*?)</td>', prime):
            listed += 1
            names = [plain(x) for x in re.split(r"(?i)<br\s*/?>", sponsors) if plain(x)]
            first = re.sub(r"^(?:REPRESENTATIVES?|SENATORS?)\s+", "", names[0]).split(",")[0].strip() if names else ""
            if sq(first) == sq(r["label"]):
                bill = re.sub(r"\s+", "", root)
                out.append({"legislature": leg, "bioguide_id": r["bioguide_id"], "name": r["name"], "label": r["label"],
                            "bill": bill, "title": plain(title), "prime_sponsors": "; ".join(names)})
                n += 1
        print(f"{leg} {code} {r['name']}: {listed} prime-sponsored, {n} first-named", flush=True)
    with open(LIST_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {LIST_OUT}: {len(out)} items")


def hsid(bill):
    """'HB77' -> 'HB0077A' (version A, the bill as introduced)."""
    typ, num = re.match(r"([A-Z]+)(\d+)", bill).groups()
    return f"{typ}{int(num):04d}A" if typ in ("HB", "SB") else f"{typ}{int(num):03d}A"


def crawl_texts(limit=0):
    with open(LIST_OUT, newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    if limit:
        items = items[:limit]
    print(f"{len(items)} items to fetch", flush=True)
    out = []
    for i, b in enumerate(items, 1):
        leg, bill = int(b["legislature"]), b["bill"]
        txt = os.path.join(CACHE, "texts", f"{leg}_{bill}.txt")
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read()
        else:
            raw = cached(os.path.join(CACHE, "plaintext", f"{leg}_{hsid(bill)}.txt"),
                         lambda: fetch(f"{BASE}/Bill/Plaintext/{leg}?Hsid={hsid(bill)}")).decode("utf-8", "replace")
            if re.search(r"(?i)BE IT (?:ENACTED|RESOLVED)|RESOLUTION|BILL NO", raw):
                lines = [l.rstrip() for l in html.unescape(raw).split("\n")]
                text = "\n".join(l for l in lines if l.strip())
            if text:
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
        y0, y1 = LEGS[leg]
        out.append({"BioguideId": b["bioguide_id"], "Name": b["name"], "Session": f"{y0}-{y1} ({leg}th Legislature)",
                    "BillNumber": bill, "BillId": f"AK-{leg}-{bill}", "Title": b["title"], "IntroducedDate": "",
                    "House": "HOUSE" if bill.startswith("H") else "SENATE", "AuthorName": b["label"],
                    "IntroducedBy": b["prime_sponsors"][:200], "IntroducedByMatch": "Unavailable" if text else "",
                    "TextVersion": "Introduced", "TextPath": txt if text else ""})
        if i % 100 == 0:
            print(f"  ...{i}/{len(items)}", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists", action="store_true")
    ap.add_argument("--texts", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="--texts: only the first N items (smoke test)")
    args = ap.parse_args()
    if args.lists:
        crawl_lists()
    if args.texts:
        crawl_texts(args.limit)


if __name__ == "__main__":
    main()
