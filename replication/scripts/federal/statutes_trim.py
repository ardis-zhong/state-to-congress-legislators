"""
Cut one measure's text out of a Statutes at Large granule (used by fetch_statutes_text.py).

GovInfo's per-law PDFs are whole printed pages, so a granule's text also holds the end of the measure printed before
it and the start of the one after; a few granules even start a page late or early (the measure's heading is in the
neighbouring granule) or are filed under the wrong volume. These functions find the measure's own part:

  laws (public and private)  from the law's heading ('Public Law 99-446' followed by '99th Congress', 'AN ACT',
                             'Joint Resolution' or the date line; OCR may misread one character of the number) to
                             the next law's heading after its 'Approved <date>.' line.
  concurrent resolutions     the block ending with the resolution's own 'Agreed to / Approved / Passed <date>.'
                             line, chosen by its printed bracket ('[H. Con. Res. 278]', one OCR character tolerated)
                             or, where the bracket is unreadable, by its printed caption matching GPO's title
                             (unique match required).

Each function returns (text, method); a method starting with 'unresolved' or 'truncated' means the measure was not
found complete in the text given (the caller then tries the neighbouring granules).
"""

import re

MONTH = r"(?:Jan|Feb|Mar|Apr|May|June|July|Aug|Sept|Oct|Nov|Dec)[a-z]*\.?"
HEAD = re.compile(r"^[^\n]{0,25}?\b(Public|Private)\s*(?:L\s?a\S{0,3}\s+)?(\d[\dA-Za-z^]{0,2})\s*[-–—.]\s*[^\w\n]{0,3}\s*"
                  r"([\d^][\dA-Za-z^]{0,3})[^\n]{0,80}\n(?:[^\n]{0,12}\n){0,2}[^\n]{0,30}"
                  r"(?:Congress|\d+\w{0,2}\s+Con\S{1,5}ss|A[Nn]\s+A[A-Za-z]{1,2}\b|\^\s+ACT\b|J[Oo][Ii][Nn][Tt]\s+R[Ee][Ss][Oo][Ll][Uu][Tt][Ii][Oo][Nn]|"
                  + MONTH + r"[a-z]?,?\s*\d)", re.M)
APPROVED = re.compile(r"Approved\s+" + MONTH + r"\s*\d{1,2}\s*,?\s*\d{4}")
RUN = re.compile(r"^.{0,60}\b\d{2,3}\s+STAT\.?\s+\d+.{0,60}$", re.M)        # running page header
BRK = re.compile(r"\[\s*([HS8])[^\]\n]{0,10}?(?:R\W?e\W?s|les)\W{0,3}\s*([\w^]{1,4})\s*\]", re.I)
ENDL = re.compile(r"^[^\n]{0,30}(?:Agreed\s+to|Approved|Passed)\s+[A-Z]\S{2,10}\s*\d{1,2}\s*[,.]?\s*[\dil]{4}[^\n]*$", re.M)
OPEN = re.compile(r"(?m)^.{0,40}(Reso\S{2,4}\s+\S{1,3}\s+the\b|[RB]e[s5]o\S{1,10}\s*the\b|Whereas|Wh\S{2}eas)")
STOP = {"OF", "THE", "AND", "IN", "FOR", "TO", "ON", "A", "AN", "BY", "WITH", "HIS", "HER", "AS"}


def near(a, b):
    """Same length and at most one character different (OCR)."""
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1


def near1(a, b):
    """At most one character substituted, dropped or added (OCR: '97-^22' read as '97-22' for 97-322)."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return near(a, b)
    if len(a) > len(b):
        a, b = b, a
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))


STUB = re.compile(r"(?m)^[^\n]{0,25}?\b(Public|Private)\s*(?:L\s?a\S{0,3}\s+)?\d{2,3}")
BILLPAT = {"HR": r"H[.,]?\s*R[.,]?", "S": r"[S8s5][.,]?", "HJRES": r"H\.?\s*J\.?\s*Res\.?", "SJRES": r"S\.?\s*J\.?\s*Res\.?"}


def words(s):
    return {w for w in re.findall(r"[A-Z0-9]+", s.upper()) if w not in STOP}


def trim_law(text, law, known=frozenset(), btype="", bnum=""):
    m = re.match(r"(Public|Private) Law (\d+)-(\d+)", law or "")
    if not m:
        return text.strip(), "unresolved (no law number)"
    heads = list(HEAD.finditer(text))
    mine = [h for h in heads if (h.group(1), h.group(2), h.group(3)) == m.groups()]
    how = "law heading"
    if not mine:
        # a near match whose number is another real law of the volume is that law, not an OCR slip
        nr = [h for h in heads if h.group(1) == m.group(1) and near1(h.group(2) + "-" + h.group(3), m.group(2) + "-" + m.group(3))
              and f"{h.group(1)} Law {h.group(2)}-{h.group(3)}" not in known]
        if len(nr) == 1:
            mine, how = nr, "law heading (OCR near match)"
    if not mine and btype in BILLPAT:
        # the heading's number is unreadable ('Public Law 93-'): the heading followed within a few lines by the
        # law's printed bill number ('[S. 1769]')
        brk = re.compile(r"\[\s*" + BILLPAT[btype] + r"\s*" + bnum + r"\s*\]", re.I)
        st = [x for x in STUB.finditer(text) if x.group(1) == m.group(1) and brk.search(text[x.start():x.start() + 500])
              and not any(h.start() == x.start() and f"{h.group(1)} Law {h.group(2)}-{h.group(3)}" in known for h in heads)]
        if len(st) == 1:
            mine, how = st, "law heading (unreadable number; bill number printed below)"
    if not mine:
        return text.strip(), "unresolved (heading not in text)"
    s = mine[0].start()
    appr = [a.end() for a in APPROVED.finditer(text) if a.start() > s]
    later = [h.start() for h in heads if h.start() > s and h.start() != s]
    nxt = [x for x in later if appr and appr[0] <= x] if appr else later
    if nxt:
        return text[s:nxt[0]].strip(), how
    if not appr and not re.search(r"LEGISLATIVE HISTORY", text[s:]):
        return text[s:].strip(), "truncated (no end of law in text)"
    return text[s:].strip(), how


def trim_conres(text, btype, bnum, title, known=frozenset()):
    letter = btype[0]
    cuts = [0] + [e.end() for e in ENDL.finditer(text)] + [len(text)]
    blocks = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1) if text[cuts[i]:cuts[i + 1]].strip()]
    info = []
    tw = words(title)
    for s, e in blocks:
        b = text[s:e]
        bs = [(x.group(1).upper().replace("8", "S"), x.group(2)) for x in BRK.finditer(b)]
        r = OPEN.search(b)
        cap = b[:r.start()] if r else b[:300]
        info.append((bs, len(tw & words(cap)) / len(tw) if tw else 0, bool(r)))
    exact = [i for i, (bs, _, _) in enumerate(info) if (letter, bnum) in bs]
    nearb = [i for i, (bs, _, _) in enumerate(info)
             if any(l == letter and near(n, bnum) and (l, n) not in known for l, n in bs)]
    other = lambda i: any(re.fullmatch(r"\d+", n) and not near(n, bnum) for _, n in info[i][0])
    if len(exact) == 1:
        i, how = exact[0], "resolution bracket"
    elif not exact and len(nearb) == 1:
        i, how = nearb[0], "resolution bracket (OCR near match)"
    else:
        cands = sorted(((sim, i) for i, (bs, sim, r) in enumerate(info) if r and sim >= 0.75 and not other(i)), reverse=True)
        if not cands or (len(cands) > 1 and cands[1][0] == cands[0][0]):
            return text.strip(), "unresolved (resolution not identified)"
        i, how = cands[0][1], "resolution caption"
    s, e = blocks[i]
    s, e = split_merged(text, s, e, letter, bnum)
    t = text[s:e].lstrip("\n")
    rh = RUN.match(t)
    t = (t[rh.end():] if rh else t).strip()
    if e == len(text) and not ENDL.search(t):
        return t, "truncated (no end of resolution in text)"
    if how == "resolution caption" and not OPEN.search(t):
        return t, "truncated (resolution starts before this text)"
    return t, how


def caption_start(text, pos, floor):
    """Start of the capital-letter caption printed above the bracket at pos: walk up over lines that hold no run of
    lower-case words (captions and date lines), stopping at the previous measure's last line."""
    line_start = text.rfind("\n", floor, pos) + 1
    while line_start > floor:
        prev_start = text.rfind("\n", floor, line_start - 1) + 1
        prev = text[prev_start:line_start]
        if (re.search(r"[a-z]{3,}\s+[a-z]{2,}\s+[a-z]{2,}", prev) or ENDL.search(prev)
                or re.match(r"\s*\S{0,30}?(Agreed\s+to|Approved|Passed)\b", prev)):
            break
        line_start = prev_start
    return max(line_start, floor)


def split_merged(text, s, e, letter, bnum):
    """A block can hold two resolutions when OCR lost the 'Agreed to ...' line between them: if another clean
    bracket ('[H. Con. Res. 69]') is printed in it, keep only the part that belongs to ours."""
    marks = []
    for x in BRK.finditer(text, s, e):
        l, n = x.group(1).upper().replace("8", "S"), x.group(2)
        marks.append((x.start(), l == letter and near(n, bnum), bool(re.fullmatch(r"\d+", n))))
    mine = [m for m in marks if m[1]]
    if not mine:
        return s, e
    me = mine[0][0]
    before = [m for m in marks if not m[1] and m[2] and m[0] < me]
    after = [m for m in marks if not m[1] and m[2] and m[0] > me]
    if before:
        s = caption_start(text, me, before[-1][0])
    if after:
        e = caption_start(text, after[0][0], me)
    return s, e


PRINTCODE = re.compile(r"^\W*\d{1,3}\s*[-_]\s*\S{2,4}\s*[O0n]?\b.{0,30}$")


def clean_tail(text):
    """Drop page furniture after the measure's last line: a running page header, GPO's print code at the foot of a
    volume's last page ('71-194 0 - 89 - 10 : QL. 3 PartA', '47-348 O - 72 - 53 (Pt. 2)'), or scanner specks (a line
    with no word of four or more letters)."""
    lines = text.rstrip().split("\n")
    while len(lines) > 1:
        last = lines[-1].strip()
        if RUN.fullmatch(last) or (PRINTCODE.match(last) and (re.search(r"Q[Ll]|Pt\.|Part", last) or not re.search(r"[a-z]{4,}", last))) \
                or not re.search(r"[A-Za-z]{4,}", last):
            lines.pop()
            continue
        break
    return "\n".join(lines).strip()


def trim(text, law, btype, bnum, title, known=frozenset()):
    """known: the volume's other measures ('Public Law 99-586' strings and ('H', '278') resolution pairs)."""
    t, how = (trim_conres(text, btype, bnum, title, known) if "CONRES" in btype
              else trim_law(text, law, known, btype, bnum))
    return clean_tail(t), how


def ok(method):
    return not method.startswith(("unresolved", "truncated"))


BRACKET = re.compile(r"\[([^\[\]\n]{2,24})\]")


def printed_bill(text):
    """The first bill citation printed in brackets in the margin ('[H.R. 1234]', '[H.J. Res. 1041]') whose number
    is cleanly read, as (type, number, True), or None."""
    for m in BRACKET.finditer(text[:2500]):
        inside = m.group(1).strip()
        n = re.search(r"(?:^|[^\w])(\d(?:[\d ]*\d)?)$", inside)
        lead = re.match(r"([HS8s5])", inside)
        if not n or not lead:
            continue
        mid = inside[:n.start(1)].upper().replace(" ", "")
        if not re.fullmatch(r"[HS85][.,]?(J[.,]?)?(CON[.,]?)?(R[.,]?|RES[.,]?)?", mid):
            continue           # not a bill citation ('[S. 1769]', '[H. Con. Res. 69]' are)
        h = "H" if mid[0] == "H" else "S"
        typ = h + ("CONRES" if "CON" in mid else "JRES" if "J" in mid else "R" if h == "H" else "")
        return typ, n.group(1).replace(" ", ""), True
    return None


def printed_bill_differs(text, btype, bnum):
    """The printed citation if it names a different measure than (btype, bnum); OCR near matches are the same."""
    p = printed_bill(text)
    if not p or not p[2]:          # nothing printed, or the number is not cleanly read
        return None
    typ, num, _ = p
    if typ[0] == btype[0] and near1(num.replace(" ", ""), bnum):   # same measure ('[S.Res. 134]' for S.J. Res. 134)
        return None
    if "CONRES" in btype and typ in ("HR", "S"):   # an unreadable 'Con. Res.' read as a bill: not evidence
        return None
    return f"{typ} {num}"
