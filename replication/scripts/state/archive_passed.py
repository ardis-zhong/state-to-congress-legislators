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


# ---------------------------------------------------------------------------------------------- Florida
FL_OTHER_BILL = re.compile(r"(?:Iden\.?/Sim\.?/Compare|Link/Iden/Sim/Compare|companion bill\(s\)|See also|"
                           r"refer to|see\s+(?:CS/)*[HS])[^;]*", re.I)
FL_LAW = re.compile(r"Approved by Governor|Became Law without Governor|Chapter No\.|Location: Became Law|"
                    r"filed with Secretary of State|veto overridden|Became Law", re.I)


def fl_decide(typ, actions):
    """actions: the bill's own history text, with clauses about other (identical or companion) bills removed."""
    a = FL_OTHER_BILL.sub(" ", actions)
    if re.search(r"Veto Message|Vetoed", a, re.I) and not re.search(r"veto overridden", a, re.I):
        return "No", "vetoed"
    if FL_LAW.search(a):
        return "Yes", "became law / filed with Secretary of State"
    if typ in ("HR", "SR") and re.search(r"\bAdopted\b", a):
        return "Yes", "resolution adopted"
    if re.search(r"Laid on Table|Substituted", a, re.I) and FL_OTHER_BILL.search(actions):
        return "No", "laid on table: an identical/companion bill passed instead"
    return "No", "died / not passed"


def florida(want):
    """1998-2012: the Senate site's session bill lists (fl_senate_cache/lists/<session>_<house|senate>_<page>.html) give
    each measure's full 'Last Action'. 1995-1997: Online Sunshine bill pages kept by the Internet Archive
    (fl_wayback_cache/pages/<year>/<H123>.html) give the dated history. Yes = approved by the Governor, became law
    without signature, chapter number, or (resolutions, memorials) 'Signed by Officers and filed with Secretary of
    State'; simple resolutions (HR, SR) also when 'Adopted'. A bill laid on the table because an identical or companion
    bill passed instead did not itself pass. Clauses naming the other bill ('refer to SB 48 (Ch. 99-413)', 'See also
    SR 84 (Adopted)') are removed before matching. A blank archived page = Unknown."""
    out = {}
    for f in sorted(glob.glob("fl_senate_cache/lists/*.html")):
        code = os.path.basename(f).split("_")[0]
        t = open(f, "rb").read().decode("utf-8", "replace")
        for m in re.finditer(r">\s*(?:CS/)*([HS][A-Z]*)\s+(\d+[A-Z]?)\s*</a>(.*?)Last Action:\s*(.*?)(?=</)", t, re.S):
            bid = f"FL-{code}-{m.group(1)}{m.group(2)}"          # special sessions: 'HB 55B' -> FL-2001B-HB55B
            if bid in want and bid not in out:
                a = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(4))).replace("&amp;", "&").replace("&#39;", "'")
                out[bid] = fl_decide(m.group(1), a)
    for f in glob.glob("fl_wayback_cache/pages/*/*.html"):
        year = f.split("/")[-2]
        m = re.match(r"([HS])(\d+)\.html$", os.path.basename(f))
        bid = f"FL-{year}-{m.group(1)}B{m.group(2)}" if m else ""
        if bid not in want or bid in out:
            continue
        entries = []                                  # dated entries, with their wrapped continuation lines
        for l in lines_of(f):
            if re.match(r"\d\d/\d\d/\d\d\s", l):
                entries.append(l)
            elif entries and not re.match(r"(BILL TEXT|STATUTE CITATIONS|SUBJECT INDEX|Bill Text|Statute Citations)", l):
                entries[-1] += " " + l
            elif entries:
                break
        if not entries:
            out[bid] = ("Unknown", "archived page has no history")
            continue
        typ = "HR" if m.group(1) == "H" and int(m.group(2)) >= 9000 else m.group(1) + "B"   # House resolutions: 9001 on
        res = fl_decide(typ, " ; ".join(entries))
        if res[0] == "No" and res[1] == "died / not passed" and not re.search(
                r"(?i)died|withdrawn|indefinitely postponed|laid on table|carried over", entries[-1]):
            res = ("Unknown", "archived copy taken before the session ended")
        out[bid] = res
    return out


# ---------------------------------------------------------------------------------------------- Texas
def texas(want):
    """FTP author reports (tx_ftp_cache/authors/<session>_<code>.htm) give each measure's last action with the body that
    took it ('Last Action: 06/09/1993 E Effective on 9/1/93'). E (executive) actions mean law ('Effective ...', 'Signed by
    the Governor') or, for concurrent and joint resolutions, 'Signed by the Governor' / 'Filed with the Secretary of
    State', except 'Vetoed by the Governor'. Simple resolutions (HR, SR) end with 'Adopted' or 'Reported enrolled'
    after adoption. Anything else = not passed."""
    out = {}
    for f in glob.glob("tx_ftp_cache/authors/*.htm"):
        code = os.path.basename(f).split("_")[0]
        s = plain(f)
        for m in re.finditer(r"\b([HS][A-Z]*) (\d+) Author:.*?Last Action:\s*(\d\d/\d\d/\d{4})\s+([A-Z])\s+(.*?)\s+Caption:", s):
            bid = f"TX-{code}-{m.group(1)}{m.group(2)}"
            if bid not in want or bid in out:
                continue
            ty, who, act = m.group(1), m.group(4), m.group(5)
            if who == "E":
                out[bid] = ("No", "vetoed by the Governor") if "Vetoed" in act else ("Yes", f"last action: {act[:40]}")
            elif ty in ("HR", "SR") and re.match(r"(Adopted|Reported enrolled)", act):
                out[bid] = ("Yes", "resolution adopted")
            else:
                out[bid] = ("No", f"last action: {act[:40]}")
    return out


# ---------------------------------------------------------------------------------------------- batch: one-page sources
def louisiana(want):
    """BillInfo pages (la_legis_cache/info/<i>.html) give 'Current Status': 'Signed by the Governor - Act 445', 'Became
    Act without signature' = law; 'Sent to the Secretary of State' / 'Enrolled' + adopted = resolution adopted; 'Pending
    ...', 'Withdrawn ...', 'Subject to call ...', 'Vetoed ...' = not passed. Each page's bill and session come from the
    saved search lists (la_legis_cache/lists|search/<session>_*.html), since the page header shows the current session."""
    key = {}
    for f in glob.glob("la_legis_cache/lists/*.html") + glob.glob("la_legis_cache/search/*.html"):
        sess = os.path.basename(f).split("_")[0]
        for i, b in re.findall(r'BillInfo\.aspx\?i=(\d+)"[^>]*>\s*([A-Z]+\d+)\s*<', open(f, errors="replace").read()):
            key.setdefault(i, f"LA-{sess}-{b}")
    out = {}
    for f in glob.glob("la_legis_cache/info/*.html"):
        bid = key.get(os.path.basename(f)[:-5])
        if bid not in want or bid in out:
            continue
        m = re.search(r"Current Status:\s*(.{0,80}?)\s+(?:Text|Digests|Amendments|Authors|Votes)\b", plain(f))
        st = (m.group(1) if m else "").strip()
        if not st:
            out[bid] = ("Unknown", "no current status on the saved page")
        elif re.search(r"Signed by the Governor|Act\s*\d+|without (the Governor's )?signature|Sent to the Secretary of State|"
                       r"veto overridden", st, re.I):
            out[bid] = ("Yes", f"current status: {st[:50]}")
        else:
            out[bid] = ("No", f"current status: {st[:50]}")
    return out


def mississippi(want):
    """Author pages (ms_billstatus_cache/author_pages/<session>_<name>.htm) list each measure with its final action:
    'Approved by Governor' (law), 'Enrolled Bill Signed' (concurrent resolution adopted by both houses), 'Adopted' /
    'Immediate Release' (simple resolution adopted); 'Died ...', 'Vetoed', 'Veto Sustained', 'Failed' = not passed."""
    out = {}
    for f in glob.glob("ms_billstatus_cache/author_pages/*"):
        sess = os.path.basename(f).split("_")[0]
        s = plain(f)
        for m in re.finditer(r"\b((?:H|S)[A-Z]*) ?(\d{1,4})\b(.*?)\b\d\d/\d\d (?:\([HS]\) )?([A-Z][A-Za-z ]{3,32}?)(?= (?:H|S)[A-Z]* ?\d{1,4}\b| KEY| End|$)", s):
            bid = f"MS-{sess}-{m.group(1)}{int(m.group(2)):04d}"      # pages print 'SC 508'; Table 4 ids pad: SC0508
            if bid not in want or bid in out:
                continue
            st = m.group(4).strip()
            if re.match(r"(Approved by Governor|Enrolled Bill Signed|Veto Overridden)", st):
                out[bid] = ("Yes", st)
            elif re.match(r"(Adopted|Immediate Release)", st) and m.group(1) in ("HR", "SR"):   # concurrent: 'Enrolled Bill Signed'
                out[bid] = ("Yes", f"resolution: {st}")
            else:
                out[bid] = ("No", st)
    return out


def maryland(want):
    """Sponsor pages (md_mga_cache/sponsors/<year>_<key>.htm) give 'Status as of <date>: Became Law - Chapter 621' /
    'Became Law - Joint Resolution 2' / 'Became Law - Overridden Veto' (passed), or 'Vetoed by the Governor ...' / 'Bill is
    in the House - Unfavorable ...' (not passed)."""
    out = {}
    for f in glob.glob("md_mga_cache/sponsors/*.htm"):
        year = os.path.basename(f)[:4]
        for m in re.finditer(r"\b(HB|SB|HJ|SJ)\s*(\d+)\s+Status as of [A-Za-z]+ \d+, \d{4}:\s*(.*?)\s+Sponsored By", plain(f)):
            bid = f"MD-{year}-{m.group(1)}{m.group(2)}"
            if bid in want and bid not in out:
                st = m.group(3)
                out[bid] = ("Yes", st[:50]) if st.startswith("Became Law") else ("No", st[:50])
    return out


def west_virginia(want):
    """Bill history pages (wv_legislature_cache/history/<year>_RS_<num>.html): 'LAST ACTION: H Chapter 99, Acts 1996' =
    law; anything else (committee referral, 'Vetoed by Governor', ...) = not passed. No last action on the page = Unknown."""
    out = {}
    for f in glob.glob("wv_legislature_cache/history/*.html"):
        m0 = re.match(r"(\d{4})_RS_(\d+)\.html$", os.path.basename(f))
        s = plain(f)
        h = re.search(r"\b(House|Senate) Bill (\d+)\b", s)
        if not m0 or not h:
            continue
        bid = f"WV-{m0.group(1)}-{h.group(1)[0]}B{h.group(2)}"
        if bid not in want or bid in out:
            continue
        m = re.search(r"LAST ACTION:\s*(.{0,60}?)\s\d\d/\d\d/\d\d", s)
        if not m:
            out[bid] = ("Unknown", "no last action on the saved page")
        else:
            out[bid] = ("Yes", m.group(1)) if re.search(r"Chapter \d+|Acts \d{4}", m.group(1)) else ("No", m.group(1))
    return out


def alaska(want):
    """BASIS prime-sponsorship tables (ak_akleg_cache/sponsorship/<legislature>_<code>.html): Current Status 'CHAPTER 72
    SLA 01' = law, 'LEGIS RESOLVE 12' = resolution adopted by both houses; a committee ('(H) FIN') or 'FAILED' = not passed."""
    out = {}
    for f in glob.glob("ak_akleg_cache/sponsorship/*.html"):
        leg = os.path.basename(f).split("_")[0]
        for m in re.finditer(r"\b([HS][A-Z]*) (\d+) (.*?)(?:REPRESENTATIVES?|SENATORS?) [A-Z ,.'-]+? "
                             r"((?:\([HS]\) \w+)|[A-Z][A-Z ]*?\d+(?: [A-Z]+ \d+)?|[A-Z][A-Z ]+) (\d\d/\d\d/\d{4})", plain(f)):
            bid = f"AK-{leg}-{m.group(1)}{m.group(2)}"
            if bid in want and bid not in out:
                st = m.group(4)
                out[bid] = ("Yes", st) if re.match(r"(CHAPTER|LEGIS RESOLVE|PERMANENTLY FILED)", st) else ("No", st)
    return out


def idaho(want):
    """Year-end mini-data status lists (id_legislature_cache/lists/<year>.html): '(+) indicates ADOPTED or LAW';
    'LAW+' / 'ADOPTED+' = passed, anything else = not passed."""
    out = {}
    for f in glob.glob("id_legislature_cache/lists/*.html"):
        year = os.path.basename(f)[:4]
        s = plain(f)
        for m in re.finditer(r"\b([HS](?:JR|CR|JM|R|M)?)0*(\d+)a*\b [^.]{2,60}?\.{3,}\s*(.{1,40}?)(?=\s+[HS](?:JR|CR|JM|R|M)?\d{3,4}a*\b|$)", s):
            bid = f"ID-{year}-{m.group(1)}{m.group(2)}"
            if bid in want and bid not in out:
                st = m.group(3).strip()
                out[bid] = ("Yes", st) if re.search(r"\b(LAW|ADOPTED)\b", st) else ("No", st)
    return out


def kentucky(want):
    """Legislative Record pages (ky_record_cache/items/<session>_<bill>.html) carry each measure's history: 'signed by
    Governor', 'became law without Governor's signature', 'filed ... Secretary of State', 'Acts ch.' = passed; simple
    resolutions (HR, SR) also when 'adopted'. Otherwise not passed."""
    out = {}
    for f in glob.glob("ky_record_cache/items/*.html"):
        m0 = re.match(r"(\d\d[a-z]{2})_([A-Z]+\d+)\.html$", os.path.basename(f))
        bid = f"KY-{m0.group(1).upper()}-{m0.group(2)}" if m0 else ""
        if bid not in want:
            continue
        s = plain(f)
        if re.search(r"signed by (the )?Governor|became law without|Secretary of State|Acts,? ch\.|veto overridden", s, re.I) \
                and not re.search(r"vetoed(?!.*overrid)", s, re.I):
            out[bid] = ("Yes", "history: signed / filed")
        elif re.match(r"[HS]R\d", m0.group(2)) and re.search(r"\badopted\b", s, re.I):
            out[bid] = ("Yes", "resolution adopted")
        else:
            out[bid] = ("No", "history: not signed or adopted")
    return out


def new_mexico(want):
    """Legislation pages (nm_nmlegis_cache/bills/<session>_<bill>.html): a chapter number ('Ch. 59', 'SGND BY GOV ... Ch.')
    = law; memorials and resolutions passed by their house(s) ('PASSED/H') count as adopted. Otherwise not passed."""
    out = {}
    for f in glob.glob("nm_nmlegis_cache/bills/*.html"):
        m0 = re.match(r"(\w+?)_([A-Z]+\d+)\.html$", os.path.basename(f))
        bid = f"NM-{m0.group(1)}-{m0.group(2)}" if m0 else ""
        if bid not in want:
            continue
        s = plain(f)
        if re.search(r"\bCh\.\s?\d+|SGND BY GOV", s):
            out[bid] = ("Yes", "chaptered / signed by the Governor")
        elif re.match(r"[HS](M|R)\d", m0.group(2)) and "PASSED/" in s:
            out[bid] = ("Yes", "memorial/resolution passed")
        else:
            out[bid] = ("No", "no chapter")
    return out


def ohio(want):
    """SOLAR version lists (oh_solar_cache/versions/general_assembly_<ga>_<bill>.json): a governor's signing date or
    effective date on any version = law; a simple resolution with an 'As Adopted' version, or a concurrent/joint
    resolution with an 'As Enrolled' version, was adopted. No saved version list = Unknown."""
    import json
    out = {}
    for f in glob.glob("oh_solar_cache/versions/general_assembly_*.json"):
        m0 = re.match(r"general_assembly_(\d+)_([a-z]+)(\d+)\.json$", os.path.basename(f))
        if not m0:
            continue
        bid = f"OH-GA{m0.group(1)}-{m0.group(2).upper()}{m0.group(3)}"
        if bid not in want:
            continue
        try:
            v = json.load(open(f))
        except Exception:
            continue
        names = {x.get("version") or "" for x in v}
        if any(x.get("governor_signed_date") or x.get("effective_date") for x in v):
            out[bid] = ("Yes", "signed by the Governor")
        elif m0.group(2) in ("hr", "sr") and "As Adopted" in names:
            out[bid] = ("Yes", "resolution adopted")
        elif m0.group(2) in ("hcr", "scr", "hjr", "sjr") and "As Enrolled" in names:
            out[bid] = ("Yes", "resolution adopted by both houses")
        else:
            out[bid] = ("No", "last version: " + sorted(names)[-1] if names else "no versions")
    return out


def connecticut(want):
    """2001-2009: the Connecticut General Assembly's bill_info.csv (ct_cga_cache/ftp/<year>bill_info.csv) gives the public
    or special act number (pasa_num) of every bill that became law. 1993-2000 bills: no saved status (Unknown)."""
    out = {}
    for f in glob.glob("ct_cga_cache/ftp/*bill_info.csv"):
        year = os.path.basename(f)[:4]
        for r in csv.DictReader(open(f, newline="", encoding="utf-8", errors="replace")):
            m = re.match(r"([A-Z]+)0*(\d+)$", (r.get("bill_num") or "").strip())
            if not m:
                continue
            for bid in (f"CT-{year}-{m.group(1)}{int(m.group(2)):05d}", f"CT-{year}-{m.group(1)}{m.group(2)}"):
                if bid in want and bid not in out:
                    pa = (r.get("pasa_num") or "").strip()
                    out[bid] = ("Yes", f"{(r.get('pasa_type') or '').strip()} act {pa}") if pa not in ("", "0", "NULL") else ("No", "no act number")
    return out


def by_version(want, versions_yes, versions_no, note):
    """Sources whose single saved text is the bill's final state (New Hampshire's archived files are 'FINAL VERSION' when
    the bill passed, the introduced or amended text when it died; Colorado's Session Laws hold only enacted acts)."""
    return {b: ("Yes", note) if v in versions_yes else ("No", note) for b, v in want.items() if v in versions_yes | versions_no}


EXTRACTORS = [("CA", california), ("PA", pennsylvania), ("NJ", new_jersey), ("FL", florida), ("TX", texas), ("LA", louisiana), ("MS", mississippi), ("MD", maryland), ("WV", west_virginia),
              ("AK", alaska), ("ID", idaho), ("KY", kentucky), ("NM", new_mexico), ("OH", ohio), ("CT", connecticut)]

NOT_AVAILABLE = {}


def main():
    t4 = table4()
    want = set(t4)
    res = {}
    for st, fn in EXTRACTORS:
        got = fn({b for b in want if t4[b][0] == st})
        res.update({b: v + (t4[b][1],) for b, v in got.items()})
    nh = {b: t4[b][2] for b in want if t4[b][0] == "NH"}
    co = {b: t4[b][2] for b in want if t4[b][1] == "Colorado General Assembly (Internet Archive)"}
    for got in (by_version(nh, {"Enrolled"}, {"Introduced", "Amended"}, "final archived file: enrolled (passed) or not"),
                by_version(co, {"Chaptered"}, set(), "Session Laws chapter")):
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
