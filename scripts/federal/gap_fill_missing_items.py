#!/usr/bin/env python3
"""
Targeted re-fetch for the ~33 people whose full extraction came up short of
their expected total after de-duplication.

WHY THIS IS NEEDED:
The main extraction script (fetch_all_sponsored_legislation.py) paginates
Congress.gov's API sorted by updateDate. For any person needing more than one
page (>250 lifetime items), items that share the same updateDate can be
ordered slightly differently between two separate HTTP requests -- so a small
number of items can appear TWICE across a page boundary while a similar
number of OTHER items get silently pushed past it and never appear at all.
The original script's own self-check (collected count == API's reported
count) does not catch this, because it's a quantity check, not an identity
check: duplicates and skips can offset each other and still add up to the
right total.

This script re-fetches just the affected people, but keeps paging several
pages PAST the naive cutoff and de-duplicates by each item's canonical API
URL as it goes. Since the underlying historical data hasn't changed, items
that got displaced by the reordering are still in the paginated stream
somewhere nearby -- fetching a bit further recovers them.

USAGE:
    python3 gap_fill_missing_items.py
    (reads gapfill_targets.csv, writes gapfill_recovered.csv and
    gapfill_log.csv, in the current directory)
"""

import csv
import json
import sys
import time
import urllib.request
import urllib.error

API_KEY = None  # set from argv[1] at runtime, see main()
BASE_URL = "https://api.congress.gov/v3/member/{bioguide_id}/sponsored-legislation"
PAGE_LIMIT = 250
MAX_RETRIES = 5
EXTRA_SAFETY_PAGES = 4  # pages fetched past the naive ceil(expected/250) cutoff

OUTPUT_FIELDS = [
    "BioguideId", "Name", "State", "Congress", "ItemCategory", "Chamber",
    "Type", "Number", "IntroducedDate", "PolicyArea", "Title",
    "LatestActionDate", "LatestActionText", "Url",
]
LOG_FIELDS = ["BioguideId", "Name", "State", "ExpectedCount", "UniqueRecovered", "StillShort", "PagesFetched"]

HOUSE_TYPES = {"HR", "HRES", "HJRES", "HCONRES"}
SENATE_TYPES = {"S", "SRES", "SJRES", "SCONRES"}


def fetch_page(bioguide_id, offset, delay=0.35):
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
            return data
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(delay * attempt)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {last_err}")


def classify_item(item):
    type_ = item.get("type")
    if type_:
        chamber = "House" if type_ in HOUSE_TYPES else ("Senate" if type_ in SENATE_TYPES else "Unknown")
        return "Bill/Resolution", chamber, type_, item.get("number", "")
    amdt_num = item.get("amendmentNumber")
    if amdt_num:
        return "Amendment", "Unknown", "AMDT", amdt_num
    return "Unknown", "Unknown", "", item.get("number", "") or item.get("amendmentNumber", "")


def row_from_item(bioguide_id, name, state, item):
    policy_area = item.get("policyArea") or {}
    latest_action = item.get("latestAction") or {}
    category, chamber, type_, number = classify_item(item)
    return {
        "BioguideId": bioguide_id, "Name": name, "State": state,
        "Congress": item.get("congress", ""), "ItemCategory": category,
        "Chamber": chamber, "Type": type_, "Number": number,
        "IntroducedDate": item.get("introducedDate", ""),
        "PolicyArea": policy_area.get("name", ""), "Title": item.get("title", ""),
        "LatestActionDate": latest_action.get("actionDate", ""),
        "LatestActionText": latest_action.get("text", ""),
        "Url": item.get("url", ""),
    }


def gap_fill_person(bioguide_id, name, state, expected_count):
    naive_pages = -(-expected_count // PAGE_LIMIT)  # ceil
    max_pages = naive_pages + EXTRA_SAFETY_PAGES
    by_url = {}
    pages_fetched = 0
    for page_num in range(max_pages):
        offset = page_num * PAGE_LIMIT
        data = fetch_page(bioguide_id, offset)
        pages_fetched += 1
        items = data.get("sponsoredLegislation", [])
        if not items:
            break
        for item in items:
            row = row_from_item(bioguide_id, name, state, item)
            by_url[row["Url"]] = row  # de-dupe by canonical URL as we go
        if len(by_url) >= expected_count and page_num + 1 >= naive_pages:
            break
    return list(by_url.values()), pages_fetched


def main():
    global API_KEY
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python3 gap_fill_missing_items.py YOUR_API_KEY")
    API_KEY = sys.argv[1]

    with open("gapfill_targets.csv", newline="", encoding="utf-8") as f:
        targets = list(csv.DictReader(f))

    recovered_fh = open("gapfill_recovered.csv", "w", newline="", encoding="utf-8")
    log_fh = open("gapfill_log.csv", "w", newline="", encoding="utf-8")
    rec_writer = csv.DictWriter(recovered_fh, fieldnames=OUTPUT_FIELDS)
    log_writer = csv.DictWriter(log_fh, fieldnames=LOG_FIELDS)
    rec_writer.writeheader()
    log_writer.writeheader()

    total = len(targets)
    for i, t in enumerate(targets, 1):
        bg, name, state = t["BioguideId"], t["Name"], t["State"]
        expected = int(t["ExpectedCount"])
        print(f"[{i}/{total}] Re-fetching {name}, {state} ({bg})...", end=" ", flush=True)
        try:
            rows, pages = gap_fill_person(bg, name, state, expected)
            for r in rows:
                rec_writer.writerow(r)
            still_short = expected - len(rows)
            log_writer.writerow({
                "BioguideId": bg, "Name": name, "State": state,
                "ExpectedCount": expected, "UniqueRecovered": len(rows),
                "StillShort": still_short, "PagesFetched": pages,
            })
            recovered_fh.flush()
            log_fh.flush()
            print("OK" if still_short <= 0 else f"STILL SHORT by {still_short}")
        except Exception as e:  # noqa: BLE001
            log_writer.writerow({
                "BioguideId": bg, "Name": name, "State": state,
                "ExpectedCount": expected, "UniqueRecovered": 0,
                "StillShort": expected, "PagesFetched": 0,
            })
            log_fh.flush()
            print(f"FAILED: {e}")

    recovered_fh.close()
    log_fh.close()
    print("\nDone. See gapfill_recovered.csv and gapfill_log.csv")


if __name__ == "__main__":
    main()
