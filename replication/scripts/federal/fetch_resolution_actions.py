#!/usr/bin/env python3
"""
Whether each sponsored simple or concurrent resolution was adopted, from its full action history on Congress.gov
(api.congress.gov/v3/bill/<congress>/<type>/<number>/actions), for Table 7's `passed` column.

Table 7 otherwise reads a resolution's status from its latest recorded action only, and for resolutions that is
usually a step after the vote: 'Motion to reconsider laid on the table Agreed to without objection.' (House, right
after agreeing to a resolution), 'Message on Senate action sent to the House.', or the older 'Measure passed House.'.
The action history carries the Library of Congress's standard action codes, which settle it:

  8000   Passed/agreed to in House          17000  Passed/agreed to in Senate
  21000  Conference report agreed to in House   23000  Conference report agreed to in Senate

  simple resolution (HRES, SRES)       adopted = agreed to in its own chamber (8000 / 17000)
  concurrent resolution (HCONRES, SCONRES)  adopted = agreed to in both chambers; if the second chamber amended
                                       it ('with an amendment', 'amended'), the differences must have been resolved
                                       too: conference report agreed to in both (21000 and 23000), or a 'Resolving
                                       differences' action in which a chamber agreed to / concurred in the other's
                                       amendment

Only resolutions whose latest action is past committee are fetched (latest action 'Introduced', 'Referred to
Committee', 'Reported by Committee / On Calendar' or 'Held at the Desk' means no floor vote followed).

Output: federal_resolution_actions.csv (Congress, Type, Number, AgreedHouse, AgreedSenate, SecondAmended,
DifferencesResolved, Adopted). Cache: federal_actions_cache/ (one JSON per resolution; resumable). The key comes from
CONGRESS_API_KEY. About 11,000 requests, ~1.5 hours (8 at a time).

USAGE (from the repo root):  python3 replication/scripts/federal/fetch_resolution_actions.py
"""

import csv
import json
from concurrent.futures import ThreadPoolExecutor
import os
import re
import sys
import time
import urllib.error
import urllib.request

API = "https://api.congress.gov/v3/bill"
STATUS = "sponsored_legislation_full_status.csv"
CACHE = "federal_actions_cache"
OUT = "federal_resolution_actions.csv"
TYPES = {"HRES", "SRES", "HCONRES", "SCONRES"}
SKIP = {"Introduced", "Referred to Committee", "Reported by Committee / On Calendar", "Held at the Desk"}
WORKERS = 8   # Congress.gov answers in ~4 s; 8 at a time is ~2 requests a second (the key allows 20,000 an hour)


def get(url, dest):
    if os.path.exists(dest):
        return json.load(open(dest, encoding="utf-8"))
    key = os.environ.get("CONGRESS_API_KEY") or sys.exit("Set CONGRESS_API_KEY in the environment")
    for attempt in range(6):
        try:
            req = urllib.request.Request(f"{url}&api_key={key}",
                                         headers={"User-Agent": "state-to-congress-legislators/1.0 (research dataset)"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".part"
            json.dump(data, open(tmp, "w", encoding="utf-8"))
            os.replace(tmp, dest)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"actions": []}
            time.sleep(120 * (attempt + 1) if e.code == 429 else 15 * (attempt + 1))
        except Exception:
            time.sleep(15 * (attempt + 1))
    print(f"  could not fetch {url}", flush=True)
    return None


def actions(c, t, n):
    out, offset = [], 0
    while True:
        d = get(f"{API}/{c}/{t.lower()}/{n}/actions?format=json&limit=250&offset={offset}",
                os.path.join(CACHE, f"{c}_{t}_{n}_{offset}.json"))
        if d is None:
            return None
        acts = d.get("actions", [])
        out += acts
        total = (d.get("pagination") or {}).get("count", len(out))
        offset += 250
        if not acts or offset >= total:
            return out


def classify(t, acts):
    loc = [(a.get("actionDate", ""), str(a.get("actionCode") or ""), a.get("text", "")) for a in acts
           if (a.get("sourceSystem") or {}).get("name") == "Library of Congress"]
    house = sorted(d for d, code, _ in loc if code == "8000")
    senate = sorted(d for d, code, _ in loc if code == "17000")
    if t in ("HRES", "SRES"):
        ok = bool(house) if t == "HRES" else bool(senate)
        return bool(house), bool(senate), False, False, ok
    if not house or not senate:
        return bool(house), bool(senate), False, False, False
    # the second chamber's vote: the later of the two first agreements
    second_code = "17000" if senate[0] >= house[0] else "8000"
    second_text = " ".join(txt for d, code, txt in loc if code == second_code)
    amended = re.search(r"with an amendment|amended", second_text, re.I) is not None
    resolved = False
    if amended:
        conf = {code for _, code, _ in loc}
        resolved = ("21000" in conf and "23000" in conf) or any(
            re.search(r"Resolving differences", txt, re.I)
            and re.search(r"(?<!dis)agreed to|(?<!not )concurred in|Agreed to", txt)
            and not re.search(r"disagree|Failed|not agreed|insist", txt, re.I) for _, _, txt in loc)
    return True, True, amended, resolved, (not amended) or resolved


def main():
    todo = []
    with open(STATUS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = r["Type"].upper()
            if r["ItemCategory"] == "Bill/Resolution" and t in TYPES and r["BillStatus"] not in SKIP:
                todo.append((r["Congress"], t, r["Number"]))
    todo = sorted(set(todo), key=lambda k: (int(k[0]), k[1], int(k[2])))
    print(f"{len(todo)} resolutions to check", flush=True)
    with ThreadPoolExecutor(WORKERS) as pool:
        histories = {}
        for i, (k, acts) in enumerate(zip(todo, pool.map(lambda k: actions(*k), todo)), 1):
            histories[k] = acts
            if i % 500 == 0:
                print(f"  ...{i}/{len(todo)} fetched", flush=True)
    rows = []
    for i, (c, t, n) in enumerate(todo, 1):
        acts = histories[(c, t, n)]
        if acts is None:
            rows.append([c, t, n, "", "", "", "", "unavailable"])
            continue
        h, s, am, res, ok = classify(t, acts)
        rows.append([c, t, n, h, s, am, res, "Yes" if ok else "No"])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Congress", "Type", "Number", "AgreedHouse", "AgreedSenate", "SecondAmended", "DifferencesResolved",
                    "Adopted"])
        w.writerows(rows)
    print(f"Wrote {OUT}: {len(rows)} resolutions, adopted {sum(1 for r in rows if r[7] == 'Yes')}, "
          f"unavailable {sum(1 for r in rows if r[7] == 'unavailable')}", flush=True)


if __name__ == "__main__":
    main()
