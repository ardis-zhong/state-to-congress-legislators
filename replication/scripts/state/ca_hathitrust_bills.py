#!/usr/bin/env python3
"""
California state bills, 1969-1988, from the OCR text of the Legislature's printed
bill volumes in HathiTrust (California state-text pilot, phase C; Ardis 2026-10-18).
PROTOTYPE: tested on sample volumes while the bulk dataset request is pending.

Each volume (one folder of page files, 00000001.txt ..., as HathiTrust's
"Text (.zip)" download unpacks) holds a range of bills, each printed as introduced
and usually again as amended. For every page that starts a bill:
  - the bill type and number come from the heading ("ASSEMBLY BILL ... No. 81");
  - the version is "Introduced" when the page has "Introduced by" and no
    "AMENDED IN ..." line; amended reprints are skipped;
  - the lead author comes from the Legislative Counsel's digest line,
    "<type> <number>, as introduced, <Author>." (e.g. "AB 22, as introduced, W.
    Brown."), which names exactly one author even when many members introduced it;
  - the text runs from that page to the page before the next bill start;
  - reprints of an introduced bill are skipped: the first printing is kept, because a
    reprint can name a later author (e.g. 1977 SB 84: Nejedly, reprinted as Rains).
No model in the loop: regular expressions over the OCR text only.

OUTPUT: one row per introduced bill found (volume, page, type, number, author as
printed, date, text) plus, per volume, the bill numbers in its range that were not
found, so gaps in the scanned series are recorded.

USAGE (from the repo root):
    python3 replication/scripts/state/ca_hathitrust_bills.py hathitrust_cache/<volume folder> [...]
"""

import csv
import glob
import os
import re
import sys

TYPES = {  # printed heading -> abbreviation used in digests and bill IDs
    "ASSEMBLY BILL": "AB", "SENATE BILL": "SB",
    "ASSEMBLY CONCURRENT RESOLUTION": "ACR", "SENATE CONCURRENT RESOLUTION": "SCR",
    "ASSEMBLY JOINT RESOLUTION": "AJR", "SENATE JOINT RESOLUTION": "SJR",
    "ASSEMBLY CONSTITUTIONAL AMENDMENT": "ACA", "SENATE CONSTITUTIONAL AMENDMENT": "SCA",
}
HEADING = re.compile(r"\b(" + "|".join(sorted(TYPES, key=len, reverse=True)) + r")\b")
NUMBER = re.compile(r"\bNo\.?\s*(\d{1,4})\b")
AMENDED = re.compile(r"AMENDED\s+IN\s+(ASSEMBLY|SENATE)", re.I)
DATE = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
                  r"\s+\d{1,2},\s*(19\d\d)")


def digest_author(text, abbr, num):
    """'SB 81, as introduced, Nejedly.' -> 'Nejedly'; keeps initials ('W. Brown') and drops
    the parenthetical drafting code some years print ('Badham (H.A.D.)')."""
    m = re.search(rf"\b{abbr}\s*{num}\s*[,.]\s*as\s+introduced\s*[,.]\s*((?:[A-Z]\.\s*)*[A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+)?)",
                  text)
    return " ".join(m.group(1).split()) if m else ""


def parse_volume(folder):
    pages = sorted(p for p in glob.glob(os.path.join(folder, "0*.txt")) if "colophon" not in p)
    text = [open(p, encoding="utf-8", errors="replace").read() for p in pages]
    starts = []
    for i, t in enumerate(text):
        head = t[:900]
        h = HEADING.search(head)
        n = NUMBER.search(head)
        if not (h and n) or "DIGEST" not in t and "Introduced by" not in head:
            continue
        version = "Amended" if AMENDED.search(head) else ("Introduced" if "Introduced by" in head else "Other")
        starts.append((i, TYPES[h.group(1)], int(n.group(1)), version))
    rows, seen = [], set()
    for k, (i, abbr, num, version) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(text)
        body = "\n".join(text[i:end])
        if version != "Introduced" or (abbr, num) in seen:
            continue  # amended versions, and reprints of an introduced bill (the first printing names
                      # the original introducer; a reprint can name a later author, e.g. 1977 SB 84)
        seen.add((abbr, num))
        d = DATE.search(text[i][:900])
        rows.append({"volume": os.path.basename(folder.rstrip("/")), "page": i + 1, "type": abbr, "number": num,
                     "author": digest_author(body[:6000], abbr, num), "date": d.group(0) if d else "",
                     "pages": end - i, "text": body})
    return rows


def main():
    out = []
    for folder in sys.argv[1:]:
        rows = parse_volume(folder)
        out.extend(rows)
        found = {(r["type"], r["number"]) for r in rows}
        main_type = max({r["type"] for r in rows}, key=lambda t: sum(r["type"] == t for r in rows)) if rows else ""
        nums = sorted(n for t, n in found if t == main_type)
        missing = [n for n in range(nums[0], nums[-1] + 1) if n not in nums] if nums else []
        print(f"{os.path.basename(folder)}: {len(rows)} introduced bills; {main_type} {nums[:1]}..{nums[-1:]}; "
              f"no author: {sum(1 for r in rows if not r['author'])}; missing numbers: {missing}")
    with open("ca_hathitrust_sample.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[k for k in out[0] if k != "text"], extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
