import csv, sys, collections
S = sys.argv[1]
uni = {u["bioguide"]: u for u in csv.DictReader(open(S + "/universe.csv"))}
ev = collections.defaultdict(dict)
for r in csv.DictReader(open(S + "/cdir_hits.csv")):
    if r["in_pop"] == "False" and int(r["n_good"]) > 0: ev[r["bioguide"]]["cdir"] = f"{r['n_good']} hits/{r['editions']} eds: {r['good_example']}"
for r in csv.DictReader(open(S + "/bio2005_hits.csv")):
    if r["in_pop"] == "False" and int(r["n_good"]) > 0: ev[r["bioguide"]]["bio2005"] = r["good_example"]
for r in csv.DictReader(open(S + "/wikidata_hits.csv")):
    if r["in_pop"] == "False": ev[r["bioguide"]]["wikidata"] = r["positions"] or ("TERRITORY: " + r["territorial"])
for r in csv.DictReader(open(S + "/cel_hits.csv")):
    if r["first_name_match"] == "True": ev[r["bioguide"]].setdefault("cel", "")
    if r["first_name_match"] == "True": ev[r["bioguide"]]["cel"] += f"{r['cel_name']} {r['cel_chamber']} {r['cel_years']}; "
for r in csv.DictReader(open(S + "/legiscan_hits.csv")):
    if r["in_pop"] == "False": ev[r["bioguide"]]["legiscan"] = r["example"]
for r in csv.DictReader(open(S + "/openstates_hits.csv")):
    if r["in_pop"] == "False": ev[r["bioguide"]]["openstates"] = f"{r['os_name']} {r['os_state']} {r['os_years']}"
cols = ["cdir", "bio2005", "wikidata", "cel", "legiscan", "openstates"]
w = csv.writer(open(S + "/candidates.csv", "w"))
w.writerow(["bioguide", "name", "state", "first_fed", "last_fed", "birth", "wikipedia", "n_sources"] + cols)
for b in sorted(ev, key=lambda b: (-len(ev[b]), uni[b]["name"])):
    u = uni[b]
    w.writerow([b, u["name"], u["state"], u["first_fed"], u["last_fed"], u["birth"], u["wikipedia"], len(ev[b])] + [ev[b].get(c, "") for c in cols])
print(len(ev), "candidates;", collections.Counter(len(v) for v in ev.values()))
# residual: non-pop members with no biography in either directory
cd = {r["bioguide"]: int(r["editions"]) for r in csv.DictReader(open(S + "/cdir_hits.csv"))}
b5 = {r["bioguide"] for r in csv.DictReader(open(S + "/bio2005_hits.csv"))}
nobio = [b for b, u in uni.items() if u["in_pop"] == "False" and not cd.get(b) and b not in b5]
print("non-pop members with no biography in either directory:", len(nobio))
for b in nobio: print("  ", b, uni[b]["name"], uni[b]["state"], uni[b]["first_fed"], uni[b]["last_fed"], "WD" if uni[b]["wikidata"] else "")
