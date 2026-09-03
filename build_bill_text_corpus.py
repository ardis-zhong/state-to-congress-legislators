#!/usr/bin/env python3
"""
Consolidate the raw federal and state bill-text caches into one file per
legislator (keyed by BioguideId), joining each manifest back to the
sponsorship data that identifies who sponsored each bill.

WHY: the raw caches (federal_billtext_cache/, legiscan_billtext_cache/) hold
one small .txt file per bill -- tens of thousands of files combined, not a
reasonable thing to commit to git. This rolls them up into roughly one file
per legislator (~900, not ~54,000), in newline-delimited JSON (.jsonl) --
one JSON object per bill, tagged Source: "Federal" or "State" -- so the
corpus is organized the way this research actually is: by person, with
their state and federal bills together, not by archive/session.

INPUTS (defaults match this project's established filenames; run from the
folder that has all four of these plus the two raw cache folders):
    --federal-manifest   federal_bill_text_manifest.csv
    --federal-sponsored  sponsored_legislation_final.csv   (BioguideId <-> Congress/Type/Number)
    --state-manifest     bill_text_manifest.csv
    --state-sponsored    state_legislation_sponsored.csv   (BioguideId <-> DocId/BillId)

OUTPUT:
    data/processed/bill_text/{BioguideId}.jsonl -- one JSON object per line, e.g.:
    {"Source": "Federal", "Congress": "116", "BillType": "hr", "BillNumber": "1234",
     "Title": "...", "IntroducedDate": "...", "Url": "...", "TextLength": 1234,
     "Text": "..."}

Run this from the repo root, after both bill-text fetches are complete.
"""

import argparse
import csv
import json
import os
from collections import defaultdict

csv.field_size_limit(10_000_000)


def load_federal_sponsorship(path):
    """(Congress, lowercase Type, Number) -> BioguideId, plus bill metadata."""
    key_to_bioguide = {}
    key_to_meta = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            btype = (r.get("Type") or "").lower()
            if not btype:
                continue
            key = (r["Congress"], btype, r["Number"])
            key_to_bioguide[key] = r["BioguideId"]
            key_to_meta[key] = {
                "Title": r.get("Title", ""),
                "IntroducedDate": r.get("IntroducedDate", ""),
                "PolicyArea": r.get("PolicyArea", ""),
                "Url": r.get("Url", ""),
                "Name": r.get("Name", ""),
            }
    return key_to_bioguide, key_to_meta


def load_state_sponsorship(path):
    """DocId -> list of (BioguideId, bill metadata) -- a doc can be shared by
    more than one tracked legislator (e.g. co-sponsors), AND a single bill
    row's DocIds field can itself list several doc_ids semicolon-separated
    (one per document version across the bill's lifecycle) -- e.g.
    "1002340;1038964;1039094". Every individual doc_id in that list needs to
    map back to this same bill/person, since the bill-text fetch queried
    each one separately."""
    doc_to_people = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            doc_ids_field = r.get("DocIds")
            if not doc_ids_field:
                continue
            entry = {
                "BioguideId": r["BioguideId"],
                "Name": r.get("Name", ""),
                "BillNumber": r.get("BillNumber", ""),
                "Title": r.get("Title", ""),
                "Description": r.get("Description", ""),
                "StateAbbr": r.get("StateAbbr", ""),
                "SessionTitle": r.get("SessionTitle", ""),
                "Status": r.get("Status", ""),
                "StatusDate": r.get("StatusDate", ""),
                "SponsorType": r.get("SponsorType", ""),
                "Url": r.get("Url", ""),
            }
            for doc_id in doc_ids_field.split(";"):
                doc_id = doc_id.strip()
                if doc_id:
                    doc_to_people[doc_id].append(entry)
    return doc_to_people


def read_text(base_dir, text_path):
    if not text_path:
        return None
    full = os.path.join(base_dir, text_path)
    if not os.path.exists(full):
        return None
    with open(full, encoding="utf-8", errors="replace") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--federal-manifest", default="federal_bill_text_manifest.csv")
    ap.add_argument("--federal-sponsored", default="sponsored_legislation_final.csv")
    ap.add_argument("--state-manifest", default="bill_text_manifest.csv")
    ap.add_argument("--state-sponsored", default="state_legislation_sponsored.csv")
    ap.add_argument("--base-dir", default=".",
                     help="directory the manifests' TextPath columns are relative to")
    ap.add_argument("--out-dir", default="data/processed/bill_text")
    ap.add_argument("--dry-run", action="store_true",
                     help="report join/match stats only, don't read text or write files")
    args = ap.parse_args()

    if not args.dry_run:
        os.makedirs(args.out_dir, exist_ok=True)

    print("Loading federal sponsorship join data...")
    fed_key_to_bg, fed_key_to_meta = load_federal_sponsorship(args.federal_sponsored)
    print(f"  {len(fed_key_to_bg)} federal (Congress, Type, Number) keys loaded")

    print("Loading state sponsorship join data...")
    doc_to_people = load_state_sponsorship(args.state_sponsored)
    print(f"  {len(doc_to_people)} state DocIds loaded")

    records_by_bioguide = defaultdict(list)

    # --- federal ---
    fed_matched = 0
    fed_unmatched = 0
    fed_no_text = 0
    with open(args.federal_manifest, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("TextPath"):
                fed_no_text += 1
                continue
            key = (r["Congress"], r["BillType"], r["BillNumber"])
            bg = fed_key_to_bg.get(key)
            if not bg:
                fed_unmatched += 1
                continue
            if args.dry_run:
                fed_matched += 1
                continue
            text = read_text(args.base_dir, r["TextPath"])
            if text is None:
                fed_no_text += 1
                continue
            meta = fed_key_to_meta.get(key, {})
            records_by_bioguide[bg].append({
                "Source": "Federal",
                "Congress": r["Congress"],
                "BillType": r["BillType"],
                "BillNumber": r["BillNumber"],
                "Title": meta.get("Title", ""),
                "IntroducedDate": meta.get("IntroducedDate", ""),
                "PolicyArea": meta.get("PolicyArea", ""),
                "Url": meta.get("Url", ""),
                "TextLength": len(text),
                "Text": text,
            })
            fed_matched += 1

    print(f"Federal: {fed_matched} bill-texts matched to a legislator, "
          f"{fed_unmatched} had text but no sponsorship match, "
          f"{fed_no_text} had no text available")

    # --- state ---
    state_matched = 0
    state_no_text = 0
    state_unmatched = 0
    with open(args.state_manifest, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("TextPath"):
                state_no_text += 1
                continue
            people = doc_to_people.get(r["DocId"], [])
            if not people:
                state_unmatched += 1
                continue
            if args.dry_run:
                state_matched += 1
                continue
            text = read_text(args.base_dir, r["TextPath"])
            if text is None:
                state_no_text += 1
                continue
            for p in people:
                records_by_bioguide[p["BioguideId"]].append({
                    "Source": "State",
                    "StateAbbr": p.get("StateAbbr", ""),
                    "SessionTitle": p.get("SessionTitle", ""),
                    "BillNumber": p.get("BillNumber", ""),
                    "Title": p.get("Title", ""),
                    "Description": p.get("Description", ""),
                    "Status": p.get("Status", ""),
                    "StatusDate": p.get("StatusDate", ""),
                    "SponsorType": p.get("SponsorType", ""),
                    "Url": p.get("Url", ""),
                    "TextLength": len(text),
                    "Text": text,
                })
            state_matched += 1

    print(f"State: {state_matched} bill-texts matched to at least one legislator, "
          f"{state_unmatched} had text but no sponsorship match, "
          f"{state_no_text} had no text available")

    if args.dry_run:
        print("\n(dry run -- no files written)")
        return

    print(f"\nWriting {len(records_by_bioguide)} legislator file(s) to {args.out_dir}/ ...")
    for bg, records in sorted(records_by_bioguide.items()):
        out_path = os.path.join(args.out_dir, f"{bg}.jsonl")
        with open(out_path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    both = sum(
        1 for recs in records_by_bioguide.values()
        if any(r["Source"] == "Federal" for r in recs)
        and any(r["Source"] == "State" for r in recs)
    )
    print(f"Done. {len(records_by_bioguide)} legislator file(s) written; "
          f"{both} of them have both Federal and State records.")


if __name__ == "__main__":
    main()
