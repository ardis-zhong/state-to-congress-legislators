#!/usr/bin/env python3
"""
LegiScan reconnaissance, round 2.

Round 1 confirmed getSponsoredList(people_id) returns only bare bill stubs
(bill_id, number, session_id) -- no title/status/dates. This probe checks
the two real alternatives before we commit to an architecture:

  1. getBill(bill_id) -- the full per-bill record, called on one real
     bill_id recovered from round 1 (Anna Caballero's AB1136, bill_id
     1978671), to see exactly what fields a full bill record carries
     (title, status, sponsors list, dates, etc).
  2. getDatasetList(state=CA) -- the bulk per-state/session dataset
     listing, to see dataset sizes and access_keys, without actually
     downloading a multi-hundred-MB ZIP yet.

USAGE:
    python3 legiscan_probe2.py YOUR_LEGISCAN_API_KEY
"""

import json
import sys
import time
import urllib.request

MAX_RETRIES = 5


def call(op, key, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://api.legiscan.com/?key={key}&op={op}" + (f"&{qs}" if qs else "")
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sdsu-research-script/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(0.3)
            return data
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(1 * attempt)
    raise RuntimeError(f"Failed op={op} params={params} after {MAX_RETRIES} retries: {last_err}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 legiscan_probe2.py YOUR_LEGISCAN_API_KEY")
        sys.exit(1)
    key = sys.argv[1]

    print("Fetching getBill for a real bill_id (1978671, Anna Caballero's AB1136)...")
    bill = call("getBill", key, id=1978671)

    print("Fetching getDatasetList for CA (does not download the archive itself)...")
    datasets = call("getDatasetList", key, state="CA")

    out = {"getBill": bill, "getDatasetList_CA": datasets}
    with open("legiscan_probe2.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print("\nWrote legiscan_probe2.json -- please send this back.")


if __name__ == "__main__":
    main()
