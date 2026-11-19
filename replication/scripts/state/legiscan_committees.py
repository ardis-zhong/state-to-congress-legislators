#!/usr/bin/env python3
"""
Committee referrals for the LegiScan bills in Table 4 (its `committees` column), from the cached LegiScan session
datasets (legiscan_dataset_cache/*.zip; no new API calls).

Each bill's JSON carries:
  referrals   every committee referral LegiScan parsed (date, chamber, committee name)      -> Source 'referrals'
  committee   the committee the bill sits in now                                           -> Source 'current committee'
  history     the action log; where neither of the above is filled, referral actions are read from it
              ('Referred to House IR Committee', 'Assigned to Senate JUD Committee', Maryland's 'First Reading
              House Rules and Executive Nominations')                                        -> Source 'history'
How complete LegiScan's referral data is varies by state (near 100% for New Jersey, Pennsylvania, Michigan; empty
referral lists for Arizona and Maryland, whose histories are read instead).

Output: legiscan_bill_committees.csv (State, SessionId, BillNumber, LegiScanBillId, Order, Chamber, Committee, Date,
Source): one row per bill and committee, in referral order, for the bills in state_legislation_sponsored.csv.

USAGE (from the repo root, after legiscan_fetch_state_bills.py):  python3 replication/scripts/state/legiscan_committees.py
"""

import csv
import glob
import json
import os
import re
import zipfile

SPONSORED = "state_legislation_sponsored.csv"
CACHE = "legiscan_dataset_cache"
OUT = "legiscan_bill_committees.csv"
HIST = [
    # 'Referred to House IR Committee', 'Read first time. Referred to Committee on Health and Human Services. To printer.'
    re.compile(r"(?:Re-?referred|Referred|Assigned|Rereferred|Recommitted)\s+to\s+(?:the\s+)?(?:(House|Senate|Assembly)\s+)?"
               r"(?:Committee\s+on\s+|Com\.\s+on\s+)?(.+?)(?:\s+Committee)?\s*(?:\.(?:\s|$)|;|$)", re.I),
    re.compile(r"^First Reading\s+(House|Senate)\s+(.+?)\s*$", re.I),            # Maryland
]
OHIO = re.compile(r"^To\s+(.+?)\s*$")                                             # Ohio: 'To Health, Human Services, & Aging'
SKIP = re.compile(r"\b(calendar|desk|governor|secretary|clerk|printer|engross|enroll|floor|third reading|second reading|"
                  r"sub|subcommittee|conference|committee of the whole|general file|table)\b", re.I)
CH = {"H": "House", "S": "Senate", "A": "House", "J": "Joint"}
LOWER = {"CA": "Assembly", "NY": "Assembly", "NV": "Assembly", "WI": "Assembly", "NJ": "General Assembly",
         "VA": "House of Delegates", "MD": "House of Delegates", "WV": "House of Delegates"}


def chamber(state, name):
    """Each state's own name for its lower chamber (LegiScan codes every lower chamber H or A)."""
    return LOWER.get(state, "House") if name in ("House", "Assembly") else name


def clean(name):
    name = re.sub(r"\s+", " ", name).strip(" .;,")
    return re.sub(r"\s+Committee$", "", name, flags=re.I)


def committees(b):
    refs = b.get("referrals") or []
    if refs:
        return [(CH.get(r.get("chamber", ""), r.get("chamber", "")), clean(r.get("name", "")), r.get("date", ""), "referrals")
                for r in refs if r.get("name")]
    c = b.get("committee")
    if isinstance(c, dict) and c.get("name"):
        return [(CH.get(c.get("chamber", ""), c.get("chamber", "")), clean(c["name"]), "", "current committee")]
    out = []
    for h in b.get("history") or []:
        act = (h.get("action") or "").strip()
        pre = re.match(r"^(House|Senate):\s*", act)            # Virginia: 'House: Referred to Committee on ...'
        if pre:
            act = act[pre.end():]
        pats = HIST + ([OHIO] if b.get("state") == "OH" else [])
        for pat in pats:
            m = pat.search(act) if pat is not OHIO else pat.match(act)
            if not m:
                continue
            name = m.group(m.lastindex)
            if SKIP.search(name) or len(name) > 90 or re.fullmatch(r"(?i)(the\s+)?(House|Senate|Assembly|committee)", name.strip(" .")):
                continue      # 'Referred to Senate' = sent to the other chamber, not a committee
            ch = ((m.group(1) if pat is not OHIO and m.lastindex > 1 else "") or "").title() \
                or (pre.group(1) if pre else "") or CH.get(h.get("chamber", ""), "")
            out.append((ch, clean(name), h.get("date", ""), "history"))
            break
    seen, uniq = set(), []
    for row in out:
        if (row[0], row[1].lower()) not in seen:
            seen.add((row[0], row[1].lower()))
            uniq.append(row)
    return uniq


def main():
    want = {}
    with open(SPONSORED, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            want.setdefault(r["SessionId"], set()).add(r["BillId"])
    rows, found = [], 0
    for z in sorted(glob.glob(os.path.join(CACHE, "*.zip"))):
        sid = os.path.basename(z).rsplit("_", 1)[-1].replace(".zip", "")
        if sid not in want:
            continue
        zf = zipfile.ZipFile(z)
        for name in zf.namelist():
            if "/bill/" not in name or not name.endswith(".json"):
                continue
            b = json.loads(zf.read(name))["bill"]
            if str(b.get("bill_id")) not in want[sid]:
                continue
            found += 1
            for i, (ch, com, date, src) in enumerate(committees(b), 1):
                rows.append([b.get("state", ""), sid, b.get("bill_number", ""), b.get("bill_id"), i,
                             chamber(b.get("state", ""), ch), com, date, src])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["State", "SessionId", "BillNumber", "LegiScanBillId", "Order", "Chamber", "Committee", "Date", "Source"])
        w.writerows(rows)
    total = sum(len(v) for v in want.values())
    print(f"Wrote {OUT}: {len(rows)} committee rows; {found} of {total} bills found in the datasets, "
          f"{len({r[3] for r in rows})} with at least one committee")


if __name__ == "__main__":
    main()
