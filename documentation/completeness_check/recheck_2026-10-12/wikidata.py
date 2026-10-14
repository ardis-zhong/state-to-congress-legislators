import csv, json, sys, time, urllib.request, urllib.parse
S = sys.argv[1]
uni = list(csv.DictReader(open(S + "/universe.csv")))
qids = [u["wikidata"] for u in uni if u["wikidata"]]
out = []
B = 400
for i in range(0, len(qids), B):
    vals = " ".join("wd:" + q for q in qids[i:i + B])
    # positions held, with the "of" (P642) and "electoral district" (P768) qualifiers for generic positions
    q = f"""SELECT ?p ?pos ?posLabel ?ofLabel ?distLabel ?start ?end WHERE {{
      VALUES ?p {{ {vals} }}
      ?p p:P39 ?st . ?st ps:P39 ?pos .
      OPTIONAL {{ ?st pq:P580 ?start }} OPTIONAL {{ ?st pq:P582 ?end }}
      OPTIONAL {{ ?st pq:P642 ?of }} OPTIONAL {{ ?st pq:P768 ?dist }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }}"""
    data = None
    for attempt in range(6):
        try:
            req = urllib.request.Request("https://query.wikidata.org/sparql",
                data=urllib.parse.urlencode({"query": q, "format": "json"}).encode(),
                headers={"User-Agent": "state-to-congress-legislators research script (SDSU thesis)",
                         "Accept": "application/sparql-results+json"})
            data = json.load(urllib.request.urlopen(req, timeout=180)); break
        except Exception as e:
            print("retry", i, e, file=sys.stderr, flush=True); time.sleep(70)
    if data is None:
        sys.exit(f"batch {i} failed")
    for b in data["results"]["bindings"]:
        out.append({k: b.get(k, {}).get("value", "") for k in ("p", "pos", "posLabel", "ofLabel", "distLabel", "start", "end")})
    print(i, len(out), len({r['p'] for r in out}), file=sys.stderr, flush=True)
    time.sleep(65)
w = csv.DictWriter(open(S + "/wikidata_positions.csv", "w", newline=""), fieldnames=out[0].keys())
w.writeheader(); w.writerows(out)
print("done", file=sys.stderr)
