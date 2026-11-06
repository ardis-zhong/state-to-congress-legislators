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
    ap.add_argument("--states", default=",".join(BYLINE))
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
    for i, r in enumerate(rows, 1):
        doc = r["IntroducedDocId"]
        text, mime, raw = doc_text(doc, key)
        if doc not in manifest and text:
            manifest[doc] = {"DocId": doc, "Mime": mime, "RawPath": raw,
                             "TextPath": os.path.join(L.CACHE_DIR, f"{doc}.txt"), "TextLength": len(text)}
        out.append({"StateAbbr": r["StateAbbr"], "BioguideId": r["BioguideId"], "Name": r["Name"],
                    "SessionId": r["SessionId"], "SessionTitle": r["SessionTitle"], "BillNumber": r["BillNumber"],
                    "NumSponsors": r["NumSponsors"], "DocId": doc, "HasText": "Yes" if text else "No",
                    "FirstNamed": first_named(r["StateAbbr"], text)})
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
