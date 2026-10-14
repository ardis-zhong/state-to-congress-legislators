"""Step 1: every member of Congress with a term ending after 1979-01-03 (the universe), flagged
for whether they are already in person_level.csv. Usage: python3 universe.py WORKDIR"""
import json, csv, sys
S = sys.argv[1] + "/"
pop = {r["BioguideId"] for r in csv.DictReader(open("replication/data/population/person_level.csv"))}
L = json.load(open("legislators-current.json")) + json.load(open("legislators-historical.json"))
uni = []
for p in L:
    ts = [t for t in p["terms"] if t["end"] > "1979-01-03"]
    if not ts:
        continue
    b = p["id"]["bioguide"]
    uni.append(dict(bioguide=b, name=p["name"].get("official_full") or f"{p['name']['first']} {p['name']['last']}",
                    first=p["name"]["first"], last=p["name"]["last"], nick=p["name"].get("nickname", ""),
                    state=ts[-1]["state"], states=";".join(sorted({t["state"] for t in p["terms"]})),
                    chambers=";".join(sorted({t["type"] for t in ts})),
                    first_fed=min(t["start"] for t in p["terms"])[:4], last_fed=max(t["end"] for t in p["terms"])[:4],
                    birth=p.get("bio", {}).get("birthday", ""), wikidata=p["id"].get("wikidata", ""),
                    wikipedia=p["id"].get("wikipedia", ""), in_pop=b in pop))
w = csv.DictWriter(open(S + "universe.csv", "w"), fieldnames=uni[0].keys()); w.writeheader(); w.writerows(uni)
print(len(uni), "members since 1979;", sum(u["in_pop"] for u in uni), "in the population")
