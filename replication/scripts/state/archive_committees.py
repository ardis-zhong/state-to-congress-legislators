#!/usr/bin/env python3
"""
Committee referrals for Table 4's state-archive rows (bills from the legislatures' own records, before LegiScan),
read from files already saved by the state scripts (no new requests). One extractor per source; a source whose saved
files hold no referral record is listed in NOT_AVAILABLE below.

Output: archive_bill_committees.csv (BillId = Table 4 bill_id, Order, Chamber, Committee, Date, Source), one row per
bill and committee in referral order.

USAGE (from the repo root):  python3 replication/scripts/state/archive_committees.py
"""

import collections
import csv
import os
import re
import zipfile

OUT = "archive_bill_committees.csv"


def table4_ids():
    ids = set()
    import pandas as pd
    t = pd.read_csv("datasets/csv/table4_state_bill_text.csv", usecols=["bill_id", "text_source"], dtype=str)
    ids |= set(t.loc[t.text_source != "LegiScan", "bill_id"])
    return ids


# ---------------------------------------------------------------------------------------------- California
def ca_rows(z, name):
    with z.open(name) as f:
        for line in f:
            yield [c.strip("`") for c in line.decode("utf-8", "replace").rstrip("\r\n").split("\t")]


COM = re.compile(r"\bComs?\.\s+on\s+")
COM_END = re.compile(r"\s+(?:for|with|pursuant|per|Re-?referred|Read|From|In|To|Ordered|Hearing|Set|May|Do|Withdrawn)\b"
                     r"|\(|\.\s+[A-Z][a-z]|\.?\s*$")


def ca_abbrevs(text):
    """'Referred to Coms. on ED. and APPR.' -> ['ED', 'APPR']; 'To Com. on RLS. for assignment.' -> ['RLS'];
    'Re-referred to Com. on B. & P.' -> ['B.&P'] (California joins separate committees with 'and' and uses '&' inside
    an abbreviation)."""
    out = []
    for m in COM.finditer(text):
        seg = text[m.end():]
        seg = seg[:COM_END.search(seg).start()]
        for part in re.split(r"\s+and\s+", seg):
            ab = re.sub(r"\s+", "", part).strip(".,")
            if ab and re.fullmatch(r"[A-Z][A-Z&.,]*", ab):
                out.append(ab)
    return out


STOPW = {"and", "of", "the", "on", "for"}


def by_initials(ab, coms):
    """The one committee of the session and chamber whose words the abbreviation's parts begin ('H.&H.S' ->
    'Health and Human Services', 'ENV.QUAL' -> 'Environmental Quality'); None unless exactly one matches."""
    parts = [p for p in re.split(r"[.,&]+", ab.lower()) if p]
    hits = []
    for name in coms:
        words = [w for w in re.findall(r"[a-z]+", name.lower()) if w not in STOPW]
        if len(words) == len(parts) and all(w.startswith(p) for p, w in zip(parts, words)):
            hits.append(name)
    return hits[0] if len(hits) == 1 else None


def california(want):
    """Legislature's pubinfo archives 1999-2011 (ca_pubinfo_cache/), BILL_HISTORY_TBL. From 2007 each referral action
    ('To Com. on ED.') carries the committee's location code (CS44, named in LOCATION_CODE_TBL); before 2007 only the
    action text names it, by abbreviation, so the abbreviations are named from the coded 2007-2011 rows (per chamber),
    and the chamber is followed through the bill's history ('In Senate.', 'passed, and to Senate'). Floor locations
    (Engrossing, Second Reading) are not committees and are left out."""
    hist, names, abbr, session_coms = {}, {}, {}, {}
    for year in range(1999, 2012, 2):
        path = os.path.join("ca_pubinfo_cache", f"pubinfo_{year}.zip")
        if not os.path.exists(path):
            continue
        z = zipfile.ZipFile(path)
        for r in ca_rows(z, "LOCATION_CODE_TBL.dat"):
            if len(r) > 5 and re.match(r"C[XS]\d+$", r[1]):
                names[r[1]] = re.sub(r"^(Asm|Sen)\s+", "", r[4])
                session_coms.setdefault((str(year), "Assembly" if r[1].startswith("CX") else "Senate"), set()).add(
                    re.sub(r"^(Asm|Sen)\s+", "", r[4]))
        for r in ca_rows(z, "BILL_HISTORY_TBL.dat"):
            if len(r) < 12:
                continue
            pid = r[0]
            bid = f"CA-{pid[:4]}-{pid[9:]}" + (f"X{pid[8]}" if pid[8] != "0" else "")
            code = r[11] if re.match(r"C[XS]\d+$", r[11] or "") else ""
            abs_ = ca_abbrevs(r[3])
            if code and len(abs_) == 1:
                abbr.setdefault(("Assembly" if code.startswith("CX") else "Senate", abs_[0]), {}).setdefault(code, 0)
                abbr[("Assembly" if code.startswith("CX") else "Senate", abs_[0])][code] += 1
            if bid in want:
                hist.setdefault(bid, []).append((r[2][:10], int(r[1]) if r[1].isdigit() else 0, r[3], code))
    # abbreviation -> committee name: the code most often seen with it in that chamber
    abname = {k: names.get(max(v, key=v.get), "") for k, v in abbr.items()}
    out = []
    for bid, acts in hist.items():
        typ = re.match(r"CA-\d+-([A-Z]+)", bid).group(1)
        house = "Assembly" if typ.startswith("A") or typ == "HR" else "Senate"   # HR = Assembly 'House Resolution'
        seen = []
        for date, _, text, code in sorted(acts, key=lambda a: (a[0], -a[1])):
            if re.search(r"\bIn Senate\b|passed,? and to Senate|to Senate\.", text):
                house = "Senate"
            elif re.search(r"\bIn Assembly\b|passed,? and to Assembly|to Assembly\.", text):
                house = "Assembly"
            if not re.search(r"\b(referred|re-referred|re-refer|To Coms?\.)", text, re.I):
                continue
            if code:
                ch, coms = ("Assembly" if code.startswith("CX") else "Senate"), [names.get(code, code)]
            else:
                ch = house
                sess = str(int(bid.split("-")[1]) - (0 if int(bid.split("-")[1]) % 2 else 1))
                coms = [abname.get((ch, a)) or by_initials(a, session_coms.get((sess, ch), set())) or a
                        for a in ca_abbrevs(text)]
            for com in coms:
                if (ch, com) not in [(c, n) for c, n, _ in seen]:
                    seen.append((ch, com, date))
        for i, (ch, com, date) in enumerate(seen, 1):
            out.append([bid, i, ch, com, date, "California Legislature bill history"])
    unknown = sorted({k for k in abbr} - set(abname))
    return out


# ---------------------------------------------------------------------------------------------- Pennsylvania
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def iso(text):
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s*(\d{1,2}),\s*(\d{4})", text or "")
    return f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}" if m and m.group(1).lower() in MONTHS else ""


def lines_of(path):
    import html as H
    s = H.unescape(re.sub(r"<[^>]+>", "\n", open(path, encoding="utf-8", errors="replace").read()))
    return [re.sub(r"\s+", " ", l).strip() for l in s.split("\n") if l.strip()]


def smart_title(name):
    small = {"and", "of", "the", "on", "for", "in", "to"}
    words = name.lower().split()
    return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def pennsylvania(want):
    """palegis.us bill pages saved by pa_palegis_bills.py (pa_palegis_cache/bills/<session>_<bill>.html): the bill's
    history lists 'Referred to HIGHWAY SAFETY, July 23, 1969' / 'Re-referred to APPROPRIATIONS, ...' under 'In the
    House' / 'In the Senate' headings."""
    out = []
    for f in os.listdir("pa_palegis_cache/bills"):
        m = re.match(r"(\d{4})_([A-Z]+\d+)\.html$", f)
        if not m:
            continue
        bid = f"PA-{m.group(1)}-{m.group(2)}"
        if bid not in want:
            continue
        house = "House" if m.group(2).startswith("H") else "Senate"
        seen = []
        lines = lines_of(os.path.join("pa_palegis_cache/bills", f))
        origin, in_history = house, False
        for l in lines:
            h = re.fullmatch(r"In the (House|Senate)", l)
            if h:
                house = h.group(1)
                continue
            r = re.match(r"(?:Re-?referred|Referred|Recommitted) to ([A-Z][A-Z &,.'/()-]+?),\s+([A-Z][a-z]{2}.*\d{4})", l)
            if r and not in_history:       # the dated history starts in the bill's own chamber (headings above are milestones)
                in_history, house = True, origin
            if r:
                name = r.group(1).strip()
                ch, date = house, iso(r.group(2))
                # the page prints the history twice; the second copy starts without a chamber heading
                if (name, date) in [(n, d) for _, n, d in seen]:
                    continue
                if (ch, name) not in [(c, n) for c, n, _ in seen]:
                    seen.append((ch, name, date))
        for i, (ch, com, date) in enumerate(seen, 1):
            out.append([bid, i, ch, smart_title(com), date, "Pennsylvania General Assembly bill history"])
    return out


# ---------------------------------------------------------------------------------------------- New Jersey
def new_jersey(want):
    """The Legislature's bill-tracking databases (pub.njleg.gov/leg-databases/<session>data/DBASE.ZIP, saved under
    nj_legdb_cache/<9697|9899|2000..2010>/): BILLHIST.DBF actions carry 'REF <code>' for each referral ('INT 1RA REF
    ASI', 'REP/ACA REF AAP'), named in COMMITT.DBF (subcommittee and special codes left out)."""
    import io
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import nj_legdb_bills as L
    out = []
    for code, year in [("9697", 1996), ("9899", 1998)] + [(str(y), y) for y in range(2000, 2011, 2)]:
        path = os.path.join("nj_legdb_cache", code, "DBASE.ZIP")
        if not os.path.exists(path):
            continue
        z = zipfile.ZipFile(path)
        tab = lambda t: L.dbf_rows(z.read(next(n for n in z.namelist() if n.upper() == f"{t}.DBF")))
        coms = {r["CODE"]: r for r in tab("COMMITT")}
        refs = {}
        for r in tab("BILLHIST"):
            bid = f"NJ-{year}-{r['BILLTYPE']}{L.num(r['BILLNUMBER'])}"
            if bid not in want:
                continue
            for c in re.findall(r"\bREF\s+([A-Z]{3})\b", r["ACTION"]):
                refs.setdefault(bid, []).append((r["DATEACTION"], float(r["SEQUENCE"] or 0), c))
        for bid, acts in refs.items():
            seen = []
            for d, _, c in sorted(acts):
                info = coms.get(c)
                if not info or "sub" in (info.get("DESCRIPTIO") or "").lower() or info.get("TYPE", "").startswith("Special"):
                    continue
                if c not in [x for x, _ in seen]:
                    seen.append((c, f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""))
            for i, (c, d) in enumerate(seen, 1):
                info = coms[c]
                ch = {"A": "General Assembly", "S": "Senate"}.get(info.get("HOUSE") or c[0], "")
                out.append([bid, i, ch, " ".join(info["DESCRIPTIO"].split()), d, "New Jersey Legislature bill history"])
    return out


# ---------------------------------------------------------------------------------------------- Florida 1995-1997
def florida_1995(want):
    """Online Sunshine bill pages 1995-1997 as kept by the Internet Archive (fl_wayback_cache/pages/<year>/<H9089>.html):
    the history prints '04/11/95 HOUSE  Referred to Rules & Calendar -HJ 00449' (several committees separated by ';',
    entries wrapping onto the next line). Florida 1998-2009 rows: the saved files are bill lists and texts only."""
    out = []
    base = "fl_wayback_cache/pages"
    for year in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        for f in os.listdir(os.path.join(base, year)):
            m = re.match(r"([HS])(\d+)\.html$", f)
            if not m:
                continue
            bid = f"FL-{year}-{m.group(1)}B{m.group(2)}"
            if bid not in want:
                continue
            entries, cur = [], None
            for l in lines_of(os.path.join(base, year, f)):
                e = re.match(r"(\d{2})/(\d{2})/(\d{2})\s+(HOUSE|SENATE)\s+(.*)$", l)
                if e:
                    cur = [e, e.group(5)]
                    entries.append(cur)
                elif cur is not None and not re.match(r"(BILL TEXT|STATUTE CITATIONS|SUBJECT INDEX)", l):
                    cur[1] += " " + l
                else:
                    cur = None
            seen = []
            for e, text in entries:
                for r in re.finditer(r"(?:Re-?referred|Referred) to ([^-]+?)(?:\s+-[HS]J\b|;\s*(?:Read|Placed|Withdrawn|Adopted)|$)",
                                     text, re.I):
                    for com in re.split(r";\s*", r.group(1)):
                        com = com.strip(" .;")
                        if not com or re.search(r"(?i)calendar$|^the", com) and "Rules" not in com:
                            continue
                        ch = e.group(4).title()
                        if (ch, com) not in [(c, n) for c, n, _ in seen]:
                            yy = int(e.group(3))
                            seen.append((ch, com, f"{1900 + yy if yy > 50 else 2000 + yy}-{e.group(1)}-{e.group(2)}"))
            for i, (ch, com, d) in enumerate(seen, 1):
                out.append([bid, i, ch, com.replace(" & ", " and "), d, "Florida Legislature bill history (Internet Archive)"])
    return out


# ---------------------------------------------------------------------------------------------- printed referrals
# States whose introduced bill prints its first referral near the top (the committee(s) the bill was sent to when it was
# introduced, in its own chamber). Pattern per Table 4 text_source; group 1 = committee text; SPLIT separates several.
END = r"(?=\s*(?:-{2,}|─|_{3,}|AN ACT|A BILL|A RESOLUTION|CONCURRENT|JOINT|SUMMARY|LCO|Introduced|It is enacted|WHEREAS|RESOLVED|ANALYSIS|\.\s|\.?$))"
PRINTED = {
    # New York prints the committee path on later printings too ('-- reported and referred to the Committee on Codes');
    # Senate bills: 'when printed to be committed to the Committee on Finance'
    "New York State Assembly": r"(?:referred|recommitted|re-referred|committed) to the Committee on (.+?)" + END,
    "Virginia General Assembly": r"Referred to (?:the )?Committee (?:on|for) (.+?)" + END,
    "Michigan Legislature": r"and referred to the Committee on (.+?)\.",
    "North Carolina General Assembly": r"Referred to:\s*(.+?)" + END,
    "Maryland General Assembly": r"Assigned to:\s*(.+?)" + END,
    "Washington Legislature": r"Referred to Committee on (.+?)\.(?:\s|$)",
    "West Virginia Legislature": r"referred to the Committee on (.+?)\.?\]",
    "Wisconsin Legislature": r"Referred to (?:joint )?Committee on (.+?)\.(?:\s|$)",
    "Nevada Legislature": r"Referred to Committee on (.+?)" + END,
    "New Hampshire General Court (Internet Archive)": r"REFERRED TO:\s*(.+?)" + END,
    "New Hampshire General Court": r"REFERRED TO:\s*(.+?)" + END,
    "Rhode Island General Assembly": r"Referred To:\s*(?:House|Senate)?\s*Committee on (.+?)" + END,
    "Connecticut General Assembly": r"Referred to Committee on ([A-Z][A-Z ,&'/-]+?)" + END,
    "Mississippi Legislature": r"By: .{0,400}? To: (.+?)(?=\s+(?:SENATE|HOUSE) (?:BILL|CONCURRENT|RESOLUTION|JOINT)|\s+\(As Sent)",
}
SPLIT = re.compile(r"\s*;?\s*(?:and\s+)?then\s+(?:to\s+)?(?:the\s+Committee\s+on\s+)?|\s*;\s*")
LOWER = {"NY": "Assembly", "WI": "Assembly", "NV": "Assembly", "VA": "House of Delegates", "WV": "House of Delegates",
         "MD": "House of Delegates"}


def printed(want):
    import pandas as pd
    out = []
    pats = {k: re.compile(v) for k, v in PRINTED.items()}
    for ch in pd.read_csv("datasets/csv/table4_state_bill_text.csv", usecols=["bill_id", "state", "text_source", "bill_text"],
                          dtype=str, chunksize=5000):
        ch = ch[ch.text_source.isin(list(pats))]
        for bid, st, src, text in zip(ch.bill_id, ch.state, ch.text_source, ch.bill_text.fillna("")):
            if bid not in want:
                continue
            head = " ".join(text[:3000].split())
            ms = list(pats[src].finditer(head))
            if not ms:
                continue
            num = bid.split("-")[-1]
            lower = num[0] in "AH" and not (st == "NY" and num.startswith("S"))
            if st == "NY":
                lower = num.startswith("A")
            chamber = LOWER.get(st, "House") if lower else "Senate"
            coms = []
            for m in ms:
                for c in SPLIT.split(m.group(1)):
                    c = re.sub(r"^the\s+(?=Judiciary$)", "", c.strip(" .,;"))     # WV 'the Judiciary'
                    c = re.sub(r"-\s+", "", c) if re.search(r"\w-\s+\w", c) else c   # 'recom- mitted' line breaks
                    if c and c not in coms and len(c) <= 90 and not re.search(r"(?i)^(read and passed|passed|adopted|and)$", c):
                        coms.append(c)
            for i, com in enumerate(coms, 1):
                out.append([bid, i, chamber, smart_title(com) if com.isupper() else com, "",
                            f"{src} (printed on the bill)"])
    return ms_clean(out)


def ms_clean(rows):
    """Mississippi prints the sponsor list in two columns, so its continuation can follow 'To: Rules' ('Rules Dearing,
    Frazier, Horhn'). Committee names printed cleanly on other bills are the reference: a run-on value is cut to the
    longest of them it starts with, or dropped."""
    ms = [r for r in rows if r[0].startswith("MS-")]
    surname_tail = re.compile(r"\(\d+(?:st|nd|rd|th)\)|,\s+[A-Z][a-z'-]+,\s+[A-Z]")
    freq = collections.Counter(r[3] for r in ms)
    clean = {c for c, n in freq.items() if n >= 3 and not surname_tail.search(c)}
    out, k = [], {}
    for r in rows:
        if not r[0].startswith("MS-") or r[3] in clean:
            out.append(r)
            continue
        hits = [c for c in clean if r[3].startswith(c + " ") or r[3].startswith(c + ",")]
        if hits:
            r = r[:3] + [max(hits, key=len)] + r[4:]
            if (r[0], r[3]) not in {(x[0], x[3]) for x in out[-5:]}:
                out.append(r)
    # renumber Order per bill
    seen = collections.defaultdict(int)
    for r in out:
        seen[r[0]] += 1
        r[1] = seen[r[0]]
    return out


# ---------------------------------------------------------------------------------------------- Illinois
def illinois(want):
    """Bill status saved by il_ilga_bills.py (il_ilga_cache/status/<GA>_<bill>.html|.xml). 1997-2002 Legisnet pages:
    '97-02-27 H ASSIGNED TO COMMITTEE HUMAN SERVS' (the Legislature's abbreviations, kept as printed); 2003-2008 Bill
    Status XML: <statusdate>, <chamber>, <action>Assigned to Registration and Regulation Committee</action>. Rules /
    Assignments referrals (the gatekeeping step before assignment) are kept, as recorded."""
    out = []
    base = "il_ilga_cache/status"
    for f in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        m = re.match(r"(\d+)_([A-Z]+\d+)\.(html|xml)$", f)
        if not m:
            continue
        bid = f"IL-GA{m.group(1)}-{m.group(2)}"
        if bid not in want:
            continue
        raw = open(os.path.join(base, f), encoding="utf-8", errors="replace").read()
        steps = []
        if m.group(3) == "xml":
            for d, ch, act in re.findall(r"<statusdate>([^<]*)</statusdate>\s*<chamber>([^<]*)</chamber>\s*<action>([^<]*)</action>", raw):
                r = re.match(r"(?:Referred|Re-referred|Assigned|Re-assigned)\s+to\s+(?:the\s+)?(.+?)(?:\s+Committee)?\s*$", act.strip())
                if r and not re.search(r"(?i)amendment|motion", act):
                    mm, dd, yy = (d.split("/") + ["", "", ""])[:3]
                    import html as H
                    steps.append((ch.strip(), H.unescape(r.group(1).strip()), f"{yy}-{int(mm):02d}-{int(dd):02d}" if yy else ""))
        else:
            for l in lines_of(os.path.join(base, f)):
                r = re.match(r"(\d{2})-(\d{2})-(\d{2})\s+([HS])\s+(?:ASSIGNED TO COMMITTEE|RE-ASSIGNED TO COMMITTEE|REFERRED TO "
                             r"(?:HOUSE |SENATE )?(?:RULES COMMITTEE|COMMITTEE ON)?|RE-COMMITTED TO COMMITTEE|RE-REFERRED TO "
                             r"(?:RULES COMMITTEE)?)\s*(.*)$", l)
                if r and not re.search(r"(?i)amendment|motion", l):
                    yy = int(r.group(1))
                    com = r.group(5).strip() or "RULES"
                    if re.match(r"RULES\b", com):
                        com = "RULES"
                    steps.append(("House" if r.group(4) == "H" else "Senate", com,
                                  f"{1900 + yy if yy > 50 else 2000 + yy}-{r.group(2)}-{r.group(3)}"))
        seen = []
        for ch, com, d in steps:
            if (ch, com.lower()) not in [(c, n.lower()) for c, n, _ in seen]:
                seen.append((ch, com, d))
        for i, (ch, com, d) in enumerate(seen, 1):
            out.append([bid, i, ch, smart_title(com) if com.isupper() else com, d, "Illinois General Assembly bill status"])
    return out


# ---------------------------------------------------------------------------------------------- Louisiana
def louisiana(want):
    """BillInfo pages saved by la_legis_bills.py (la_legis_cache/info/<id>.html; ids in la_authored_bills.csv): the
    history (latest first) reads '... referred to the Committee on Education.'; 'Received in the Senate' moves the bill."""
    ids = {}
    if os.path.exists("la_authored_bills.csv"):
        with open("la_authored_bills.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                ids[r["bill_info_id"]] = f"LA-{r['session']}-{r['bill']}"
    out = []
    for i, bid in ids.items():
        path = os.path.join("la_legis_cache/info", f"{i}.html")
        if bid not in want or not os.path.exists(path):
            continue
        house = "House" if bid.split("-")[-1].startswith("H") else "Senate"
        seen = []
        for l in reversed(lines_of(path)):
            if re.search(r"(?i)received in the senate", l):
                house = "Senate"
            elif re.search(r"(?i)received in the house", l):
                house = "House"
            for r in re.finditer(r"(?i)referred to the committee on ([^.;]+)", l):
                com = r.group(1).strip()
                if (house, com.lower()) not in [(c, n.lower()) for c, n in seen]:
                    seen.append((house, com))
        for k, (ch, com) in enumerate(seen, 1):
            out.append([bid, k, ch, smart_title(com) if com.isupper() else com[:1].upper() + com[1:], "",
                        "Louisiana Legislature bill history"])
    return out


# ---------------------------------------------------------------------------------------------- Minnesota
def minnesota(want):
    """Revisor's bill status pages saved by mn_revisor_bills.py (mn_revisor_cache/status/<legislature>_<bill>.html):
    chronological actions 'House' / '03/13/1995' / 'First reading, referred to' / 'Local Government and Metropolitan
    Affairs' (the committee on the next line; 're-refer to' likewise)."""
    out = []
    base = "mn_revisor_cache/status"
    for f in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        m = re.match(r"(\d+)_([A-Z]+\d+)\.html$", f)
        if not m:
            continue
        bid = f"MN-{m.group(1)}-{m.group(2)}"
        if bid not in want:
            continue
        L = lines_of(os.path.join(base, f))
        ch, date, seen = "", "", []
        for k, l in enumerate(L):
            if l in ("House", "Senate"):
                ch = l
            d = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", l)
            if d:
                date = f"{d.group(3)}-{d.group(1)}-{d.group(2)}"
            if re.search(r"(?i)(referred|re-?refer|re-?referred) to$", l) and k + 1 < len(L):
                com = L[k + 1].strip()
                if com and (ch, com) not in [(c, n) for c, n, _ in seen] and len(com) < 90:
                    seen.append((ch, com, date))
        for i, (c, com, d) in enumerate(seen, 1):
            out.append([bid, i, c, com, d, "Minnesota Revisor of Statutes bill status"])
    return out


# ---------------------------------------------------------------------------------------------- Oregon 1997-2005
OR_HEAD = re.compile(r"\b(HB|SB|HJR|SJR|HCR|SCR|HJM|SJM|HR|SR|HM|SM)\s+(\d{3,4})\s+(?=By\b|--|\()")


def oregon(want):
    """Measure Histories kept by the Internet Archive (or_wayback_cache/histories/<yy>reg_hsemh|senmh_*.txt|html): each
    measure's entry reads '1-30(H) First reading. Referred to Speaker's desk. 2-1 Referred to Rules, Redistricting and
    Public Affairs.'; dates marked (H)/(S) give the chamber. Desk referrals are not committees."""
    import html as H
    out, seen_bills = [], set()
    base = "or_wayback_cache/histories"
    for f in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        m = re.match(r"(\d{2})reg_", f)
        if not m:
            continue
        year = 1900 + int(m.group(1)) if int(m.group(1)) > 50 else 2000 + int(m.group(1))
        text = open(os.path.join(base, f), encoding="utf-8", errors="replace").read()
        if f.endswith(".html"):
            text = H.unescape(re.sub(r"<[^>]+>", " ", text))
        text = " ".join(text.split())
        heads = list(OR_HEAD.finditer(text))
        for k, h in enumerate(heads):
            bid = f"OR-{year}R1-{h.group(1)}{h.group(2)}"
            if bid not in want or bid in seen_bills:
                continue
            block = text[h.end():heads[k + 1].start() if k + 1 < len(heads) else len(text)]
            ch, seen = ("House" if h.group(1).startswith("H") else "Senate"), []
            for tok in re.finditer(r"(\d{1,2}-\d{1,2})\((H|S)\)|(?:Referred|Subsequent referral|referral) to ([^.;]+?)(?:\.|;| by order|$)", block):
                if tok.group(2):
                    ch = "House" if tok.group(2) == "H" else "Senate"
                    continue
                for com in re.split(r",?\s+(?:then|with subsequent referral to|and then to|and subsequent referral to)\s+", tok.group(3)):
                    com = com.strip(" ,")
                    if com and not re.search(r"(?i)desk|^the (house|senate)$", com) and (ch, com) not in seen:
                        seen.append((ch, com))
            if seen:
                seen_bills.add(bid)
            for i, (c, com) in enumerate(seen, 1):
                out.append([bid, i, c, com, "", "Oregon Legislature measure history (Internet Archive)"])
    return out


# ---------------------------------------------------------------------------------------------- Kentucky 1998-2009
def kentucky(want):
    """Legislative Record bill pages saved by ky_record_bills.py (ky_record_cache/items/<session>_<bill>.html): the
    history reads 'Jan 4-introduced in House; to Tourism Development and Energy (H)', 'Feb 25-to Agriculture and
    Natural Resources (S)'. Calendar and floor steps are not committees."""
    out = []
    base = "ky_record_cache/items"
    for f in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        m = re.match(r"(\w+?)_([A-Z]+\d+)\.html$", f)
        if not m:
            continue
        bid = f"KY-{m.group(1).upper()}-{m.group(2)}"
        if bid not in want:
            continue
        seen = []
        for l in lines_of(os.path.join(base, f)):
            for r in re.finditer(r"\bto ([A-Z][A-Za-z ,&.'/-]+?) \((H|S)\)", l):
                com = r.group(1).strip()
                if re.search(r"(?i)calendar|orders of the day|governor|^(house|senate)$|clerk", com):
                    continue
                ch = "House" if r.group(2) == "H" else "Senate"
                if (ch, com) not in seen:
                    seen.append((ch, com))
        for i, (c, com) in enumerate(seen, 1):
            out.append([bid, i, c, com, "", "Kentucky Legislative Record bill history"])
    return out


EXTRACTORS = [("California", california), ("Pennsylvania", pennsylvania), ("New Jersey", new_jersey),
              ("Florida", florida_1995), ("Printed referrals", printed), ("Illinois", illinois),
              ("Louisiana", louisiana), ("Minnesota", minnesota), ("Oregon", oregon), ("Kentucky", kentucky)]
# Archive sources whose saved files hold no referral record (blank `committees` in Table 4; the legislatures' sites or
# archives would have to be read again for them):
NOT_AVAILABLE = {
    "California 1989-1998": "pubinfo 1989-1997 has no history table; the 1993-98 bill history pages were not saved",
    "Florida 1998-2009": "only the bill lists and filed texts were saved",
    "Florida 1995-1997 (part)": "pages for about half the bills were not saved by the first version of the scan",
    "Texas": "the FTP author reports give only each bill's last action; the per-bill histories were not saved",
    "Hawaii": "introduction lists and texts only",
    "Ohio": "SOLAR legislation lists and versions only",
    "Tennessee, Georgia, Arizona, Massachusetts, Oklahoma, Colorado (Internet Archive)": "bill texts only",
    "South Carolina, Arkansas, Missouri, Iowa, Alaska, South Dakota, North Dakota, New Mexico, Nebraska, Wyoming, Idaho":
        "bill texts and sponsor lists only",
    "Oregon 2007-2009": "OLIS documents only",
}


def main():
    want = table4_ids()
    rows = []
    for st, fn in EXTRACTORS:
        got = fn(want)
        print(f"  {st}: {len(got)} committee rows for {len({r[0] for r in got})} bills", flush=True)
        rows += got
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["BillId", "Order", "Chamber", "Committee", "Date", "Source"])
        w.writerows(rows)
    print(f"Wrote {OUT}: {len(rows)} rows for {len({r[0] for r in rows})} of {len(want)} archive bills")


if __name__ == "__main__":
    main()
