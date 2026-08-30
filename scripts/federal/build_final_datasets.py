import csv, re
from collections import defaultdict

def load(f):
    with open(f, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))

# ---------- billcount lookup: (Name,State,Chamber) -> BioguideId ----------
bc_rows = load('billcount_FINAL.csv')
bg_lookup = {}
for r in bc_rows:
    bg_lookup[(r['Name'], r['State'], r['Chamber'])] = r['BioguideId']

# ---------- Load Senate ----------
sen_rows = []
for f in ['/home/claude/senate_project/data/senators_A.csv',
          '/home/claude/senate_project/data/senators_B.csv',
          '/home/claude/senate_project/data/senators_C.csv']:
    sen_rows.extend(load(f))
for r in sen_rows:
    r['BioguideId'] = bg_lookup.get((r['Name'], r['State'], 'Senate'), '')

# ---------- Load House (repair overflow commas) ----------
HOUSE_FIELDS = ['Name','State','District','StateLegChamber','StateLegYears','StateLegTerms',
                'HouseYears','HouseCongresses','HouseTerms','BillsIntroducedHouse',
                'BillsIntroducedStateLeg','Notes/Sources']
NCOL = len(HOUSE_FIELDS)

def load_repair(f):
    rows = []
    with open(f, newline='', encoding='utf-8') as fh:
        reader = csv.reader(fh)
        header = next(reader)
        for raw in reader:
            if len(raw) < NCOL:
                raw = raw + ['']*(NCOL-len(raw))
            elif len(raw) > NCOL:
                head = raw[:NCOL-1]
                tail = ','.join(raw[NCOL-1:])
                raw = head + [tail]
            rows.append(dict(zip(HOUSE_FIELDS, raw)))
    return rows

STATE_FIX = {'OH':'Ohio','PA':'Pennsylvania','RI':'Rhode Island','NC':'North Carolina','NY':'New York','OR':'Oregon'}
house_files_regular = [
 'house_batch1_group1.csv','house_batch1_california.csv','house_batch1_group3.csv',
 'house_batch2_groupA.csv','house_batch2_groupB.csv','house_batch2_groupC.csv',
 'house_batch3_groupA.csv','house_batch3_groupB.csv','house_batch3_groupC.csv',
 'house_batch4_FINAL.csv',
 'house_batch5_texas.csv','house_batch5_groupB.csv','house_batch5_groupC.csv',
]
house_rows = []
for f in house_files_regular:
    rows = load_repair('/home/claude/house_project/data/'+f)
    for r in rows:
        if r['State'] in STATE_FIX:
            r['State'] = STATE_FIX[r['State']]
    house_rows.extend(rows)
for r in house_rows:
    r['BioguideId'] = bg_lookup.get((r['Name'], r['State'], 'House'), '')

print('Senate rows:', len(sen_rows), '| House rows:', len(house_rows))
missing_bg = [r for r in sen_rows+house_rows if not r['BioguideId']]
print('Rows with no BioguideId (should be 0):', len(missing_bg))

# ---------- Build person-level table keyed by BioguideId ----------
sen_by_bg = defaultdict(list)
for r in sen_rows:
    sen_by_bg[r['BioguideId']].append(r)
house_by_bg = defaultdict(list)
for r in house_rows:
    house_by_bg[r['BioguideId']].append(r)

# TotalSponsoredItems per bioguide (same figure regardless of chamber row, since it's a career total)
bc_by_bg = {}
for r in bc_rows:
    if r['TotalSponsoredItems'].isdigit():
        bc_by_bg[r['BioguideId']] = int(r['TotalSponsoredItems'])

all_bg = sorted(set(sen_by_bg) | set(house_by_bg))
print('Unique BioguideIds (people):', len(all_bg))

PERSON_FIELDS = [
    'BioguideId','Name','State','Chambers',
    'StateLegChamber','StateLegYears','StateLegTerms',
    'SenateYears','SenateCongresses','SenateTerms',
    'HouseYears','HouseCongresses','HouseTerms','District',
    'TotalSponsoredItems','BillsIntroducedStateLeg','Notes'
]
person_rows = []
for bg in all_bg:
    srow = sen_by_bg[bg][0] if bg in sen_by_bg else None
    hrow = house_by_bg[bg][0] if bg in house_by_bg else None
    chambers = []
    if srow: chambers.append('Senate')
    if hrow: chambers.append('House')
    # Prefer the Senate-listed name/state as canonical when both exist (matches this project's earlier convention)
    name = (srow or hrow)['Name']
    state = (srow or hrow)['State']
    stateleg_chamber = (srow or {}).get('StateLegChamber') or (hrow or {}).get('StateLegChamber') or ''
    stateleg_years = (srow or {}).get('StateLegYears') or (hrow or {}).get('StateLegYears') or ''
    stateleg_terms = (srow or {}).get('StateLegTerms') or (hrow or {}).get('StateLegTerms') or ''
    stateleg_bills = (srow or {}).get('BillsIntroducedStateLeg') or (hrow or {}).get('BillsIntroducedStateLeg') or ''
    notes_parts = []
    if srow: notes_parts.append('Senate record: ' + srow.get('Notes/Sources',''))
    if hrow: notes_parts.append('House record: ' + hrow.get('Notes/Sources',''))
    person_rows.append({
        'BioguideId': bg, 'Name': name, 'State': state, 'Chambers': '+'.join(chambers),
        'StateLegChamber': stateleg_chamber, 'StateLegYears': stateleg_years, 'StateLegTerms': stateleg_terms,
        'SenateYears': (srow or {}).get('SenateYears',''), 'SenateCongresses': (srow or {}).get('SenateCongresses',''),
        'SenateTerms': (srow or {}).get('SenateTerms',''),
        'HouseYears': (hrow or {}).get('HouseYears',''), 'HouseCongresses': (hrow or {}).get('HouseCongresses',''),
        'HouseTerms': (hrow or {}).get('HouseTerms',''), 'District': (hrow or {}).get('District',''),
        'TotalSponsoredItems': bc_by_bg.get(bg, ''),
        'BillsIntroducedStateLeg': stateleg_bills,
        'Notes': ' || '.join(notes_parts),
    })

with open('person_level.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=PERSON_FIELDS)
    w.writeheader()
    w.writerows(person_rows)

print('Wrote person_level.csv:', len(person_rows), 'rows')

both_chamber_count = sum(1 for r in person_rows if r['Chambers'] == 'Senate+House')
print('Both-chamber individuals:', both_chamber_count)
