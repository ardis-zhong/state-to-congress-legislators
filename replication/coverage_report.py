"""
coverage_report.py -- how much of each person's service the built tables cover, and where the gaps are.

Reads the built tables in datasets/csv/ and the congress-legislators term records (legislators-current.json,
legislators-historical.json at the repo root, local) and writes documentation/coverage_report.md.

Units:
  - State service: person-years from Table 1's state_leg_years (ranges counted inclusively, 'present' = the
    current year), 1969 on. A person-year counts as covered when the person has a Table 4 row (state bill text)
    or a Table 3 state score in that year, from a session that names that year (bills prefiled in December
    carry the year before their session), or in the other year of the same two-year session (odd-even), since
    many legislatures number and print bills per biennium.
  - Federal service: person-Congresses from the term records (a Congress counts when a term overlaps it by at
    least 30 days), 91st Congress (1969) on. Covered = the person has at least one Table 7 item (sponsored
    bill or resolution), Table 5 row (text) or Table 3 federal score for that Congress. A Congress with no
    sponsored item can be genuinely empty (e.g. a member who served a few months), so Table 7/5 coverage below
    100% is not by itself missing data; replication checks found Congress.gov lists no bills for those
    person-Congresses.

USAGE (from the repo root, after build_tables.py):
    python3 replication/coverage_report.py
"""

import collections
import csv
import datetime
import json
import re

import pandas as pd

OUT = "documentation/coverage_report.md"
REASONS = "replication/data/reference/coverage_gap_reasons.csv"
NOW = datetime.date.today().year
FIRST_YEAR = 1969

# Why a state's person-years before LegiScan have no text, where the cause is known (see the state pilots in
# datasets/README.md). Years are the earliest year each state's own digital record reaches.
STATE_NOTES = {
    "California": "1969-1988 print only (HathiTrust scans; research dataset request pending); 1989-1992 enacted bills only",
    "Florida": "before 1998 print only (State Library holds printed bills)",
    "New York": "before 1999 not online (Assembly site starts 1999-2000)",
    "Texas": "before 1993 not online (FTP texts start 1993)",
    "Illinois": "before 1997 not online (Legisnet starts 1997; 1993-1996 Public Acts only)",
    "Ohio": "before 1997 not online (SOLAR starts 1997)",
    "Michigan": "before 1989 not online",
    "Georgia": "before 1995 not online; 1995-2008 only what the Internet Archive kept",
    "Virginia": "before 1994 not online (LIS starts 1994)",
    "Pennsylvania": "1970s Senate prime-sponsor records partly wrong on palegis.us (scanned texts used)",
    "New Jersey": "before 2000 not online",
    "Massachusetts": "before 2009 only what the Internet Archive kept (Senate sample; no sponsor index)",
    "Maryland": "before 1996 not online",
    "Minnesota": "before 1995 not online",
    "Wisconsin": "before 1995 not online",
    "Washington": "before 1991 not online",
    "North Carolina": "before 1989 not online",
    "Louisiana": "before 1997 not online; 2010 site author list incomplete (Richmond)",
    "Tennessee": "only what the Internet Archive kept (1997-2008); before 1997 not online; capitol.tn.gov blocks crawlers",
    "Missouri": "House not crawlable (robots.txt; webmaster contact listed); Senate from 1996",
    "Indiana": "pre-2010 archive blocks automated access (403); IGA API needs a key",
    "Arizona": "before 1999 not online; 1999-2009 only what the Internet Archive kept",
    "Colorado": "pre-2014 site behind a Cloudflare challenge; texts disallowed by robots.txt",
    "Kansas": "site behind Cloudflare; archive starts ~2011",
    "Oklahoma": "robots.txt disallows all crawling",
    "Alabama": "no pre-LegiScan archive found",
    "Montana": "site behind bot defense (F5)",
    "Vermont": "old site robots.txt disallows all",
    "Maine": "robots.txt blocks AI crawlers (respected)",
    "Connecticut": "by-legislator index blocked by robots.txt; introducer files from 2001",
    "Idaho": "almost all measures introduced by committees (no member named)",
    "Hawaii": "before 1999 House/Senate Journals only; 2012 status pages mostly not archived",
    "Kentucky": "before 1998 not online",
    "Iowa": "before 1995 not online",
    "Arkansas": "before 1991 not online",
    "South Carolina": "before 1985 not online; 1985-1990 enacted bills only",
    "New Hampshire": "before 1989 not online",
    "Nevada": "before 1997 not online",
    "Oregon": "before 1997 not online; special sessions not read",
    "Utah": "archive from 1997",
    "New Mexico": "before 1996 not online",
    "Mississippi": "before 1999 not online",
    "West Virginia": "before 1993 not online",
    "Alaska": "before 1993 not online",
    "Nebraska": "before 1999 not read",
    "North Dakota": "before 1997 not online",
    "South Dakota": "before 1997 not online",
    "Rhode Island": "before 1997 not online",
    "Wyoming": "before 2003 not online",
    "Delaware": "no pre-LegiScan archive checked",
}


def state_years(s):
    """Years in a Table 1 state_leg_years string ('1975-1979 (House); 1980-1986 (Senate)', 'April 1969-November
    1972', '2024-present'). Ranges inclusive; bare years added."""
    out = set()
    s = str(s).replace("–", "-").replace("—", "-")
    rng = r"((?:19|20)\d\d)\s*-\s*(?:[A-Za-z]+\.?\s+)?((?:19|20)\d\d|present|Present|current)"
    for a, b in re.findall(rng, s):
        out |= set(range(int(a), (NOW if not b[0].isdigit() else int(b)) + 1))
    for a in re.findall(r"(?:19|20)\d\d", re.sub(rng, " ", s)):
        out.add(int(a))
    return out


def congress_start(c):
    return datetime.date(1789 + 2 * (c - 1), 1, 3)


def congresses(terms):
    out = set()
    for t in terms:
        if t.get("type") not in ("rep", "sen"):
            continue
        a = datetime.date.fromisoformat(t["start"])
        b = min(datetime.date.fromisoformat(t["end"]), datetime.date.today())  # current terms: served so far
        for c in range(max(1, (a.year - 1789) // 2), (b.year - 1789) // 2 + 3):
            lo, hi = max(a, congress_start(c)), min(b, congress_start(c + 1))
            if (hi - lo).days >= 30:
                out.add(c)
    return out


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "–"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(lines)


def main():
    t1 = pd.read_csv("datasets/csv/table1_state_to_federal.csv", dtype=str, keep_default_na=False)
    t2 = pd.read_csv("datasets/csv/table2_demographics.csv", dtype=str, keep_default_na=False)
    t3 = pd.read_csv("datasets/csv/table3_effectiveness_scores.csv", dtype=str, keep_default_na=False)
    t4 = pd.read_csv("datasets/csv/table4_state_bill_text.csv", dtype=str, keep_default_na=False,
                     usecols=["bioguide_id", "year", "state", "state_session", "text_source"])
    t5 = pd.read_csv("datasets/csv/table5_federal_bill_text.csv", dtype=str, keep_default_na=False,
                     usecols=["bioguide_id", "congress"])
    t7 = pd.read_csv("datasets/csv/table7_federal_bill_topics.csv", dtype=str, keep_default_na=False,
                     usecols=["bioguide_id", "congress"])
    people = dict(zip(t1.bioguide_id, t1.name))
    home = dict(zip(t1.bioguide_id, t1.state))
    md = [f"# Coverage report\n\nGenerated {datetime.date.today().isoformat()} by `replication/coverage_report.py` "
          f"from the built tables ({len(t1):,} people). State service is counted in person-years from {FIRST_YEAR} "
          "(Table 1's state legislative years, ranges inclusive), federal service in person-Congresses from the "
          "91st (1969). A state person-year counts as covered when the person has a row dated that year, a row from a "
          "session that names that year, or a row in the other year of the same two-year session.\n"]

    # ---- state side
    sy = {b: {y for y in state_years(s) if y >= FIRST_YEAR} for b, s in zip(t1.bioguide_id, t1.state_leg_years)}
    text_years, sles_years = collections.defaultdict(set), collections.defaultdict(set)
    for b, y, ss in zip(t4.bioguide_id, t4.year, t4.state_session):
        if y.isdigit():
            text_years[b].add(int(y))
        # the years the session names too: bills prefiled in December carry the year before their session
        ys = [int(x) for x in re.findall(r"(?:19|20)\d\d", ss)]
        if ys:
            text_years[b] |= set(range(min(ys), max(ys) + 1))
    st3 = t3[t3.level == "State"]
    for b, s in zip(st3.bioguide_id, st3.session):
        ys = [int(x) for x in re.findall(r"(?:19|20)\d\d", s)]
        if ys:
            sles_years[b] |= set(range(min(ys), max(ys) + 1))

    def cov(have, b, y):
        g = have.get(b, ())
        return y in g or (y + 1 if y % 2 else y - 1) in g

    rows = [(b, home[b], y, cov(text_years, b, y), cov(sles_years, b, y)) for b, ys in sy.items() for y in ys]
    c = pd.DataFrame(rows, columns=["b", "state", "y", "text", "sles"])
    c["decade"] = c.y // 10 * 10
    md.append("## State service (Tables 3 and 4)\n")
    md.append(f"{c.b.nunique():,} people served in a state legislature in {FIRST_YEAR} or later: "
              f"{len(c):,} person-years.\n")
    dec = []
    for d, g in c.groupby("decade"):
        dec.append((f"{d}s" if d >= 1970 else "1969", f"{len(g):,}", f"{g.text.sum():,}", pct(g.text.sum(), len(g)),
                    f"{g.sles.sum():,}", pct(g.sles.sum(), len(g))))
    dec.append(("All", f"{len(c):,}", f"{c.text.sum():,}", pct(c.text.sum(), len(c)), f"{c.sles.sum():,}",
                pct(c.sles.sum(), len(c))))
    md.append(table(["Decade", "Person-years", "With bill text (T4)", "%", "With SLES score (T3)", "%"], dec))
    md.append("\nSLES (CEL's State Legislative Effectiveness Scores) begin by state between the late 1980s and "
              "the 2000s, so earlier state service has no score anywhere.\n")

    md.append("### Person-years without state bill text, by state\n")
    md.append("Person-years with no Table 4 row, by period, and the reason where known. 2009 on is LegiScan's "
              "window (plus the legislatures' own records for sessions LegiScan records without sponsor roles); "
              "a person-year there can also be empty because the person filed no bill as lead sponsor "
              "(leaders, members who joined mid-session).\n")
    srows = []
    for st, g in c.groupby("state"):
        miss = g[~g.text]
        if miss.empty:
            continue
        parts = [((miss.y < 1989).sum()), ((miss.y >= 1989) & (miss.y <= 2008)).sum(), (miss.y >= 2009).sum()]
        srows.append((st, g.b.nunique(), len(g), len(miss), *parts, STATE_NOTES.get(st, "")))
    srows.sort(key=lambda r: -r[3])
    md.append(table(["State", "People", "Person-years", "Without text", "1969-88", "1989-2008", "2009 on",
                     "Why (pre-LegiScan)"], srows))

    none = sorted(b for b in sy if sy[b] and not text_years.get(b))
    md.append(f"\n{len(none)} people with state service since {FIRST_YEAR} have no Table 4 row at all.\n")
    late = c[(~c.text) & (c.y >= 2009)]
    md.append(f"### Appendix: person-years from 2009 on without state bill text ({len(late)})\n")
    md.append("LegiScan covers every state from 2009 or 2010, so each of these needs a reason. Reviewed reasons come "
              f"from `{REASONS}`; a first or last year of service without a reviewed reason is marked as an edge year "
              "(most members join or leave in January, between sessions, and file no bill that year).\n")
    reasons = {}
    with open(REASONS, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            for y in state_years(r["years"]):
                reasons[(r["bioguide_id"], y)] = r["reason"]
    arows = []
    for (b, st), g in late.groupby(["b", "state"]):
        ys = sorted(g.y)
        spans, start = [], ys[0]
        for prev, y in zip(ys, ys[1:] + [None]):
            if y != prev + 1:
                spans.append(f"{start}" if start == prev else f"{start}-{prev}")
                start = y
        why = sorted({reasons.get((b, y), "") for y in ys} - {""})
        if not why:
            first, last = min(sy[b]), max(sy[b])
            why = ["edge year (first or last year of service; not individually checked)"
                   if all(y in (first, last) or (y - 1) not in sy[b] or (y + 1) not in sy[b] for y in ys)
                   else "not yet reviewed"]
        arows.append((people[b], b, st, ", ".join(spans), "; ".join(why)))
    md.append(table(["Name", "Bioguide ID", "State", "Years without text", "Reason"],
                    sorted(arows, key=lambda r: (r[2], r[0]))))

    # ---- federal side
    terms = {}
    for f in ("legislators-current.json", "legislators-historical.json"):
        for p in json.load(open(f)):
            terms[p["id"]["bioguide"]] = p["terms"]
    pc = [(b, k) for b in people for k in congresses(terms.get(b, [])) if k >= 91]
    f = pd.DataFrame(pc, columns=["b", "congress"])
    les = set(zip(t3[t3.level == "Federal"].bioguide_id, t3[t3.level == "Federal"].session.astype(int)))
    items = set(zip(t7.bioguide_id, t7.congress.astype(int)))
    texts = set(zip(t5.bioguide_id, t5.congress.astype(int)))
    f["les"] = [(b, k) in les for b, k in zip(f.b, f.congress)]
    f["items"] = [(b, k) in items for b, k in zip(f.b, f.congress)]
    f["text"] = [(b, k) in texts for b, k in zip(f.b, f.congress)]
    f["decade"] = ((f.congress - 1) * 2 + 1789) // 10 * 10
    md.append("## Federal service (Tables 3, 5 and 7)\n")
    md.append(f"{f.b.nunique():,} people, {len(f):,} person-Congresses from the 91st Congress (1969).\n")
    frows = []
    for d, g in f.groupby("decade"):
        frows.append((f"{d}s", f"{len(g):,}", pct(g.les.sum(), len(g)), pct(g["items"].sum(), len(g)),
                      pct(g.text.sum(), len(g))))
    frows.append(("All", f"{len(f):,}", pct(f.les.sum(), len(f)), pct(f["items"].sum(), len(f)),
                  pct(f.text.sum(), len(f))))
    md.append(table(["Decade (Congress start)", "Person-Congresses", "LES score (T3)", "≥1 sponsored item (T7)",
                     "≥1 bill text (T5)"], frows))
    gaps = f.groupby("congress").agg(n=("b", "size"), les=("les", "sum"), items=("items", "sum"), text=("text", "sum"))
    md.append("\nBy Congress where coverage is short of the served count:\n")
    grows = [(k, r.n, r.les, r["items"], r.text) for k, r in gaps.iterrows()
             if r.les < r.n or r["items"] < r.n or r.text < r.n]
    md.append(table(["Congress", "Served", "LES", "Items", "Text"], grows))
    md.append("\nKnown causes: CEL's LES starts with the 93rd Congress (1973) and has not scored the 119th yet; "
              "Congress.gov's sponsored-legislation API starts with the 93rd; Congress.gov has almost no digital "
              "bill text before the 101st (1989). A person-Congress with no sponsored item at all is usually "
              "genuine (short service, or a member who sponsored nothing as lead sponsor).\n")

    # ---- Table 2
    vet = t2.veteran.value_counts().to_dict() if "veteran" in t2 else {}
    md.append("## Demographics (Table 2)\n")
    md.append(f"Veteran status: {', '.join(f'{k} {v:,}' for k, v in vet.items())}. 'Not found' = no Congressional "
              "Directory or Biographical Directory biography in the editions used.\n")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
