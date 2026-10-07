#!/usr/bin/env python3
"""
Phase A of the state-bill extraction: match each of the 248 target
legislators (people whose state-legislature service years overlap
LegiScan's coverage window for their state) to a LegiScan people_id.

WHY THIS IS ITS OWN STEP:
LegiScan has no name-search endpoint. The only way to find a person's
people_id is to pull the roster of every session that could plausibly
include them (getSessionPeople) and match by name. This step does that,
flags anything that isn't a clean match for manual review (rather than
guessing), and caches every raw API response to disk so nothing has to be
re-fetched in later phases.

INPUT:  state_bill_targets.csv (248 rows: Name, BioguideId, State,
        StateAbbr, StateLegChamber, StateLegYears, MinYear, MaxYear)

OUTPUT: legiscan_people_matches.csv       -- one row per target person:
            MatchStatus (MATCHED / AMBIGUOUS / NOT_FOUND), MatchedPeopleIds
            (semicolon-separated -- a person can have more than one
            LegiScan people_id if their record changed, e.g. a chamber
            switch), and match details for manual review of anything not
            a clean single match.
        legiscan_session_cache/            -- one JSON file per state
            (raw getSessionList) and one per queried session_id (raw
            getSessionPeople), so later phases can reuse this without
            spending more queries.

USAGE:
    python3 legiscan_match_people.py YOUR_LEGISCAN_API_KEY
"""

import csv
import json
import os
import re
import sys
import time
import urllib.request

MAX_RETRIES = 5
CACHE_DIR = "legiscan_session_cache"

# Common nickname <-> formal-name equivalences, used only as a fallback
# when an exact first-name match fails. Deliberately conservative: if a
# match still isn't found after this, the row is flagged for manual
# review rather than guessed via fuzzy matching.
NICKNAMES = {
    "chuck": "charles", "charlie": "charles", "bob": "robert", "rob": "robert",
    "bobby": "robert", "bill": "william", "billy": "william", "will": "william",
    "jim": "james", "jimmy": "james", "mike": "michael", "mickey": "michael",
    "dave": "david", "tom": "thomas", "tommy": "thomas", "rich": "richard",
    "rick": "richard", "ricky": "richard", "dick": "richard", "steve": "steven",
    "dan": "daniel", "danny": "daniel", "greg": "gregory", "ken": "kenneth",
    "kenny": "kenneth", "jeff": "jeffrey", "larry": "lawrence", "ron": "ronald",
    "ronnie": "ronald", "ted": "theodore", "ned": "edward", "ed": "edward",
    "eddie": "edward", "liz": "elizabeth", "beth": "elizabeth", "betsy": "elizabeth",
    "sam": "samuel", "sammy": "samuel", "andy": "andrew", "drew": "andrew",
    "nick": "nicholas", "matt": "matthew", "joe": "joseph", "joey": "joseph",
    "tony": "anthony", "al": "albert", "frank": "francis", "pat": "patrick",
    "patty": "patricia", "peggy": "margaret", "meg": "margaret", "gerry": "gerald",
    "jerry": "gerald", "chris": "christopher", "kathy": "katherine",
    "cathy": "catherine", "kate": "katherine", "katie": "katherine",
    "abe": "abraham", "alex": "alexander", "ben": "benjamin", "benny": "benjamin",
    "carl": "carlton", "curt": "curtis", "gene": "eugene", "hank": "henry",
    "harry": "harold", "jack": "john", "johnny": "john", "leo": "leon",
    "les": "leslie", "lou": "louis", "marge": "margaret", "max": "maxwell",
    "nate": "nathaniel", "norm": "norman", "phil": "philip", "russ": "russell",
    "stan": "stanley", "vic": "victor", "walt": "walter", "wally": "walter",
    # Added after reviewing round-1 NOT_FOUND results:
    "sandy": "sandra", "becca": "rebecca", "herb": "herbert", "don": "donald",
    "debbie": "deborah", "deb": "deborah", "randy": "randall", "maggie": "margaret",
    "fred": "frederick", "freddie": "frederick", "jen": "jennifer", "jenny": "jennifer",
    "tim": "timothy", "timmy": "timothy", "jake": "jacob", "mick": "michael",
    "jamie": "james", "thom": "thomas", "buddy": "earl", "erik": "eric",
    # Added after checking legal first names for round-2 NOT_FOUND results:
    "doug": "douglas", "dougie": "douglas",
    # Rep. Jamie Raskin's legal first name is "Jamin" (Jamin Ben Raskin) --
    # "Jamie" is a nickname for Jamin here, not for James. Folding "jamin"
    # into the same "james" bucket as "jamie" lets either spelling match
    # the other; verified via history.house.gov and fedsoc.org bios.
    "jamin": "james",
}

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Bioguide-keyed overrides for people whose LegiScan-era state-legislature
# name differs from their current (post-marriage/current) name in a way
# nickname substitution can't fix -- i.e. a genuinely different last name,
# not a spelling/nickname variant. Each entry is a list of extra
# (first, last) name tuples (already normalize_token'd) to try, IN
# ADDITION to the name parsed from the target's Name column.
#
# Rep. Jaime Herrera Beutler served in the WA House as "Jaime Herrera"
# (2007-2011); she married and added "Beutler" in 2012, after her state
# legislative service ended. Her LegiScan-era WA records should be under
# "Herrera", not "Herrera Beutler" -- confirmed via Wikipedia/Ballotpedia
# bios noting the 2012 marriage postdates her House of Reps service.
NAME_OVERRIDES = {
    "H001056": [("jaime", "herrera")],  # Jaime Herrera Beutler
    # Rep. Dan Bishop's legal name is "James Daniel Bishop" (confirmed via
    # LegiStorm bio); "Dan" is short for his middle name Daniel. The round-2
    # diagnostic found an unmatched "James Bishop" in his 11 NC candidate
    # sessions -- almost certainly this record under his formal first name.
    "B001311": [("james", "bishop")],  # Dan Bishop
    # Rep. Mick Mulvaney's legal name is "John Michael Mulvaney" (confirmed
    # via LegiStorm bio); "Mick" is short for Michael, but SC legislature
    # rosters apparently use his other given name, John. Diagnostic found
    # an unmatched "John Mulvaney" in his 2 SC candidate sessions.
    "M001182": [("john", "mulvaney")],  # Mick Mulvaney
    # Rep. Van Taylor's legal name is "Nicholas Van Campen Taylor" (confirmed
    # via LegiStorm bio); "Van" is his middle name, which he uses publicly.
    # Diagnostic found an unmatched "Nicholas Taylor" among his 11 TX
    # candidate sessions (also found an unrelated "Larry Taylor" -- a
    # different, real TX state senator -- which this override does not
    # match since it targets the first name "nicholas" specifically).
    "T000479": [("nicholas", "taylor")],  # Van Taylor
    # Sen. Kai Kahele's legal first name is "Kaiali'i" (he's often called
    # "Kai" for short). Diagnostic found an unmatched "Kaiali'i Kahele" in
    # his 10 HI candidate sessions -- also an unmatched "Gilbert Kahele",
    # who is a DIFFERENT person (his father, a separate former HI state
    # senator) and must not be matched here. Targeting "kaialii" (the
    # normalized form of "Kaiali'i") specifically avoids pulling in Gilbert.
    "K000396": [("kaialii", "kahele")],  # Kai Kahele
    # Rep. Doug LaMalfa's CA Senate roster entry spells his surname as two
    # words, "La Malfa" (people_id 11235, SD-004, confirmed by direct grep
    # of the user's legiscan_session_cache/sessionpeople_82.json). split_name
    # takes the LAST whitespace-separated token as the surname, so that
    # record parses as first="doug", last="malfa" -- not "lamalfa" as his
    # target Name column parses. This override tries that exact variant.
    "L000578": [("doug", "malfa")],  # Doug LaMalfa
}


def normalize_token(t):
    return re.sub(r"[^a-z]", "", t.lower())


def split_name(full_name):
    """Return (first, last) normalized tokens, stripping middle names/suffixes."""
    tokens = [normalize_token(t) for t in re.split(r"[\s,]+", full_name) if t.strip()]
    tokens = [t for t in tokens if t and t not in SUFFIXES]
    if not tokens:
        return "", ""
    first = tokens[0]
    last = tokens[-1] if len(tokens) > 1 else tokens[0]
    return first, last


def names_match(first_a, last_a, first_b, last_b):
    if last_a != last_b:
        return False
    if first_a == first_b:
        return True
    fa = NICKNAMES.get(first_a, first_a)
    fb = NICKNAMES.get(first_b, first_b)
    return fa == fb


def call(op, key, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://api.legiscan.com/?key={key}&op={op}" + (f"&{qs}" if qs else "")
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sdsu-research-script/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(0.25)
            return data
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(1 * attempt)
    raise RuntimeError(f"Failed op={op} params={params} after {MAX_RETRIES} retries: {last_err}")


def cached_call(op, key, cache_key, **params):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{cache_key}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = call(op, key, **params)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def main():
    if len(sys.argv) not in (2, 3):
        print("Usage: python3 legiscan_match_people.py YOUR_LEGISCAN_API_KEY [targets_file.csv]")
        print("  targets_file.csv defaults to replication/data/targets/state_bill_targets.csv (the original 247-person")
        print("  scope). Pass replication/data/targets/state_bill_targets_full.csv to cover the full 1019-person")
        print("  population (see dataset-completion-status.md / population-added-109-people.md).")
        sys.exit(1)
    key = sys.argv[1]
    targets_path = sys.argv[2] if len(sys.argv) == 3 else "replication/data/targets/state_bill_targets.csv"

    with open(targets_path, newline="", encoding="utf-8") as f:
        targets = list(csv.DictReader(f))
    print(f"Loaded {len(targets)} target people from {targets_path}.")

    states_needed = sorted(set(t["StateAbbr"] for t in targets))
    print(f"Fetching session lists for {len(states_needed)} states...")
    sessions_by_state = {}
    for st in states_needed:
        data = cached_call("getSessionList", key, f"sessionlist_{st}", state=st)
        sessions_by_state[st] = data.get("sessions", []) or []
        print(f"  {st}: {len(sessions_by_state[st])} sessions")

    # Determine, for each target, which session_ids to check.
    target_sessions = {}  # index -> list of session dicts
    all_session_ids_needed = set()
    for i, t in enumerate(targets):
        st = t["StateAbbr"]
        lo, hi = int(t["MinYear"]), int(t["MaxYear"])
        relevant = [
            s for s in sessions_by_state.get(st, [])
            if s.get("year_start") and s.get("year_end")
            and not (s["year_end"] < lo or s["year_start"] > hi)
        ]
        target_sessions[i] = relevant
        for s in relevant:
            all_session_ids_needed.add(s["session_id"])

    print(f"\n{len(all_session_ids_needed)} unique sessions need a getSessionPeople call.")
    session_people = {}  # session_id -> list of people dicts
    for n, sid in enumerate(sorted(all_session_ids_needed), 1):
        data = cached_call("getSessionPeople", key, f"sessionpeople_{sid}", id=sid)
        people = (data.get("sessionpeople", {}) or {}).get("people", []) or []
        # LegiScan's data occasionally has a stray non-dict entry (e.g. a
        # literal `false`) in the people array -- skip anything that isn't
        # a real person record rather than crashing on it.
        people = [p for p in people if isinstance(p, dict)]
        session_people[sid] = people
        if n % 25 == 0 or n == len(all_session_ids_needed):
            print(f"  ...{n}/{len(all_session_ids_needed)} sessions fetched")

    print("\nMatching...")
    results = []
    for i, t in enumerate(targets):
        name_variants = [split_name(t["Name"])]
        name_variants.extend(NAME_OVERRIDES.get(t["BioguideId"], []))
        candidates = {}  # people_id -> person dict
        for s in target_sessions[i]:
            for p in session_people.get(s["session_id"], []):
                first_p, last_p = split_name(p.get("name", ""))
                if any(names_match(first_t, last_t, first_p, last_p)
                       for first_t, last_t in name_variants):
                    candidates[p["people_id"]] = p

        if not candidates:
            status = "NOT_FOUND"
            ids = ""
            # Diagnostic aid: surface anyone sharing just the last name
            # (first name mismatched or missing entirely), so a genuine
            # legal-name difference -- e.g. a maiden name, or someone
            # rostered under a formal first name they never otherwise use
            # -- is visible in the CSV instead of requiring a re-dig
            # through the session cache.
            last_name_targets = {lt for _, lt in name_variants}
            near_misses = {}
            for s in target_sessions[i]:
                for p in session_people.get(s["session_id"], []):
                    _, last_p = split_name(p.get("name", ""))
                    if last_p in last_name_targets:
                        near_misses[p["people_id"]] = p.get("name", "")
            if near_misses:
                detail = (
                    f"No first-name match in {len(target_sessions[i])} candidate "
                    f"sessions, but same last name found under: "
                    + ", ".join(f"{pid}={name}" for pid, name in near_misses.items())
                )
            else:
                detail = f"No name match in {len(target_sessions[i])} candidate sessions."
        else:
            # Distinct people_ids for the same matched name -- keep all,
            # but flag if candidates disagree on last name spelling variants
            # (shouldn't happen given names_match logic, but double check
            # party/bioguide consistency isn't feasible here without more
            # data, so just report count).
            status = "MATCHED" if len(candidates) >= 1 else "NOT_FOUND"
            ids = ";".join(str(pid) for pid in candidates)
            names_found = sorted(set(p.get("name", "") for p in candidates.values()))
            detail = f"{len(candidates)} distinct people_id(s): " + ", ".join(
                f"{pid}={candidates[pid].get('name')}" for pid in candidates
            )
            if len(names_found) > 1:
                status = "AMBIGUOUS"

        results.append({
            "Name": t["Name"], "BioguideId": t["BioguideId"], "State": t["State"],
            "StateAbbr": t["StateAbbr"], "MatchStatus": status,
            "MatchedPeopleIds": ids, "Detail": detail,
            "NumCandidateSessions": len(target_sessions[i]),
        })

    with open("legiscan_people_matches.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Name", "BioguideId", "State", "StateAbbr",
                                           "MatchStatus", "MatchedPeopleIds", "Detail",
                                           "NumCandidateSessions"])
        w.writeheader()
        w.writerows(results)

    counts = {}
    for r in results:
        counts[r["MatchStatus"]] = counts.get(r["MatchStatus"], 0) + 1
    print("\n=== Match summary ===")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print("\nWrote legiscan_people_matches.csv")
    print("Please send back legiscan_people_matches.csv (the legiscan_session_cache/ "
          "folder can stay local -- the next phase will reuse it directly on your machine).")


if __name__ == "__main__":
    main()
