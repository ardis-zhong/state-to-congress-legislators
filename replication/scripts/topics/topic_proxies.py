#!/usr/bin/env python3
"""
Proxy topic evidence for checking the Table 6 classifier, from replication/data/reference/topic_keyword_crosswalk.csv
(one keyword list, applied the same way to federal and state bills so the federal bills can calibrate it).

For each bill, the policy areas its evidence points to:
  committee_areas   from the committees it was referred to (Table 7 / Table 4 `committees`)
  subject_areas     from the legislature's own subject-index terms (LegiScan `subjects`; state bills only)
  heading_areas     from California's Legislative Counsel subject heading, the part of the title before ':'
                    ('Transportation: reports.'; California bills only)
Only rules marked informative=Yes count; fiscal, procedural and commemorative matches are recorded in *_flags.
A bill whose evidence matches no informative rule has an empty set (no check possible).

Outputs (topics_data/): federal_topic_proxies.csv, state_topic_proxies.csv:
  bill_id, committee_areas, committee_flags, subject_areas, subject_flags, heading_areas, heading_flags
(areas '|'-joined). Prints, for the federal bills with a current policy area, how often the true label falls inside
the committee areas: the ceiling a perfect classifier would reach on this check.

USAGE (from the repo root, after build_topic_data.py):  python3 replication/scripts/topics/topic_proxies.py
"""

import csv
import gzip
import os
import re
import sys
from collections import Counter

csv.field_size_limit(sys.maxsize)

XWALK = "replication/data/reference/topic_keyword_crosswalk.csv"
DATA = "topics_data"
CA_HEADING = re.compile(r"^\s*([A-Z][^:]{2,80}):")


def load_rules():
    rules = []
    with open(XWALK, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rules.append((r["rule_id"], re.compile(r["pattern"], re.I),
                          [a for a in r["policy_areas"].split("|") if a], r["informative"] == "Yes"))
    return rules


def areas(texts, rules):
    """Union of informative policy areas over the given strings, plus the non-informative rule ids matched."""
    out, flags = set(), set()
    for t in texts:
        t = re.sub(r"^\s*[^:]{0,30}:\s*", "", t) if re.match(r"^\s*(House|Senate|Assembly|General Assembly|"
                                                              r"House of Delegates|Joint)\s*:", t) else t
        for rid, pat, pas, informative in rules:
            if pat.search(t):
                if informative:
                    out.update(pas)
                else:
                    flags.add(rid)
    return "|".join(sorted(out)), "|".join(sorted(flags))


def split(s):
    return [x.strip() for x in (s or "").split(";") if x.strip()]


def run(kind, rules):
    src = os.path.join(DATA, f"{kind}_topic_data.csv.gz")
    dst = os.path.join(DATA, f"{kind}_topic_proxies.csv")
    stats = Counter()
    with gzip.open(src, "rt", newline="", encoding="utf-8") as f, open(dst, "w", newline="", encoding="utf-8") as g:
        w = csv.writer(g, lineterminator="\n")
        w.writerow(["bill_id", "committee_areas", "committee_flags", "subject_areas", "subject_flags",
                    "heading_areas", "heading_flags"])
        for r in csv.DictReader(f):
            ca, cf = areas(split(r["committees"]), rules)
            sa, sf = areas(split(r.get("subjects", "")), rules) if kind == "state" else ("", "")
            ha = hf = ""
            if kind == "state" and r["state"] == "CA":
                m = CA_HEADING.match(r["title"])
                if m:
                    ha, hf = areas([m.group(1)], rules)
            w.writerow([r["bill_id"], ca, cf, sa, sf, ha, hf])
            stats["bills"] += 1
            stats["committee evidence"] += bool(ca)
            stats["subject evidence"] += bool(sa)
            stats["heading evidence"] += bool(ha)
            if kind == "federal" and r["label_set"] == "current":
                stats["labeled"] += 1
                if ca:
                    stats["labeled with committee evidence"] += 1
                    stats["label inside committee areas"] += r["label"] in ca.split("|")
    print(f"Wrote {dst}: " + ", ".join(f"{k} {v:,}" for k, v in stats.items()))
    if kind == "federal" and stats["labeled with committee evidence"]:
        print(f"  ceiling: true policy area inside the committee areas for "
              f"{stats['label inside committee areas'] / stats['labeled with committee evidence']:.1%} of labeled "
              f"federal bills with committee evidence")


if __name__ == "__main__":
    rules = load_rules()
    run("federal", rules)
    run("state", rules)
