#!/usr/bin/env python3
"""
Table 4's first_named column (Ardis, 2026-11-14): is the person the first sponsor named on the bill?

The state-archive sources keep a bill only when the person is named first (or is the legislature's single
lead sponsor). LegiScan's "Primary Sponsor", used from 2009 on, often covers several people per bill
(co-primes, joint authors, every co-introducer, committee members), so Table 4 keeps those rows and this
column says which ones name the person first. No model in the loop: one regular expression per state reads
the sponsor line printed on the bill's own text.

  Yes      the text's sponsor line names the person first; or the text prints no sponsor line and the
           source records the person as the bill's only lead sponsor (LegiScan's only primary sponsor, or
           the archive's lead-sponsor record, checked against the text where the text prints one)
  No       the sponsor line names someone else (another member or a committee) first
  Unknown  no sponsor line is printed and the source lists more than one lead sponsor

sponsor_line(state, bill_number, text) returns the printed list (lower case) or None;
first_entry() cuts its first name; is_first() compares it with the person's name.
"""

import re
import unicodedata

MONTH = r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
T = r"(?:representatives?|senators?|delegates?|assembly ?(?:wo)?m[ae]n|assembly members?|reps?\.|sens?\.)"

# state -> regular expressions on the normalized lower-case text; group 1 is the sponsor list
PATTERNS = {
    "AL": [rf"\bby {T} (.{{1,3500}}?)(?: rfd| first read| \d)"],
    "AR": [rf"\bby: {T} (.{{1,3500}}?)(?: by:| for an act| a bill| \d|$)"],
    "AZ": [rf"introduced by {T} (.{{1,3500}}?)(?: an act| a (?:concurrent|joint)| a resolution| a memorial|$)"],
    "CA": [r"\bauthors?: (.{1,3500}?)(?: \(principal| \(coauthors?| (?:coauthors?|principal coauthors?)[: ]| \d{4}-\d\d-\d\d| an act)",
           r"introduced by (.{1,3500}?)(?: \(principal| \(coauthors?| (?:coauthors?|principal coauthors?)[: ]| " + MONTH + r" \d{1,2},? \d{4}| \d{4}-\d\d-\d\d| an act| relative to| a resolution|$)"],
    "CO": [r"(?:house|senate) sponsorship (.{1,3500}?)(?:,? (?:house|senate) sponsorship|,? (?:house|senate) committees|$)",
           r"\bby (?:representatives?|senators?)(?:\(s\))? (.{1,3500}?)(?:; also| a bill|$)"],
    "DE": [r"\bsponsor: (.{1,3500}?)(?: additional sponsor| sens?\. [a-z\-']+[,;]| reps?\. [a-z\-']+[,;]| co-?sponsors?:|$)"],
    "FL": [r"\bby (?:the )?((?:[a-z]+ )?committees? on [a-z ,&]{1,80}?)(?:;| and | \d|$)",
           r"\bby (?:senators?|representatives?) (.{1,3500}?)(?: \d| a bill|$)"],
    "GA": [rf"\bby: {T} (.{{1,3500}}?)(?: a bill| a resolution| a joint|$)"],
    "IA": [r"\bby ((?:committee on [a-z ]+|[a-z][a-z'\-.=]*(?: ?,? (?:and )?[a-z][a-z'\-.=]*){0,160}))(?: \d+)*(?: a bill| a resolution| a joint| a concurrent| \(companion| passed)"],
    "IL": [r"introduced [^,]{0,40}, by (.{1,3500}?)(?: synopsis| - | \d|$)", r"\bby: (?:reps?\.|sens?\.) (.{1,3500}?)(?: synopsis|$)"],
    "IN": [rf"effective: .{{1,3500}}?\. ([a-z][^.]{{1,200}}?) {MONTH} \d", r"introduced by: ([a-z][^_]{1,200}?) _",
           r"digest of introduced resolution .{1,3500}? ([a-z][a-z ,\-']{1,200}?)\s*,?\s*(?:___\s*,?\s*)?(?:read first time|" + MONTH + ")"],
    "KS": [r"\bby (senators?|representatives?|(?:house |senate |joint )?committee on .{1,3500}?|[a-z ]+ committee)(?: |$)(.{0,200})"],
    "LA": [rf"\bby {T} ((?:[a-z]\. )?[a-z'\-]{{2,}}.{{0,250}}?)(?: an act| a resolution| a concurrent| a joint|:|$)"],
    "MA": [r"presented by:? (.{1,3500}?)(?: _{3,}| to the honorable|$)", r"\bby (m(?:r|rs|s)\. .{1,3500}?)(?:, a petition|\(|$)"],
    "MD": [rf"\bby: {T} (.{{1,3500}}?)(?: introduced and read| read and examined| requested:| \d|$)",
           r"\bby: (the (?:president|speaker)|chair, .{1,3500}?) "],
    "ME": [r"presented by (.{1,3500}?)(?:\. cosponsored|\. printed| cosponsored|$)"],
    "MI": [rf"introduced by {T} (.{{1,3500}}?)(?: and referred| referred|$)", rf"\b{T} (.{{1,3500}}?) offered the following"],
    "MN": [r"authored by (.{1,3500}?)(?: the bill was read| \d\d/\d\d/\d{4}|$)", r"\((?:senate|house) ?authors: ?(.{1,300}?)\)"],
    "MO": [rf"introduced by {T}(?: s)? (.{{1,3500}}?)(?:\. | read 1st| \(| \d|$)"],
    "MS": [rf"\bby: {T} (.{{1,3500}}?)(?: house bill| senate bill| [a-z]+ (?:concurrent|joint)| to | \d|$)"],
    "MT": [r"introduced by (.{1,3500}?)(?: \d| a bill| a joint| a resolution|$)"],
    "NC": [rf"sponsors?: {T} (.{{1,3500}}?)(?: \(primary sponsors?\)|\.? referred to|\.? $)"],
    "ND": [r"introduced by (.{1,3500}?)(?: a bill| a concurrent| a resolution| \d|$)"],
    "NE": [r"introduced by (.{1,3500}?)(?:\.? read first time| \d{1,2}/|$)"],
    "NH": [r"sponsors: (.{1,3500}?)(?: committee:| analysis|$)"],
    "NJ": [r"sponsored by:? (.{1,3500}?)(?: co-sponsored by| synopsis|$)"],
    "NM": [r"introduced by (.{1,3500}?)(?: an act| a memorial| a joint| a resolution| a concurrent|$)"],
    "NV": [r"(?:bill|resolution) no\. \d+ ?- ?((?:assembly(?:man|woman|men|women)|senators?|committee) .{1,3500}?)(?: " + MONTH +
           r" \d| joint sponsors?:| _{3,}| \(on behalf|$)"],
    "NY": [r"introduced by (?:m\. of a\.|members? of assembly|sens?\.|senators?) (.{1,3500}?)(?: --| - read| read once| read twice|$)",
           r"\bby: (?:m\. of a\.|sens?\.|senators?) (.{1,3500}?)(?: commending| congratulating| honoring| memorializing| mourning| celebrating| recognizing| commemorating| proclaiming| [a-z]+ing |$)"],
    "OH": [r"\d{4}-\d{4} ((?:(?:speaker|president) [a-z'\-]+,? )?(?:representatives?|senators?) .{1,3500}?)(?: cosponsors?:| a bill| a resolution| a joint| a concurrent| to | a r e s| a b i l l| r e s o l u t i o n|$)"],
    "OK": [r"\bby: (.{1,3500}?)(?: as introduced| an act| a joint| a concurrent| a resolution|$)"],
    "OR": [r"sponsored by (.{1,3500}?)(?: \(at the request| \(presession| summary| \(| ; ?(?:senators?|representatives?) [a-z])"],
    "PA": [r"introduced by (.{1,3500}?), " + MONTH + r" \d{1,2}, \d{4}"],
    "SD": [r"introduced by:? (.{1,3500}?)(?: (?:\d )?(?:a bill|an act|a joint|a concurrent|for an act)|$)"],
    "TN": [],
    "TX": [r"\bby: (.{1,3500}?) (?:[hs]\.(?:b|r|j\.r|c\.r)\.|[hs]\.? ?[bjcr]\.? ?(?:r\.)? ?no\.)"],
    "UT": [r"chief sponsor: (.{1,3500}?)(?: (?:house|senate) sponsor| \d|$)"],
    "VA": [r"patrons?-+ ?(.{1,3500}?)(?: -{3,}| unanimous consent| referred|$)"],
    "VT": [r"introduced by (.{1,3500}?)(?: referred| date:| subject:| statement|$)",
           r"\bby ((?:senators?|representatives?) .{1,300}?)(?:, j\.r\.[sh]\.|, [sh]\.r\.|\. |$)"],
    "WA": [rf"\bby {T} (.{{1,3500}}?)(?: read first time| \(by request| ; by request| \d| prefiled|$)",
           r"\bby ((?:house|senate) committee on .{1,3500}?)(?: \(|$)"],
    "WI": [rf"introduced by (?:the )?(?:{T} |joint legislative council|committee on )(.{{0,3500}}?)(?:[,;] cosponsored by|\. referred| by request|$)",
           r"introduced by (joint (?:committee|legislative council) .{0,80}?|committee on .{1,3500}?)(?:\.|,|$)"],
    "WV": [r"\(by (.{1,3500}?)\)", rf"\bby {T} (.{{1,3500}}?)(?: \[introduced| a bill| a resolution|$)"],
    "CT": [r"introduced by:? (.{1,3500}?)(?: general assembly| an act|$)"],
    "HI": [],
    "KY": [],
    "SC": [r"introduced by (.{1,3500}?)(?: (?:s|h)\. \d|$)"],
    "RI": [r"introduced by:? (.{1,3500}?)(?: date introduced| referred to|$)"],
    "WY": [r"sponsored by:? (.{1,3500}?)(?: a bill| a joint| for an act|$)"],
    "ID": [r"\bby (.{1,3500}?)(?: an act| a joint| a concurrent| a resolution|$)"],
    "AK": [],
}

TITLES = re.compile(r"^(?:(?:introduced|sponsored|presented) by:? |by:? |the honorable |honorable |(?:assembly ?members?|assembly(?:wo)?m[ae]n|"
                    r"representatives?|senators?|delegates?|reps?\.|sens?\.|dels?\.|m\. of a\.|members? of assembly|mr\.|mrs\.|ms\.|"
                    r"messrs\.?|speaker|president|majority leader|minority leader|pro tem(?:pore)?|chief sponsor:|councilmembers?)\s*(?:\(s\))?[: ]*)+")
SPLIT = re.compile(r",|;|&| and |\(| of the | of [a-z]| for the |\s+-+\s|--| district\b| dist \d|\s{2,}|:|"
                   r" (?:representatives?|senators?|speaker|president|delegates?|assembly ?(?:wo)?m[ae]n|assembly members?)\b")


def normalize(text):
    t = unicodedata.normalize("NFKD", text[:3500].replace("–", "-").replace("—", "-").replace("‑", "-"))
    t = t.encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\(cid:\d+\)", " ", t)
    t = re.sub(r"_{3,}", " ___ ", t)
    return " ".join(t.split())


def sponsor_line(state, bill_number, text):
    t = normalize(text)
    pats = PATTERNS.get(state, [])
    if state == "NY":  # uni-bills print both houses' introducers: read the line for the bill's own house
        if bill_number[:1] in ("A", "K", "R", "E"):
            pats = [r"introduced by (?:m\. of a\.|members? of assembly) (.{1,3500}?)(?: --| - read| read once| read twice|$)",
                    r"introduced by (committee on rules)",
                    r"\bby: m\. of a\. (.{1,200}?)(?: legislative resolution| [a-z]+ing |$)"]
        else:
            pats = [r"introduced by (?:sens?\.|senators?) (.{1,3500}?)(?: --| - read| read twice|$)",
                    r"introduced by (committee on rules)",
                    r"\bby: (?:sens?\.|senators?) (.{1,200}?)(?: [a-z]+ing |$)"]
    if state == "TN":  # 'HOUSE BILL 3234 By McCord SENATE BILL 3170 By Burchett': the line for this bill's number
        num = re.sub(r"\D", "", bill_number).lstrip("0")
        house = "house" if bill_number[:1] == "H" else "senate"
        m = re.search(rf"{house} (?:bill|joint resolution|resolution) (?:no\. )?0*{num} by (.{{1,80}}?)"
                      r"(?: an act| a resolution| a joint| (?:house|senate) (?:bill|joint|resolution)|$)", t)
        return m.group(1) if m else None
    if state == "OH":  # whole-chamber resolutions print the names run together: 'REPRESENTATIVESEITZ -SPEAKERHUSTED -...'
        m = re.search(r"\b[hs]\.(?:con\.|c\.|j\.)?r\.no\.\d+ (representatives?|senators?|speaker|president)([a-z']{2,})", t)
        if m:
            return "SQUASHED " + m.group(1) + " " + m.group(2)
    for p in pats:
        for m in re.finditer(p, t):
            g = [x for x in m.groups() if x is not None]
            s = " ".join(g).strip()
            if s and s != "___" and first_entry(s) is not None:
                return s
            break  # only the first match of each pattern
    return None


def first_entry(line):
    if line.startswith("SQUASHED "):  # 'representative' + 'seitz' or 'representatives' + 'eitz': keep both readings
        _, title, rest = line.split(" ", 2)
        return rest + (" " + title[-1] + rest if title.endswith("s") else "")
    s = re.sub(r"\b([a-z]),([a-z]{3,})", r"\1\2", line)  # OCR 'm,urphy'
    s = re.sub(r"\b\d{1,3}\b(?! ?(?:st|nd|rd|th)\b)(?! ?\()", " ", s)  # printed line numbers
    s = " ".join(s.split()).lstrip(":;,. ")
    s = TITLES.sub("", s)
    if re.match(r"(?:the )?(?:joint |house |senate |legislative |standing |select )*committee|council|joint legislative|rules|"
                r"appropriations|ways and means|finance|budget|judiciary\b", s):
        return "COMMITTEE"
    e = SPLIT.split(s, maxsplit=1)[0].strip(" .")
    # not a name: the pattern ran into the bill's own words (treated as no sponsor line)
    if len(re.sub(r"[^a-z]", "", e)) < 2 or re.search(r"\b(?:synopsis|read (?:first|once|twice)|a bill|an act|the bill|resolution|"
                                                     r"introduced|whereas|section \d|relating to|mask|legislature|general assembly)\b", e):
        return None
    return e


NICK = {"bill": "w", "bob": "r", "rob": "r", "dick": "r", "rick": "r", "jim": "j", "mike": "m", "tom": "t", "ted": "e",
        "chuck": "c", "jack": "j", "jerry": "g", "peggy": "m", "betsy": "e", "kathy": "k", "sandy": "s", "chris": "c",
        "tony": "a", "andy": "a", "joe": "j", "dan": "d", "don": "d", "ron": "r", "ken": "k", "pat": "p", "liz": "e",
        "buddy": "e", "kay": "k", "ben": "b", "alex": "a", "nick": "n", "matt": "m", "greg": "g", "steve": "s"}


def _close(a, b):
    """one OCR error (substitution, insertion or deletion) in a surname of six letters or more"""
    if len(b) < 6 or abs(len(a) - len(b)) > 1:
        return False
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.83


def is_first(entry, name, variants):
    """variants: surnames (lower case, letters only) the person is printed under. Initials count only in the
    'J. Smith' / 'Moore (B)' form; when a first name is printed, the surname decides."""
    if entry is None:
        return None
    if entry == "COMMITTEE":
        return False
    e = re.sub(r"[^a-z' .\-()]", " ", entry)
    words = [w.replace("'", "").replace("-", "") for w in re.split(r"[\s\-.()]+", e) if w]
    joined = "".join(words)
    hit = any(v in words or (len(v) >= 6 and v in joined) or any(_close(w, v) for w in words) for v in variants)
    if not hit:
        return False
    others = [w for w in words if len(w) >= 3 and not any(v == w or _close(w, v) for v in variants)]
    inits = set(re.findall(r"(?:^|\s)([a-z])\.(?=\s|$)", e)) | set(re.findall(r"\(([a-z])\)", e))
    if inits and not others:
        toks = [w.lower() for w in re.split(r"[\s.\-]+", name) if w]
        allowed = {w[0] for w in toks} | {NICK[w] for w in toks if w in NICK}
        if not inits & allowed:
            return False
    return True


# Surnames a member is printed under besides the last word of the Table 1 name (married or maiden names,
# compound surnames).
ALIAS = {"Sydney Kamlager-Dove": ["kamlager"], "Madeleine Dean": ["cunnane", "dean"], "Mary Peltola": ["kapsner", "nelson"],
         "Tulsi Gabbard": ["tamayo"], "Jaime Herrera Beutler": ["herrera", "herrerabeutler"],
         "Cathy McMorris Rodgers": ["mcmorris", "mcmorrisrodgers"], "Juanita Millender-McDonald": ["mcdonald", "millendermcdonald"],
         "Bonnie Watson Coleman": ["watsoncoleman", "coleman"], "Debbie Wasserman Schultz": ["wassermanschultz", "wasserman"],
         "Ileana Ros-Lehtinen": ["roslehtinen", "ros"], "Lucille Roybal-Allard": ["roybalallard"]}


def variants(name):
    toks = [re.sub(r"[^a-z\-']", "", unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode().lower()) for w in name.split()]
    toks = [w for w in toks if w and w not in ("jr", "sr", "ii", "iii", "iv")]
    last = toks[-1]
    v = {last.replace("-", "").replace("'", "")} | set(last.split("-"))
    return {x.replace("'", "") for x in v if len(x) >= 2} | set(ALIAS.get(name, []))


def value(state, bill_number, text, name, basis):
    """Yes / No / Unknown. basis says what the source records when the text prints no sponsor line:
    'lead' (the bill's only lead sponsor), 'checked' (an archive source whose own reviewed check found the
    person named first) or 'multi' (one of several lead sponsors)."""
    line = sponsor_line(state, bill_number, text)
    entry = first_entry(line) if line is not None else None
    first = is_first(entry, name, variants(name))
    if first is None:
        return "Yes" if basis in ("lead", "checked") else "Unknown"
    if first:
        return "Yes"
    # the reviewed archive check outranks this generic reading, except where a committee is named first
    return "Yes" if basis == "checked" and entry != "COMMITTEE" else "No"
