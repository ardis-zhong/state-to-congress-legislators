#!/usr/bin/env python3
"""
LegiScan reconnaissance, round 3 -- bulk dataset structure.

Why this probe exists:
Round 1/2 established that getSponsoredList(people_id) only returns bare
bill stubs, and getBill(bill_id) returns full metadata but each "texts"
entry is just a URL/hash -- not the actual document content (you'd need a
separate getBillText(doc_id) call per document to get that). For 246
matched legislators, each potentially sponsoring hundreds of bills across
many sessions, calling getBill/getBillText one bill/doc at a time would
burn through the free 30,000-query/month cap fast.

LegiScan also offers a bulk "dataset" API (getDatasetList + getDataset)
that returns one ZIP per state+session containing every bill in that
session, pre-packaged. If that ZIP embeds full bill text (not just a URL),
one dataset download replaces potentially thousands of getBill/getBillText
calls AND solves the eventual full-text requirement in the same pass. This
probe downloads exactly ONE real (small) dataset ZIP to confirm:

  1. The exact request/response shape of getDataset (it's a base64-encoded
     ZIP inside the JSON response, per LegiScan's docs -- confirming this
     against a real response rather than assumed).
  2. Whether each bill's JSON inside that ZIP embeds actual document text
     (base64 "doc" field) or just text metadata like the live getBill call.
  3. Realistic per-session ZIP size, so we can estimate total download
     volume across every (state, session) our 246 matched people need.

USAGE:
    python3 legiscan_probe3.py YOUR_LEGISCAN_API_KEY
"""

import base64
import json
import os
import sys
import time
import urllib.request
import zipfile
import io

MAX_RETRIES = 5


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


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 legiscan_probe3.py YOUR_LEGISCAN_API_KEY")
        sys.exit(1)
    key = sys.argv[1]

    # Idaho is one of our smaller-coverage states (Raul Labrador, Russ
    # Fulcher) -- pick its smallest listed dataset to keep this probe cheap
    # and fast. Falls back to CA's smallest if ID has no datasets for some
    # reason.
    print("Fetching getDatasetList for a small test state (ID)...")
    dl = call("getDatasetList", key, state="ID").get("datasetlist", [])
    if not dl:
        print("No ID datasets found, falling back to CA...")
        dl = call("getDatasetList", key, state="CA").get("datasetlist", [])

    smallest = min(dl, key=lambda d: d.get("dataset_size", 1 << 62))
    print(f"Smallest dataset: session_id={smallest['session_id']} "
          f"({smallest['session_title']}), zip size ~{smallest['dataset_size']:,} bytes")

    print("Calling getDataset (this downloads the actual ZIP, base64-encoded in the response)...")
    ds = call("getDataset", key, id=smallest["session_id"], access_key=smallest["access_key"])
    dataset = ds.get("dataset", {})
    zip_b64 = dataset.get("zip", "")
    print(f"Response dataset keys: {list(dataset.keys())}")
    print(f"Decoded zip will be ~{len(zip_b64) * 3 // 4:,} bytes")

    zip_bytes = base64.b64decode(zip_b64)
    with open("legiscan_probe3_dataset.zip", "wb") as f:
        f.write(zip_bytes)
    print(f"Wrote legiscan_probe3_dataset.zip ({len(zip_bytes):,} bytes)")

    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = zf.namelist()
    print(f"\nZIP contains {len(names)} entries. First 15:")
    for n in names[:15]:
        print(f"  {n}")

    bill_files = [n for n in names if "/bill/" in n and n.endswith(".json")]
    print(f"\n{len(bill_files)} bill JSON files found.")

    if bill_files:
        sample_name = bill_files[0]
        sample = json.loads(zf.read(sample_name).decode("utf-8"))
        with open("legiscan_probe3_sample_bill.json", "w", encoding="utf-8") as f:
            json.dump(sample, f, indent=2)
        print(f"Wrote legiscan_probe3_sample_bill.json (from {sample_name})")

        bill = sample.get("bill", sample)
        texts = bill.get("texts", [])
        print(f"\nSample bill '{bill.get('bill_number')}' has {len(texts)} text entries.")
        if texts:
            t0 = texts[0]
            has_doc_field = "doc" in t0
            print(f"First text entry keys: {list(t0.keys())}")
            print(f"Embeds actual document content (base64 'doc' field present)? {has_doc_field}")
            if has_doc_field:
                doc_b64 = t0.get("doc", "")
                print(f"Embedded doc is ~{len(doc_b64) * 3 // 4:,} bytes decoded, "
                      f"mime={t0.get('mime')}")

    print("\nDone. Please send back legiscan_probe3_sample_bill.json "
          "(the full ZIP can stay local -- just confirming structure here).")


if __name__ == "__main__":
    main()
