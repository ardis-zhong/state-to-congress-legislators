#!/usr/bin/env python3
"""
LegiScan reconnaissance script -- run this BEFORE any full state-bill
extraction.

WHY THIS STEP EXISTS:
Unlike Congress.gov, LegiScan's archives do not go back to 1979 for any
state -- how far back varies state by state (Texas's archive, for example,
only starts in 2009). Before spending time building a 910-person name-
matching pipeline and running a full extraction, we need to know:

  1. How far back each of the 50 states' LegiScan archives actually go,
     so we know which of our 910 legislators have ANY state-legislature
     years that fall inside LegiScan's coverage window at all.
  2. The exact JSON shape of getSessionPeople / getPerson / getSponsoredList
     (LegiScan's closest analog to Congress.gov's sponsored-legislation
     endpoint), confirmed against one real response rather than assumed
     from documentation, before any pipeline code is written against it.

This script makes a small, cheap number of API calls (well under the free
30,000/month cap) and writes two output files:
  - legiscan_state_coverage.csv  (one row per state: earliest/latest
    session year, number of sessions on file)
  - legiscan_schema_probe.json   (one real getSessionPeople response, one
    real getPerson response, and one real getSponsoredList response, for
    inspection)

USAGE:
    python3 legiscan_coverage_check.py YOUR_LEGISCAN_API_KEY

Get a free API key (30,000 queries/month) by registering at
https://legiscan.com/user/register, then generating a key on your account
page. This is a separate key from the Congress.gov one used earlier.
"""

import csv
import json
import sys
import time
import urllib.error
import urllib.request

STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
]

MAX_RETRIES = 5


def call(op, key, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://api.legiscan.com/?key={key}&op={op}" + (f"&{qs}" if qs else "")
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sdsu-research-script/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(0.3)
            return data
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(1 * attempt)
    raise RuntimeError(f"Failed op={op} params={params} after {MAX_RETRIES} retries: {last_err}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 legiscan_coverage_check.py YOUR_LEGISCAN_API_KEY")
        sys.exit(1)
    key = sys.argv[1]

    print("=== Step 1: checking session archive depth for all 50 states + DC ===\n")
    rows = []
    ca_session_id = None
    for st in STATES:
        try:
            data = call("getSessionList", key, state=st)
        except Exception as e:  # noqa: BLE001
            print(f"{st}: ERROR ({e})")
            rows.append({"State": st, "EarliestSessionYear": "", "LatestSessionYear": "",
                         "NumSessions": 0, "Status": f"ERROR: {e}"})
            continue

        sessions = data.get("sessions", []) or []
        status = data.get("status", "")
        if not sessions:
            print(f"{st}: no sessions returned (status={status})")
            rows.append({"State": st, "EarliestSessionYear": "", "LatestSessionYear": "",
                         "NumSessions": 0, "Status": status})
            continue

        years = [s.get("year_start") for s in sessions if s.get("year_start")]
        earliest = min(years) if years else ""
        latest = max(years) if years else ""
        print(f"{st}: {earliest}-{latest}  ({len(sessions)} sessions on file)")
        rows.append({"State": st, "EarliestSessionYear": earliest, "LatestSessionYear": latest,
                     "NumSessions": len(sessions), "Status": status})

        if st == "CA" and sessions:
            # remember a real session_id for the schema probe below
            most_recent = max(sessions, key=lambda s: s.get("year_start", 0))
            ca_session_id = most_recent.get("session_id")

    with open("replication/data/reference/legiscan_state_coverage.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["State", "EarliestSessionYear", "LatestSessionYear",
                                           "NumSessions", "Status"])
        w.writeheader()
        w.writerows(rows)
    print("\nWrote legiscan_state_coverage.csv")

    print("\n=== Step 2: schema probe (getSessionPeople -> getPerson -> getSponsoredList) ===\n")
    probe = {}
    if ca_session_id is None:
        print("Could not find a California session_id to probe with -- skipping schema probe.")
    else:
        people_data = call("getSessionPeople", key, id=ca_session_id)
        probe["getSessionPeople"] = people_data
        people_list = (people_data.get("sessionpeople", {}) or {}).get("people", [])
        if people_list:
            first_person = people_list[0]
            pid = first_person.get("people_id")
            print(f"Probing person_id={pid} ({first_person.get('name')})")
            probe["getPerson"] = call("getPerson", key, id=pid)
            probe["getSponsoredList"] = call("getSponsoredList", key, id=pid)
        else:
            print("getSessionPeople returned no people -- skipping getPerson/getSponsoredList probe.")

    with open("legiscan_schema_probe.json", "w", encoding="utf-8") as f:
        json.dump(probe, f, indent=2)
    print("Wrote legiscan_schema_probe.json")

    print("\nDone. Please send back both legiscan_state_coverage.csv and "
          "legiscan_schema_probe.json.")


if __name__ == "__main__":
    main()
