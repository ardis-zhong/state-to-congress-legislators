#!/usr/bin/env python3
"""
Phase C of the state-bill extraction: fetch full text for the Introduced
version of every bill in state_legislation_sponsored.csv.

WHY "INTRODUCED" SPECIFICALLY:
Congress.gov's Policy Area / subject terms (assigned by CRS) are generated
from a bill's text as introduced, not its final/amended form. To keep
state and federal bill text comparable under the same convention, this
phase fetches only the Introduced-version doc_id that Phase B
(legiscan_fetch_state_bills.py) already identified per bill -- not every
text version on file.

HOW TEXT IS RETRIEVED:
Unlike the bulk getDataset ZIPs (metadata only, confirmed via probe),
LegiScan's getBillText(id=doc_id) op returns the actual document content,
base64-encoded, in whatever format the state originally filed it in --
usually text/html or application/pdf, occasionally application/msword or
plain text. This script:
  1. Fetches (or reuses a cached copy of) each unique Introduced doc_id.
  2. Saves the raw decoded file (.html/.pdf/.doc/...) so nothing is lost.
  3. Extracts plain text out of it: HTML is stripped with the stdlib
     parser; PDF is extracted with pdfplumber if it's installed (auto-
     installed on first run if missing); other formats are left raw-only
     and flagged in the manifest for manual handling.

SAFETY: getBillText is called once per UNIQUE doc_id (many bills in
state_legislation_sponsored.csv share a doc_id when a bill has more than
one of our 246 people as a sponsor), and every fetch is cached to disk
immediately, so a re-run after an interruption costs nothing for doc_ids
already done.

INPUT:  state_legislation_sponsored.csv (from legiscan_fetch_state_bills.py)
OUTPUT: legiscan_billtext_cache/<doc_id>.raw.<ext>  -- original file
        legiscan_billtext_cache/<doc_id>.txt        -- extracted plain text
        bill_text_manifest.csv                      -- doc_id -> file paths,
            mime, extracted text length, extraction method/errors

USAGE:
    python3 legiscan_fetch_bill_text.py YOUR_LEGISCAN_API_KEY
"""

import base64
import csv
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

MAX_RETRIES = 5
CACHE_DIR = "legiscan_billtext_cache"

MIME_EXT = {
    "text/html": "html", "text/plain": "txt", "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}

_pdfplumber = None


def get_pdfplumber():
    """Lazily import pdfplumber, installing it on first use if missing."""
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
            print("WARNING: could not install pdfplumber. PDF bills will be saved raw-only "
                  "(no extracted .txt) -- install manually with 'pip3 install pdfplumber' "
                  "and re-run this script to backfill extraction.")
            _pdfplumber = False
            return False
    import pdfplumber
    _pdfplumber = pdfplumber
    return pdfplumber


def call(op, key, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://api.legiscan.com/?key={key}&op={op}" + (f"&{qs}" if qs else "")
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sdsu-research-script/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(0.3)
            return data
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(1 * attempt)
    raise RuntimeError(f"Failed op={op} params={params} after {MAX_RETRIES} retries: {last_err}")


def strip_html(raw_bytes):
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


def load_unique_docs(path, sponsor_types=None):
    """Returns doc_id -> {bill_ids: set(), mime: str}.

    sponsor_types: if given, only rows whose SponsorType is in this set are
    included. Use this to scope a fetch down (e.g. Primary Sponsor bills
    only) when the full unique-bill count is too large for the current
    API quota -- widen it later with a separate run once more quota is
    available; already-fetched doc_ids are cached and won't be re-fetched.
    """
    docs = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if sponsor_types and row.get("SponsorType") not in sponsor_types:
                continue
            did = (row.get("IntroducedDocId") or "").strip()
            if not did:
                continue
            entry = docs.setdefault(did, {"bill_ids": set(), "mime": row.get("IntroducedMime", "")})
            entry["bill_ids"].add(row.get("BillId", ""))
    return docs


def main():
    if len(sys.argv) not in (2, 3):
        print("Usage: python3 legiscan_fetch_bill_text.py YOUR_LEGISCAN_API_KEY [--all-sponsor-types]")
        print("  By default this only fetches text for bills where one of our 246 people was the")
        print("  PRIMARY sponsor (~32,824 unique bills) -- this alone is close to LegiScan's free")
        print("  30,000-query/month cap. Pass --all-sponsor-types to also include Co-Sponsor/")
        print("  Sponsor/Joint Sponsor bills (~97,033 unique bills total, several months of free quota).")
        sys.exit(1)
    key = sys.argv[1]
    scope_all = len(sys.argv) == 3 and sys.argv[2] == "--all-sponsor-types"
    sponsor_types = None if scope_all else {"Primary Sponsor"}

    print("Loading unique Introduced doc_ids from state_legislation_sponsored.csv "
          + ("(all sponsor types)..." if scope_all else "(Primary Sponsor bills only)..."))
    docs = load_unique_docs("state_legislation_sponsored.csv", sponsor_types)
    print(f"  {len(docs)} unique doc_id(s) to fetch.")
    if len(docs) > 30000:
        print(f"  NOTE: this exceeds LegiScan's free 30,000/month cap -- the script will keep "
              f"running and caching what it can; re-run next month to pick up the rest "
              f"(already-fetched doc_ids are skipped automatically).")

    os.makedirs(CACHE_DIR, exist_ok=True)
    manifest = []
    first_call_diagnostic_shown = False
    consecutive_failures = 0
    STOP_AFTER_CONSECUTIVE_FAILURES = 8  # likely quota/outage, not per-doc issues

    for i, (doc_id, info) in enumerate(sorted(docs.items()), 1):
        if i % 50 == 0 or i == len(docs):
            print(f"  ...{i}/{len(docs)} doc_id(s) processed")

        # Reuse a cached raw file from a prior run if we have one, regardless
        # of extension (glob for doc_id.raw.*).
        existing = [f for f in os.listdir(CACHE_DIR) if f.startswith(f"{doc_id}.raw.")]
        if existing:
            raw_path = os.path.join(CACHE_DIR, existing[0])
            mime = info["mime"]
            with open(raw_path, "rb") as f:
                raw_bytes = f.read()
            consecutive_failures = 0
        else:
            resp = call("getBillText", key, id=doc_id)
            if not first_call_diagnostic_shown:
                text_obj = resp.get("text", {})
                print(f"\n[diagnostic] First getBillText response -- top-level keys: "
                      f"{list(resp.keys())}, text object keys: {list(text_obj.keys())}\n")
                first_call_diagnostic_shown = True
            text_obj = resp.get("text", {})
            doc_b64 = text_obj.get("doc", "")
            mime = text_obj.get("mime", info["mime"])
            if not doc_b64:
                consecutive_failures += 1
                manifest.append({"DocId": doc_id, "BillIds": ";".join(sorted(info["bill_ids"])),
                                  "Mime": mime, "RawPath": "", "TextPath": "",
                                  "TextLength": 0,
                                  "Error": f"getBillText returned no content "
                                           f"(status={resp.get('status')}, resp={resp})"})
                if consecutive_failures >= STOP_AFTER_CONSECUTIVE_FAILURES:
                    print(f"\n{consecutive_failures} consecutive failed fetches -- this looks like "
                          f"a quota limit or outage rather than isolated bad doc_ids. Stopping here "
                          f"so we don't burn through the remaining {len(docs) - i} doc_id(s) on "
                          f"doomed requests. Last response: {resp}\n"
                          f"Re-run this same command later (next month, if it's a quota cap) -- "
                          f"everything fetched so far is cached and will be skipped.")
                    break
                continue
            consecutive_failures = 0
            raw_bytes = base64.b64decode(doc_b64)
            ext = MIME_EXT.get(mime, "bin")
            raw_path = os.path.join(CACHE_DIR, f"{doc_id}.raw.{ext}")
            with open(raw_path, "wb") as f:
                f.write(raw_bytes)

        text_path = os.path.join(CACHE_DIR, f"{doc_id}.txt")
        error = None
        if os.path.exists(text_path):
            with open(text_path, encoding="utf-8") as f:
                extracted = f.read()
        elif mime == "text/html":
            extracted = strip_html(raw_bytes)
        elif mime == "text/plain":
            extracted = raw_bytes.decode("utf-8", errors="replace")
        elif mime == "application/pdf":
            extracted, error = extract_pdf(raw_path)
        else:
            extracted, error = None, f"no extractor for mime type {mime!r} -- raw file saved"

        if extracted:
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(extracted)

        manifest.append({
            "DocId": doc_id, "BillIds": ";".join(sorted(info["bill_ids"])), "Mime": mime,
            "RawPath": raw_path, "TextPath": text_path if extracted else "",
            "TextLength": len(extracted) if extracted else 0, "Error": error or "",
        })

    with open("bill_text_manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["DocId", "BillIds", "Mime", "RawPath", "TextPath",
                                           "TextLength", "Error"])
        w.writeheader()
        w.writerows(manifest)

    n_ok = sum(1 for m in manifest if m["TextLength"] > 0)
    n_err = sum(1 for m in manifest if m["Error"])
    print(f"\n=== Done ===")
    print(f"  {n_ok}/{len(manifest)} doc(s) got extracted plain text.")
    print(f"  {n_err} doc(s) had an issue (see Error column in bill_text_manifest.csv).")
    print("\nPlease send back bill_text_manifest.csv (the cached raw/text files can stay "
          "local -- they're large; we'll figure out how to package them for GitHub next).")


if __name__ == "__main__":
    main()
