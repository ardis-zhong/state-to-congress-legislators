#!/usr/bin/env python3
"""
LegiScan sessions with no sponsor roles (most states' 2009-2012 sessions): every sponsor is listed as
"Sponsor", in no reliable order, so Table 4 could keep only bills whose sole listed sponsor is the person.
For states whose legislature's archive can't be used for these sessions, this script reads the sponsor line
printed on the bill's own introduced text (from LegiScan's getBillText) and records who is named first
(Ardis, 2026-11-04: complete the dataset). No model in the loop: one regular expression per state.

Step 1 (--fetch): for every multi-sponsor row of our people in these sessions, fetch the introduced text
    (cached in legiscan_billtext_cache/, as legiscan_fetch_bill_text.py does; bill_text_manifest_roleless.csv)
    and write legiscan_roleless_first_named.csv: the first name printed.
Step 2: the first-named strings are reviewed per person into
    replication/data/reference/legiscan_roleless_names.csv (StateAbbr, BioguideId, FirstNamed, Note), which
    decides who is who ("Moore (B)", "Scott of the 153rd"). build_tables.py keeps a row when its FirstNamed is
    on that list.

USAGE (from the repo root; the key comes from the LEGISCAN_API_KEY environment variable):
    python3 replication/scripts/state/legiscan_roleless_check.py --fetch [--states GA,AZ] [--limit N]
"""

import argparse
import base64
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import legiscan_fetch_bill_text as L  # noqa: E402

STATE_SPONSORED = "state_legislation_sponsored.csv"
MANIFEST = "bill_text_manifest_roleless.csv"
OUT = "legiscan_roleless_first_named.csv"
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
TITLE = r"(?:Representatives?|Senators?)"
BYLINE = {
    "GA": rf"By:\s*{TITLE}\s+(.+?\bof the\s+\d+)",
    "AZ": rf"Introduced by\s+{TITLE}\s+(.+?)(?:,|:|;|\s+AN ACT|\s+A (?:CONCURRENT|JOINT)|\s+A RESOLUTION|$)",
    "IN": rf"(?:Introduced by:\s*([A-Z][^_]*?)\s*_|Effective:.*?\.\s+([A-Z][^.]*?)\s+{MONTH} \d)",
    "NH": r"SPONSORS:\s*(?:Rep\.|Sen\.)\s*(.+?)(?:,|;)",
    "AL": rf"By\s+{TITLE}\s+(.+?)(?:,|\s+and\s|\s+\d+\s+RFD|\s+\d\s)",
    "IA": r"\bBY\s+([A-Z][A-Za-z'\-]+(?:\s+[a-z]\.)?)",
    "MO": r"INTRODUCED BY\s+(?:REPRESENTATIVES?(?: S)?|SENATORS?)\s+(.+?)(?:,|\.|\s+AND\s|\s+\(Sponsor\))",
    "MA": r"PRESENTED BY:\s*(.+?)\s*(?:_{3,}|$)",
    "NV": r"NO\.\s*\d+\s*[–—-]\s*(?:SENATORS?|ASSEMBLY(?:MAN|WOMAN|MEN))\s+(.+?)(?:,|;|\s+AND\s|\s+[A-Z]+ \d{1,2}, \d{4})",
    "LA": r"\bBY\s+(?:REPRESENTATIVES?|SENATORS?)\s+(.+?)(?:,|\s+AND\s|\s+[A-Z/ ,]+:)",
    "UT": r"Chief Sponsor:\s*(.+?)\s+\d",
    "OK": r"By:\s*(.+?)(?:\s+of the\s|,|\s+and\s|\s+AS INTRODUCED)",
    "CO": r"(?:HOUSE|SENATE) SPONSORSHIP\s+(.+?)(?:,|\s+(?:HOUSE|SENATE) SPONSORSHIP)",
}


HI_CDX = "hi_capitol_cache/status_wayback"  # Wayback CDX listings of capitol.hawaii.gov measure_indiv pages


def hi_status_index():
    """(year, type, number) -> (original URL, timestamp) of an archived Hawaii status page (2010-2012).
    capitol.hawaii.gov itself is behind a bot check, so only the Internet Archive's copies are read."""
    import glob
    have = {}
    for path in sorted(glob.glob(os.path.join(HI_CDX, "hi_cdx_*.txt"))):
        for line in open(path, errors="replace"):
            p = line.split()
            m = re.search(r"session(201[012])/lists/measure_indiv\.aspx\?billtype=([A-Z]+)&billnumber=(?:%20)?\s*0*(\d+)", p[0] if p else "", re.I) \
                or re.search(r"measure_indiv\.aspx\?billtype=([A-Z]+)&billnumber=0*(\d+)&year=(201[012])", p[0] if p else "", re.I)
            if not m:
                continue
            g = m.groups()
            year, typ, num = (g[0], g[1], g[2]) if g[0].startswith("20") else (g[2], g[0], g[1])
            have.setdefault((int(year), typ.upper(), int(num)), (p[0], p[1] if len(p) > 1 and p[1].isdigit() else ""))
    return have


def hi_first_introducer(year, bill, index, cache={}):
    """The first name in 'Introducer(s):' on the archived status page, e.g. 'TAKAI' or 'SAY (BR)'."""
    import time
    import urllib.request
    m = re.match(r"([A-Z]+?)0*(\d+)$", bill)
    hit = index.get((year, m.group(1), int(m.group(2)))) if m else None
    if not hit:
        return None
    path = os.path.join(HI_CDX, "pages", f"{year}_{m.group(1)}{int(m.group(2))}.html")
    if not os.path.exists(path):
        url, ts = hit
        wb = f"https://web.archive.org/web/{ts}id_/{url}" if ts else f"https://web.archive.org/web/2013id_/{url}"
        for attempt in range(4):
            time.sleep(3)
            try:
                with urllib.request.urlopen(urllib.request.Request(wb, headers={"User-Agent": "state-to-congress-legislators/1.0 (research dataset)"}), timeout=120) as r:
                    data = r.read()
                break
            except Exception:
                time.sleep(20 * (attempt + 1))
        else:
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    page = open(path, encoding="utf-8", errors="replace").read()
    import html as _html
    t = " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", page)).split())
    intro = re.search(r"Introducer\(s\):\s*(.+?)(?:\s+Current Referral|\s+Companion|\s+Report Title|\s+Measure Title|$)", t)
    return intro.group(1).split(",")[0].strip() if intro else ""


def first_named(state, text):
    flat = " ".join((text or "")[:6000].split())
    m = re.search(BYLINE[state], flat)
    # the first person named (Indiana lists every author after the digest, comma separated; Massachusetts too)
    name = next((g for g in m.groups() if g), "") if m else ""
    return " ".join(name.split(",")[0].split())


def doc_text(doc_id, key):
    """(text, mime, raw path), from the cache or LegiScan."""
    txt = os.path.join(L.CACHE_DIR, f"{doc_id}.txt")
    if os.path.exists(txt):
        with open(txt, encoding="utf-8", errors="replace") as f:
            return f.read(), "", ""
    d = L.call("getBillText", key, id=doc_id).get("text", {})
    raw = base64.b64decode(d.get("doc", "") or "")
    mime = d.get("mime", "")
    path = os.path.join(L.CACHE_DIR, f"{doc_id}.raw.{L.MIME_EXT.get(mime, 'bin')}")
    with open(path, "wb") as f:
        f.write(raw)
    error = None
    if mime == "text/html":
        text = L.strip_html(raw)
    elif mime == "text/plain":
        text = raw.decode("utf-8", errors="replace")
    elif mime == "application/pdf":
        text, error = L.extract_pdf(path)
    elif mime in L.TEXTUTIL_MIMES:
        text, error = L.extract_via_textutil(path, mime)
    else:
        text, error = "", f"no extractor for {mime}"
    if text:
        with open(txt, "w", encoding="utf-8") as f:
            f.write(text)
    if error:
        print(f"  {doc_id}: {error}", flush=True)
    return text or "", mime, path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--states", default=",".join(list(BYLINE) + ["HI"]))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    key = os.environ["LEGISCAN_API_KEY"]
    states = args.states.split(",")
    csv.field_size_limit(10 ** 9)
    with open(STATE_SPONSORED, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["StateAbbr"] in states and r["SessionHasRoles"] == "No"
                and r["NumSponsors"].isdigit() and int(r["NumSponsors"]) > 1 and r["IntroducedDocId"]]
    if args.limit:
        rows = rows[:args.limit]
    print(f"{len(rows)} rows, {len({r['IntroducedDocId'] for r in rows})} documents", flush=True)
    manifest = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, newline="", encoding="utf-8") as f:
            manifest = {m["DocId"]: m for m in csv.DictReader(f)}
    out = []
    hi_index = hi_status_index() if "HI" in states else {}
    for i, r in enumerate(rows, 1):
        doc = r["IntroducedDocId"]
        if r["StateAbbr"] == "HI":  # Hawaii's texts print a blank "INTRODUCED BY:"; the status page names them
            year = int(re.search(r"20\d\d", r["SessionTitle"]).group(0))
            named = hi_first_introducer(year, r["BillNumber"], hi_index)
            surname = re.sub(r"[^A-Z]", "", r["Name"].split()[-1].upper())
            if not named or surname not in re.sub(r"[^A-Z]", "", named.upper()):  # not first: no text needed
                out.append({"StateAbbr": "HI", "BioguideId": r["BioguideId"], "Name": r["Name"], "SessionId": r["SessionId"],
                            "SessionTitle": r["SessionTitle"], "BillNumber": r["BillNumber"], "NumSponsors": r["NumSponsors"],
                            "DocId": doc, "HasText": "", "FirstNamed": named or ""})
                continue
        else:
            named = None
        text, mime, raw = doc_text(doc, key)
        if doc not in manifest and text:
            manifest[doc] = {"DocId": doc, "Mime": mime, "RawPath": raw,
                             "TextPath": os.path.join(L.CACHE_DIR, f"{doc}.txt"), "TextLength": len(text)}
        out.append({"StateAbbr": r["StateAbbr"], "BioguideId": r["BioguideId"], "Name": r["Name"],
                    "SessionId": r["SessionId"], "SessionTitle": r["SessionTitle"], "BillNumber": r["BillNumber"],
                    "NumSponsors": r["NumSponsors"], "DocId": doc, "HasText": "Yes" if text else "No",
                    "FirstNamed": named if named is not None else first_named(r["StateAbbr"], text)})
        if i % 200 == 0:
            print(f"  ...{i}/{len(rows)}", flush=True)
            with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["DocId", "Mime", "RawPath", "TextPath", "TextLength"], lineterminator="\n")
                w.writeheader()
                w.writerows(manifest.values())
    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["DocId", "Mime", "RawPath", "TextPath", "TextLength"], lineterminator="\n")
        w.writeheader()
        w.writerows(manifest.values())
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {OUT}: {len(out)} rows; {sum(1 for o in out if not o['FirstNamed'])} with no sponsor line found")


if __name__ == "__main__":
    main()
