#!/usr/bin/env python3
"""
Phase B of the state-bill extraction: pull every bill sponsored by our 246
matched legislators, using LegiScan's BULK dataset API instead of per-bill
calls.

WHY BULK DATASETS INSTEAD OF getSponsoredList/getBill:
Probing getSponsoredList on one real, long-serving legislator returned
1,306 bare bill stubs. Extrapolated across 246 people, calling getBill
individually for every distinct bill would run into the tens of thousands
of API calls -- uncomfortably close to (or past) LegiScan's free
30,000-query/month cap. LegiScan's getDataset op instead returns one ZIP
per state+session containing full metadata for EVERY bill in that
session (same schema as getBill -- confirmed via probe). That turns the
job into ~100-200 bulk downloads (one per state+session actually touched
by our 246 people) instead of tens of thousands of individual calls.

NOTE ON FULL TEXT: the probe also confirmed the bulk ZIP's "texts" array
is metadata-only (doc_id, url, mime, text_size) -- no embedded document
content, same as the live getBill call. Full document text requires a
separate getBillText(doc_id) call per document. That's deliberately NOT
done here -- this phase only collects sponsorship + status metadata. Full
text should be a follow-up phase, scoped to whichever subset of bills
actually needs it (fetching full text for every version of every bill
any of the 246 people ever touched would be a much larger, likely
unnecessary, download).

INPUT:
    legiscan_people_matches.csv  -- from legiscan_match_people.py (needs
        MatchStatus == MATCHED rows; MatchedPeopleIds may be semicolon-
        separated)
    state_bill_targets.csv       -- for each matched person's MinYear/
        MaxYear (state-legislature service window), used to figure out
        which sessions are actually relevant to them
    legiscan_session_cache/      -- reused from the matching phase
        (sessionlist_<state>.json per-state session lists -- these are
        cache hits, no new API calls)

OUTPUT:
    state_legislation_sponsored.csv -- one row per (person, bill) they
        sponsored (primary or co-sponsor) in a session overlapping their
        service window: bill metadata, status, dates, sponsor role.
    legiscan_dataset_cache/      -- one raw ZIP per (state, session_id)
        fetched, so a re-run costs nothing for sessions already pulled.
    legiscan_missing_datasets.csv -- any (state, session_id) LegiScan
        doesn't have a published dataset for, so it's visible rather than
        silently dropped.

USAGE:
    python3 legiscan_fetch_state_bills.py YOUR_LEGISCAN_API_KEY
"""

import base64
import csv
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

MAX_RETRIES = 5
SESSION_CACHE_DIR = "legiscan_session_cache"
DATASET_CACHE_DIR = "legiscan_dataset_cache"

# Per LegiScan's public API documentation for the numeric `status` field
# on a bill record.
STATUS_MAP = {
    0: "N/A", 1: "Introduced", 2: "Engrossed", 3: "Enrolled",
    4: "Passed", 5: "Vetoed", 6: "Failed/Dead",
}

# Per LegiScan's public API documentation for `sponsor_type_id`.
SPONSOR_TYPE_MAP = {0: "Sponsor", 1: "Primary Sponsor", 2: "Co-Sponsor", 3: "Joint Sponsor"}


def call(op, key, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://api.legiscan.com/?key={key}&op={op}" + (f"&{qs}" if qs else "")
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sdsu-research-script/1.0"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(0.3)
            return data
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(1 * attempt)
    raise RuntimeError(f"Failed op={op} params={params} after {MAX_RETRIES} retries: {last_err}")


def cached_json_call(op, key, cache_key, cache_dir, **params):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{cache_key}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = call(op, key, **params)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def load_matched_people(path):
    """Returns (people_id -> person dict, state_abbr -> set(people_id))."""
    people_id_to_person = {}
    state_to_ids = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["MatchStatus"] != "MATCHED":
                continue
            ids = [pid.strip() for pid in row["MatchedPeopleIds"].split(";") if pid.strip()]
            for pid in ids:
                people_id_to_person[pid] = row
                state_to_ids.setdefault(row["StateAbbr"], set()).add(pid)
    return people_id_to_person, state_to_ids


def load_target_years(path):
    """Returns BioguideId -> (MinYear, MaxYear) int tuple."""
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out[row["BioguideId"]] = (int(row["MinYear"]), int(row["MaxYear"]))
            except (ValueError, KeyError):
                continue
    return out


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 legiscan_fetch_state_bills.py YOUR_LEGISCAN_API_KEY")
        sys.exit(1)
    key = sys.argv[1]

    print("Loading matched people and target years...")
    people_id_to_person, state_to_ids = load_matched_people("legiscan_people_matches.csv")
    target_years = load_target_years("state_bill_targets.csv")
    print(f"  {len(people_id_to_person)} matched people_id(s) across {len(state_to_ids)} states.")

    # Figure out which (state, session_id) pairs are actually needed, using
    # the same per-state cached session lists the matching phase built.
    print("\nDetermining needed (state, session) pairs from each person's service window...")
    needed_sessions = {}  # state -> set(session_id)
    for state, pids in state_to_ids.items():
        sl_path = os.path.join(SESSION_CACHE_DIR, f"sessionlist_{state}.json")
        if not os.path.exists(sl_path):
            print(f"  WARNING: no cached session list for {state} "
                  f"(expected {sl_path}) -- skipping this state.")
            continue
        with open(sl_path, encoding="utf-8") as f:
            sessions = (json.load(f).get("sessions", []) or [])

        # Union of MinYear/MaxYear across every matched person in this state.
        lo = min(target_years[p["BioguideId"]][0] for p in
                  (people_id_to_person[pid] for pid in pids) if p["BioguideId"] in target_years)
        hi = max(target_years[p["BioguideId"]][1] for p in
                  (people_id_to_person[pid] for pid in pids) if p["BioguideId"] in target_years)

        relevant = [
            s for s in sessions
            if s.get("year_start") and s.get("year_end")
            and not (s["year_end"] < lo or s["year_start"] > hi)
        ]
        needed_sessions[state] = {s["session_id"] for s in relevant}
        print(f"  {state}: {len(relevant)} session(s) needed (years {lo}-{hi})")

    total_sessions = sum(len(v) for v in needed_sessions.values())
    print(f"\n{total_sessions} total (state, session) pairs needed across "
          f"{len(needed_sessions)} states.")

    # Fetch each state's dataset list (cheap, 1 call/state) to get access_keys.
    print("\nFetching dataset lists (for access_keys)...")
    dataset_lists = {}
    for state in needed_sessions:
        data = cached_json_call("getDatasetList", key, f"datasetlist_{state}",
                                 SESSION_CACHE_DIR, state=state)
        dataset_lists[state] = {d["session_id"]: d for d in data.get("datasetlist", []) or []}

    # Download (or reuse cached) ZIPs, then parse bills out of each.
    os.makedirs(DATASET_CACHE_DIR, exist_ok=True)
    missing = []
    rows = []
    n = 0
    for state, session_ids in needed_sessions.items():
        target_ids_this_state = state_to_ids[state]
        for sid in sorted(session_ids):
            n += 1
            if n % 10 == 0 or n == total_sessions:
                print(f"  ...{n}/{total_sessions} (state,session) pairs processed")

            ds_info = dataset_lists[state].get(sid)
            if ds_info is None:
                missing.append({"State": state, "SessionId": sid,
                                 "Reason": "no dataset published for this session"})
                continue

            zip_path = os.path.join(DATASET_CACHE_DIR, f"{state}_{sid}.zip")
            if os.path.exists(zip_path):
                with open(zip_path, "rb") as f:
                    zip_bytes = f.read()
            else:
                resp = call("getDataset", key, id=sid, access_key=ds_info["access_key"])
                zip_b64 = resp.get("dataset", {}).get("zip", "")
                if not zip_b64:
                    missing.append({"State": state, "SessionId": sid,
                                     "Reason": f"getDataset returned no zip (status={resp.get('status')})"})
                    continue
                zip_bytes = base64.b64decode(zip_b64)
                with open(zip_path, "wb") as f:
                    f.write(zip_bytes)

            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
            bill_files = [nm for nm in zf.namelist() if "/bill/" in nm and nm.endswith(".json")]
            for bf in bill_files:
                try:
                    bill = json.loads(zf.read(bf).decode("utf-8")).get("bill", {})
                except (json.JSONDecodeError, KeyError):
                    continue
                for sp in bill.get("sponsors", []):
                    pid = str(sp.get("people_id", ""))
                    if pid not in target_ids_this_state:
                        continue
                    person = people_id_to_person[pid]
                    texts = bill.get("texts", []) or []
                    doc_ids = ";".join(str(t.get("doc_id")) for t in texts)
                    # Identify the Introduced-version text specifically (type_id
                    # 1, per LegiScan's docs -- confirmed against real bill
                    # records in probes 2 and 3). This is the version we'll
                    # fetch full text for in the next phase, to match how
                    # Congress.gov/CRS assigns topic labels from the bill as
                    # introduced. Falls back to the earliest-dated text on
                    # file if a bill has no type_id==1 entry (rare, but some
                    # states' oldest records are incomplete).
                    intro = next((t for t in texts if t.get("type_id") == 1), None)
                    if intro is None and texts:
                        intro = min(texts, key=lambda t: t.get("date") or "9999-99-99")
                    rows.append({
                        "Name": person["Name"], "BioguideId": person["BioguideId"],
                        "State": person["State"], "StateAbbr": state,
                        "PeopleId": pid, "SessionId": sid,
                        "SessionTitle": bill.get("session", {}).get("session_title", ""),
                        "BillId": bill.get("bill_id"), "BillNumber": bill.get("bill_number"),
                        "Title": bill.get("title", ""), "Description": bill.get("description", ""),
                        "Status": STATUS_MAP.get(bill.get("status"), bill.get("status")),
                        "StatusDate": bill.get("status_date", ""),
                        "CurrentBody": bill.get("current_body", ""),
                        "SponsorType": SPONSOR_TYPE_MAP.get(sp.get("sponsor_type_id"),
                                                             sp.get("sponsor_type_id")),
                        "SponsorOrder": sp.get("sponsor_order"),
                        "DocIds": doc_ids,
                        "IntroducedDocId": intro.get("doc_id") if intro else "",
                        "IntroducedDocType": intro.get("type") if intro else "",
                        "IntroducedDocDate": intro.get("date") if intro else "",
                        "IntroducedMime": intro.get("mime") if intro else "",
                        "IntroducedTextSize": intro.get("text_size") if intro else "",
                        "Url": bill.get("url", ""), "StateLink": bill.get("state_link", ""),
                    })

    fieldnames = ["Name", "BioguideId", "State", "StateAbbr", "PeopleId", "SessionId",
                  "SessionTitle", "BillId", "BillNumber", "Title", "Description", "Status",
                  "StatusDate", "CurrentBody", "SponsorType", "SponsorOrder", "DocIds",
                  "IntroducedDocId", "IntroducedDocType", "IntroducedDocDate", "IntroducedMime",
                  "IntroducedTextSize", "Url", "StateLink"]
    with open("state_legislation_sponsored.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    if missing:
        with open("legiscan_missing_datasets.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["State", "SessionId", "Reason"])
            w.writeheader()
            w.writerows(missing)

    print(f"\n=== Done ===")
    print(f"  {len(rows)} (person, bill) sponsorship rows written to state_legislation_sponsored.csv")
    print(f"  {len(missing)} (state, session) pairs had no dataset available "
          f"(see legiscan_missing_datasets.csv)" if missing else "  No missing datasets.")
    print("\nPlease send back state_legislation_sponsored.csv"
          + (" and legiscan_missing_datasets.csv" if missing else "")
          + " (legiscan_dataset_cache/ can stay local).")


if __name__ == "__main__":
    main()
