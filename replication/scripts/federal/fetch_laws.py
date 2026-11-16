#!/usr/bin/env python3
"""
Every bill and joint resolution that became law, per Congress (93rd-119th), from Congress.gov's law list
(api.congress.gov/v3/law/<congress>), for Table 7's `passed` column.

Table 7's passed status otherwise comes from each bill's latest recorded action (classify_status.py). For older
bills Congress.gov's latest action is sometimes a procedural step recorded after enactment ('Message on Senate
action sent to the House.' for H.R. 2 of the 100th Congress, which became law over a veto), so a bill on the law
list is passed whatever its latest action says.

Output: federal_laws.csv (Congress, BillType, BillNumber, LawType, LawNumber). Cache: federal_laws_cache/.
The key comes from CONGRESS_API_KEY. About 120 requests.

USAGE (from the repo root):  python3 replication/scripts/federal/fetch_laws.py
"""

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.congress.gov/v3/law"
CACHE = "federal_laws_cache"
OUT = "federal_laws.csv"
CONGRESSES = range(93, 120)
DELAY = 1.0


def get(url, dest):
    if os.path.exists(dest):
        return json.load(open(dest, encoding="utf-8"))
    key = os.environ.get("CONGRESS_API_KEY") or sys.exit("Set CONGRESS_API_KEY in the environment")
    for attempt in range(5):
        time.sleep(DELAY)
        try:
            req = urllib.request.Request(f"{url}&api_key={key}",
                                         headers={"User-Agent": "state-to-congress-legislators/1.0 (research dataset)"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            json.dump(data, open(dest, "w", encoding="utf-8"))
            return data
        except urllib.error.HTTPError as e:
            time.sleep(60 * (attempt + 1) if e.code == 429 else 10 * (attempt + 1))
        except Exception:
            time.sleep(10 * (attempt + 1))
    sys.exit(f"could not fetch {url}")


def main():
    rows = []
    for c in CONGRESSES:
        offset, got = 0, []
        while True:
            d = get(f"{API}/{c}?format=json&limit=250&offset={offset}", os.path.join(CACHE, f"{c}_{offset}.json"))
            bills = d.get("bills", [])
            got += bills
            total = d.get("pagination", {}).get("count", 0)
            offset += 250
            if not bills or offset >= total:
                break
        for b in got:
            for law in b.get("laws") or []:
                rows.append([c, b["type"].upper(), b["number"], law.get("type", ""), law.get("number", "")])
        print(f"  {c}th Congress: {len(got)} bills ({total} per Congress.gov)", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Congress", "BillType", "BillNumber", "LawType", "LawNumber"])
        w.writerows(rows)
    print(f"Wrote {OUT}: {len(rows)} laws")


if __name__ == "__main__":
    main()
