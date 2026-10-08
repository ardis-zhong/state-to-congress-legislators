#!/usr/bin/env python3
"""
Download the Center for Effective Lawmaking's legislative effectiveness scores
(thelawmakers.org/data-download) for Table 3:

    House LES, 93rd-118th Congress     CELHouse93to118Reduced-REVISED-06.26.2025.dta
    Senate LES, 93rd-118th Congress    CELSenate93to118Reduced.dta
    State SLES, all states thru 2025   sles_all_50_states_202609.dta
    State SLES codebook                sles_all_state_codebook.pdf

Files go to cel_cache/ at the repo root (gitignored); files already present
are skipped. CEL updates these files from time to time under new names, so
check the download page for newer versions before rebuilding.

How to cite (per thelawmakers.org):
    House:  Volden, Craig, and Alan E. Wiseman. 2014. Legislative Effectiveness
            in the United States Congress: The Lawmakers. New York: Cambridge
            University Press; updated at www.thelawmakers.org.
    Senate: Volden, Craig, and Alan E. Wiseman. 2018. "Legislative
            Effectiveness in the United States Senate." Journal of Politics
            80(2): 731-735; updated at www.thelawmakers.org.
    States: Bucchianeri, Peter, Craig Volden, and Alan E. Wiseman. 2026.
            "State Legislative Effectiveness Scores Data set"; updated at
            www.thelawmakers.org.

USAGE (from the repo root):
    python3 replication/scripts/effectiveness/fetch_cel_scores.py
"""

import os
import urllib.request

BASE = "https://thelawmakers.org/wp-content/uploads/"
FILES = [
    "2025/06/CELHouse93to118Reduced-REVISED-06.26.2025.dta",
    "2025/03/CELSenate93to118Reduced.dta",
    "2026/10/sles_all_50_states_202609.dta",
    "2026/10/sles_all_state_codebook.pdf",
]
CACHE_DIR = "cel_cache"


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    for path in FILES:
        dest = os.path.join(CACHE_DIR, os.path.basename(path))
        if os.path.exists(dest):
            print(f"  already have {os.path.basename(path)}")
            continue
        req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0 (academic research)"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        with open(dest + ".part", "wb") as f:
            f.write(data)
        os.replace(dest + ".part", dest)
        print(f"  {os.path.basename(path)}: {len(data) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
