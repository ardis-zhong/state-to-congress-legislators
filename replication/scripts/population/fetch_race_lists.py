#!/usr/bin/env python3
"""
Download the Office of the House Historian's official per-Congress lists of
Black, Hispanic, and Asian and Pacific Islander members of Congress, and match
every row to a Bioguide ID.

SOURCES (history.house.gov, "Historical Data" pages of each exhibition):
    Black Americans in Congress
    Hispanic Americans in Congress
    Asian and Pacific Islander Americans in Congress

MATCHING: each list row gives Congress, "LAST, First" name, state, and chamber.
A row is matched to the member of the official congress-legislators term
records (legislators-current/historical.json, downloaded by
fetch_legislator_party_gender.py) who served in that chamber, for that state,
during that Congress, with the same last name. Rows that match zero or several
members are reported, not guessed.

OUTPUTS:
    replication/data/reference/house_historian_race_lists.csv
        every list row as published, plus the matched bioguide_id
    replication/data/processed/race_by_bioguide.csv
        one row per Bioguide ID that appears on at least one list:
        bioguide_id, race (list labels joined with "; ")

USAGE (from the repo root):
    python3 replication/scripts/population/fetch_race_lists.py
"""

import csv
import html
import json
import re
import unicodedata
import urllib.request

BASE = "https://history.house.gov/Exhibitions-and-Publications/"
LISTS = [
    ("Black", BASE + "BAIC/Historical-Data/Black-American-Representatives-and-Senators-by-Congress/"),
    ("Hispanic", BASE + "HAIC/Historical-Data/Hispanic-American-Representatives,-Senators,-Delegates,"
                        "-and-Resident-Commissioners-by-Congress/"),
    ("Asian or Pacific Islander", BASE + "APA/Historical-Data/By-Congress/"),
]
LEGISLATOR_FILES = ["legislators-current.json", "legislators-historical.json"]
OUT_ROWS = "replication/data/reference/house_historian_race_lists.csv"
OUT_PEOPLE = "replication/data/processed/race_by_bioguide.csv"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (academic research)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def cell_text(c):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()


def parse_table(page):
    """Yield (congress_number, name, state, party, chamber) for each member row."""
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [cell_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(cells) != 5 or cells[0] == "Congress":
            continue
        m = re.match(r"(\d+)", cells[0])
        # the name cell can carry a footnote number at the end, e.g. "LONG, Jefferson Franklin 1"
        name = re.sub(r"\s+\d+$", "", cells[1])
        yield int(m.group(1)), name, cells[2], cells[3], cells[4]


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def load_terms():
    people = []
    for path in LEGISLATOR_FILES:
        with open(path, encoding="utf-8") as f:
            people.extend(json.load(f))
    return people


def main():
    people = load_terms()
    rows, unmatched, ambiguous = [], [], []
    for label, url in LISTS:
        n = 0
        for congress, name, state, party, chamber in parse_table(fetch(url)):
            n += 1
            start = f"{1787 + 2 * congress}-01-03"
            end = f"{1789 + 2 * congress}-01-03"
            typ = "sen" if chamber == "Senate" else "rep"
            last = norm(name.split(",")[0])
            first = norm((name.split(",") + [""])[1].split()[0]) if "," in name else ""
            serving = {p["id"]["bioguide"]: p for p in people
                       if any(t["type"] == typ and t["state"] == state and t["start"] < end
                              and t["end"] > start for t in p["terms"])}
            # exact last-name match first; fall back to compound names
            # (e.g. "LEE CARTER" vs. "Lee Carter", "LUJAN GRISHAM")
            cands = {bg for bg, p in serving.items() if norm(p["name"]["last"]) == last}
            if not cands:
                cands = {bg for bg, p in serving.items()
                         if last in norm(p["name"]["last"]) or norm(p["name"]["last"]) in last}
            if len(cands) > 1 and first:
                # same-surname colleagues (e.g. Lincoln and Mario Diaz-Balart): use the first name
                def given(p):
                    n = p["name"]
                    return {norm(n.get(k, "")) for k in ("first", "nickname", "middle") if n.get(k)}
                cands = {bg for bg in cands
                         if any(g and (g.startswith(first) or first.startswith(g))
                                for g in given(serving[bg]))}
            if len(cands) > 1:
                # father/son with the same name (e.g. Donald Payne Sr./Jr.): use the suffix
                is_jr = bool(re.search(r"\bJr\.?", name))
                cands = {bg for bg in cands
                         if ("jr" in norm(serving[bg]["name"].get("suffix", ""))) == is_jr}
            bg = cands.pop() if len(cands) == 1 else ""
            if not bg:
                (ambiguous if cands else unmatched).append((label, congress, name, state, chamber))
            rows.append({"list": label, "congress": congress, "name": name, "state": state,
                         "party": party, "chamber": chamber, "bioguide_id": bg})
        print(f"{label}: {n} list rows")

    with open(OUT_ROWS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    labels = {}
    for r in rows:
        if r["bioguide_id"]:
            labels.setdefault(r["bioguide_id"], set()).add(r["list"])
    order = [label for label, _ in LISTS]
    with open(OUT_PEOPLE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["bioguide_id", "race"])
        for bg in sorted(labels):
            w.writerow([bg, "; ".join(x for x in order if x in labels[bg])])

    print(f"Matched {sum(1 for r in rows if r['bioguide_id'])}/{len(rows)} rows "
          f"-> {len(labels)} distinct people")
    for kind, lst in [("UNMATCHED", unmatched), ("AMBIGUOUS", ambiguous)]:
        for x in lst:
            print(f"  {kind}: {x}")


if __name__ == "__main__":
    main()
