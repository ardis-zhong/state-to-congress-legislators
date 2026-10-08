#!/usr/bin/env python3
"""
Link population members to their State Legislative Effectiveness Scores.
CEL's state file has no Bioguide IDs: each row is a state, chamber, term,
name ("Last, First M."), and CEL's own per-person sles_id. This script finds,
for each person, the one sles_id (or, rarely, two -- e.g. a separate id in
each chamber) that is the same individual.

RULES (no model in the loop; anything uncertain goes to review):
  1. Candidates come from the person's state(s) of state-legislative service
     (their congressional state, plus any other state named in StateLegChamber)
     and must have a term overlapping their researched state-legislature years
     (+/- 1 year).
  2. The SLES last name must equal the person's last name, compared word by
     word for compound names ("Lujan Grisham", "Diaz-Balart").
  3. If several different people remain, keep those whose given names include
     the person's first name, nickname, or middle name (from the
     congress-legislators records or the name used in this project).
  4. Exactly one remaining person (one or more sles_ids with the same name) ->
     matched. Zero or several -> listed for review. Decisions on reviewed
     cases are recorded in replication/data/reference/sles_review.csv and
     applied here.

People whose state service ended before CEL's coverage of their state begins
(1993-2003, varies by state) are "before coverage" and have no state scores.

INPUTS:  cel_cache/sles_all_50_states_202609.dta (fetch_cel_scores.py),
         replication/data/population/person_level.csv,
         legislators-current.json / legislators-historical.json
OUTPUT:  replication/data/processed/sles_matches.csv
         one row per person: bioguide_id, name, status, state, sles_ids,
         sles_name, first_term, last_term, note

USAGE (from the repo root):
    python3 replication/scripts/effectiveness/match_sles.py
"""

import csv
import json
import re
import unicodedata

import pandas as pd

SLES_FILE = "cel_cache/sles_all_50_states_202609.dta"
PERSON_LEVEL = "replication/data/population/person_level.csv"
LEGISLATOR_FILES = ["legislators-current.json", "legislators-historical.json"]
REVIEW = "replication/data/reference/sles_review.csv"
OUT = "replication/data/processed/sles_matches.csv"

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


NICKNAMES = {  # nickname -> formal given name, for names CEL lists formally
    "jim": "james", "jimmy": "james", "bob": "robert", "rob": "robert", "bobby": "robert",
    "bill": "william", "billy": "william", "will": "william", "dick": "richard", "rick": "richard",
    "chris": "christopher", "tom": "thomas", "mike": "michael", "ed": "edward", "ted": "edward",
    "dan": "daniel", "danny": "daniel", "matt": "matthew", "steve": "steven", "sam": "samuel",
    "vic": "victor", "joe": "joseph", "tony": "anthony", "andy": "andrew", "pat": "patrick",
    "chuck": "charles", "charlie": "charles", "jerry": "gerald", "larry": "lawrence", "ron": "ronald",
    "don": "donald", "doug": "douglas", "greg": "gregory", "jeff": "jeffrey", "jon": "jonathan",
    "ken": "kenneth", "nick": "nicholas", "pete": "peter", "phil": "philip", "ray": "raymond",
    "russ": "russell", "tim": "timothy", "dave": "david", "debbie": "deborah", "cathy": "catherine",
    "kathy": "katherine", "liz": "elizabeth", "beth": "elizabeth", "sue": "susan", "jackie": "jacqueline",
    "fred": "frederick", "hank": "henry", "jack": "john", "buddy": "", "gil": "gilbert",
}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def words(s):
    return [norm(w) for w in re.split(r"[\s\-]+", str(s)) if norm(w)]


def given_names(name, display_name, middle=False):
    """Given names of a population member, as normalized words of 2+ letters, plus formal forms.
    First names and nicknames by default; middle names only when middle=True."""
    keys = ("middle",) if middle else ("first", "nickname")
    g = {norm(name.get(k, "")) for k in keys if name.get(k)}
    if middle:
        return {x for x in g if len(x) >= 2}
    g |= {norm(w) for w in display_name.split()[:-1]}
    g = {x for x in g if len(x) >= 2}
    return g | {NICKNAMES[x] for x in g if NICKNAMES.get(x)}


def given_match(given, sles_given):
    """True if a given name matches a given-name word in CEL's 'Last, First M.' (prefix ok: Fred/Frederick)."""
    for w in words(sles_given):
        if len(w) < 2:
            continue  # initials don't count
        if any(w == g or (len(g) >= 3 and (w.startswith(g) or g.startswith(w))) for g in given):
            return True
    return False


def leg_states(p):
    states = {STATES[p["State"]]} if p["State"] in STATES else set()
    text = p["StateLegChamber"].replace("West Virginia", "WEST_VIRGINIA")
    for name, abbr in STATES.items():
        if name == "West Virginia":
            if "WEST_VIRGINIA" in text:
                states.add(abbr)
        elif re.search(r"\b" + name + r"\b", text):
            states.add(abbr)
    return states


def leg_years(p):
    years = [int(y) for y in re.findall(r"(?:19|20)\d\d", p["StateLegYears"])]
    if re.search(r"\bpresent\b", p["StateLegYears"], re.I):  # not "representing"
        years.append(2026)
    return (min(years), max(years)) if years else None


def main():
    sles = pd.read_stata(SLES_FILE)
    sles["y0"] = sles.term.str[:4].astype(int)
    sles["y1"] = sles.term.str[-4:].astype(int)
    sles["last"] = sles.name.map(lambda n: str(n).split(",")[0])
    sles["given"] = sles.name.map(lambda n: str(n).split(",", 1)[1] if "," in str(n) else "")
    coverage = sles.groupby("state").y0.min().to_dict()

    people = {}
    for path in LEGISLATOR_FILES:
        with open(path, encoding="utf-8") as f:
            for p in json.load(f):
                people[p["id"]["bioguide"]] = p
    with open(PERSON_LEVEL, newline="", encoding="utf-8") as f:
        population = list(csv.DictReader(f))
    with open(REVIEW, newline="", encoding="utf-8") as f:
        decisions = {r["bioguide_id"]: r for r in csv.DictReader(f)}

    rows = []
    for p in population:
        bg = p["BioguideId"]
        name = people[bg]["name"]
        out = {"bioguide_id": bg, "name": p["Name"], "status": "", "state": "", "sles_ids": "",
               "sles_name": "", "first_term": "", "last_term": "", "note": ""}
        states, span = leg_states(p), leg_years(p)
        if bg in decisions:
            d = decisions[bg]
            out.update(status=d["status"], state=d["state"], sles_ids=d["sles_ids"], note=d["decision_note"])
        elif not span:
            out.update(status="no state years", note="StateLegYears has no year")
        elif all(span[1] < coverage.get(s, 9999) for s in states):
            out.update(status="before coverage",
                       note="state service ended before CEL coverage of " + "/".join(sorted(states)))
        else:
            lo, hi = span
            cand = sles[sles.state.isin(states) & (sles.y1 >= lo - 1) & (sles.y0 <= hi + 1)]
            last = words(name["last"])
            given = given_names(name, p["Name"])
            exact = cand[cand["last"].map(lambda x: words(x) == last or norm(x) == "".join(last)
                                          or (len(last) > 1 and set(last) <= set(words(x)))
                                          or (len(words(x)) > 1 and set(words(x)) <= set(last)))]
            if not exact.empty:
                persons = exact.groupby("name").sles_id.unique()
                if len(persons) > 1:
                    # first name / nickname first; middle name only if that settles nothing
                    # (Jeff Jackson's middle name, Neal, is another legislator's first name)
                    by_first = [n for n in persons.index if given_match(given, n.split(",", 1)[-1])]
                    if not by_first:
                        mid = given_names(name, p["Name"], middle=True)
                        by_first = [n for n in persons.index if given_match(mid, n.split(",", 1)[-1])]
                    persons = persons.loc[by_first]
            else:
                # Looser surname match -- CEL files some compound or changed names differently
                # ("Beutler, Jaime Herrera", "Gabbard Tamayo, Tulsi", "Walorskiswihart, Jackie") --
                # so a first-name match is required.
                loose = cand[cand.name.map(lambda n: set(last) <= set(words(n))
                                           or norm(str(n).split(",")[0]).startswith("".join(last)))]
                persons = loose.groupby("name").sles_id.unique()
                persons = persons.loc[[n for n in persons.index if given_match(given, n.split(",", 1)[-1])]]
            if len(persons) == 1:
                ids = sorted(int(i) for i in persons.iloc[0])
                out.update(status="matched", sles_ids=";".join(map(str, ids)), sles_name=persons.index[0])
            elif len(persons) == 0 and all(hi <= coverage.get(s, 9999) for s in states):
                # service ended in the year coverage starts: these members left the legislature
                # that January to take their seat in Congress, so they have no scored term
                out.update(status="before coverage",
                           note="state service ended as CEL coverage of " + "/".join(sorted(states)) + " began")
            elif len(persons) == 0:
                out.update(status="REVIEW", note="no SLES person with this last name/state/years")
            else:
                out.update(status="REVIEW", note="several candidates: " + " | ".join(persons.index))
        if out["status"] == "matched":
            mine = sles[sles.sles_id.isin([int(i) for i in out["sles_ids"].split(";")])
                        & sles.state.isin(states | ({out["state"]} if out["state"] else set()))]
            out.update(state=";".join(sorted(mine.state.unique())), sles_name=out["sles_name"] or mine.name.iloc[0],
                       first_term=mine.term.min(), last_term=mine.term.max())
        rows.append(out)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(counts)
    for r in rows:
        if r["status"] == "REVIEW":
            print(f"  REVIEW {r['bioguide_id']} {r['name']}: {r['note']}")


if __name__ == "__main__":
    main()
