#!/usr/bin/env python3
"""
Whether each LegiScan bill in Table 4 passed (for Table 6's `passed` column), from the cached LegiScan session datasets
(legiscan_dataset_cache/*.zip; no new API calls).

Rule, matching Table 7: a measure passed if it became law or, for a measure that never goes to the governor, if every
chamber it needs adopted it.
  - any measure: a progress step 7 (veto Override) or 8 (Chaptered); otherwise status 5 (Vetoed) or 6 (Failed) means not
    passed, even after an earlier 'passed' step (Maine marks the legislature's enactment vote as passed, before the
    governor acts); otherwise LegiScan status 4 (Passed) or a progress step 4
  - simple resolutions of one chamber (bill_type R, SR): also passed once that chamber adopted them:
    progress step 2 (passed the chamber of origin), or a history line recording the chamber's adoption ('Adopted.',
    'Read. Amended. Adopted.', 'Report and Resolution Adopted', 'Resolution adopted', 'Adopted by Publication', 'Adopted
    by the Senate'); committee, amendment and motion adoptions do not count
  - concurrent and joint resolutions, memorials, constitutional amendments (CR, JR, M, JM, CM, CA, JRCA): also passed
    once enrolled (progress step 3: adopted by both chambers; these do not go to the governor in most states)
  - everything else, including bills enrolled but vetoed or never signed: not passed
Bills still pending in a session in progress at the freeze count as not passed (as in Table 7).

Output: legiscan_bill_passed.csv (BillId = Table 4 bill_id, LegiScanBillId, BillType, Status, Progress, Passed, Rule).

USAGE (from the repo root, after legiscan_fetch_state_bills.py):  python3 replication/scripts/state/legiscan_passed.py
"""

import collections
import csv
import glob
import json
import os
import re
import sys
import zipfile

csv.field_size_limit(sys.maxsize)
T4 = "datasets/csv/table4_state_bill_text.csv"
CACHE = "legiscan_dataset_cache"
OUT = "legiscan_bill_passed.csv"
ONE_CHAMBER = {"R", "SR"}
TWO_CHAMBER_NO_GOVERNOR = {"CR", "JR", "M", "JM", "CM", "CA", "JRCA"}   # Florida memorials need both chambers
ADOPTED = re.compile(r"^(?:Read\.\s+)?(?:Amended\.\s+)?(?:Report and Resolution |Resolution |Memorial )?Adopted\b"
                     r"(?!\s+(?:as amended\s+)?by (?:the )?committee)|\badopted by (?:the )?(?:senate|house|assembly)\b|"
                     r"^Adopted by Publication", re.I)


def decide(b):
    pe = {p.get("event") for p in b.get("progress") or []}
    ty = b.get("bill_type") or ""
    if pe & {7, 8}:
        return "Yes", "progress: chaptered or veto overridden"
    if b.get("status") in (5, 6):                 # vetoed (not overridden) or failed/died after an earlier 'passed' step
        return "No", "vetoed or failed"
    if b.get("status") == 4 or 4 in pe:
        return "Yes", "status/progress: passed"
    if ty in ONE_CHAMBER:
        if 2 in pe:
            return "Yes", "simple resolution: passed its chamber"
        if any(ADOPTED.search((h.get("action") or "").strip()) for h in b.get("history") or []):
            return "Yes", "simple resolution: history records adoption"
    if ty in TWO_CHAMBER_NO_GOVERNOR and 3 in pe:
        return "Yes", "concurrent/joint resolution: enrolled (adopted by both chambers)"
    return "No", "not passed"


def main():
    want = collections.defaultdict(dict)
    with open(T4, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["text_source"] == "LegiScan":
                st, sid, num = r["bill_id"].split("-", 2)
                want[sid][num] = r["bill_id"]
    out, rules = [], collections.Counter()
    for z in sorted(glob.glob(os.path.join(CACHE, "*.zip"))):
        sid = os.path.basename(z).rsplit("_", 1)[-1].replace(".zip", "")
        if sid not in want:
            continue
        zf = zipfile.ZipFile(z)
        for name in zf.namelist():
            if "/bill/" not in name or not name.endswith(".json"):
                continue
            b = json.loads(zf.read(name))["bill"]
            bid = want[sid].get(b.get("bill_number"))
            if not bid:
                continue
            passed, rule = decide(b)
            rules[(passed, rule)] += 1
            pe = sorted({p.get("event") for p in b.get("progress") or []})
            out.append([bid, b.get("bill_id"), b.get("bill_type", ""), b.get("status"), " ".join(map(str, pe)), passed, rule])
    out.sort()
    with open(OUT, "w", newline="", encoding="utf-8") as g:
        w = csv.writer(g, lineterminator="\n")
        w.writerow(["BillId", "LegiScanBillId", "BillType", "Status", "Progress", "Passed", "Rule"])
        w.writerows(out)
    total = sum(len(v) for v in want.values())
    print(f"Wrote {OUT}: {len(out)} of {total} LegiScan bills in Table 4")
    for (p, r), n in sorted(rules.items()):
        print(f"  {p:3s} {n:6,}  {r}")


if __name__ == "__main__":
    main()
