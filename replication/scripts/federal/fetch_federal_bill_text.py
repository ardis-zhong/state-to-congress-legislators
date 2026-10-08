#!/usr/bin/env python3
"""
Federal counterpart to legiscan_fetch_bill_text.py: fetch full text for the
Introduced version of every federally sponsored bill in our final federal
dataset (output of scripts/federal/build_final_datasets.py).

WHY "INTRODUCED" SPECIFICALLY:
Same reasoning as the state-bill text fetch -- Congress.gov's own Policy
Area / subject terms (assigned by CRS) are generated from a bill's text as
introduced, not its final/amended form. Fetching the Introduced version
keeps federal and state bill text comparable under the same convention.

HOW TEXT IS RETRIEVED (two-step, and importantly, NOT both metered):
  1. GET https://api.congress.gov/v3/bill/{congress}/{billType}/{billNumber}/text
     -- this IS a metered api.congress.gov call (counts against your
     api.data.gov rate limit). Returns a list of "textVersions" (Introduced,
     Engrossed, Enrolled, etc.), each with one or more `formats` (Formatted
     Text / PDF / Formatted XML) and a document URL.
  2. GET that document URL directly -- these live on www.congress.gov as
     plain static files, NOT behind api.congress.gov, so downloading the
     actual bill text does NOT count against your API rate limit. Only
     step 1 (one call per unique bill) does.

RATE LIMIT: api.data.gov keys default to 1,000 requests/hour, resetting on
a rolling basis (NOT a hard monthly cap like LegiScan) -- much friendlier
for a bulk job like this. This script paces itself at roughly 900
metadata calls/hour to stay safely under that, and backs off automatically
on a 429 (rate limited) response instead of stopping.

INPUT:  a federal dataset CSV with (at minimum) columns identifying each
        bill's Congress number, bill type (e.g. "hr", "s", "hjres"), and
        bill number. Pass the path as the first argument.
OUTPUT: federal_billtext_cache/<congress>-<billtype>-<billnumber>.raw.<ext>
        federal_billtext_cache/<congress>-<billtype>-<billnumber>.txt
        federal_bill_text_manifest.csv

USAGE (from the repo root):
    python3 replication/scripts/federal/fetch_federal_bill_text.py "$CONGRESS_API_KEY" \
        sponsored_legislation_full_status.csv [--min-congress N] [--max-congress N] [--delay SECONDS]
    The manifest is appended after every bill; re-running skips finished bills.
"""

import csv
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

MAX_RETRIES = 5
CACHE_DIR = "federal_billtext_cache"
API_BASE = "https://api.congress.gov/v3"
MIN_SECONDS_BETWEEN_CALLS = 4.0  # ~900 calls/hour, safely under the 1,000/hour cap

# Column-name aliases we'll try, in order, for each field we need.
# The user's final federal dataset schema wasn't confirmed when this script
# was written -- if none of these match, the script prints all actual
# column names it found so we can add the right alias in one pass.
CONGRESS_ALIASES = ["congress", "Congress", "CongressNumber"]
BILLTYPE_ALIASES = ["billtype", "BillType", "bill_type", "type", "Type"]
BILLNUMBER_ALIASES = ["billnumber", "BillNumber", "bill_number", "number", "Number"]
ITEMCATEGORY_ALIASES = ["ItemCategory", "itemcategory", "Category"]

# Real bill/resolution type abbreviations used by api.congress.gov's /bill/
# endpoint. Floor amendments ("amdt") are NOT bills -- they live at a
# completely different endpoint (/amendment/{congress}/{type}/{number}/text)
# and have no Policy Area/CRS label anyway, so they're out of scope here and
# must be filtered out before fetching, not just left to fail one by one.
VALID_BILL_TYPES = {"hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres"}

_pdfplumber = None


def get_pdfplumber():
    global _pdfplumber
    if _pdfplumber is not None:
        return _pdfplumber
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        print("pdfplumber not found -- installing it now (pip install pdfplumber)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pdfplumber"],
                        check=False)
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            print("WARNING: could not install pdfplumber. PDF bills will be saved raw-only.")
            _pdfplumber = False
            return False
    import pdfplumber
    _pdfplumber = pdfplumber
    return pdfplumber


def strip_markup(raw_bytes):
    """Works for both HTML and XML bill text -- strip tags, unescape entities."""
    text = raw_bytes.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_pdf(path):
    pdfplumber = get_pdfplumber()
    if not pdfplumber:
        return None, "pdfplumber unavailable"
    try:
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return "\n\n".join(pages).strip(), None
    except Exception as e:  # noqa: BLE001
        return None, f"pdfplumber error: {e}"


_last_call_time = 0.0


def api_call(path, key, **params):
    """Call an api.congress.gov endpoint (metered). Paces itself and backs
    off on 429 rather than giving up -- the rate limit is hourly/rolling,
    not a hard monthly cap, so waiting it out is the right move."""
    global _last_call_time
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API_BASE}{path}?api_key={key}&format=json" + (f"&{qs}" if qs else "")
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        elapsed = time.time() - _last_call_time
        if elapsed < MIN_SECONDS_BETWEEN_CALLS:
            time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sdsu-research-script/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            _last_call_time = time.time()
            return data
        except urllib.error.HTTPError as e:
            _last_call_time = time.time()
            if e.code == 429:
                wait = 60 * attempt
                print(f"  Rate limited (429) -- waiting {wait}s before retrying...")
                time.sleep(wait)
                last_err = "429 rate limited"
                continue
            last_err = f"HTTP {e.code}: {e.read()[:200]}"
            time.sleep(2 * attempt)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(2 * attempt)
    raise RuntimeError(f"Failed {path} params={params} after {MAX_RETRIES} retries: {last_err}")


def fetch_document(url):
    """Fetch the actual bill text document -- a plain static file on
    www.congress.gov, NOT metered against the API rate limit."""
    req = urllib.request.Request(url, headers={"User-Agent": "sdsu-research-script/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def detect_column(fieldnames, aliases, label):
    for alias in aliases:
        if alias in fieldnames:
            return alias
    print(f"\nERROR: couldn't find a column for '{label}'. Tried: {aliases}")
    print(f"Actual columns in your file: {fieldnames}")
    print("Tell Claude the real column name(s) and this script's alias list will be updated.\n")
    return None


def load_unique_bills(path):
    """Returns {(congress, billtype, billnumber): {"rows": [...]}}.

    Skips amendments (ItemCategory == "Amendment", or any Type that isn't a
    real bill-type abbreviation) -- they need a different API endpoint
    entirely and aren't in scope for this fetch. See VALID_BILL_TYPES above.
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        c_col = detect_column(fieldnames, CONGRESS_ALIASES, "Congress number")
        t_col = detect_column(fieldnames, BILLTYPE_ALIASES, "Bill type (hr/s/hjres/...)")
        n_col = detect_column(fieldnames, BILLNUMBER_ALIASES, "Bill number")
        if not (c_col and t_col and n_col):
            sys.exit(1)
        cat_col = detect_column(fieldnames, ITEMCATEGORY_ALIASES, "ItemCategory") \
            if any(a in fieldnames for a in ITEMCATEGORY_ALIASES) else None

        bills = {}
        skipped_amendments = 0
        for row in reader:
            congress = (row.get(c_col) or "").strip()
            billtype = (row.get(t_col) or "").strip().lower()
            billnumber = (row.get(n_col) or "").strip()
            if not (congress and billtype and billnumber):
                continue
            is_amendment = (cat_col and "amend" in (row.get(cat_col) or "").lower()) \
                or billtype not in VALID_BILL_TYPES
            if is_amendment:
                skipped_amendments += 1
                continue
            key = (congress, billtype, billnumber)
            bills.setdefault(key, []).append(row)
        if skipped_amendments:
            print(f"  Skipped {skipped_amendments} amendment row(s) -- different API endpoint, out of scope.")
        return bills


def pick_introduced_version(text_versions):
    """Prefer a version whose type mentions 'Introduced'; if a bill somehow
    has none listed yet (very new/not yet processed by GPO), fall back to
    the earliest-dated version available."""
    introduced = [v for v in text_versions if "introduced" in (v.get("type") or "").lower()]
    if introduced:
        return introduced[0]
    dated = [v for v in text_versions if v.get("date")]
    if dated:
        return min(dated, key=lambda v: v["date"])
    return text_versions[0] if text_versions else None


def pick_format(formats):
    """Prefer Formatted Text (HTML) -- easiest to extract cleanly -- then
    Formatted XML, then PDF."""
    by_type = {f.get("type"): f for f in formats}
    for pref in ("Formatted Text", "Formatted XML", "PDF"):
        if pref in by_type:
            return pref, by_type[pref]["url"]
    if formats:
        f = formats[0]
        return f.get("type", "unknown"), f["url"]
    return None, None


MANIFEST = "federal_bill_text_manifest.csv"
MANIFEST_FIELDS = ["Congress", "BillType", "BillNumber", "VersionType", "SourceUrl", "Format",
                   "TextPath", "TextLength", "Error"]
# Outcomes that won't change on a retry; anything else (network/API errors) is retried.
FINAL_ERRORS = ("no textVersions available", "no formats available")


def main():
    import argparse
    global MIN_SECONDS_BETWEEN_CALLS
    ap = argparse.ArgumentParser()
    ap.add_argument("api_key")
    ap.add_argument("csv_path", help="federal dataset with Congress/Type/Number columns")
    ap.add_argument("--min-congress", type=int, default=0)
    ap.add_argument("--max-congress", type=int, default=999)
    ap.add_argument("--delay", type=float, default=MIN_SECONDS_BETWEEN_CALLS,
                    help="seconds between metered api.congress.gov calls (default %(default)s)")
    args = ap.parse_args()
    key = args.api_key
    MIN_SECONDS_BETWEEN_CALLS = args.delay

    print(f"Loading unique bills from {args.csv_path}...")
    bills = {k: v for k, v in load_unique_bills(args.csv_path).items()
             if args.min_congress <= int(k[0]) <= args.max_congress}
    os.makedirs(CACHE_DIR, exist_ok=True)

    # The manifest is appended to after every bill, so an interrupted run loses nothing and
    # a re-run skips every bill already settled (text saved, or no text exists).
    done = set()
    if os.path.exists(MANIFEST):
        with open(MANIFEST, newline="", encoding="utf-8") as f:
            for m in csv.DictReader(f):
                if int(m["TextLength"] or 0) > 0 or m["Error"] in FINAL_ERRORS:
                    done.add((m["Congress"], m["BillType"].lower(), m["BillNumber"]))
    todo = sorted(k for k in bills if k not in done)
    print(f"  {len(bills)} unique bill(s) in Congresses {args.min_congress}-{args.max_congress}; "
          f"{len(todo)} still to fetch.")
    print(f"  At one metered call per {MIN_SECONDS_BETWEEN_CALLS:g}s, roughly "
          f"{len(todo) * (MIN_SECONDS_BETWEEN_CALLS + 0.4) / 3600:.1f} hour(s).\n")

    cached = set(os.listdir(CACHE_DIR))  # listed once, not once per bill
    new_file = not os.path.exists(MANIFEST)
    mf = open(MANIFEST, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(mf, fieldnames=MANIFEST_FIELDS)
    if new_file:
        writer.writeheader()

    def record(congress, billtype, billnumber, **kw):
        row = {"Congress": congress, "BillType": billtype, "BillNumber": billnumber, "VersionType": "",
               "SourceUrl": "", "Format": "", "TextPath": "", "TextLength": 0, "Error": ""}
        row.update(kw)
        writer.writerow(row)
        mf.flush()
        return row

    n_ok = n_err = 0
    consecutive_failures = 0
    STOP_AFTER_CONSECUTIVE_FAILURES = 10

    for i, (congress, billtype, billnumber) in enumerate(todo, 1):
        bill_key = f"{congress}-{billtype}-{billnumber}"
        if i % 250 == 0 or i == len(todo):
            print(f"  ...{i}/{len(todo)} bill(s) processed ({n_ok} with text)", flush=True)

        text_path = os.path.join(CACHE_DIR, f"{bill_key}.txt")
        if f"{bill_key}.txt" in cached:
            record(congress, billtype, billnumber, VersionType="(cached)", TextPath=text_path,
                   TextLength=os.path.getsize(text_path))
            n_ok += 1
            continue

        try:
            resp = api_call(f"/bill/{congress}/{billtype}/{billnumber}/text", key)
        except RuntimeError as e:
            consecutive_failures += 1
            n_err += 1
            record(congress, billtype, billnumber, Error=str(e))
            if consecutive_failures >= STOP_AFTER_CONSECUTIVE_FAILURES:
                print(f"\n{consecutive_failures} consecutive failures -- stopping. "
                      f"Re-run the same command later; finished bills are skipped.")
                break
            continue
        consecutive_failures = 0

        version = pick_introduced_version(resp.get("textVersions", []))
        if not version:
            record(congress, billtype, billnumber, Error="no textVersions available")
            continue
        fmt_type, doc_url = pick_format(version.get("formats", []))
        if not doc_url:
            record(congress, billtype, billnumber, VersionType=version.get("type", ""),
                   Error="no formats available")
            continue
        try:
            raw_bytes = fetch_document(doc_url)
        except Exception as e:  # noqa: BLE001
            n_err += 1
            record(congress, billtype, billnumber, VersionType=version.get("type", ""), SourceUrl=doc_url,
                   Format=fmt_type, Error=f"document fetch failed: {e}")
            continue

        ext = {"Formatted Text": "html", "Formatted XML": "xml", "PDF": "pdf"}.get(fmt_type, "bin")
        raw_path = os.path.join(CACHE_DIR, f"{bill_key}.raw.{ext}")
        with open(raw_path, "wb") as f:
            f.write(raw_bytes)
        error = None
        if fmt_type in ("Formatted Text", "Formatted XML"):
            extracted = strip_markup(raw_bytes)
        elif fmt_type == "PDF":
            extracted, error = extract_pdf(raw_path)
        else:
            extracted, error = None, f"no extractor for format {fmt_type!r} -- raw file saved"
        if extracted:
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(extracted)
            n_ok += 1
        record(congress, billtype, billnumber, VersionType=version.get("type", ""), SourceUrl=doc_url,
               Format=fmt_type, TextPath=text_path if extracted else "",
               TextLength=len(extracted) if extracted else 0, Error=error or "")

    mf.close()
    print(f"\n=== Done ===\n  {n_ok} bill(s) with extracted text this run; {n_err} error(s) to retry "
          f"(re-run the same command). See {MANIFEST}.")


if __name__ == "__main__":
    main()
