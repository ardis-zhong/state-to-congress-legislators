#!/usr/bin/env python3
"""
Committee referrals for every sponsored federal bill and resolution (Table 7's `committees` column).

  108th Congress (2003) on   GPO's official Bill Status bulk data (govinfo.gov/bulkdata/BILLSTATUS/<congress>/<type>/
                             BILLSTATUS-<congress>-<type>.zip; one XML per measure, <committees><item> with name, chamber,
                             systemCode and activities such as 'Referred To' with dates). No key needed.
  93rd-107th (1973-2002)     Congress.gov's per-measure committees list (api.congress.gov/v3/bill/<c>/<type>/<n>/committees),
                             the same information for the years the bulk data does not cover. Key from CONGRESS_API_KEY.
  91st-92nd (1969-1972)      none: Congress.gov has no records for these Congresses, and the Congressional Bills Project
                             file used for them has no committee field.

Both sources list every full committee the measure was referred to or acted on (subcommittees are kept in the detail
file only). Congress.gov names committees by their current names (a 1988 bill shows 'Health, Education, Labor, and
Pensions'); the systemCode (e.g. sshr00) identifies the committee across renamings.

Output: federal_bill_committees.csv (Congress, Type, Number, Chamber, Committee, SystemCode, Activities, Subcommittees),
one row per measure and committee; measures with no committee (e.g. privileged resolutions) have no row.
Cache: federal_committees_cache/ (symlink to T9; billstatus/ zips, api/ JSON; resumable).

USAGE (from the repo root):  python3 replication/scripts/federal/fetch_committees.py
"""

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor

STATUS = "sponsored_legislation_full_status.csv"
CACHE = "federal_committees_cache"
OUT = "federal_bill_committees.csv"
BULK = "https://www.govinfo.gov/bulkdata/BILLSTATUS"
API = "https://api.congress.gov/v3/bill"
UA = {"User-Agent": "state-to-congress-legislators/1.0 (research dataset)"}
FIRST_BULK = 108
WORKERS = 12   # ~4 s per answer -> ~3 requests a second (the key allows 20,000 an hour)


def fetch(url, dest, binary=True):
    if os.path.exists(dest):
        return open(dest, "rb").read()
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r:
                data = r.read()
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".part"
            open(tmp, "wb").write(data)
            os.replace(tmp, dest)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            time.sleep(120 * (attempt + 1) if e.code == 429 else 15 * (attempt + 1))
        except Exception:
            time.sleep(15 * (attempt + 1))
    print(f"  could not fetch {url.split('api_key')[0]}", flush=True)
    return None


def bulk_rows(congress, typ, wanted):
    """Committee rows for the wanted numbers of one Congress and type, from the Bill Status zip."""
    data = fetch(f"{BULK}/{congress}/{typ.lower()}/BILLSTATUS-{congress}-{typ.lower()}.zip",
                 os.path.join(CACHE, "billstatus", f"BILLSTATUS-{congress}-{typ.lower()}.zip"))
    if not data:
        return [], set()
    out, seen = [], set()
    z = zipfile.ZipFile(os.path.join(CACHE, "billstatus", f"BILLSTATUS-{congress}-{typ.lower()}.zip"))
    for name in z.namelist():
        num = name.rsplit(typ.lower(), 1)[-1].replace(".xml", "")
        if num not in wanted:
            continue
        seen.add(num)
        bill = ET.fromstring(z.read(name)).find("bill")
        if bill is None:
            continue
        for item in bill.findall("committees/item"):
            acts = [f"{(a.findtext('name') or '').strip()} {(a.findtext('date') or '')[:10]}".strip()
                    for a in item.findall("activities/item")]
            subs = [(s.findtext("name") or "").strip() for s in item.findall("subcommittees/item")]
            out.append([str(congress), typ, num, (item.findtext("chamber") or "").strip(),
                        (item.findtext("name") or "").strip(), (item.findtext("systemCode") or "").strip(),
                        "; ".join(acts), "; ".join(s for s in subs if s)])
    return out, seen


def api_rows(k):
    c, t, n = k
    key = os.environ.get("CONGRESS_API_KEY") or sys.exit("Set CONGRESS_API_KEY in the environment")
    dest = os.path.join(CACHE, "api", f"{c}_{t}_{n}.json")
    raw = fetch(f"{API}/{c}/{t.lower()}/{n}/committees?format=json&limit=250&api_key={key}", dest)
    if raw is None:
        return k, None
    d = json.loads(raw) if raw else {}
    out = []
    for item in d.get("committees", []) or []:
        acts = [f"{a.get('name', '')} {(a.get('date') or '')[:10]}".strip() for a in item.get("activities", []) or []]
        subs = [s.get("name", "") for s in item.get("subcommittees", []) or []]
        out.append([c, t, n, item.get("chamber", ""), item.get("name", ""), item.get("systemCode", ""),
                    "; ".join(acts), "; ".join(s for s in subs if s)])
    return k, out


def main():
    todo = set()
    with open(STATUS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["ItemCategory"] == "Bill/Resolution":
                todo.add((r["Congress"], r["Type"].upper(), r["Number"]))
    rows, missing = [], []
    bulk = {}
    for c, t, n in todo:
        if int(c) >= FIRST_BULK:
            bulk.setdefault((int(c), t), set()).add(n)
    print(f"{len(todo)} measures: {sum(len(v) for v in bulk.values())} from Bill Status bulk data, "
          f"{len(todo) - sum(len(v) for v in bulk.values())} from the Congress.gov API", flush=True)
    for (c, t), wanted in sorted(bulk.items()):
        got, seen = bulk_rows(c, t, wanted)
        rows += got
        missing += [(str(c), t, n) for n in wanted - seen]   # not in the zip (e.g. very recent): use the API
        print(f"  bulk {c} {t}: {len(seen)}/{len(wanted)} measures, {len(got)} committee rows", flush=True)
    api_todo = sorted([k for k in todo if int(k[0]) < FIRST_BULK] + missing, key=lambda k: (int(k[0]), k[1], int(k[2])))
    print(f"API: {len(api_todo)} measures", flush=True)
    failed = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        for i, (k, got) in enumerate(pool.map(api_rows, api_todo), 1):
            if got is None:
                failed += 1
            else:
                rows += got
            if i % 2000 == 0:
                print(f"  ...{i}/{len(api_todo)}", flush=True)
    rows.sort(key=lambda r: (int(r[0]), r[1], int(r[2]) if r[2].isdigit() else 0, r[3], r[4]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Congress", "Type", "Number", "Chamber", "Committee", "SystemCode", "Activities", "Subcommittees"])
        w.writerows(rows)
    print(f"Wrote {OUT}: {len(rows)} committee rows for {len({tuple(r[:3]) for r in rows})} measures; "
          f"{failed} measures could not be fetched", flush=True)


if __name__ == "__main__":
    main()
