import csv, sys
S = sys.argv[1]
ADD = {
 "B001308": "New York State Assembly 2011-2018 (District 119)",
 "S001210": "Florida House of Representatives 2012-2018 (District 59)",
 "F000477": "North Carolina House of Representatives 2012-2013; North Carolina Senate 2013-2022 (District 23)",
 "N000187": "California State Assembly 2000-2006; California State Senate 2006-2012",
 "R000619": "Ohio Senate 2019-2024 (District 33)",
 "G000607": "California State Assembly 2014-2026 (District 3; minority leader 2022-2025)",
 "M001166": "California State Senate 2024-present (District 5), after leaving Congress",
 "S001219": "New York State Assembly 2025-present (District 148), after leaving Congress",
 "W000781": "Ohio House of Representatives 1961-1967",
 "P000546": "Washington House of Representatives 1959-1967; Washington State Senate 1967-1971",
 "C000269": "Rhode Island House of Representatives 1957-1963 (minority leader)",
 "E000204": "Illinois House of Representatives 1957-1965",
 "S000463": "New Mexico Senate 1960-1970",
 "W000253": "Connecticut House of Representatives 1963-1969",
 "M000797": "Hawaii territorial House 1956-1958 and territorial Senate 1958-1959; Hawaii State Senate 1962-1964",
 "C000807": "Pennsylvania House of Representatives 1965-1966; Pennsylvania Senate 1967-1969 (District 17)",
 "M000703": "Illinois House of Representatives 1956-1966",
 "D000344": "Michigan Senate 1951-1954 (District 3)",
 "V000047": "Ohio Senate 1940-1942",
 "B000351": "Oklahoma House of Representatives 1947-1949",
 "V000006": "North Carolina House of Representatives 1955-1960",
 "A000221": "Ohio House of Representatives 1957-1961",
 "D000279": "Ohio House of Representatives 1951-1955",
 "P000553": "Wisconsin State Assembly 1951-1953",
 "M000433": "New York State Senate 1954-1964",
}
TERR = {
 "W000686": "Guam Legislature (speaker 1951-1965)",
 "B001245": "Guam Legislature 1981-1983, 1987-1995",
 "S001204": "Guam Legislature 2013-2019",
 "M001219": "Guam Legislature 2019-2023",
 "G000582": "House of Representatives of Puerto Rico 2002-2017 (speaker 2009-2013)",
 "S001077": "American Samoa Senate 1970-1978",
}
NAMESAKE = {
 "L000570": "father Ben Lujan was the New Mexico House member/speaker",
 "M001214": "father Frank Mrvan was the Indiana state senator",
 "G000544": "father Henry B. Gonzalez was the Texas state senator",
 "C000794": "son Jerry Costello II was the Illinois House member",
 "O000107": "son Solomon Ortiz Jr. was the Texas House member",
 "W000121": "son William C. Wampler Jr. (Virginia Senate) and grandson (House of Delegates)",
 "Q000016": "son Jack Quinn III was the New York Assembly member",
 "C000488": "son Wm. Lacy Clay Jr. was the Missouri state senator",
 "B000463": "son Gus Bilirakis was the Florida House member",
 "A000052": "son Joseph Addabbo Jr. is the New York state senator",
 "M000019": "son Connie Mack IV was the Florida House member",
 "K000105": "unrelated Edward Kennedy (Massachusetts Senate 2019-)",
 "K000379": "CEL middle-name match (Thomas P. Kennedy), different person",
 "D000096": "CEL middle-initial match (Monique D. Davis), different person",
 "M001211": "CEL middle-initial match (David E. Miller), different person",
 "M001168": "CEL middle-initial match (Thomas J. Murphy); Murphy was a legislative aide only",
 "J000303": "CEL middle-initial match (Robert B. Jones), different person",
 "T000405": "CEL match is Curtis R. Tucker Jr., different person",
 "N000180": "CEL middle-initial match (John E. Nelson), different person",
 "S000606": "CEL matches are other New Hampshire Smiths",
 "S001163": "brother John Salazar was the Colorado House member",
 "T000075": "CEL match is Larry Gene Taylor, different person",
 "M001146": "LegiScan VoteSmart link points to a different James Marshall (Georgia House District 14)",
 "R000583": "LegiScan link is Illinois state senator Tom Rooney, different person",
 "G000598": "Open States match is a different Robert Garcia (California Assembly 2024-)",
 "T000484": "husband Nathan Small is the New Mexico House member",
 "B000575": "son Matt Blunt was the Missouri House member",
 "R000295": "CEL match is Edgar S. Robb, different person",
 "W000811": "lost a 1998 Illinois House race; CEL match is Thomas E. Walsh",
 "S000522": "CEL match is Joann H. Smith; Chris Smith was a legislative agent (lobbyist), not a member",
}
STAFF = {
 "H000712": "sergeant-at-arms of the Pennsylvania House (staff)",
 "F000257": "staff to state legislators",
 "D000563": "parliamentarian / counsel, Illinois Senate (staff)",
 "C001035": "Directory hit is a district-office listing, not service",
 "A000055": "unsuccessful candidate for the Alabama House (1990)",
 "C001066": "unsuccessful candidate for the Florida Senate (2000)",
 "S000749": "House of Delegates of the South Carolina Bar (not legislature)",
 "L000598": "staffer, New York Senate",
}
WIKIDATA_ERR = {
 "F000348": "Waterbury alderman; no state legislative service in Bioguide, Directory or Wikipedia",
 "H000390": "no state legislative service in Bioguide, Directory or Wikipedia",
 "R000597": "Horry County Council; no state legislative service in Directory or Wikipedia",
 "C000567": "no state legislative service in Bioguide, Directory or Wikipedia",
 "K000118": "Hartford city council and CT secretary of the state; her husband James Kennelly was CT House speaker",
}
BLEED = "text from a neighbouring biography in the scanned Directory; the member's own biography and Wikipedia show no state legislative service"
BLEED_IDS = ["F000088", "R000485", "N000009", "S000294", "H000114", "B000556", "D000388", "B001267", "S000785", "A000356", "E000077", "J000211"]
OTHER = {
 "C000388": "unsuccessful candidate for the Idaho legislature (1952); 'General Assembly' hit is the United Nations",
 "P000193": "'General Assembly' hit is the United Nations",
 "P000513": "'General Assembly' hit is the United Nations",
 "W000154": "'General Assembly' hit is the United Nations",
 "S000997": "'General Assembly' hit is the United Nations",
 "G000445": "'General Assembly' hit is a civic award; New Hampshire Executive Council, not legislature",
 "R000046": "'General Assembly' hit is a Knights of Columbus award",
 "A000208": "Directory hit is about North Dakota's House delegation (Congress)",
 "F000102": "Directory hit is an honour from the California Legislature",
 "T000035": "Directory hit: elected governor by the legislature (1947); not a member",
 "D000492": "Directory hit describes his district's state assembly districts",
 "N000009": BLEED,
}
uni = {u["bioguide"]: u for u in csv.DictReader(open(S + "/universe.csv"))}
cands = {r["bioguide"]: r for r in csv.DictReader(open(S + "/candidates.csv"))}
cd = {r["bioguide"]: int(r["editions"]) for r in csv.DictReader(open(S + "/cdir_hits.csv"))}
b5 = {r["bioguide"] for r in csv.DictReader(open(S + "/bio2005_hits.csv"))}
nobio = [b for b, u in uni.items() if u["in_pop"] == "False" and not cd.get(b) and b not in b5]
rows = []
for b in list(cands) + [x for x in nobio if x not in cands]:
    u = uni[b]; c = cands.get(b, {})
    srcs = ";".join(k for k in ("cdir", "bio2005", "wikidata", "cel", "legiscan", "openstates") if c.get(k)) or "none (no biography in either Directory; checked on Wikipedia)"
    if b in ADD: v, why = "ADD", ADD[b]
    elif b in TERR: v, why = "TERRITORY (Ardis to decide)", TERR[b]
    elif b in NAMESAKE: v, why = "REJECT: namesake", NAMESAKE[b]
    elif b in STAFF: v, why = "REJECT: not a member", STAFF[b]
    elif b in WIKIDATA_ERR: v, why = "REJECT: Wikidata error", WIKIDATA_ERR[b]
    elif b in BLEED_IDS: v, why = "REJECT: OCR bleed", BLEED
    elif b in OTHER: v, why = "REJECT: false keyword hit", OTHER[b]
    elif b not in cands: v, why = ("TERRITORY (Ardis to decide)" if u["state"] in ("GU", "PR", "VI", "AS", "MP", "DC") else "REJECT: no state legislative service"), "no state legislative service on Wikipedia" if u["state"] not in ("GU","PR","VI","AS","MP","DC") else "territorial delegate; not yet checked"
    else: v, why = "UNRESOLVED", ""
    ev = " || ".join(f"{k}: {c[k][:200]}" for k in ("cdir", "bio2005", "wikidata", "cel", "legiscan", "openstates") if c.get(k))
    rows.append([b, u["name"], u["state"], f"{u['first_fed']}-{u['last_fed']}", srcs, v, why, ev, "Wikipedia (en), 2026-10-12"])
rows.sort(key=lambda r: (r[5] != "ADD", not r[5].startswith("TERR"), r[5], r[1]))
out = "documentation/completeness_check/completeness_recheck_2026-10-12.csv"
w = csv.writer(open(out, "w", newline="", encoding="utf-8"), lineterminator="\n")
w.writerow(["bioguide_id", "name", "state", "federal_years", "flagged_by", "verdict", "state_legislative_service_or_reason", "source_evidence", "verified_with"])
w.writerows(rows)
import collections
print(collections.Counter(r[5] for r in rows))
for r in rows:
    if r[5] == "UNRESOLVED": print("UNRESOLVED", r[0], r[1])
