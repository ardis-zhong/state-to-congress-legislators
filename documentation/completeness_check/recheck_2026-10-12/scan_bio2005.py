"""Find state legislative service in the 2005 Biographical Directory for members since 1979."""
import re, glob, csv, json, sys, unicodedata
sys.path.insert(0, S_DIR := sys.argv[1])
from scan_cdir_rules import hits  # same keyword rules as the Directory scan
def n(s): return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower())
START = re.compile(r"^([A-Z][A-Z'’ .\-]{1,40}?)(?:, (?:Jr\.|Sr\.|II|III|IV))?, ([A-Z][^\n]*)")
STATES = ["Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut","Delaware","Florida","Georgia","Hawaii","Idaho","Illinois","Indiana","Iowa","Kansas","Kentucky","Louisiana","Maine","Maryland","Massachusetts","Michigan","Minnesota","Mississippi","Missouri","Montana","Nebraska","Nevada","New Hampshire","New Jersey","New Mexico","New York","North Carolina","North Dakota","Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island","South Carolina","South Dakota","Tennessee","Texas","Utah","Vermont","Virginia","Washington","West Virginia","Wisconsin","Wyoming","American Samoa","Guam","Puerto Rico","Virgin Islands","District of Columbia","Northern Mariana Islands"]
POST = dict(zip(STATES, "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AS GU PR VI DC MP".split()))
bios = []
for f in sorted(glob.glob("bioguide2005_cache/*.txt")):
    lines = open(f).read().split("\n")
    cur = None
    for i, ln in enumerate(lines):
        m = START.match(ln)
        nxt = ln + " " + (lines[i + 1] if i + 1 < len(lines) else "")
        if m and "." not in m.group(1) and len(m.group(1).replace(" ", "")) >= 2 \
                and re.search(r"\b(?:a|an) (?:Representative|Senator|Delegate|Resident Commis)", nxt):
            if cur: bios.append(cur)
            cur = [m.group(1), ln]
        elif cur:
            cur.append(ln)
    if cur: bios.append(cur)
def join(ls):
    t = ""
    for ln in ls:
        if t.endswith("-") and not (ln[:1].isdigit() and t[-2:-1].isdigit()):
            t = t[:-1] + ln
        else:
            t += " " + ln
    return " ".join(t.split())
parsed = []
for b in bios:
    text = join(b[1:])
    m = re.search(r"\b(?:a|an) (?:Representative|Senator|Delegate|Resident Commissioner)[^;]{0,80}? from (?:the )?(" + "|".join(STATES) + r")", text[:400])
    if not m:
        continue
    # stop at the next biography heading that the line-based split missed ("... interment. SMITH, John, a")
    nxt = re.search(r"[.)]\s+[A-Z][A-Z'’\-]+(?: [A-Z][A-Z'’\-]+)*,(?: Jr\.,| Sr\.,)? [A-Z][a-z]+", text[60:])
    if nxt:
        text = text[:60 + nxt.start() + 1]
    parsed.append((b[0], text, POST[m.group(1)]))
print(len(bios), "bio starts;", len(parsed), "with state", file=sys.stderr)
L = json.load(open("legislators-current.json")) + json.load(open("legislators-historical.json"))
P = {p["id"]["bioguide"]: p for p in L}
uni = {u["bioguide"]: u for u in csv.DictReader(open(S_DIR + "/universe.csv"))}
by_last = {}
for b in uni:
    by_last.setdefault(n(P[b]["name"]["last"]), []).append(b)
found = {}
for surname, text, st in parsed:
    cands = [b for b in by_last.get(n(surname), []) if st in uni[b]["states"].split(";")]
    born = re.search(r"\bborn\b.{0,160}?\b(1[89]\d\d)\b", text[:500])
    for b in cands:
        by = uni[b]["birth"][:4]
        nm = P[b]["name"]
        head = n(text[:160])
        given = any(n(nm.get(k, "")) and n(nm.get(k, "")) in head for k in ("first", "nickname", "middle"))
        if by and born and born.group(1) == by and given:
            found.setdefault(b, []).append(text)
w = csv.writer(open(S_DIR + "/bio2005_hits.csv", "w"))
w.writerow(["bioguide", "in_pop", "n_bios", "n_good", "n_bad", "good_example", "bad_example"])
for b, texts in found.items():
    if len(texts) > 1:  # two biographies matched the same person (namesakes): keep the one with recent years
        texts = [t for t in texts if re.search(r"\b(19[7-9]\d|20\d\d)\b", t)] or texts
    hs = [h for t in texts for h in hits(t)]
    good = [c for bad, c in hs if not bad]; badl = [c for bad, c in hs if bad]
    w.writerow([b, uni[b]["in_pop"], len(texts), len(good), len(badl), good[0] if good else "", badl[0] if badl else ""])
served_by_2005 = [b for b in uni if int(uni[b]["first_fed"]) <= 2004]
print("universe members serving by 2005:", len(served_by_2005), "; matched to a bio:", sum(b in found for b in served_by_2005), file=sys.stderr)
