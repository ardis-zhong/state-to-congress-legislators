#!/usr/bin/env python3
"""
Federal bill text before 1989 for enacted measures: the law as printed in the United States Statutes at Large
(GovInfo collection STATUTE, volumes 83-102 = 91st-100th Congresses, 1969-1988). Congress.gov has digital bill
text only from the 101st Congress (1989), so for 1969-1988 Table 5 had no text at all; the Statutes give the
enacted text of every bill that became law (public and private laws) and of concurrent resolutions, as GPO's
scans with a text layer. Like the state "enacted bills only" sources, these rows are the measure as enacted, not
as introduced (text_source = "Statutes at Large" in Table 5).

  --mods    one MODS metadata file per volume (lists every law with its primary bill: the measure enacted)
  --texts   for every law whose primary bill is a Table 7 bill marked passed, fetch the law's PDF, read its
            text layer with pdfplumber, and write federal_statutes_manifest.csv

Matching is on the primary bill only (Congress, type, number); the companion ("secondary") bill named in the
metadata is not credited.

GovInfo's per-law PDFs are whole printed pages, so each text is cut down to the measure itself (statutes_trim.py:
the law's heading to the next law's heading; a concurrent resolution's block, found by its printed bracket or
caption). Where the measure is not complete in its own granule (GPO's page is one off, or the granule is filed under
the wrong volume), the neighbouring granules' pages are added and the cut is made again; a measure still not found
gets no text (TrimMethod says why). Untrimmed page text stays in federal_statutes_cache/text/, the cut text is in
federal_statutes_cache/trimmed/. The key comes from CONGRESS_API_KEY (api.data.gov), as for the other GovInfo scripts.
Cache: federal_statutes_cache/ (symlink to the T9 drive). Requests at least 4 seconds apart (api.data.gov allows
1,000 an hour).

USAGE (from the repo root):  python3 replication/scripts/federal/fetch_statutes_text.py --mods --texts
"""

import argparse
import csv
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import statutes_trim  # noqa: E402

API = "https://api.govinfo.gov"
CACHE = "federal_statutes_cache"
VOLUMES = range(83, 103)          # 91st Congress (1969) to 100th (1988)
CONGRESSES = range(91, 101)
STATUS = "sponsored_legislation_full_status.csv"   # Table 7's source (classify_status.py)
CBP = "cbp_sponsored_legislation_1969_1972.csv"      # 1969-1972 bills (cbp_bills_1969_1972.py)
OUT = "federal_statutes_manifest.csv"
DELAY = 4.0
NS = {"m": "http://www.loc.gov/mods/v3"}
_last = [0.0]


def key():
    k = os.environ.get("CONGRESS_API_KEY", "")
    if not k:
        sys.exit("Set CONGRESS_API_KEY in the environment")
    return k


def get(url, dest, binary=False):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return open(dest, "rb").read()
    for attempt in range(5):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(f"{url}{'&' if '?' in url else '?'}api_key={key()}",
                                         headers={"User-Agent": "state-to-congress-legislators/1.0 (research dataset)"})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            time.sleep(60 * (attempt + 1) if e.code == 429 else 10 * (attempt + 1))
        except Exception:
            time.sleep(10 * (attempt + 1))
    print(f"  could not fetch {url.split('?')[0]}", flush=True)
    return None


def mods():
    for v in VOLUMES:
        data = get(f"{API}/packages/STATUTE-{v}/mods", os.path.join(CACHE, "mods", f"STATUTE-{v}.xml"))
        print(f"  volume {v}: {len(data or b''):,} bytes", flush=True)


ORDER = {}   # volume -> granule ids in printed order
IDENT = {}   # granule id -> {'Public Law 99-586', ('H', '278')}: what the granule's measure is called in print


def laws():
    """granule id -> (congress, type, number, class, citation, law, title, pdf url) for every law in the volumes."""
    out = {}
    for v in VOLUMES:
        path = os.path.join(CACHE, "mods", f"STATUTE-{v}.xml")
        if not os.path.exists(path):
            continue
        root = ET.parse(path).getroot()
        for item in root.findall("m:relatedItem[@type='constituent']", NS):
            ext = item.find("m:extension", NS)
            if ext is None:
                continue
            cls = (ext.findtext("m:granuleClass", default="", namespaces=NS) or "").strip()
            gid = (ext.findtext("m:accessId", default="", namespaces=NS) or "").strip()
            prim = [b for b in ext.findall("m:bill", NS) if b.get("priority") == "primary"]
            if gid:
                lw = ext.find("m:law", NS)
                ORDER.setdefault(v, []).append(gid)
                IDENT[gid] = ({f"{'Private' if lw.get('isPrivate') == 'true' else 'Public'} Law {lw.get('congress')}-{lw.get('number')}"}
                              if lw is not None else set()) | {(b.get("type").upper()[0], b.get("number")) for b in prim
                                                               if "CONRES" in (b.get("type") or "").upper()}
            if not gid or not prim:
                continue
            b = prim[0]
            law = ext.find("m:law", NS)
            cite = item.findtext("m:identifier[@type='Statute citation']", default="", namespaces=NS)
            title = item.findtext("m:titleInfo/m:title", default="", namespaces=NS)
            out[gid] = (b.get("congress"), b.get("type"), b.get("number"), cls, cite,
                        f"{'Private' if law is not None and law.get('isPrivate') == 'true' else 'Public'} Law "
                        f"{law.get('congress')}-{law.get('number')}" if law is not None else "", title,
                        f"{API}/packages/STATUTE-{v}/granules/{gid}/pdf")
    return out


def pdf_url(gid):
    return f"{API}/packages/{gid.rsplit('-Pg', 1)[0]}/granules/{gid}/pdf"


def pages(gid):
    """The granule's pages as text (cached as JSON), fetching its PDF if needed."""
    import json
    import pdfplumber
    cache = os.path.join(CACHE, "pages", f"{gid}.json")
    if os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    pdf = os.path.join(CACHE, "pdf", f"{gid}.pdf")
    if not get(pdf_url(gid), pdf, binary=True):
        return []
    with pdfplumber.open(pdf) as p:
        out = [(pg.extract_text() or "") for pg in p.pages]
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(out, open(cache, "w", encoding="utf-8"))
    return out


def neighbours(gid):
    """Granule runs whose pages may hold the rest of this measure, nearest first: (granules, 'before' | 'after' |
    'instead'). GPO's first page is sometimes one or two pages late or early, so up to three granules back and two
    ahead are tried, each with every granule in between."""
    v = int(gid.split("-")[1])
    order = ORDER.get(v, [])
    i = order.index(gid) if gid in order else -1
    out = []
    if i >= 0:
        for d in (1, 2, 3):
            if i - d >= 0:
                out.append((order[i - d:i], "before"))
            if d <= 2 and i + d < len(order):
                out.append((order[i + 1:i + d + 1], "after"))
    page = gid.split("-Pg")[1].split("-")[0]
    for w in (v + 1, v - 1):   # filed under the wrong volume (GPO metadata error)
        out += [([g], "instead") for g in ORDER.get(w, []) if g.split("-Pg")[1].split("-")[0] == page]
    return out


def known_near(gid):
    """The measures printed next to this one (they may appear in its text; an OCR near match to them is rejected)."""
    v = int(gid.split("-")[1])
    order = ORDER.get(v, [])
    i = order.index(gid) if gid in order else 0
    return set().union(*[IDENT.get(g, set()) for g in order[max(0, i - 3):i + 4] if g != gid])


def cut(gid, raw, c, typ, num, law, title):
    """(text, method) for the measure, trying the neighbouring granules when its own text does not hold it."""
    kn = known_near(gid)
    text, how = statutes_trim.trim(raw, law, typ, num, title, kn)
    if statutes_trim.ok(how):
        return text, how
    own = pages(gid)
    for run, where in neighbours(gid):
        other = []
        for g in run:
            other += pages(g)
        if not other:
            continue
        if where == "instead":
            merged = other
        else:
            seen = {p.strip() for p in own}
            extra = [p for p in other if p.strip() not in seen]
            merged = extra + own if where == "before" else own + extra
        kn2 = kn | set().union(*[IDENT.get(g, set()) for g in run]) - {law, (typ[0], num)}
        t2, h2 = statutes_trim.trim("\n".join(merged), law, typ, num, title, kn2)
        if statutes_trim.ok(h2):
            return t2, f"{h2} (with {', '.join(run)})"
    return "", how


def texts():
    import pdfplumber
    passed = set()
    with open(STATUS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            # every bill of our people in Congresses 93-100: a law's primary bill was enacted by definition
            if r.get("ItemCategory") == "Bill/Resolution" and r["Congress"].isdigit() and int(r["Congress"]) in CONGRESSES:
                passed.add((r["Congress"], r["Type"].upper(), r["Number"]))
    if os.path.exists(CBP):
        with open(CBP, newline="", encoding="utf-8") as f:
            passed |= {(r["Congress"], r["Type"].upper(), r["Number"]) for r in csv.DictReader(f)}
    allstat = laws()
    print(f"{len(allstat)} laws/resolutions with a primary bill in volumes {VOLUMES.start}-{VOLUMES.stop - 1}; "
          f"{len(passed)} bills of our people in Congresses 93-100", flush=True)
    todo = [(g, v) for g, v in allstat.items() if (v[0], v[1], v[2]) in passed]
    print(f"{len(todo)} to read", flush=True)
    rows = []
    for i, (gid, (c, typ, num, cls, cite, law, title, url)) in enumerate(sorted(todo), 1):
        pdf = os.path.join(CACHE, "pdf", f"{gid}.pdf")
        txt = os.path.join(CACHE, "text", f"{gid}.txt")
        if not os.path.exists(txt):
            data = get(url, pdf, binary=True)
            if not data:
                rows.append([c, typ, num, gid, cite, law, cls, title, "", 0, "PDF not available"])
                continue
            try:
                with pdfplumber.open(pdf) as p:
                    text = "\n".join((pg.extract_text() or "") for pg in p.pages)
            except Exception as e:
                print(f"  {gid}: {e}", flush=True)
                text = ""
            os.makedirs(os.path.dirname(txt), exist_ok=True)
            with open(txt, "w", encoding="utf-8") as f:
                f.write(text)
        raw = open(txt, encoding="utf-8").read()
        text, how = cut(gid, raw, c, typ, num, law, title) if raw.strip() else ("", "no text in PDF")
        # the bill printed in the margin must be the one GPO's metadata names (a caption match is its own evidence)
        other = statutes_trim.printed_bill_differs(text, typ, num) if text and not how.startswith("resolution caption") else None
        if other:
            text, how = "", f"rejected (text prints {other}; GPO metadata names {typ} {num})"
        out = os.path.join(CACHE, "trimmed", f"{gid}.txt")
        if text:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
        rows.append([c, typ, num, gid, cite, law, cls, title, out if text else "", len(text), how])
        if i % 100 == 0:
            print(f"  ...{i}/{len(todo)}", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Congress", "BillType", "BillNumber", "GranuleId", "Citation", "Law", "GranuleClass", "Title",
                    "TextPath", "TextLength", "TrimMethod"])
        w.writerows(rows)
    print(f"Wrote {OUT}: {len(rows)} measures, {sum(1 for r in rows if r[9])} with text", flush=True)
    from collections import Counter
    for k, n in Counter(r[10].split(" (with ")[0] + (" (with neighbour)" if " (with " in r[10] else "") for r in rows).most_common():
        print(f"  {n:5d}  {k}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", action="store_true")
    ap.add_argument("--texts", action="store_true")
    a = ap.parse_args()
    if a.mods:
        mods()
    if a.texts:
        texts()


if __name__ == "__main__":
    main()
