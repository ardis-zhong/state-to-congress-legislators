#!/usr/bin/env python3
"""
Full, uncapped extraction of every sponsored bill/resolution/amendment for all
913 legislators in extraction_queue.csv, via the official Congress.gov API.

WHY THIS SCRIPT INSTEAD OF AN LLM TOOL:
Every item is parsed directly from the API's raw JSON with Python's json module.
There is no summarization step and no model "reading" the data anywhere in this
pipeline -- the only way this project's earlier WebFetch-based pilots could
possibly go wrong (a smaller model paraphrasing/collapsing/misreading a page)
does not exist here. Each person's page count is cross-checked against the
API's own reported total (`pagination.count`) before being marked complete, so
partial/incomplete pulls are caught automatically instead of silently shipped.

REQUIREMENTS:
    - Python 3.8+
    - `pip install requests`
    - Run this on a machine with normal internet access (NOT inside a
      network-sandboxed Claude session -- this will not run there; api.congress.gov
      is unreachable from that environment by design).
    - extraction_queue.csv in the same directory (913 rows: Name, State,
      Chambers, BioguideId, MaxCongress, TotalSponsoredItems).

USAGE:
    python fetch_all_sponsored_legislation.py                 # full run, all 913 people
    python fetch_all_sponsored_legislation.py --limit-people 5  # smoke-test on 5 people first
    python fetch_all_sponsored_legislation.py --resume          # skip people already in the output file

OUTPUT:
    sponsored_legislation_full.csv -- one row per sponsored item (bill,
    resolution, OR amendment -- nothing is dropped). Columns:
        BioguideId, Name, State, Congress, ItemCategory, Chamber, Type, Number,
        IntroducedDate, PolicyArea, Title, LatestActionDate, LatestActionText, Url

    fetch_log.csv -- one row per person: items collected, API-reported count,
    whether they matched, and how many pages/retries it took. Read this after
    the run -- ItemsMatch=False rows are the ones that need a manual look.

RUNTIME:
    ~208,462 total items across 913 people at limit=250/page is roughly 900-1,000
    API calls. With the default 0.35s delay between calls that's on the order of
    6-7 minutes of pure request time, plus whatever retries occur. Congress.gov's
    posted rate limit is generous (several thousand requests/hour per key), so
    this conservative pacing should not come close to it, but --delay is exposed
    below in case you want to slow it down further.
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error

API_KEY = None  # set from --api-key at runtime, see main()
BASE_URL = "https://api.congress.gov/v3/member/{bioguide_id}/sponsored-legislation"
PAGE_LIMIT = 250
MAX_RETRIES = 5

OUTPUT_FIELDS = [
    "BioguideId", "Name", "State", "Congress", "ItemCategory", "Chamber",
    "Type", "Number", "IntroducedDate", "PolicyArea", "Title",
    "LatestActionDate", "LatestActionText", "Url",
]
LOG_FIELDS = [
    "BioguideId", "Name", "State", "ExpectedCount", "CollectedCount",
    "ItemsMatch", "Pages", "Retries", "Error",
]

HOUSE_TYPES = {"HR", "HRES", "HJRES", "HCONRES"}
SENATE_TYPES = {"S", "SRES", "SJRES", "SCONRES"}


def fetch_page(bioguide_id, offset, delay):
    url = (
        BASE_URL.format(bioguide_id=bioguide_id)
        + f"?api_key={API_KEY}&format=json&limit={PAGE_LIMIT}&offset={offset}"
        + "&sort=updateDate+desc"
    )
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sdsu-research-script/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(delay)
            return data, attempt - 1  # retries used
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code == 429:
                time.sleep(delay * (2 ** attempt) + 1)  # back off harder on rate limiting
            else:
                time.sleep(delay * attempt)
        except Exception as e:  # noqa: BLE001 - genuinely want to retry on anything transient
            last_err = str(e)
            time.sleep(delay * attempt)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {last_err}")


def classify_item(item):
    """Return (category, chamber, type_, number) for a raw sponsoredLegislation item.

    Real bills/resolutions carry a "type" + "number" field and (usually) a
    policyArea. Floor amendments carry "amendmentNumber" instead and
    structurally have no title/policyArea in the API -- that's not missing
    data, it's the schema, and this script preserves that distinction rather
    than guessing.
    """
    type_ = item.get("type")
    if type_:
        chamber = "House" if type_ in HOUSE_TYPES else ("Senate" if type_ in SENATE_TYPES else "Unknown")
        return "Bill/Resolution", chamber, type_, item.get("number", "")
    amdt_num = item.get("amendmentNumber")
    if amdt_num:
        return "Amendment", "Unknown", "AMDT", amdt_num
    return "Unknown", "Unknown", "", item.get("number", "") or item.get("amendmentNumber", "")


def extract_person(bioguide_id, name, state, delay, log_rows_seen_error_bioguides):
    offset = 0
    collected = []
    pages = 0
    retries_total = 0
    expected_count = None
    while True:
        data, retries = fetch_page(bioguide_id, offset, delay)
        retries_total += retries
        pages += 1
        pagination = data.get("pagination", {})
        if expected_count is None:
            expected_count = pagination.get("count", 0)
        items = data.get("sponsoredLegislation", [])
        if not items:
            break
        for item in items:
            policy_area = item.get("policyArea") or {}
            latest_action = item.get("latestAction") or {}
            category, chamber, type_, number = classify_item(item)
            collected.append({
                "BioguideId": bioguide_id,
                "Name": name,
                "State": state,
                "Congress": item.get("congress", ""),
                "ItemCategory": category,
                "Chamber": chamber,
                "Type": type_,
                "Number": number,
                "IntroducedDate": item.get("introducedDate", ""),
                "PolicyArea": policy_area.get("name", ""),
                "Title": item.get("title", ""),
                "LatestActionDate": latest_action.get("actionDate", ""),
                "LatestActionText": latest_action.get("text", ""),
                "Url": item.get("url", ""),
            })
        offset += PAGE_LIMIT
        if offset >= expected_count:
            break
    return collected, expected_count, pages, retries_total


def load_queue(path, limit_people):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if limit_people:
        rows = rows[:limit_people]
    return rows


def already_done(output_path):
    if not os.path.exists(output_path):
        return set()
    with open(output_path, newline="", encoding="utf-8") as fh:
        return {r["BioguideId"] for r in csv.DictReader(fh)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="replication/data/targets/extraction_queue.csv")
    ap.add_argument("--output", default="sponsored_legislation_full.csv")
    ap.add_argument("--log", default="fetch_log.csv")
    ap.add_argument("--delay", type=float, default=0.35, help="seconds between API calls")
    ap.add_argument("--limit-people", type=int, default=0, help="0 = all people; use e.g. 5 for a smoke test")
    ap.add_argument("--resume", action="store_true", help="skip people already present in --output")
    ap.add_argument("--api-key", required=True, help="Congress.gov API key")
    args = ap.parse_args()

    global API_KEY
    API_KEY = args.api_key

    people = load_queue(args.queue, args.limit_people)
    done_ids = already_done(args.output) if args.resume else set()

    out_mode = "a" if (args.resume and done_ids) else "w"
    log_mode = "a" if (args.resume and done_ids) else "w"

    out_fh = open(args.output, out_mode, newline="", encoding="utf-8")
    log_fh = open(args.log, log_mode, newline="", encoding="utf-8")
    out_writer = csv.DictWriter(out_fh, fieldnames=OUTPUT_FIELDS)
    log_writer = csv.DictWriter(log_fh, fieldnames=LOG_FIELDS)
    if out_mode == "w":
        out_writer.writeheader()
    if log_mode == "w":
        log_writer.writeheader()

    total = len(people)
    mismatches = []
    for i, p in enumerate(people, 1):
        bioguide_id = p["BioguideId"]
        name, state = p["Name"], p["State"]
        if bioguide_id in done_ids:
            print(f"[{i}/{total}] SKIP (already done): {name} ({bioguide_id})")
            continue
        print(f"[{i}/{total}] Fetching {name}, {state} ({bioguide_id})...", end=" ", flush=True)
        try:
            items, expected, pages, retries = extract_person(bioguide_id, name, state, args.delay, mismatches)
            match = (len(items) == expected)
            for row in items:
                out_writer.writerow(row)
            log_writer.writerow({
                "BioguideId": bioguide_id, "Name": name, "State": state,
                "ExpectedCount": expected, "CollectedCount": len(items),
                "ItemsMatch": match, "Pages": pages, "Retries": retries, "Error": "",
            })
            out_fh.flush()
            log_fh.flush()
            status = "OK" if match else f"MISMATCH (expected {expected}, got {len(items)})"
            print(status)
            if not match:
                mismatches.append(bioguide_id)
        except Exception as e:  # noqa: BLE001
            log_writer.writerow({
                "BioguideId": bioguide_id, "Name": name, "State": state,
                "ExpectedCount": "", "CollectedCount": 0,
                "ItemsMatch": False, "Pages": 0, "Retries": 0, "Error": str(e),
            })
            log_fh.flush()
            print(f"FAILED: {e}")
            mismatches.append(bioguide_id)

    out_fh.close()
    log_fh.close()

    print()
    print(f"Done. {total} people processed. {len(mismatches)} had a mismatch or error.")
    if mismatches:
        print("Re-run with --resume after removing those BioguideIds' rows from the log/output")
        print("to retry just the failed ones, or inspect fetch_log.csv for details.")


if __name__ == "__main__":
    main()
