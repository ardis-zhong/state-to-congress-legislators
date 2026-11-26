#!/usr/bin/env python3
"""
Whether each state-archive bill in Table 4 passed (for Table 6's `passed` column), from files the archive scripts
already saved (no new downloads). LegiScan bills are handled by legiscan_passed.py.

Rule, matching Table 7 and legiscan_passed.py: a measure passed if it became law (signed, chaptered, became law without
signature, veto overridden) or, for a measure that never goes to the governor, if every chamber it needs adopted it
(simple resolutions: their chamber; concurrent and joint resolutions, memorials, constitutional amendments: both).

Each source is read by its own function below, which says what it reads. Passed is
  Yes      the saved record shows passage
  No       the saved record is a complete history (or final status) and shows no passage
  Unknown  nothing saved records the outcome (listed in NOT_AVAILABLE; would need new downloads)

Output: archive_bill_passed.csv (BillId = Table 4 bill_id, Passed, Evidence, Source).

USAGE (from the repo root):  python3 replication/scripts/state/archive_passed.py
"""

import collections
import csv
import glob
import os
import re
import sys
import zipfile

csv.field_size_limit(sys.maxsize)
T4 = "datasets/csv/table4_state_bill_text.csv"
OUT = "archive_bill_passed.csv"


def table4():
    """Table 4 archive rows: bill_id -> (state, text_source, text_version)."""
    out = {}
    with open(T4, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["text_source"] != "LegiScan":
                out[r["bill_id"]] = (r["state"], r["text_source"], r["text_version"])
    return out


def plain(path):
    t = open(path, "rb").read().decode("utf-8", "replace")
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t).replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", t)


# ---------------------------------------------------------------------------------------------- California
def california(want):
    """1999-2012: pubinfo BILL_TBL.MEASURE_STATE (Chaptered = law, or a concurrent/joint resolution or constitutional
    amendment filed; a Senate resolution is 'Enrolled' once adopted; any other final state = not passed, e.g. a bill
    left 'Enrolled' was vetoed) and, for Assembly resolutions (HR), whose state never changes, BILL_HISTORY_TBL
    ('Read and adopted.'). 1989-1997 pubinfo holds only chaptered measures; 1993-98 bills not in it are checked against
    the saved leginfo listing (which lists a 'Chaptered' version when there is one)."""
    out = {}
    chaptered_old = set()
    for z in sorted(glob.glob("ca_pubinfo_cache/pubinfo_*.zip")):
        year = os.path.basename(z)[8:12]
        if not year.isdigit():
            continue
        zf = zipfile.ZipFile(z)
        names = {n.upper().split("/")[-1]: n for n in zf.namelist()}
        bills = {}
        for line in zf.open(names["BILL_TBL.DAT"]):
            c = [x.strip("`") for x in line.decode("utf-8", "replace").rstrip("\r\n").split("\t")]
            if len(c) < 6:
                continue
            bid = f"CA-{c[1][:4]}-{c[3]}{c[4]}" + (f"X{c[2]}" if c[2] != "0" else "")
            bills[c[0]] = (bid, c[3], c[5])
        if int(year) <= 1997:                                  # chaptered-only years
            chaptered_old |= {v[0] for v in bills.values() if v[2] == "Chaptered"}
            continue
        adopted = set()
        if "BILL_HISTORY_TBL.DAT" in names:
            for line in zf.open(names["BILL_HISTORY_TBL.DAT"]):
                c = line.decode("utf-8", "replace").split("\t")
                if len(c) > 3 and c[0].strip("`") in bills and bills[c[0].strip("`")][1] == "HR" \
                        and re.search(r"\badopted\b", c[3], re.I) and not re.search(r"committee|amendment", c[3], re.I):
                    adopted.add(c[0].strip("`"))
        for key, (bid, typ, state) in bills.items():
            if bid not in want:
                continue
            if state == "Chaptered":
                out[bid] = ("Yes", "measure state: Chaptered")
            elif typ == "SR" and state == "Enrolled":
                out[bid] = ("Yes", "Senate resolution enrolled (adopted)")
            elif typ == "HR":
                out[bid] = ("Yes", "history: Read and adopted") if key in adopted else ("No", "history: no adoption")
            else:
                out[bid] = ("No", f"final measure state: {state}")
    for bid in want:
        if bid in out or not bid.startswith("CA-"):
            continue
        if bid in chaptered_old:
            out[bid] = ("Yes", "in the chaptered measures table")
            continue
        year = int(bid.split("-")[1])
        if 1993 <= year <= 1998:
            m = re.match(r"([A-Z]+)(\d+)(?:X(\d+))?$", bid.split("-")[2])
            sess = {1993: "93-94", 1995: "95-96", 1997: "97-98"}[year - (year % 2 == 0)]
            path = f"ca_leginfo_cache/{sess}/listing/{m.group(1).lower()}" + \
                (f"x{m.group(3)}" if m.group(3) else "") + f"_{m.group(2)}.html"      # special session: abx1_14.html
            if not os.path.exists(path):
                hits = glob.glob(f"ca_leginfo_cache/{sess}/listing/{m.group(1).lower()}_{m.group(2)}*.html")
                path = hits[0] if len(hits) == 1 else path
            if os.path.exists(path):
                chap = re.search(r"\bChaptered\s*-\s*\d", plain(path))
                out[bid] = ("Yes", "listing: Chaptered version") if chap else ("No", "listing: no chaptered version")
    return out


# ---------------------------------------------------------------------------------------------- Pennsylvania
def lines_of(path):
    t = open(path, "rb").read().decode("utf-8", "replace")
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", "\n", t).replace("&nbsp;", " ").replace("&#160;", " ").replace("&amp;", "&")
    return [re.sub(r"\s+", " ", l).strip() for l in t.split("\n") if l.strip()]


def pennsylvania(want):
    """palegis.us bill pages (pa_palegis_cache/bills/<session>_<bill>.html) carry the full history: a law shows
    'Approved by the Governor' or 'Act No. ...' (or 'became law without the Governor's signature' / veto overridden);
    a resolution shows 'Adopted' / 'Resolution is adopted'; a joint resolution (constitutional amendment, which does not
    go to the Governor) passed once both chambers gave it final passage. Anything else = not passed."""
    out = {}
    for f in os.listdir("pa_palegis_cache/bills"):
        m = re.match(r"(\d{4})_([A-Z]+\d+)\.html$", f)
        if not m or f"PA-{m.group(1)}-{m.group(2)}" not in want:
            continue
        bid = f"PA-{m.group(1)}-{m.group(2)}"
        L = lines_of(os.path.join("pa_palegis_cache/bills", f))
        text = " | ".join(L)
        if any(re.match(r"(Approved by the Governor|Act No\.\s*\d)", l) for l in L) or \
                re.search(r"without (the )?(Governor's )?signature|veto (was )?overridden|over the Governor's veto", text, re.I):
            out[bid] = ("Yes", "history: approved by the Governor / Act No.")
            continue
        if re.match(r"[HS]R\d", m.group(2)):
            adopted = [i for i, l in enumerate(L) if re.match(r"(Resolution is adopted|Adopted)\b", l)]
            concurrent = re.search(r"\bconcurrent resolution\b", text, re.I)
            if adopted and (not concurrent or len(adopted) >= 2):
                out[bid] = ("Yes", "history: resolution adopted")
            else:
                out[bid] = ("No", "history: resolution not adopted" + (" by both chambers" if adopted else ""))
            continue
        if re.search(r"\bA Joint Resolution\b", text):
            fp = [l for l in L if re.match(r"(Third consideration and )?final passage", l, re.I)]
            if len(fp) >= 2:
                out[bid] = ("Yes", "joint resolution: final passage in both chambers")
                continue
        out[bid] = ("No", "history: not approved by the Governor")
    return out


# ---------------------------------------------------------------------------------------------- New Jersey
def new_jersey(want):
    """The Legislature's bill-tracking databases (nj_legdb_cache/<9697|9899|2000..2010>/DBASE.ZIP). MAINBILL.CHAPTERLAW is
    filled for every bill or joint resolution that became law (approved, or enacted after a conditional or line-item
    veto, or without approval); BILLHIST action codes record adoption of resolutions: PA = passed the Assembly, PS =
    passed the Senate, PBH = passed both houses, FSS = filed with the Secretary of State. Simple resolutions (AR, SR)
    need their own house; concurrent resolutions (ACR, SCR, including constitutional amendments) need both."""
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import nj_legdb_bills as L
    out = {}
    for code, year in [("9697", 1996), ("9899", 1998)] + [(str(y), y) for y in range(2000, 2011, 2)]:
        path = os.path.join("nj_legdb_cache", code, "DBASE.ZIP")
        if not os.path.exists(path):
            continue
        z = zipfile.ZipFile(path)
        tab = lambda t: L.dbf_rows(z.read(next(n for n in z.namelist() if n.upper() == f"{t}.DBF")))
        main = {}
        for r in tab("MAINBILL"):
            bid = f"NJ-{year}-{r['BILLTYPE']}{L.num(r['BILLNUMBER'])}"
            if bid in want:
                main[bid] = r
        codes = collections.defaultdict(set)
        for r in tab("BILLHIST"):
            bid = f"NJ-{year}-{r['BILLTYPE']}{L.num(r['BILLNUMBER'])}"
            if bid in main:
                codes[bid] |= set(r["ACTION"].split())
        for bid, r in main.items():
            ty, c = r["BILLTYPE"], codes[bid]
            if (r.get("CHAPTERLAW") or "").strip():
                out[bid] = ("Yes", f"chapter law {(r.get('PAMPHLETLA') or '').split('.')[0]} c.{r['CHAPTERLAW'].split('.')[0]}")
            elif ty == "AR":
                out[bid] = ("Yes", "history: passed Assembly") if c & {"PA", "FSS"} else ("No", "history: not adopted")
            elif ty == "SR":
                out[bid] = ("Yes", "history: passed Senate") if c & {"PS", "FSS"} else ("No", "history: not adopted")
            elif ty in ("ACR", "SCR"):
                both = "PBH" in c or "FSS" in c or {"PA", "PS"} <= c
                out[bid] = ("Yes", "history: passed both houses") if both else ("No", "history: not passed by both houses")
            else:
                out[bid] = ("No", f"no chapter law (governor action: {r.get('GOVERNORAC') or 'none'})")
    return out


EXTRACTORS = [("CA", california), ("PA", pennsylvania), ("NJ", new_jersey)]

NOT_AVAILABLE = {}


def main():
    t4 = table4()
    want = set(t4)
    res = {}
    for st, fn in EXTRACTORS:
        got = fn({b for b in want if t4[b][0] == st})
        res.update({b: v + (t4[b][1],) for b, v in got.items()})
    rows, tally = [], collections.Counter()
    for b in sorted(want):
        passed, ev, src = res.get(b, ("Unknown", "no saved record of the outcome", t4[b][1]))
        rows.append([b, passed, ev, src])
        tally[(t4[b][0], passed)] += 1
    with open(OUT, "w", newline="", encoding="utf-8") as g:
        w = csv.writer(g, lineterminator="\n")
        w.writerow(["BillId", "Passed", "Evidence", "Source"])
        w.writerows(rows)
    by = collections.defaultdict(dict)
    for (st, p), n in tally.items():
        by[st][p] = n
    print(f"Wrote {OUT}: {len(rows):,} archive bills; " +
          ", ".join(f"{p} {sum(v.get(p, 0) for v in by.values()):,}" for p in ("Yes", "No", "Unknown")))
    for st in sorted(by, key=lambda s: -sum(by[s].values())):
        print(f"  {st}: " + ", ".join(f"{p} {by[st].get(p, 0):,}" for p in ("Yes", "No", "Unknown")))


if __name__ == "__main__":
    main()
