"""Scan Congressional Directory bios of all members since 1979 for state legislative service."""
import sys, os, re, csv, json
sys.path.insert(0, "replication/scripts/population")
import extract_veterans as ev  # noqa

STATE_NAMES = sorted(ev.STATES, key=len, reverse=True)
ST = "(?:" + "|".join(re.escape(s.title()) for s in STATE_NAMES) + ")"
CHAMBER = r"(?:house of representatives|house of delegates|senate|assembly|general assembly|legislature|legislative assembly|house)"
PATS = [
    re.compile(r"\b(?:" + ST + r"|state)\s+(?:state\s+)?" + CHAMBER + r"\b", re.I),
    re.compile(r"\bgeneral assembly\b|\bhouse of delegates\b|\bstate legislat(?:ure|or)\b", re.I),
    re.compile(r"\bstate (?:senator|representative|assemblyman|assemblywoman|assemblymember|legislator)\b", re.I),
    re.compile(r"\b(?:assemblyman|assemblywoman|assemblymember)\b", re.I),
]
FED = re.compile(r"united states|u\.\s?s\.|national|united nations|congress", re.I)
NONMEMBER = re.compile(r"\b(staff|aide|assistant|clerk|counsel|intern|page|secretary|analyst|lobby\w*|liaison|"
                       r"director|employee|consultant|research\w*|fellow|chaplain|parliamentarian|reporter|"
                       r"candidate|unsuccessful|campaign|budget office|attorney|adviser|advisor|officer|commission)\b", re.I)

def hits(bio):
    out = []
    for p in PATS:
        for m in p.finditer(bio):
            pre = bio[max(0, m.start() - 70):m.start()]
            ctx = bio[max(0, m.start() - 70):m.end() + 40]
            if FED.search(bio[max(0, m.start() - 15):m.end()]):
                continue
            # look only within the current clause (after the last ; or .)
            clause_pre = re.split(r"[;]", pre)[-1]
            bad = bool(NONMEMBER.search(clause_pre))
            out.append((bad, " ".join(ctx.split())))
    return out

