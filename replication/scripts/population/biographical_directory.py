"""
Split the text of the 2005 Biographical Directory (from
fetch_biographical_directory.py) into biographies and tie each to a Bioguide ID.

A biography starts with a line like "CHAFEE, John Hubbard (father of Lincoln
Chafee), a" followed by "Senator from Rhode Island; born in ...". It is matched
to a member of Congress only when all of these agree with the official
congress-legislators records: last name, a state the member represented, birth
year (every biography gives "born ... <year>"), and first name, nickname or
middle name. That rules out namesakes, e.g. Al Green and Gene Green (both
Texas, both born 1947).
"""

import glob
import re
import unicodedata

CACHE_GLOB = "bioguide2005_cache/GPO-CDOC-108hdoc222-4-*.txt"
STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
          "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
          "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
          "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
          "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
          "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
          "West Virginia", "Wisconsin", "Wyoming", "American Samoa", "Guam", "Puerto Rico", "Virgin Islands",
          "District of Columbia", "Northern Mariana Islands"]
POSTAL = dict(zip(STATES, "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
                          "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AS GU PR VI DC MP".split()))
# surnames are printed in capitals, with a lowercase letter only in prefixes ("McCORMACK", "AuCOIN")
START = re.compile(r"^((?:[A-Z][a-z]{1,2})?[A-Z][A-Z'’ .\-]{1,40}?)(?:, (?:Jr\.|Sr\.|II|III|IV))?, ([A-Z][^\n]*)")
ROLE = re.compile(r"\b(?:a|an) (?:Representative|Senator|Delegate|Resident Commis)")
FROM_STATE = re.compile(r"\b(?:a|an) (?:Representative|Senator|Delegate|Resident Commissioner)[^;]{0,80}? from "
                        r"(?:the )?(" + "|".join(STATES) + r")")
# a heading the line-based split missed: "... interment in X Cemetery. SMITH, John, a"
NEXT_HEADING = re.compile(r"[.)]\s+[A-Z][A-Z'’\-]+(?: [A-Z][A-Z'’\-]+)*,(?: Jr\.,| Sr\.,)? [A-Z][a-z]+")


def norm(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower())


def join_lines(lines):
    """Join a biography's lines, re-joining words hyphenated across lines (but not year ranges)."""
    text = ""
    for ln in lines:
        if text.endswith("-") and not (ln[:1].isdigit() and text[-2:-1].isdigit()):
            text = text[:-1] + ln
        else:
            text += " " + ln
    return " ".join(text.split())


def biographies():
    """Yield (surname as printed, biography text, postal state) for every biography."""
    for path in sorted(glob.glob(CACHE_GLOB)):
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        chunks, cur = [], None
        for i, ln in enumerate(lines):
            m = START.match(ln)
            # the "a Representative from" phrase can follow a long parenthetical (up to 3 lines)
            two = " ".join(lines[i:i + 3])
            # "." in the surname would be a degree line ("M.A., Case Western ...")
            if m and "." not in m.group(1) and len(m.group(1).replace(" ", "")) >= 2 and ROLE.search(two):
                if cur:
                    chunks.append(cur)
                cur = [m.group(1), ln]
            elif cur:
                cur.append(ln)
        if cur:
            chunks.append(cur)
        for chunk in chunks:
            text = join_lines(chunk[1:])
            st = FROM_STATE.search(text[:400])
            if not st:
                continue
            nxt = NEXT_HEADING.search(text[60:])
            if nxt:
                text = text[:60 + nxt.start() + 1]
            yield chunk[0], text, POSTAL[st.group(1)]


def match_biographies(people, wanted):
    """people: congress-legislators records; wanted: Bioguide IDs to look up.
    Returns {bioguide_id: biography text} for each wanted member with exactly one matching biography."""
    by_last = {}
    for p in people:
        if p["id"]["bioguide"] in wanted:
            by_last.setdefault(norm(p["name"]["last"]), []).append(p)
    found = {}
    for surname, text, state in biographies():
        born = re.search(r"\bborn\b.{0,160}?\b(1[89]\d\d)\b", text[:500])
        if not born:
            continue
        head = norm(text[:160])
        for p in by_last.get(norm(surname), []):
            states = {t["state"] for t in p["terms"]}
            nm = p["name"]
            given = any(norm(nm.get(k, "")) and norm(nm.get(k, "")) in head for k in ("first", "nickname", "middle"))
            if state in states and p.get("bio", {}).get("birthday", "")[:4] == born.group(1) and given:
                found.setdefault(p["id"]["bioguide"], []).append(text)
    # a biography can appear twice in the extracted text (page overlap): same opening = same one
    return {bg: texts[0] for bg, texts in found.items() if len({t[:200] for t in texts}) == 1}
