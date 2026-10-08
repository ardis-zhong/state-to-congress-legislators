#!/usr/bin/env python3
"""
Flag military service (Table 2's veteran column) from the member biographies
in the Congressional Directory editions downloaded by
fetch_congressional_directory.py.

DEFINITION (decided 2026-10-07): any military service -- active duty,
Reserves, or National Guard, in any era -- counts.

METHOD -- keyword rules only, no model in the loop:
  1. Split each edition into member biographies and tie each one to a
     Bioguide ID. Newer editions (zip) tag every biography with the ID.
     Older editions (one OCR'd text file) are split at each "NAME, Party, of
     Town" heading, cut into state sections, and matched to the member who,
     per the official congress-legislators term records, served that state
     in that Congress and has that last name (first name / Jr. as tiebreaks).
  2. Cut each biography into clauses at ";" and look for military service:
     a service branch (Army, Navy, Marine Corps, Air Force, Coast Guard,
     National Guard, Reserve) next to a service word (served, enlisted,
     rank, discharged, ...), a war plus "served", "military service", or
     membership in a veterans' organization that requires service (American
     Legion, VFW, AMVETS, DAV). Look-alikes such as the Armed Services
     Committee, the Army Corps of Engineers, or "Secretary of the Navy" are
     removed first.
  3. A person is a veteran if any of their biographies, in any edition,
     has a matching clause; that clause is kept as evidence.
  4. A Yes supported only by text editions while every ID-tagged biography is
     silent is flagged for review; the decision for each flagged case is
     recorded in replication/data/reference/veteran_review.csv and applied here.

OUTPUT:
    replication/data/processed/veterans_by_bioguide.csv
        bioguide_id, veteran (Yes / No / Not found), editions_found,
        evidence (the first matching clause), evidence_edition

USAGE (from the repo root):
    python3 replication/scripts/population/extract_veterans.py
"""

import csv
import html
import io
import json
import os
import re
import unicodedata
import zipfile

CACHE_DIR = "cdir_cache"
PERSON_LEVEL = "replication/data/population/person_level.csv"
LEGISLATOR_FILES = ["legislators-current.json", "legislators-historical.json"]
OUT = "replication/data/processed/veterans_by_bioguide.csv"
# Ardis's decisions on cases the rules flag for review (see the "review" column).
REVIEW_DECISIONS = "replication/data/reference/veteran_review.csv"

STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
    "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM",
    "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}

# --- military-service rules -------------------------------------------------
EXCLUDE = re.compile(
    r"(Committee on (the )?(Armed Services|Veterans'? Affairs)|Armed Services Committee|"
    r"Veterans'? Affairs (Committee|Subcommittee)|Subcommittee on [^;]*Military Construction|"
    r"Army Corps of Engineers|Corps of Engineers|Navy League|Board of Visitors|"
    r"(Secretary|Department|Under ?secretary|Assistant Secretary) of the (Army|Navy|Air Force)|"
    r"(Military|Naval|Air Force|Coast Guard) Academy (Board|appointment|nominations?)|"
    r"Federal Reserve|National Guard Caucus|Reserve Components? Caucus|Military Families Caucus|"
    r"Executive Reserve|Army Medical Center|Naval (Hospital|Medical Center)|Service to Vet-?erans|"
    r"Paralyzed Vet-?erans|Vet-?erans of America)",
    re.I)
BRANCH = (r"(U\.? ?S\.? |United States |Army |Air )?"
          r"(Army|Navy|Naval|Marine Corps|Marines|Air Force|Coast Guard|National Guard|"
          r"Air National Guard|Army Air (Corps|Forces)|Reserves?)\b")
SERVICE = (r"(served|serving|service|enlisted|drafted|commissioned|veteran|discharged|retired|"
           r"active duty|duty|officer|pilot|aviator|navigator|paratrooper|infantry|combat|"
           r"private|corporal|sergeant|specialist|lieutenant|captain|major|colonel|general|"
           r"ensign|commander|admiral|seaman|airman|petty officer|warrant officer|JAG|"
           r"judge advocate|chaplain|surgeon|medic|rank|reservist|guardsman|1st|2nd|2d|3rd|3d)")
POSITIVE = [
    re.compile(BRANCH + r"[^;]{0,80}?\b" + SERVICE, re.I),
    re.compile(r"\b" + SERVICE + r"\b[^;]{0,80}?\b" + BRANCH, re.I),
    re.compile(r"\bmilitary service\b|\bserved in the military\b|\bU\.? ?S\.? ?(Army|Navy|Marine Corps|"
               r"Air Force|Coast Guard)\b", re.I),
    re.compile(r"\b(served|service|veteran)\b[^;]{0,60}?\b(World War II|World War I|Korean (War|"
               r"conflict)|Vietnam|Persian Gulf|Desert Storm|Operation \w+ Freedom|Iraq|Afghanistan)",
               re.I),
]
# Membership in a veterans' organization that requires military service. Weaker
# evidence than a service statement: only a clause that says "member" counts,
# and awards, auxiliaries, and the VFW National Home (a charity) do not.
VET_ORG = re.compile(r"\bmember\b[^;]{0,120}?\b(American Legion|Veterans of Foreign Wars|VFW|AMVETS|"
                     r"Disabled American Veterans|Vietnam Veterans of America|"
                     r"Military Order of the Purple Heart)\b", re.I)
VET_ORG_NOT = re.compile(r"award|recipient|named|honou?r|medal|auxiliary|National Home|citation", re.I)


def military_clause(bio):
    """Return (clause, evidence_type) for the strongest evidence of military service in a
    biography: a service statement beats veterans'-organization membership. ('', '') if none."""
    org = ""
    for clause in re.split(r";", bio):
        if re.match(r"\s*(born|bom)\b", clause):  # birthplace, e.g. "born at ... Army Medical Center"
            continue
        cleaned = EXCLUDE.sub(" ", clause)
        text = re.sub(r"\s+", " ", clause).strip()
        if any(p.search(cleaned) for p in POSITIVE):
            return text, "service"
        if not org and VET_ORG.search(cleaned) and not VET_ORG_NOT.search(cleaned):
            org = text
    return (org, "veterans' organization member") if org else ("", "")


# --- helpers ----------------------------------------------------------------
def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def plain(markup):
    t = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"([a-z])- ([a-z])", r"\1\2", t)  # re-join words hyphenated across lines


def congress_of(edition_id):
    year = int(edition_id.split("-")[1])
    return (year - 1787) // 2


# --- newer editions: one biography per member, tagged with Bioguide ID ------
def bios_from_zip(path, serving_by_state):
    """The edition's mods.xml has one <relatedItem type="constituent"> per granule;
    biography granules carry the member's bioGuideId and point to html/<granule>.htm.
    Some editions leave a state's biographies inside the untagged state-delegation
    granule (e.g. New Mexico in 2022); those are parsed by name and state like the
    older editions, for members not already found in this edition."""
    seen = set()
    untagged = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        mods_name = next(n for n in names if n.endswith("/mods.xml") and n.count("/") == 1)
        mods = z.read(mods_name).decode("utf-8", errors="replace")
        edition_dir = mods_name.split("/")[0]
        for block in re.split(r'<relatedItem type="constituent"', mods)[1:]:
            gid = re.search(r'ID="id-([^"]+)"', block)
            title = re.search(r"<title>([^<]*)</title>", block)
            ids = set(re.findall(r'bioGuideId="([A-Z]\d{6})"', block))
            if not gid:
                continue
            htm = f"{edition_dir}/html/{gid.group(1)}.htm"
            if htm not in names:
                continue
            if title and "Biography" in title.group(1) and len(ids) == 1:
                bg = ids.pop()
                seen.add(bg)
                yield bg, plain(z.read(htm).decode("utf-8", errors="replace"))
            elif not ids:
                untagged.append(htm)
        text = " ".join(plain(z.read(h).decode("utf-8", errors="replace")) for h in untagged)
    for bg, bio in bios_from_text(text, serving_by_state):
        if bg not in seen:
            seen.add(bg)
            yield bg, bio


# --- older editions: one OCR'd text file ------------------------------------
NAME_TOKEN = r"(?:[A-Z][A-Za-z'.\-]*|\([A-Za-z. ]+\)|JR\.|SR\.|Jr\.|Sr\.|II|III|IV)"
BIO_START = re.compile(
    r"(" + NAME_TOKEN + r"(?:,? " + NAME_TOKEN + r"){1,7}), "
    r"((?:Democrat|Republican|Independent|Conservative|Liberal|Popular|New Progressive)"
    r"[A-Za-z\- ]{0,30}?),? (?:of |from )?(?=[A-Z])")
STATE_HEAD = re.compile(r"\b(" + "|".join(sorted(STATES, key=len, reverse=True)) + r") \(Population")


def caps_name(raw):
    """Keep the trailing all-caps run of a heading ('Population VIC FAZIO' -> 'VIC FAZIO')."""
    toks = raw.replace(",", " ").split()
    out = []
    for tok in reversed(toks):
        core = re.sub(r"[^A-Za-z]", "", tok)
        if core and (core.isupper() or core in ("Jr", "Sr")
                     or re.fullmatch(r"Mc[A-Z]+|Mac[A-Z]+|De[A-Z]+|La[A-Z]+", core)) \
                or tok.startswith("("):
            out.append(tok)
        else:
            break
    return " ".join(reversed(out))


# Older editions write the home state as an abbreviation ("of Russell, Kans."),
# newer ones as a postal code ("of Philadelphia, PA").
OLD_ABBR = {
    "ala": "AL", "alaska": "AK", "ariz": "AZ", "ark": "AR", "calif": "CA", "colo": "CO", "conn": "CT",
    "del": "DE", "fla": "FL", "ga": "GA", "hawaii": "HI", "idaho": "ID", "ill": "IL", "ind": "IN",
    "iowa": "IA", "kans": "KS", "kan": "KS", "ky": "KY", "la": "LA", "maine": "ME", "md": "MD",
    "mass": "MA", "mich": "MI", "minn": "MN", "miss": "MS", "mo": "MO", "mont": "MT", "nebr": "NE",
    "neb": "NE", "nev": "NV", "nh": "NH", "nj": "NJ", "nmex": "NM", "nm": "NM", "ny": "NY", "nc": "NC",
    "ndak": "ND", "nd": "ND", "ohio": "OH", "okla": "OK", "oreg": "OR", "ore": "OR", "pa": "PA",
    "ri": "RI", "sc": "SC", "sdak": "SD", "sd": "SD", "tenn": "TN", "tex": "TX", "utah": "UT",
    "vt": "VT", "va": "VA", "wash": "WA", "wva": "WV", "wis": "WI", "wyo": "WY",
}
POSTAL = set(STATES.values())


def state_from_bio(after_of):
    """'Russell, Kans.; born ...' -> 'KS'. Uses the text between the town and 'born'."""
    head = re.split(r"\bborn\b|\bbom\b", after_of)[0]  # 'bom' = OCR'd 'born'
    parts = [p.strip() for p in re.split(r"[,;]", head) if p.strip()]
    for part in reversed(parts[1:] or parts):
        word = part.strip(" .")
        if word.upper() in POSTAL and len(word) == 2:
            return word.upper()
        key = re.sub(r"[^a-z]", "", word.lower())
        if key in OLD_ABBR:
            return OLD_ABBR[key]
        if word.upper() in STATES:
            return STATES[word.upper()]
    return None


def bios_from_txt(path, serving_by_state):
    raw = open(path, "rb").read()
    try:
        text = raw.decode("utf-8")  # 2024+ editions
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")  # older OCR'd editions
    yield from bios_from_text(plain(text), serving_by_state)


def bios_from_text(text, serving_by_state):
    heads = [(m.start(), STATES[m.group(1)]) for m in STATE_HEAD.finditer(text)]
    starts = list(BIO_START.finditer(text))
    seps = [m.start() for m in re.finditer(r"\*\s?\*\s?\*", text)]
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        # newer editions separate biographies with "* * *": never read past one
        nxt = next((s for s in seps if s > m.end()), None)
        if nxt is not None and nxt < end:
            end = nxt
        state = state_from_bio(text[m.end():m.end() + 120])
        if not state:  # fall back to the nearest preceding state heading
            for pos, st in heads:
                if pos <= m.start():
                    state = st
        name = caps_name(m.group(1))
        if not state or not name:
            continue
        bg = match_name(name, serving_by_state.get(state, {}))
        if bg:
            yield bg, text[m.start():end]


def match_name(name, serving):
    toks = [norm(t) for t in re.sub(r"\([^)]*\)", " ", name).split() if norm(t)]
    toks = [t for t in toks if t not in ("jr", "sr", "ii", "iii", "iv")]
    if not toks:
        return None
    tails = {"".join(toks[-k:]) for k in (1, 2, 3)}  # 'DE LA GARZA' -> 'delagarza'
    cands = {bg for bg, p in serving.items() if norm(p["name"]["last"]) in tails}
    if len(cands) > 1:
        given = set(toks) | {norm(x) for x in re.findall(r"\(([^)]*)\)", name)}
        cands = {bg for bg in cands
                 if any(norm(serving[bg]["name"].get(k, "")) in given
                        for k in ("first", "nickname", "middle") if serving[bg]["name"].get(k))}
    if len(cands) > 1:
        is_jr = "JR" in name.upper().replace(".", " ").split()
        cands = {bg for bg in cands if ("jr" in norm(serving[bg]["name"].get("suffix", ""))) == is_jr}
    return cands.pop() if len(cands) == 1 else None


def main():
    with open(PERSON_LEVEL, newline="", encoding="utf-8") as f:
        population = [r["BioguideId"] for r in csv.DictReader(f)]
    people = []
    for path in LEGISLATOR_FILES:
        with open(path, encoding="utf-8") as f:
            people.extend(json.load(f))

    found = {bg: [] for bg in population}  # bg -> [(edition, (clause, evidence_type))]
    birth = {p["id"]["bioguide"]: int(p.get("bio", {}).get("birthday", "0")[:4] or 0) for p in people}
    discarded = []
    editions = sorted(f for f in os.listdir(CACHE_DIR) if f.startswith("CDIR-") and f.endswith((".txt", ".zip")))
    for fname in editions:
        edition = fname.rsplit(".", 1)[0]
        congress = congress_of(edition)
        start, end = f"{1787 + 2 * congress}-01-03", f"{1789 + 2 * congress}-01-03"
        serving_by_state = {}
        for p in people:
            for t in p["terms"]:
                if t["start"] < end and t["end"] > start:
                    serving_by_state.setdefault(t["state"], {})[p["id"]["bioguide"]] = p
        path = os.path.join(CACHE_DIR, fname)
        bios = (bios_from_zip(path, serving_by_state) if fname.endswith(".zip")
                else bios_from_txt(path, serving_by_state))
        n = 0
        for bg, bio in bios:
            n += 1
            if bg in found:
                clause, kind = military_clause(bio)
                # Guard against text from a neighbouring biography (OCR / missed headings):
                # drop evidence dated before the person turned 16.
                years = [int(y) for y in re.findall(r"\b(19\d\d|20[0-2]\d)\b", clause)]
                if clause and birth.get(bg) and years and min(years) < birth[bg] + 16:
                    discarded.append((bg, edition, clause[:100]))
                    clause, kind = "", ""
                found[bg].append((edition, (clause, kind), fname.endswith(".zip")))
        print(f"{edition}: {n} biographies matched")

    with open(REVIEW_DECISIONS, newline="", encoding="utf-8") as f:
        decisions = {r["bioguide_id"]: r for r in csv.DictReader(f)}
    counts = {}
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["bioguide_id", "veteran", "evidence_type", "editions_found", "evidence",
                    "evidence_edition", "review"])
        for bg in population:
            hits = [(e, c, tagged) for e, c, tagged in found[bg] if c[0]]
            # service statements first, and ID-tagged biographies before scanned/text ones
            hits.sort(key=lambda h: (h[1][1] != "service", not h[2]))
            status = "Yes" if hits else ("No" if found[bg] else "Not found")
            counts[status] = counts.get(status, 0) + 1
            e, (clause, kind), _ = hits[0] if hits else ("", ("", ""), False)
            # Text editions can merge a neighbour's biography into this one (dropped pages).
            # Flag a Yes that only text editions support while every ID-tagged biography is silent.
            tagged = [c for _, c, is_tagged in found[bg] if is_tagged]
            review = ("evidence only in text editions; ID-tagged biographies don't mention service"
                      if hits and tagged and not any(c[0] for c in tagged) else "")
            if bg in decisions:
                status, review = decisions[bg]["veteran"], decisions[bg]["decision_note"]
                counts["Yes" if hits else "No"] -= 1
                counts[status] = counts.get(status, 0) + 1
                if status == "No":
                    kind = clause = e = ""
            elif review:
                print(f"  NEEDS REVIEW (no decision recorded): {bg} {clause[:80]}")
            w.writerow([bg, status, kind, len(found[bg]), clause, e, review])
    print("Result:", counts)
    for d in discarded:
        print("  discarded (service year before age 16):", *d)


if __name__ == "__main__":
    main()
