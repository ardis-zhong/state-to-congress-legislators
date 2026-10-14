import csv, json, sys
from datetime import date
NAMES = {"C000807": "Lawrence Coughlin", "S000463": "Joe Skeen", "V000006": "Tim Valentine", "D000344": "Charles Diggs",
         "W000253": "Lowell Weicker", "S001219": "Joe Sempolinski", "P000546": "Joel Pritchard"}
# term records keep the scheduled end date for these early exits (resigned / died in office)
END_YEAR = {"M000703": "1979", "D000344": "1980", "A000221": "1982"}
S = sys.argv[1]
ADD = {  # bioguide: (StateLegChamber, StateLegYears, Wikipedia note)
 "B001308": ("New York State Assembly", "2011-2018", "NY Assembly District 119 2011-2018 (special election Sept 2011)"),
 "S001210": ("Florida House of Representatives", "2012-2018", "FL House District 59 2012-2018"),
 "F000477": ("North Carolina House of Representatives; North Carolina Senate", "2012-2022", "NC House District 50 2012-2013, NC Senate District 23 2013-2022"),
 "N000187": ("California State Assembly; California State Senate", "2000-2012", "CA Assembly 2000-2006, CA Senate 2006-2012"),
 "R000619": ("Ohio Senate", "2019-2024", "OH Senate District 33 2019-2024"),
 "G000607": ("California State Assembly", "2014-2026", "CA Assembly District 3 2014-2026 (minority leader 2022-2025)"),
 "M001166": ("California State Senate", "2024-present", "CA Senate District 5 from Dec 2024, after leaving Congress"),
 "S001219": ("New York State Assembly", "2025-present", "NY Assembly District 148 from Jan 2025, after leaving Congress"),
 "W000781": ("Ohio House of Representatives", "1961-1967", "OH House 1961-1967 (three terms)"),
 "P000546": ("Washington House of Representatives; Washington State Senate", "1959-1971", "WA House District 36 1959-1967, WA Senate 1967-1971"),
 "C000269": ("Rhode Island House of Representatives", "1957-1963", "RI House 1957-1963 (minority leader)"),
 "E000204": ("Illinois House of Representatives", "1957-1965", "IL House 1957-1965"),
 "S000463": ("New Mexico Senate", "1960-1970", "NM Senate 1960-1970"),
 "W000253": ("Connecticut House of Representatives", "1963-1969", "CT House 1963-1969"),
 "M000797": ("Hawaii Territorial House of Representatives; Hawaii Territorial Senate; Hawaii Senate", "1956-1959 (territorial); 1962-1964 (state)", "Hawaii territorial House 1956-1958, territorial Senate 1958-1959, Hawaii State Senate 1962-1964"),
 "C000807": ("Pennsylvania House of Representatives; Pennsylvania Senate", "1965-1969", "PA House (Montgomery County) 1965-1966, PA Senate District 17 1967-1969"),
 "M000703": ("Illinois House of Representatives", "1956-1966", "IL House 1956-1966"),
 "D000344": ("Michigan Senate", "1951-1954", "MI Senate District 3 1951-1954"),
 "V000047": ("Ohio Senate", "1940-1942", "OH Senate 1940-1942"),
 "B000351": ("Oklahoma House of Representatives", "1947-1949", "OK House (Noble County) 1947-1949"),
 "V000006": ("North Carolina House of Representatives", "1955-1960", "NC House (Nash County) 1955-1960"),
 "A000221": ("Ohio House of Representatives", "1957-1961", "OH House 1957-1961 (two terms)"),
 "D000279": ("Ohio House of Representatives", "1951-1955", "OH House 1951-1955"),
 "P000553": ("Wisconsin State Assembly", "1951-1953", "WI Assembly 1951-1953"),
 "M000433": ("New York State Senate", "1954-1964", "NY Senate 1954-1964"),
}
STATE = {"AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming"}
def cong(date):  # Congress in session on a date
    y = int(date[:4]); c = (y - 1789) // 2 + 1
    if y % 2 == 1 and date[5:] < "01-03": c -= 1
    return c
def ordn(n): return f"{n}{'th' if 10 <= n % 100 <= 20 else {1:'st',2:'nd',3:'rd'}.get(n % 10, 'th')}"
L = json.load(open("legislators-current.json")) + json.load(open("legislators-historical.json"))
P = {p["id"]["bioguide"]: p for p in L}
NOTE = "Added 2026-10-12 by the population recheck (documentation/completeness_check/completeness_recheck_2026-10-12.csv); verified on Wikipedia: {w}. Federal years, Congresses and terms from the @unitedstates/congress-legislators term records. BioguideId {b}"
house, senate, xwalk, queue, sbt = [], [], [], [], []
for b, (ch, yrs, wnote) in ADD.items():
    p = P[b]; nm = NAMES.get(b) or p["name"].get("official_full") or f"{p['name'].get('nickname') or p['name']['first']} {p['name']['last']}"
    st = STATE[p["terms"][-1]["state"]]
    chambers = []
    for typ, label in (("rep", "House"), ("sen", "Senate")):
        ts = [t for t in p["terms"] if t["type"] == typ]
        if not ts or max(t["end"] for t in ts) <= "1979-01-03":
            continue  # same convention as the 2026-09 additions: chambers with service since 1979
        chambers.append(label)
        start, end = min(t["start"] for t in ts), max(t["end"] for t in ts)
        # contiguous stints (a gap of more than 60 days starts a new one)
        stints = []
        for t in sorted(ts, key=lambda t: t["start"]):
            if stints and (date.fromisoformat(t["start"]) - date.fromisoformat(stints[-1][1])).days <= 60:
                stints[-1][1] = max(stints[-1][1], t["end"])
            else:
                stints.append([t["start"], t["end"]])
        def last_c(e): return cong(e) - (1 if e[5:] in ("01-03", "01-02") else 0)
        yrs_s = "; ".join(f"{a[:4]}-{END_YEAR.get(b, z[:4]) if z == end else z[:4]}" for a, z in stints)
        cong_s = "; ".join(f"{ordn(cong(a))}-{ordn(last_c(z))}" if cong(a) != last_c(z) else ordn(cong(a)) for a, z in stints)
        common = dict(Name=nm, State=st, StateLegChamber=ch, StateLegYears=yrs,
                      StateLegTerms="not independently term-counted this pass; see StateLegYears for span",
                      BillsIntroducedStateLeg="N/A - not digitized/available (LegiScan match not yet attempted for this person)",
                      **{"Notes/Sources": NOTE.format(w=wnote, b=b)})
        span = dict(Years=yrs_s, Congresses=cong_s, Terms=f"{len(ts)} term(s)")
        if label == "House":
            last = ts[-1]
            house.append(dict(common, District=f"{last['state']}-{last.get('district', 'AL') if last.get('district', 0) != 0 else 'AL'}",
                              HouseYears=span["Years"], HouseCongresses=span["Congresses"], HouseTerms=span["Terms"],
                              BillsIntroducedHouse="pending - added by 2026-10-12 population recheck"))
        else:
            senate.append(dict(common, SenateYears=span["Years"], SenateCongresses=span["Congresses"], SenateTerms=span["Terms"],
                               BillsIntroducedSenate="pending - added by 2026-10-12 population recheck"))
        xwalk.append(dict(Name=nm, State=st, Chamber=label, BioguideId=b, TotalSponsoredItems="", Source="pending - added by 2026-10-12 population recheck"))
    maxc = cong(max(t["end"] for t in p["terms"])) - (1 if max(t["end"] for t in p["terms"])[5:] == "01-03" else 0)
    queue.append(dict(Name=nm, State=st, Chambers="+".join(chambers), BioguideId=b, MaxCongress=maxc, TotalSponsoredItems=""))
    lo = int(yrs[:4]); hi = 2026 if "present" in yrs else int(yrs.split(";")[-1].strip()[5:9] if ";" in yrs else yrs[5:9])
    sbt.append(dict(Name=nm, BioguideId=b, State=st, StateAbbr=p["terms"][-1]["state"], StateLegChamber=ch, StateLegYears=yrs, MinYear=lo, MaxYear=hi))
HF = ["Name","State","District","StateLegChamber","StateLegYears","StateLegTerms","HouseYears","HouseCongresses","HouseTerms","BillsIntroducedHouse","BillsIntroducedStateLeg","Notes/Sources"]
SF = ["Name","State","StateLegChamber","StateLegYears","StateLegTerms","SenateYears","SenateCongresses","SenateTerms","BillsIntroducedSenate","BillsIntroducedStateLeg","Notes/Sources"]
def wr(path, fields, rows, lt="\n"):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator=lt); w.writeheader(); w.writerows(rows)
wr("replication/data/source/house/house_batch9_recheck.csv", HF, house)
wr("replication/data/source/senate/senate_batch5_recheck.csv", SF, senate)
wr("replication/data/targets/extraction_queue_recheck.csv", ["Name","State","Chambers","BioguideId","MaxCongress","TotalSponsoredItems"], queue)
# append to the crosswalk and the state-bill targets, keeping each file's line endings
for path, rows, fields in (("replication/data/population/billcount_FINAL.csv", xwalk, ["Name","State","Chamber","BioguideId","TotalSponsoredItems","Source"]),
                           ("replication/data/targets/state_bill_targets_full.csv", sbt, ["Name","BioguideId","State","StateAbbr","StateLegChamber","StateLegYears","MinYear","MaxYear"])):
    raw = open(path, "rb").read(); lt = "\r\n" if b"\r\n" in raw else "\n"
    have = {r["BioguideId"] for r in csv.DictReader(open(path, newline="", encoding="utf-8"))}
    with open(path, "a", newline="", encoding="utf-8") as f:
        if not raw.endswith(lt.encode()): f.write(lt)
        w = csv.DictWriter(f, fieldnames=fields, lineterminator=lt)
        n = 0
        for r in rows:
            if r["BioguideId"] in have and path.endswith("targets_full.csv"): continue
            w.writerow(r); n += 1
    print(path, "+", n)
print("house rows", len(house), "senate rows", len(senate), "queue", len(queue))
for r in house: print("H", r["Name"], r["State"], r["District"], r["HouseYears"], r["HouseCongresses"], r["HouseTerms"])
for r in senate: print("S", r["Name"], r["State"], r["SenateYears"], r["SenateCongresses"], r["SenateTerms"])
