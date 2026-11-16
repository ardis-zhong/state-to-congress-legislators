#!/usr/bin/env python3
"""
New Jersey bills 1996-1999 from the Legislature's own bill-tracking databases and bill texts. The current
website's bill search covers the 2000-01 session on (nj_njleg_bills.py), but the Legislature still publishes the
1996-97 and 1998-99 databases (https://pub.njleg.gov/leg-databases/9697data/DBASE.ZIP, 9899data/DBASE.ZIP; dBase
tables) and the bill texts themselves (https://pub.njleg.gov/bills/9697/A0500/16_i1.htm). This replaces the
earlier Internet Archive sample for these sessions (nj_wayback_bills.py, 3 rows).

  MAINBILL.DBF  one row per bill: FIRSTPRIME (first prime sponsor, 'Lance, Leonard'), INTRODATE, SYNOPSIS
  BILLWP.DBF    the bill's documents; DOCTYPE 'I' = introduced ('L:\\9697BILL\\A0500\\16_I1.DOC' -> 16_i1.htm;
                where a bill has several I documents, the lowest number is used)
  ROSTER.DBF    members (used to review the names below; every surname of ours is unique in its roster)

A bill counts when FIRSTPRIME is one of the population members serving then (NAMES below), and the introduced
text's sponsor line ('Sponsored by: Assemblyman LEONARD LANCE District 23', or 'By Assemblyman LANCE' on pre-filed
bills) is checked to name that person first (IntroducedByMatch, as in nj_njleg_bills.py). All bill types are kept
(A, S, joint, concurrent and simple resolutions), as for 2000 on.

Polite: one request at a time, at least 2 seconds apart (njleg.state.nj.us robots.txt allows all), a User-Agent
naming the project, every file cached under nj_legdb_cache/ (symlink to the T9 drive).

USAGE (from the repo root):  python3 replication/scripts/state/nj_legdb_bills.py
"""

import csv
import io
import os
import re
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nj_njleg_bills as nj  # noqa: E402  (get, plain, heading)

PUB = "https://pub.njleg.gov"
CACHE = "nj_legdb_cache"
SESSIONS = {"9697": 1996, "9899": 1998}
OUT = "nj_legdb_state_legislation_sponsored.csv"
# FIRSTPRIME spelling -> (bioguide, name). Reviewed against ROSTER.DBF of both sessions: Adler (Senate, district 6),
# Lance (Assembly 23), Garrett (Assembly 24), Pascrell (Assembly 35, resigned 1997), Pou (Assembly 35, from 1997),
# Conaway (Assembly 7) and Watson Coleman (Assembly 15) from 1998. No other member shares these surnames.
NAMES = {
    "Adler, John H.": ("A000364", "John Adler"),
    "Lance, Leonard": ("L000567", "Leonard Lance"),
    "Garrett, E. Scott": ("G000548", "Scott Garrett"),
    "Pascrell, William J.": ("P000096", "Bill Pascrell"),
    "Pou, Nellie": ("P000621", "Nellie Pou"),
    "Conaway, Herbert C.": ("C001136", "Herb Conaway"),
    "Watson Coleman, Bonnie": ("W000822", "Bonnie Watson Coleman"),
}


def dbf_rows(data):
    """Rows of a dBase III table (bytes) as dicts of stripped strings."""
    n, hl, rl = struct.unpack("<IHH", data[4:12])
    fields, p = [], 32
    while data[p] != 0x0D:
        d = data[p:p + 32]
        fields.append((d[:11].split(b"\0")[0].decode(), d[16]))
        p += 32
    for i in range(n):
        rec = data[hl + i * rl: hl + (i + 1) * rl]
        if not rec or rec[:1] == b"*":
            continue
        row, q = {}, 1
        for name, ln in fields:
            row[name] = rec[q:q + ln].decode("cp1252", "replace").strip()
            q += ln
        yield row


def first_sponsor(text):
    """First sponsor as printed: 'Sponsored by: Assemblyman LEONARD LANCE District 23' (1998 on), or the
    1996-97 form 'By Assemblymen PASCRELL and ROCCO An Act ...' / 'By Assemblyman LANCE An Act ...'."""
    first, _ = nj.heading(text)
    if first:
        return first
    flat = " ".join(text[:4000].split())
    m = re.search(r"\bBy (?:Assemblym[ae]n|Assemblywom[ae]n|Assembly Members?|Senators?)\s+(.+?)"
                  r"(?:,| and | An? | AN | Joint | JOINT | Concurrent | CONCURRENT |$)", flat)
    return m.group(1).strip() if m else ""


def num(s):
    return str(int(float(s))) if s else ""


def main():
    nj.DELAY = 2
    out = []
    for code, year in SESSIONS.items():
        z = nj.get(f"{PUB}/leg-databases/{code}data/DBASE.ZIP", os.path.join(CACHE, code, "DBASE.ZIP"))
        zf = zipfile.ZipFile(io.BytesIO(z))
        table = lambda t: dbf_rows(zf.read(next(n for n in zf.namelist() if n.upper() == f"{t}.DBF")))
        intro = {}
        for r in table("BILLWP"):
            if r["DOCTYPE"] == "I":
                intro.setdefault((r["BILLTYPE"], num(r["BILLNUMBER"])), []).append(r["DOCUMENT"])
        bills = [r for r in table("MAINBILL") if r["FIRSTPRIME"] in NAMES]
        print(f"{code}: {len(bills)} bills with one of our members as first prime sponsor", flush=True)
        for r in bills:
            typ, n = r["BILLTYPE"], num(r["BILLNUMBER"])
            bill = f"{typ}{n}"
            docs = sorted(intro.get((typ, n), []), key=lambda d: int(re.search(r"_I(\d+)", d, re.I).group(1)))
            text, txt = "", os.path.join(CACHE, "texts", f"{code}_{bill}.txt")
            if docs:
                folder, fname = docs[0].split("\\")[-2], docs[0].split("\\")[-1].lower().replace(".doc", ".htm")
                if os.path.exists(txt):
                    text = open(txt, encoding="utf-8").read()
                else:
                    raw = nj.get(f"{PUB}/bills/{code}/{folder}/{fname}", os.path.join(CACHE, "htm", f"{code}_{folder}_{fname}"))
                    text = nj.plain(raw.decode("cp1252", "replace")) if raw else ""
                    if text:
                        os.makedirs(os.path.dirname(txt), exist_ok=True)
                        with open(txt, "w", encoding="utf-8") as f:
                            f.write(text)
            first = first_sponsor(text)
            surname = r["FIRSTPRIME"].split(",")[0]
            sq = lambda x: re.sub(r"[^a-z]", "", x.lower())
            bare = re.sub(r",?\s+(JR\.?|SR\.?|III|II|M\.D\.)\s*$", "", first, flags=re.I)
            match = "" if not text else "Unavailable" if not first else "Yes" if sq(bare).endswith(sq(surname)) else "No"
            d = r["INTRODATE"]
            bio, name = NAMES[r["FIRSTPRIME"]]
            out.append({"BioguideId": bio, "Name": name, "Session": f"{year}-{year + 1} Regular Session",
                        "BillNumber": bill, "BillId": f"NJ-{year}-{bill}", "Title": " ".join(r["SYNOPSIS"].split()),
                        "IntroducedDate": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else "",
                        "House": "SENATE" if typ.startswith("S") else "HOUSE", "AuthorName": first,
                        "IntroducedByMatch": match, "TextVersion": "Introduced", "TextPath": txt if text else ""})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {OUT}: {len(out)} rows, {sum(1 for o in out if o['TextPath'])} with text; introducer check: "
          + ", ".join(f"{k} {sum(1 for o in out if o['IntroducedByMatch'] == k)}" for k in ("Yes", "No", "Unavailable")))


if __name__ == "__main__":
    main()
