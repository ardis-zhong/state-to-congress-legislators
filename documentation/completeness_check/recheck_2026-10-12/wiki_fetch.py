import csv, json, sys, time, urllib.request, urllib.parse, os, re
S = sys.argv[1]
uni = {u["bioguide"]: u for u in csv.DictReader(open(S + "/universe.csv"))}
want = [r["bioguide"] for r in csv.DictReader(open(S + "/candidates.csv"))]
cd = {r["bioguide"]: int(r["editions"]) for r in csv.DictReader(open(S + "/cdir_hits.csv"))}
b5 = {r["bioguide"] for r in csv.DictReader(open(S + "/bio2005_hits.csv"))}
want += [b for b, u in uni.items() if u["in_pop"] == "False" and not cd.get(b) and b not in b5 and b not in want]
UA = {"User-Agent": "state-to-congress-legislators/1.0 (https://github.com/ardis-zhong/state-to-congress-legislators) python-urllib"}
for b in want:
    out = f"{S}/wiki/{b}.txt"
    if os.path.exists(out): continue
    title = uni[b]["wikipedia"] or uni[b]["name"]
    q = urllib.parse.urlencode({"action": "query", "prop": "extracts|revisions", "explaintext": 1, "redirects": 1,
                                "rvprop": "content", "rvslots": "main", "titles": title, "format": "json", "formatversion": 2})
    d = json.load(urllib.request.urlopen(urllib.request.Request("https://en.wikipedia.org/w/api.php?" + q, headers=UA), timeout=60))
    if "query" not in d:
        print("ERR", b, title, str(d)[:200]); continue
    pg = d["query"]["pages"][0]
    wikitext = pg.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("content", "")
    infobox = wikitext[:wikitext.find("\n'''")] if "\n'''" in wikitext else wikitext[:6000]
    open(out, "w").write(f"TITLE: {pg.get('title')}\n=== INFOBOX\n{infobox}\n=== TEXT\n{pg.get('extract','')}")
    time.sleep(1.5)
print(len(want), "fetched")
