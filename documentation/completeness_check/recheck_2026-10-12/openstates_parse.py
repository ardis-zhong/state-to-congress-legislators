import re, glob, csv, sys, json, unicodedata, collections
S = sys.argv[1]
R = glob.glob(S + "/openstates/*/data")[0]
def n(s): return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower())
people = []
for f in glob.glob(R + "/*/legislature/*.yml") + glob.glob(R + "/*/retired/*.yml") + glob.glob(R + "/us/**/*.yml", recursive=True):
    t = open(f, encoding="utf-8").read()
    g = lambda k: (re.search(rf"^{k}: (.+)$", t, re.M) or [None, ""])[1].strip().strip("'\"")
    ids = dict(re.findall(r"- scheme: (\w+)\n\s+identifier: '?([^'\n]+)'?", t))
    roles = []
    for m in re.finditer(r"^- (?:start_date: '?([\d-]*)'?\n\s+)?(?:end_date: '?([\d-]*)'?\n\s+)?type: (\w+)\n\s+jurisdiction: (\S+)", t, re.M):
        roles.append(m.groups())
    st_roles = [r for r in roles if r[2] in ("upper", "lower", "legislature") and "/state:" in r[3]]
    if not st_roles:
        continue
    st = re.search(r"/state:(\w\w)", st_roles[0][3]).group(1).upper()
    people.append(dict(file=f.split("/data/")[1], name=g("name"), given=g("given_name"), family=g("family_name"),
                       state=st, bioguide=ids.get("bioguide", ""), votesmart=ids.get("votesmart", ""),
                       years=f"{min((r[0] or '9999')[:4] for r in st_roles)}-{max((r[1] or 'now')[:4] for r in st_roles)}"))
print(len(people), "Open States state legislators;", sum(1 for p in people if p["bioguide"]), "with bioguide")
L = json.load(open("legislators-current.json")) + json.load(open("legislators-historical.json"))
P = {p["id"]["bioguide"]: p for p in L}
uni = {u["bioguide"]: u for u in csv.DictReader(open(S + "/universe.csv"))}
vs = {str(p["id"]["votesmart"]): p["id"]["bioguide"] for p in L if p["id"].get("votesmart") and p["id"]["bioguide"] in uni}
hits = []
for p in people:
    b = p["bioguide"] if p["bioguide"] in uni else vs.get(p["votesmart"], "")
    if b:
        hits.append(("id", b, p))
        continue
for b, u in uni.items():
    nm = P[b]["name"]
    lasts = {n(nm["last"])}
    givens = {n(nm.get(k, "")) for k in ("first", "nickname") if nm.get(k)}
    for p in people:
        if p["state"] in u["states"].split(";") and n(p["family"] or p["name"].split()[-1]) in lasts \
                and (n(p["given"] or p["name"].split()[0]) in givens):
            hits.append(("name", b, p))
seen = set(); out = []
for kind, b, p in hits:
    if (b, p["file"]) in seen: continue
    seen.add((b, p["file"]))
    out.append([kind, b, uni[b]["in_pop"], uni[b]["name"], uni[b]["first_fed"], uni[b]["last_fed"], uni[b]["birth"][:4], p["name"], p["state"], p["years"], p["file"]])
w = csv.writer(open(S + "/openstates_hits.csv", "w")); w.writerow(["match", "bioguide", "in_pop", "name", "first_fed", "last_fed", "birth", "os_name", "os_state", "os_years", "os_file"]); w.writerows(out)
print("pop members found:", len({o[1] for o in out if o[2] == "True"}))
for o in out:
    if o[2] == "False": print(*o, sep=" | ")
