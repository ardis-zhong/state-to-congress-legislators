#!/usr/bin/env python3
"""
Model inputs for the Table 6 topic classifier (RoBERTa fine-tuned on Congress.gov policy areas).

Writes two files into topics_data/ (symlink to the T9 drive; gitignored):

  federal_topic_data.csv.gz   one row per federal bill or resolution in Table 7:
      bill_id, congress, year, type, label, label_set, committees, title, body
      label      Table 7's Congress.gov policy area ('' when none)
      label_set  'current'  = one of the 33 current Congress.gov policy areas (training data)
                 'retired'  = Commemorations (used through the 110th Congress, 2008; kept apart: see --label-set in
                              finetune_topics.py)
                 'legacy'   = a 1970s legislative subject term (93rd-95th Congresses), not a policy area: not used
                 'none'     = no policy area (1969-1972 bills, a few recent ones)
  state_topic_data.csv.gz     one row per state bill in Table 4:
      bill_id, state, year, text_source, committees, subjects, title, body
      subjects   the legislature's own subject-index terms as LegiScan carries them ('; '-joined; blank when the state
                 or source has none)

title = the bill's title (Table 7 bill_name / Table 4 bill_name). body = the bill text with the parts that name
committees or sponsors cut away, so the model cannot learn topics from committee names (committees are used to check
its accuracy): the text starts at its enacting heading ('A BILL', 'AN ACT', 'JOINT RESOLUTION', 'An act to amend ...')
when one appears near the top, any sentence saying the measure was referred to a committee is removed, line numbers
are dropped, whitespace is collapsed, and the body is cut at BODY_CHARS characters (RoBERTa reads 512 tokens, about
2,000-2,500 characters, so the cut never binds the model).

USAGE (from the repo root, after build_tables.py):  python3 replication/scripts/topics/build_topic_data.py
"""

import csv
import glob
import gzip
import json
import os
import re
import sys
import zipfile

csv.field_size_limit(sys.maxsize)

T4 = "datasets/csv/table4_state_bill_text.csv"
T5 = "datasets/csv/table5_federal_bill_text.csv"
T7 = "datasets/csv/table7_federal_bill_topics.csv"
LEGISCAN = "legiscan_dataset_cache"
OUT = "topics_data"
BODY_CHARS = 4000

CURRENT = [
    "Agriculture and Food", "Animals", "Armed Forces and National Security", "Arts, Culture, Religion",
    "Civil Rights and Liberties, Minority Issues", "Commerce", "Congress", "Crime and Law Enforcement",
    "Economics and Public Finance", "Education", "Emergency Management", "Energy", "Environmental Protection",
    "Families", "Finance and Financial Sector", "Foreign Trade and International Finance",
    "Government Operations and Politics", "Health", "Housing and Community Development", "Immigration",
    "International Affairs", "Labor and Employment", "Law", "Native Americans", "Private Legislation",
    "Public Lands and Natural Resources", "Science, Technology, Communications", "Social Sciences and History",
    "Social Welfare", "Sports and Recreation", "Taxation", "Transportation and Public Works",
    "Water Resources Development",
]
RETIRED = ["Commemorations"]

HEADING = re.compile(r"^[ \t]*(A BILL\b|AN ACT\b|An Act\b|An act\b|JOINT RESOLUTION\b|CONCURRENT RESOLUTION\b|"
                     r"(?:HOUSE |SENATE |ASSEMBLY )?(?:JOINT |CONCURRENT )?RESOLUTION\b|A RESOLUTION\b|"
                     r"A JOINT RESOLUTION\b|A CONCURRENT RESOLUTION\b|MEMORIAL\b|A MEMORIAL\b)", re.M)
REFERRAL = re.compile(r"[^.;\n]*(?:referred|re-referred|rereferred|assigned|recommitted)\s+to\s+(?:the\s+)?"
                      r"(?:joint\s+|standing\s+|select\s+)?(?:committee|com\.)[^.;]*[.;]?", re.I)
LINENO = re.compile(r"[ \t]+\d{1,3}[ \t]*$", re.M)          # Ohio/Michigan-style trailing line numbers
LEADNO = re.compile(r"^[ \t]*\d{1,4}[ \t]+(?=\S)", re.M)     # leading line numbers ('1 To amend ...')
PAGELINE = re.compile(r"(?<!\S)\d{1,3}-\d{1,2}(?!\S)")          # Texas page-line numbers ('1-1 AN ACT 1-2 relating')
NH_COMMITTEE = re.compile(r"\bCOMMITTEE\s*:.*?(?=\s(?:AMENDED ANALYSIS|ANALYSIS|AN ACT|A RESOLUTION)\b)")  # NH header line


def clean_body(text):
    text = text[:6000 + 3 * BODY_CHARS].replace("\r", "")     # only the start is kept: don't scan whole bills
    m = HEADING.search(text[:6000])
    if m:
        text = text[m.start():]
    text = REFERRAL.sub(" ", text)
    text = LINENO.sub("", text)
    text = LEADNO.sub("", text)
    text = re.sub(r"[_=\-]{5,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = NH_COMMITTEE.sub(" ", text)
    if len(PAGELINE.findall(text)) >= 10:                   # only texts printed with page-line numbers
        text = PAGELINE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:BODY_CHARS]


def label_set(t):
    if t in CURRENT:
        return "current"
    if t in RETIRED:
        return "retired"
    return "legacy" if t else "none"


def legiscan_subjects():
    """(session id, bill number) -> '; '-joined subject terms, from the cached LegiScan datasets."""
    want = set()
    with open(T4, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["text_source"] == "LegiScan":
                parts = r["bill_id"].split("-")
                want.add((parts[1], parts[2]))
    sids = {s for s, _ in want}
    out = {}
    for z in sorted(glob.glob(os.path.join(LEGISCAN, "*.zip"))):
        sid = os.path.basename(z).rsplit("_", 1)[-1].replace(".zip", "")
        if sid not in sids:
            continue
        zf = zipfile.ZipFile(z)
        for name in zf.namelist():
            if "/bill/" not in name or not name.endswith(".json"):
                continue
            b = json.loads(zf.read(name))["bill"]
            key = (sid, b.get("bill_number", ""))
            if key in want and b.get("subjects"):
                out[key] = "; ".join(s["subject_name"] for s in b["subjects"] if s.get("subject_name"))
    return out


def federal():
    meta = {}
    with open(T7, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["bill_id"] not in meta:
                meta[r["bill_id"]] = r
    path = os.path.join(OUT, "federal_topic_data.csv.gz")
    done, counts = set(), {}
    with gzip.open(path + ".part", "wt", newline="", encoding="utf-8") as g:
        w = csv.writer(g, lineterminator="\n")
        w.writerow(["bill_id", "congress", "year", "type", "label", "label_set", "committees", "title", "body"])

        def write(r, body):
            ls = label_set(r["topic"])
            counts[ls] = counts.get(ls, 0) + 1
            w.writerow([r["bill_id"], r["congress"], r["year"], r["bill_id"].split("-")[1], r["topic"], ls,
                        r["committees"], r["bill_name"], body])

        with open(T5, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                b = r["bill_id"]
                if b in done or b not in meta:
                    continue
                done.add(b)
                write(meta[b], clean_body(r["bill_text"]))
        for b, r in meta.items():
            if b not in done:
                write(r, "")
    os.replace(path + ".part", path)
    print(f"Wrote {path}: {len(meta)} measures ({len(done)} with text); label sets {counts}")


def state():
    subj = legiscan_subjects()
    path = os.path.join(OUT, "state_topic_data.csv.gz")
    done, with_subj, with_com = set(), 0, 0
    with gzip.open(path + ".part", "wt", newline="", encoding="utf-8") as g, \
            open(T4, newline="", encoding="utf-8") as f:
        w = csv.writer(g, lineterminator="\n")
        w.writerow(["bill_id", "state", "year", "text_source", "committees", "subjects", "title", "body"])
        for r in csv.DictReader(f):
            b = r["bill_id"]
            if b in done:
                continue
            done.add(b)
            s = ""
            if r["text_source"] == "LegiScan":
                parts = b.split("-")
                s = subj.get((parts[1], parts[2]), "")
            with_subj += bool(s)
            with_com += bool(r["committees"])
            w.writerow([b, r["state"], r["year"], r["text_source"], r["committees"], s, r["bill_name"],
                        clean_body(r["bill_text"])])
    os.replace(path + ".part", path)
    print(f"Wrote {path}: {len(done)} bills; {with_com} with committees, {with_subj} with LegiScan subject terms")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None   # --only federal|state
    if only in (None, "federal"):
        federal()
    if only in (None, "state"):
        state()
