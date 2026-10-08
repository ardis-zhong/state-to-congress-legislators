#!/usr/bin/env python3
"""
Download every edition of the official Congressional Directory published
since 1979 from GovInfo (api.govinfo.gov, collection CDIR). The member
biographies in these directories are the source for Table 2's veteran column
(see extract_veterans.py).

Editions from about 1997 on are split into one biography per member, each
tagged with the member's Bioguide ID; they are downloaded as one zip per
edition. Older editions exist only as one scanned document; their plain-text
version is downloaded instead.

Files are saved to cdir_cache/ at the repo root (gitignored). Already
downloaded editions are skipped, so the script can be rerun after an
interruption.

USAGE (from the repo root; the key is an api.data.gov key, the same one used
for api.congress.gov):
    python3 replication/scripts/population/fetch_congressional_directory.py --api-key "$CONGRESS_API_KEY"
"""

import argparse
import json
import os
import time
import urllib.request

API = "https://api.govinfo.gov"
CACHE_DIR = "cdir_cache"
# Note: the 1979 and 1991 text editions lack the member-biography section (so do the 1977/1978
# ones, checked 2026-10-07), so members who served only in the 96th or 102nd Congress are "Not found".
FIRST_YEAR = 1979


def get(url, key, binary=False):
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(f"{url}{sep}api_key={key}",
                                 headers={"User-Agent": "Mozilla/5.0 (academic research)"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = r.read()
                return data if binary else json.loads(data)
        except Exception as e:  # network hiccup or rate limit: back off and retry
            if attempt == 4:
                raise
            print(f"    retry after error: {e}")
            time.sleep(10 * (attempt + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", required=True)
    args = ap.parse_args()
    os.makedirs(CACHE_DIR, exist_ok=True)

    listing = get(f"{API}/collections/CDIR/1970-01-01T00:00:00Z?pageSize=1000&offsetMark=*", args.api_key)
    packages = sorted(p["packageId"] for p in listing["packages"]
                      if int(p["packageId"].split("-")[1]) >= FIRST_YEAR)
    print(f"{len(packages)} editions since {FIRST_YEAR}")

    for pid in packages:
        done = [f for f in os.listdir(CACHE_DIR) if f.startswith(pid + ".")]
        if done:
            print(f"  {pid}: already have {done[0]}")
            continue
        summary = get(f"{API}/packages/{pid}/summary", args.api_key)
        links = summary.get("download", {})
        # Older editions have a whole-document text version; newer ones are per-member granules (zip).
        ext, url = ("txt", links["txtLink"]) if "txtLink" in links else ("zip", links["zipLink"])
        data = get(url, args.api_key, binary=True)
        tmp = os.path.join(CACHE_DIR, f"{pid}.{ext}.part")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, os.path.join(CACHE_DIR, f"{pid}.{ext}"))
        print(f"  {pid}: {ext}, {len(data) / 1e6:.1f} MB")

    with open(os.path.join(CACHE_DIR, "editions.json"), "w") as f:
        json.dump(packages, f, indent=1)


if __name__ == "__main__":
    main()
