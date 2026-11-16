#!/usr/bin/env python3
"""
Every measure printed in the United States Statutes at Large from 1989 on (volumes 103-138, 101st-118th Congresses):
public and private laws with their primary bill, and adopted concurrent resolutions, from GovInfo's MODS metadata
(one file per volume, no PDFs). Used for Table 7's `passed` column, alongside Congress.gov's law lists
(fetch_laws.py): concurrent resolutions never go to the President, so they are on no law list, and Congress.gov's
law list omits some private laws. (For 1969-1988 the same evidence comes from fetch_statutes_text.py, which also
reads the texts.)

Output: federal_statutes_enacted.csv (Congress, BillType, BillNumber, GranuleClass, Law, GranuleId, Title, Volume).
`Law` is the first law named in the metadata, which for some granules is a law the measure amends: not used.
Cache: federal_statutes_cache/mods/ (shared with fetch_statutes_text.py). The key comes from CONGRESS_API_KEY.

USAGE (from the repo root):  python3 replication/scripts/federal/fetch_statutes_enacted.py
"""

import csv
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_statutes_text as F  # noqa: E402  (get, API, CACHE, NS)

VOLUMES = range(103, 139)
OUT = "federal_statutes_enacted.csv"


def main():
    rows = []
    for v in VOLUMES:
        path = os.path.join(F.CACHE, "mods", f"STATUTE-{v}.xml")
        data = F.get(f"{F.API}/packages/STATUTE-{v}/mods", path)
        if not data:
            print(f"  volume {v}: not available", flush=True)
            continue
        root = ET.parse(path).getroot()
        n = 0
        for item in root.findall("m:relatedItem[@type='constituent']", F.NS):
            ext = item.find("m:extension", F.NS)
            if ext is None:
                continue
            cls = (ext.findtext("m:granuleClass", default="", namespaces=F.NS) or "").strip()
            gid = (ext.findtext("m:accessId", default="", namespaces=F.NS) or "").strip()
            law = ext.find("m:law", F.NS)
            lawname = (f"{'Private' if law.get('isPrivate') == 'true' else 'Public'} Law {law.get('congress')}-{law.get('number')}"
                       if law is not None else "")
            title = " ".join((item.findtext("m:titleInfo/m:title", default="", namespaces=F.NS) or "").split())
            for b in ext.findall("m:bill", F.NS):
                if b.get("priority") == "primary" and b.get("type") and b.get("number"):
                    rows.append([b.get("congress"), b.get("type").upper(), b.get("number"), cls, lawname, gid, title, v])
                    n += 1
        print(f"  volume {v}: {n} measures", flush=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["Congress", "BillType", "BillNumber", "GranuleClass", "Law", "GranuleId", "Title", "Volume"])
        w.writerows(rows)
    print(f"Wrote {OUT}: {len(rows)} measures")


if __name__ == "__main__":
    main()
