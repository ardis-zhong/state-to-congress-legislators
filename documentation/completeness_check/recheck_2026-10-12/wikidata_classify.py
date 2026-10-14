import csv, re, sys, collections
S = sys.argv[1]
uni = {u["wikidata"]: u for u in csv.DictReader(open(S + "/universe.csv")) if u["wikidata"]}
STATES = "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming"
TERR = "Puerto Rico|Guam|Virgin Islands|American Samoa|Northern Mariana|District of Columbia"
CH = r"(House of Representatives|House of Delegates|Senate|State Senate|Assembly|State Assembly|General Assembly|Legislature|state representative|state senator|assemblyman|assemblymember|House)"
STATE_LEG = re.compile(rf"\b({STATES})\b.*\b{CH}|\b{CH}\b.*\b({STATES})\b|\bstate (representative|senator|legislator)\b", re.I)
FED = re.compile(r"United States|U\.S\.|congressional district|Congress\b|Governor|Lieutenant|Secretary|Attorney|Treasurer|Auditor|Comptroller|Supreme Court|Court|Board|Commission|Council|Mayor", re.I)
rows = list(csv.DictReader(open(S + "/wikidata_positions.csv")))
hits = collections.defaultdict(set); terr = collections.defaultdict(set)
for r in rows:
    q = r["p"].rsplit("/", 1)[1]
    text = " | ".join(x for x in (r["posLabel"], r["ofLabel"], r["distLabel"]) if x)
    if FED.search(text):
        continue
    yrs = f"{r['start'][:4]}-{r['end'][:4]}"
    if STATE_LEG.search(text):
        hits[q].add(f"{text} ({yrs})")
    elif re.search(TERR, text) and re.search(CH, text, re.I):
        terr[q].add(f"{text} ({yrs})")
print("people with positions:", len({r['p'] for r in rows}), "; with a state legislative position:", len(hits))
pop = [q for q in hits if uni[q]["in_pop"] == "True"]
print("in pop:", len(pop), "of", sum(1 for u in uni.values() if u["in_pop"] == "True"))
w = csv.writer(open(S + "/wikidata_hits.csv", "w")); w.writerow(["bioguide", "in_pop", "wikidata", "positions", "territorial"])
for q in set(hits) | set(terr):
    w.writerow([uni[q]["bioguide"], uni[q]["in_pop"], q, "; ".join(sorted(hits[q])), "; ".join(sorted(terr[q]))])
    if uni[q]["in_pop"] == "False":
        print(uni[q]["bioguide"], uni[q]["name"], uni[q]["state"], uni[q]["first_fed"], uni[q]["last_fed"], "|", "; ".join(sorted(hits[q] or terr[q]))[:200])
