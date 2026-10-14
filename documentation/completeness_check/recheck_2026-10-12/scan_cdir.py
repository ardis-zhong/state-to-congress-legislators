"""Scan Congressional Directory bios of all members since 1979 for state legislative service."""
import sys, os, re, csv, json
sys.path.insert(0, "replication/scripts/population")
import extract_veterans as ev

S = sys.argv[1]
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

people = []
for f in ev.LEGISLATOR_FILES:
    people += json.load(open(f))
uni = {r["bioguide"]: r for r in csv.DictReader(open(S + "/universe.csv"))}
res = {b: {"good": [], "bad": [], "editions": 0} for b in uni}
for fname in sorted(f for f in os.listdir(ev.CACHE_DIR) if f.startswith("CDIR-") and f.endswith((".txt", ".zip"))):
    edition = fname.rsplit(".", 1)[0]
    c = ev.congress_of(edition)
    start, end = f"{1787 + 2 * c}-01-03", f"{1789 + 2 * c}-01-03"
    sbs = {}
    for p in people:
        for t in p["terms"]:
            if t["start"] < end and t["end"] > start:
                sbs.setdefault(t["state"], {})[p["id"]["bioguide"]] = p
    path = os.path.join(ev.CACHE_DIR, fname)
    bios = ev.bios_from_zip(path, sbs) if fname.endswith(".zip") else ev.bios_from_txt(path, sbs)
    n = 0
    for bg, bio in bios:
        if bg not in res:
            continue
        n += 1
        res[bg]["editions"] += 1
        # biographies: keep only the career part, ignore committee lists etc. (cut at 2500 chars)
        for bad, ctx in hits(bio[:2500]):
            res[bg]["bad" if bad else "good"].append(f"{edition[5:9]}: {ctx}")
    print(edition, n, file=sys.stderr)
with open(S + "/cdir_hits.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["bioguide", "in_pop", "editions", "n_good", "n_bad", "good_example", "bad_example"])
    for b, r in res.items():
        w.writerow([b, uni[b]["in_pop"], r["editions"], len(r["good"]), len(r["bad"]),
                    r["good"][0] if r["good"] else "", r["bad"][0] if r["bad"] else ""])
