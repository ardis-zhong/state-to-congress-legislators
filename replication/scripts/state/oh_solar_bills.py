#!/usr/bin/env python3
"""
Ohio state bills, 1997-2008, from the Ohio Legislature's public legislation data service
(SOLAR API, https://search-prod.lis.state.oh.us/api/v2/, used by legislature.ohio.gov; no key),
for population members who served in the General Assembly before LegiScan's Ohio coverage
(2009 on). Ohio state-text pilot (Ardis, 2026-10-20).

  1. Every bill in the 122nd-127th General Assemblies (1997-2008, plus the 125th's special
     session): /api/v2/<general_assembly>/legislation/ (one request each). Each record lists
     the bill's primary sponsors (separately from cosponsors) with a stable member id
     (member_lpid).
  2. Bills whose primary sponsors include one of our people, per the reviewed id list
     replication/data/reference/oh_sponsor_ids_1997_2008.csv (e.g. Joyce Beatty, not her
     husband Otto Beatty; Charlie Wilson, not Jason Wilson). Joint primary sponsors count, as in
     LegiScan's Ohio data.
  3. The introduced version ("As Introduced"): /api/v2/<ga>/legislation/<bill>/ lists the
     versions; its download_html link gives the text, or for older assemblies its PDF
     (download). Many 2005-2008 resolutions are published only "As Adopted"; for those the
     earliest version is used and TextVersion says which.
  4. A check that the sponsor lines above the bill's heading name the person
     (IntroducedByMatch).

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, and
every response cached under oh_solar_cache/.

OUTPUT: oh_state_legislation_sponsored.csv (local).
USAGE (from the repo root):  python3 replication/scripts/state/oh_solar_bills.py [--limit N]
"""

import argparse
import csv
import glob
import html
import json
import os
import re
import time
import urllib.error
import urllib.request

API = "https://search-prod.lis.state.oh.us"
CACHE = "oh_solar_cache"
ASSEMBLIES = ["general_assembly_122", "general_assembly_123", "general_assembly_124", "general_assembly_125",
              "general_assembly_125_special_1", "general_assembly_126", "general_assembly_127"]
IDS = "replication/data/reference/oh_sponsor_ids_1997_2008.csv"
OUT = "oh_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
_last = [0.0]


def get(path, cache_path, binary=False):
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            data = f.read()
        return data if binary else data.decode("utf-8", errors="replace")
    for attempt in range(5):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(API + path, headers={"User-Agent": UA}),
                                        timeout=300) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = b""
                break
            time.sleep(20 * (attempt + 1))
        except Exception:
            time.sleep(20 * (attempt + 1))
    else:
        raise SystemExit(f"giving up on {path}")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(data)
    return data if binary else data.decode("utf-8", errors="replace")


def sponsor_line_match(text, name):
    """Yes when the person's surname is in the text's sponsor block, the lines above the bill or
    resolution itself ("Representatives Mottl, Hood", "Speaker Husted", or a whole-House
    resolution's "REPRESENTATIVESCHAFFER-SPEAKERHUSTED-..." run together in the PDF); No when that
    block names others only; Unavailable when there is no such block; '' without text."""
    if not text:
        return ""
    end = re.search(r"(?i)A\s*B\s*I\s*L\s*L\b|C\s*O\s*N\s*C\s*U\s*R\s*R\s*E\s*N\s*T|J\s*O\s*I\s*N\s*T\s+R\s*E\s*S"
                    r"|\bR\s*E\s*S\s*O\s*L\s*U\s*T\s*I\s*O\s*N\b|\bWHEREAS\b|\bTo\s+(?:amend|enact|honor|urge)", text[:6000])
    block = text[:end.start()] if end else text[:1500]
    if not re.search(r"(?i)representatives?|senators?|speaker|president", block):
        return "Unavailable"
    squash = lambda s: re.sub(r"[^a-z]", "", s.lower())
    return "Yes" if squash(name.split()[-1]) in squash(block) else "No"


def html_text(page):
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", page)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</tr>|</li>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def pdf_text(path):
    import pdfplumber
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages).strip()
    except Exception:
        return ""


def version_label(v):
    """'As Introduced' -> Introduced, 'As Adopted' -> Adopted, 'As Reported by ...' -> Reported, etc."""
    v = v.lower()
    for key, label in (("introduced", "Introduced"), ("adopted", "Adopted"), ("reported", "Reported"),
                       ("enrolled", "Enrolled"), ("passed", "Engrossed")):
        if key in v:
            return label
    return "Introduced" if not v else v.title()


def session_name(ga):
    n = int(re.search(r"_(\d{3})", ga).group(1))
    y = 1997 + 2 * (n - 122)
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10 if n % 100 not in (11, 12, 13) else 0, "th")
    return f"{n}{suffix} General Assembly ({y}-{y + 1})" + (" Special Session" if "special" in ga else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    with open(IDS, newline="", encoding="utf-8") as f:
        ids = {r["member_lpid"]: r for r in csv.DictReader(f)}
    todo = []
    for ga in ASSEMBLIES:
        bills = json.loads(get(f"/api/v2/{ga}/legislation/", os.path.join(CACHE, "lists", f"{ga}.json")))
        for b in bills:
            for s in b.get("sponsors") or []:
                if s.get("member_lpid") in ids:
                    todo.append((ga, b, ids[s["member_lpid"]], len(b.get("sponsors") or [])))
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} bills to fetch", flush=True)
    out = []
    for i, (ga, b, person, n_primary) in enumerate(todo, 1):
        num = b["number"]
        versions = json.loads(get(f"/api/v2/{ga}/legislation/{num}/",
                                  os.path.join(CACHE, "versions", f"{ga}_{num}.json")) or "[]")
        # the version as introduced, or the earliest one published (simple and concurrent resolutions
        # are often published only "As Adopted")
        def seq(v):
            m = re.search(r"/(\d\d)_[A-Z]+/", v.get("download") or v.get("download_html") or "")
            return int(m.group(1)) if m else 99
        intro = next((v for v in versions if v.get("version") == "As Introduced"), None) \
            or min(versions, key=seq, default=None)
        label = version_label((intro or {}).get("version", ""))
        text_path, text = os.path.join(CACHE, "texts", f"{ga}_{num}_IN.txt"), ""
        if os.path.exists(text_path):
            with open(text_path, encoding="utf-8") as f:
                text = f.read()
        date = ""
        if intro and not text and intro.get("download_html"):
            page = get(intro["download_html"], os.path.join(CACHE, "texts", f"{ga}_{num}_IN.html"))
            text = html_text(page) if page else ""
        if intro and not text and intro.get("download"):  # older assemblies publish the PDF only
            pdf_path = os.path.join(CACHE, "texts", f"{ga}_{num}_IN.pdf")
            if get(intro["download"], pdf_path, binary=True):
                text = pdf_text(pdf_path)
        if text:
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            text_path = ""
        ga_n = int(re.search(r"_(\d{3})", ga).group(1))
        code = f"{ga_n}" + ("S1" if "special" in ga else "")
        out.append({"BioguideId": person["bioguide_id"], "Name": person["name"], "Session": session_name(ga),
                    "BillNumber": num.upper(), "BillId": f"OH-GA{code}-{num.upper()}",
                    "Title": " ".join((b.get("short_title") or "").split()), "IntroducedDate": "",
                    "House": (b.get("chamber") or "").upper(), "AuthorName": person["name"],
                    "PrimarySponsors": n_primary, "IntroducedByMatch": sponsor_line_match(text, person["name"]),
                    "TextVersion": label, "TextPath": text_path})
        if i % 100 == 0:
            print(f"  ...{i}/{len(todo)}", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with introduced text")


if __name__ == "__main__":
    main()
