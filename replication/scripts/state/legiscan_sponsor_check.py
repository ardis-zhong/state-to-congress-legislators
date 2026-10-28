#!/usr/bin/env python3
"""
Checks Table 4's LegiScan rows from Connecticut, Mississippi and South Dakota against each legislature's
own record of who introduced the bill (Ardis, 2026-10-28). LegiScan gives these states no sponsor roles
(every sponsor is "Sponsor"), so Table 4 kept every listed sponsor there; other states keep only the
primary sponsor. A row is kept when the person is the bill's first (prime) sponsor:

  CT  the General Assembly's bulk introducer file (ftp.cga.ct.gov/pub/data/archive/<year>introducer.csv,
      cached by ct_cga_bills.py): First when the person's district code is the first introducer
      (intro_type I, sort_order 1); district codes from replication/data/reference/ct_introducer_codes_2001_2009.csv
      plus CT_CODES below.
  MS  the introduced text's "By: Senator(s) Hyde-Smith, ..." line (the principal author first), as in
      ms_billstatus_bills.py.
  SD  the Legislature's API: First when the person is the bill's prime sponsor (SponsorType "P" in
      /api/SessionMembers/Bills/<session member id>; ids in SD_MEMBERS below) and the bill began in
      the person's own chamber (each chamber names a prime sponsor; the first chamber's is named
      first), as in sd_legis_bills.py.

Writes replication/data/reference/legiscan_sponsor_check.csv (one row per checked LegiScan row: Verdict
First, NotFirst or Unavailable, with the evidence). build_tables.py drops the NotFirst rows from Table 4.

USAGE (from the repo root):
    python3 replication/scripts/state/legiscan_sponsor_check.py
"""

import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ct_cga_bills  # noqa: E402
import sd_legis_bills  # noqa: E402
from legiscan_fetch_bill_text import sponsor_rows_in_scope  # noqa: E402

STATE_SPONSORED = "state_legislation_sponsored.csv"
MANIFEST = "bill_text_manifest.csv"
OUT = "replication/data/reference/legiscan_sponsor_check.csv"
CT_CODES = {("2010", "E000293"): "103"}  # Elizabeth Esty, House district 103 (Cheshire)
SD_MEMBERS = {("2009", "N000184"): "645", ("2010", "N000184"): "750"}  # Kristi Noem, House district 6
SD_CHAMBER = {"N000184": "H"}


def sq(x):
    return re.sub(r"[^a-z]", "", x.lower())


def ct_verdict(r, year, tables={}):
    code = CT_CODES.get((year, r["BioguideId"]))
    if not code:
        return "Unavailable", "no reviewed district code"
    if year not in tables:
        tables[year] = {}
        for x in ct_cga_bills.table(year, "introducer"):
            tables[year].setdefault(x["bill_num"], []).append(x)
    m = re.match(r"([A-Z]+?)(J?)(\d+)$", r["BillNumber"])
    bill = f"{m.group(1)[:1]}{'J' if m.group(2) else m.group(1)[1:2]}{int(m.group(3)):05d}"
    rows = tables[year].get(bill, [])
    first = [x["intro_code"].strip() for x in rows if x["intro_type"] == "I" and x["sort_order"] == "1"]
    me = [x for x in rows if x["intro_code"].strip() == code]
    if not rows:
        return "Unavailable", f"{bill} not in the {year} introducer file"
    if code in first:
        return "First", f"{bill}: first introducer"
    role = "not listed" if not me else ("co-sponsor" if me[0]["intro_type"] == "C" else f"introducer no. {me[0]['sort_order']}")
    return "NotFirst", f"{bill}: {role}; first introducer {', '.join(first) or 'none'}"


def ms_verdict(r, text):
    m = re.search(r"By:\s*(?:Senators?\(s\)|Representatives?\(s\)|Senators?|Representatives?)?\s*(.+?)(?:\s+To:|\n)", text[:800])
    if not m:
        return "Unavailable", "no 'By:' line"
    names = " ".join(m.group(1).split())
    first = re.sub(r"\(By Request\)", "", re.split(r",| and ", names)[0], flags=re.I).strip()
    last = r["Name"].split()[-1]
    return ("First" if sq(first).endswith(sq(last)) else "NotFirst"), f"By: {names[:120]}"


def sd_verdict(r, year, prime={}):
    smid = SD_MEMBERS.get((year, r["BioguideId"]))
    if not smid:
        return "Unavailable", "no reviewed session member id"
    if smid not in prime:
        raw = sd_legis_bills.cached(os.path.join(sd_legis_bills.CACHE, "member_bills", f"{smid}.json"),
                                    lambda: sd_legis_bills.fetch(f"{sd_legis_bills.API}/SessionMembers/Bills/{smid}"))
        prime[smid] = {}
        for b in json.loads(raw or b"{}").get("Bills", []):
            bill = b["Bill"]
            num = re.sub(r"^[A-Z]+", "", bill["BillNumber"])
            prime[smid][f"{bill['BillType']}{int(num)}"] = b["SponsorType"]
    m = re.match(r"([A-Z]+)(\d+)$", r["BillNumber"])
    t = prime[smid].get(f"{m.group(1)}{int(m.group(2))}")
    if t is None:
        return "NotFirst", "not among the member's sponsored bills"
    if t == "P" and r["BillNumber"][0] != SD_CHAMBER[r["BioguideId"]]:
        return "NotFirst", "prime sponsor in the second chamber; the first chamber's prime sponsor is named first"
    return ("First" if t == "P" else "NotFirst"), f"SponsorType {t}"


def main():
    rows, sponsor_only = sponsor_rows_in_scope(STATE_SPONSORED)
    text_path = {}
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        for m in csv.DictReader(f):
            if m["TextPath"]:
                text_path[m["DocId"]] = m["TextPath"]
    out = []
    for r in rows:
        if r["StateAbbr"] not in ("CT", "MS", "SD") or r["SponsorType"] != "Sponsor":
            continue
        year = re.search(r"(?:19|20)\d\d", r["SessionTitle"]).group(0)
        if r["StateAbbr"] == "CT":
            verdict, evidence = ct_verdict(r, year)
        elif r["StateAbbr"] == "MS":
            p = text_path.get(r["IntroducedDocId"])
            text = open(p, encoding="utf-8", errors="replace").read() if p and os.path.exists(p) else ""
            verdict, evidence = ms_verdict(r, text) if text else ("Unavailable", "no LegiScan text")
        else:
            verdict, evidence = sd_verdict(r, year)
        out.append({"StateAbbr": r["StateAbbr"], "BioguideId": r["BioguideId"], "Name": r["Name"],
                    "SessionId": r["SessionId"], "SessionTitle": r["SessionTitle"], "BillNumber": r["BillNumber"],
                    "NumSponsors": r["NumSponsors"], "Verdict": verdict, "Evidence": evidence})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    for st in ("CT", "MS", "SD"):
        sub = [o for o in out if o["StateAbbr"] == st]
        print(st, len(sub), {v: sum(1 for o in sub if o["Verdict"] == v) for v in ("First", "NotFirst", "Unavailable")})
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
