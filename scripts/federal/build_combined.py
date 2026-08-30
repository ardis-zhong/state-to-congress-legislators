import csv, re
from collections import Counter
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

def load(f):
    with open(f, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))

# --- Load Senate data ---
SEN_FIELDS = ["Name","State","StateLegChamber","StateLegYears","StateLegTerms",
              "SenateYears","SenateCongresses","SenateTerms",
              "BillsIntroducedSenate","BillsIntroducedStateLeg","Notes/Sources"]
sen_rows = []
for f in ['/home/claude/senate_project/data/senators_A.csv',
          '/home/claude/senate_project/data/senators_B.csv',
          '/home/claude/senate_project/data/senators_C.csv']:
    sen_rows.extend(load(f))

# --- Load House data (repair overflow commas the same way as the final House build) ---
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

print('Senate:', len(sen_rows), 'House:', len(house_rows))

# --- Identify both-chamber people (same name + same state) ---
sen_by_key = {}
for r in sen_rows:
    sen_by_key.setdefault((r['Name'], r['State']), []).append(r)
house_by_key = {}
for r in house_rows:
    house_by_key.setdefault((r['Name'], r['State']), []).append(r)

both_keys = sorted(set(sen_by_key) & set(house_by_key))
print('Both-chamber individuals:', len(both_keys))

def start_year(s):
    m = re.search(r'(1[89]\d{2}|20\d{2})', s or '')
    return int(m.group(1)) if m else 9999

# ============ Build workbook ============
wb = Workbook()
FONT_NAME = "Arial"
header_font = Font(name=FONT_NAME, bold=True, color="FFFFFF", size=10)
header_fill = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
body_font = Font(name=FONT_NAME, size=10)
na_font = Font(name=FONT_NAME, size=10, italic=True, color="808080")
thin = Side(style="thin", color="D9D9D9")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
wrap_top = Alignment(wrap_text=True, vertical="top")

def style_header(ws, ncols, height=32):
    for c in range(1, ncols+1):
        cell = ws.cell(row=1, column=c)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = border
    ws.row_dimensions[1].height = height

def style_body(ws, last_row, ncols):
    for row in ws.iter_rows(min_row=2, max_row=last_row, min_col=1, max_col=ncols):
        for cell in row:
            is_na = isinstance(cell.value, str) and cell.value.strip().startswith("N/A")
            cell.font = na_font if is_na else body_font
            cell.alignment = wrap_top
            cell.border = border

# ---------- Sheet 0: Overview ----------
ws0 = wb.active
ws0.title = "Overview"
ws0.column_dimensions['A'].width = 46
ws0.column_dimensions['B'].width = 16
rows_overview = [
    ("Metric", "Count"),
    ("U.S. Senators (1979-present) with state legislature background", len(sen_rows)),
    ("U.S. House Members (1979-present) with state legislature background", len(house_rows)),
    ("Combined total rows (Senators + House Members tabs)", len(sen_rows)+len(house_rows)),
    ("Individuals who served in BOTH chambers of Congress (plus a state legislature)", len(both_keys)),
    ("States covered", 50),
]
for r in rows_overview:
    ws0.append(r)
style_header(ws0, 2, height=20)
for row in ws0.iter_rows(min_row=2, max_row=len(rows_overview), min_col=1, max_col=2):
    for cell in row:
        cell.font = body_font
        cell.border = border
ws0.append([])
ws0.append(["See tab \"Both Chambers\" for the 46 individuals who moved state legislature → one chamber of Congress → the other.", ""])
ws0.cell(row=ws0.max_row, column=1).font = Font(name=FONT_NAME, italic=True, size=10)
ws0.append(["Bill-introduction counts are pending: session's web tools blocked congress.gov access; user is obtaining a free api.congress.gov API key to fill this in in a future pass. See Methodology tab.", ""])
ws0.cell(row=ws0.max_row, column=1).font = Font(name=FONT_NAME, italic=True, size=10)

# ---------- Sheet: Both Chambers ----------
ws_both = wb.create_sheet("Both Chambers")
both_headers = ["Name","State","State Legislature Chamber(s)","State Legislature Years","State Legislature Terms",
                "U.S. House Years","U.S. House Congresses","U.S. House Terms",
                "U.S. Senate Years","U.S. Senate Congresses","U.S. Senate Terms",
                "Bills Introduced – House","Bills Introduced – Senate","Bills Introduced – State Legislature",
                "Sources / Notes"]
ws_both.append(both_headers)
for key in both_keys:
    name, state = key
    hrow = house_by_key[key][0]
    srow = sen_by_key[key][0]
    # prefer the fuller/state-leg description (house and senate researched independently; may differ slightly)
    stateleg_chamber = hrow.get('StateLegChamber') or srow.get('StateLegChamber')
    stateleg_years = hrow.get('StateLegYears') or srow.get('StateLegYears')
    stateleg_terms = hrow.get('StateLegTerms') or srow.get('StateLegTerms')
    notes = f"House record: {hrow.get('Notes/Sources','')} || Senate record: {srow.get('Notes/Sources','')}"
    ws_both.append([
        name, state, stateleg_chamber, stateleg_years, stateleg_terms,
        hrow.get('HouseYears'), hrow.get('HouseCongresses'), hrow.get('HouseTerms'),
        srow.get('SenateYears'), srow.get('SenateCongresses'), srow.get('SenateTerms'),
        hrow.get('BillsIntroducedHouse'), srow.get('BillsIntroducedSenate'), stateleg_terms and hrow.get('BillsIntroducedStateLeg'),
        notes
    ])
style_header(ws_both, len(both_headers))
last = ws_both.max_row
style_body(ws_both, last, len(both_headers))
widths_both = [18,14,26,18,14,18,16,14,18,16,14,26,26,20,50]
for i,w in enumerate(widths_both, start=1):
    ws_both.column_dimensions[get_column_letter(i)].width = w
ws_both.freeze_panes = "A2"
ws_both.auto_filter.ref = f"A1:{get_column_letter(len(both_headers))}{last}"

# ---------- Sheet: Senators ----------
ws_sen = wb.create_sheet("Senators")
sen_headers = ["Name", "State", "State Legislature Chamber(s)", "State Legislature Years",
    "State Legislature Terms", "U.S. Senate Years", "U.S. Senate Congresses",
    "U.S. Senate Terms", "Bills Introduced – U.S. Senate",
    "Bills Introduced – State Legislature", "Sources / Notes"]
ws_sen.append(sen_headers)
sen_sorted = sorted(sen_rows, key=lambda r: (r['State'], start_year(r['SenateYears'])))
for r in sen_sorted:
    ws_sen.append([r[k] for k in SEN_FIELDS])
style_header(ws_sen, len(sen_headers))
last = ws_sen.max_row
style_body(ws_sen, last, len(sen_headers))
widths_sen = [20, 14, 26, 20, 16, 20, 16, 22, 30, 22, 46]
for i,w in enumerate(widths_sen, start=1):
    ws_sen.column_dimensions[get_column_letter(i)].width = w
ws_sen.freeze_panes = "A2"
ws_sen.auto_filter.ref = f"A1:{get_column_letter(len(sen_headers))}{last}"

# ---------- Sheet: House Members ----------
ws_house = wb.create_sheet("House Members")
house_headers = [
    "Name", "State", "District(s)", "State Legislature Chamber(s)", "State Legislature Years",
    "State Legislature Terms", "U.S. House Years", "U.S. House Congresses",
    "U.S. House Terms", "Bills Introduced – U.S. House",
    "Bills Introduced – State Legislature", "Sources / Notes"]
ws_house.append(house_headers)
house_sorted = sorted(house_rows, key=lambda r: (r['State'], start_year(r['HouseYears'])))
for r in house_sorted:
    ws_house.append([r.get(k,'') for k in HOUSE_FIELDS])
style_header(ws_house, len(house_headers))
last = ws_house.max_row
style_body(ws_house, last, len(house_headers))
widths_house = [20, 16, 14, 30, 22, 18, 20, 18, 24, 30, 22, 50]
for i,w in enumerate(widths_house, start=1):
    ws_house.column_dimensions[get_column_letter(i)].width = w
ws_house.freeze_panes = "A2"
ws_house.auto_filter.ref = f"A1:{get_column_letter(len(house_headers))}{last}"

# ---------- Sheet: Methodology ----------
ws_m = wb.create_sheet("Methodology & Sources")
ws_m.column_dimensions['A'].width = 112
notes = [
    ("U.S. Legislators Who Served in Both a State Legislature and Congress (1979–present)", True, 13),
    ("", False, 10),
    ("Status: COMPLETE for identity/tenure data across both chambers. Bill-introduction counts PENDING.", True, 12),
    (f"{len(sen_rows)} Senators and {len(house_rows)} House members (959 rows total across the two chamber "
     "tabs) who served in Congress at any point from January 3, 1979 through August 2026, and who also held "
     "a seat in a state house/assembly or state senate at some point in their career — not necessarily in "
     "the same state they later represented in Congress. Governors, other statewide executive offices, and "
     "local/county offices are NOT counted as “state legislature” service.", False, 10),
    ("", False, 10),
    ("This workbook's tabs", True, 11),
    ("Overview: summary counts. Both Chambers: the 46 individuals confirmed (by matching name AND state "
     "across the two research passes) to have served in a state legislature, the U.S. House, AND the U.S. "
     "Senate — e.g. Sherrod Brown (Ohio House → U.S. House → U.S. Senate) or Jack Reed (Rhode Island "
     "Senate → U.S. House → U.S. Senate, still serving). Senators: the full 136-row Senate table. House "
     "Members: the full 823-row House table.", False, 10),
    ("", False, 10),
    ("Method", True, 11),
    ("Both chamber datasets were compiled the same way: Wikipedia's roster pages per state/chamber "
     "identified everyone whose congressional tenure overlapped 1979-present, then each individual's "
     "biography (Wikipedia, cross-checked with Ballotpedia) was checked for state legislature service. The "
     "House research (5 batches) included a mid-project tool outage that required a dedicated "
     "re-verification pass on ~87 rows — see the House workbook's own Methodology tab, or the project "
     "notes, for that detail.", False, 10),
    ("", False, 10),
    ("Known data gap: bills introduced — IN PROGRESS", True, 11),
    ("“Bills Introduced” is N/A for essentially every row in this workbook. Congress.gov's browsable pages "
     "and GovTrack.us both blocked automated access throughout this research (robots.txt disallow / 403 "
     "errors). However, api.congress.gov — the official Library of Congress API — was confirmed reachable "
     "and just requires a free API key (obtained by signing up at api.congress.gov/sign-up, which emails a "
     "key instantly; that sign-up form needs JavaScript and could not be completed by an automated tool). "
     "The user is obtaining that key. Once available, a follow-up pass can query the API's "
     "sponsored-legislation endpoint per member (using each person's Bioguide ID, many of which are already "
     "noted in the Sources/Notes column) to fill in real U.S. House and U.S. Senate bill counts for all 959 "
     "rows. State-legislature bill counts will likely remain largely unavailable regardless, since most "
     "states did not digitize bill-introduction records until roughly the 1990s-2000s and there is no "
     "unified cross-state historical database.", False, 10),
    ("", False, 10),
    ("Coverage caveats", True, 11),
    ("For the largest House delegations (California, Texas, New York, and to a lesser extent Illinois, "
     "Florida, Ohio, Pennsylvania, New Jersey), full completeness back to the earliest obscure one-term "
     "members of the early 1980s is very likely but not 100% guaranteed. Several individual rows carry an "
     "inline note where a specific date or term count was approximate in the source material rather than "
     "fabricated as precise.", False, 10),
    ("", False, 10),
    ("Compiled", True, 11),
    ("Research conducted August 2026 via Wikipedia, Ballotpedia, and web search. Prepared for the SDSU MA "
     "Political Science project.", False, 10),
]
r = 1
for text, bold, size in notes:
    cell = ws_m.cell(row=r, column=1, value=text)
    cell.font = Font(name=FONT_NAME, bold=bold, size=size)
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    r += 1

wb.save("US_Legislators_StateLegislature_and_Congress_1979_present.xlsx")
print("Saved combined workbook.")
