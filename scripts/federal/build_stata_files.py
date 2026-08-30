import pandas as pd
import numpy as np

# =========================================================================
# 1) BILL-LEVEL DATASET (one row per sponsored bill/resolution/amendment)
# =========================================================================
bills = pd.read_csv('sponsored_legislation_full_status.csv', dtype=str, keep_default_na=False)

bills['Congress'] = pd.to_numeric(bills['Congress'], errors='raise').astype('int16')
bills['Number'] = pd.to_numeric(bills['Number'], errors='raise').astype('int64')

for col in ['IntroducedDate', 'LatestActionDate']:
    bills[col + '_dt'] = pd.to_datetime(bills[col].replace('', np.nan), errors='coerce')

bills_out = pd.DataFrame({
    'bioguide_id': bills['BioguideId'].astype(str),
    'name': bills['Name'].astype(str),
    'state': bills['State'].astype('category'),
    'congress': bills['Congress'],
    'item_category': bills['ItemCategory'].astype('category'),
    'chamber': bills['Chamber'].astype('category'),
    'bill_type': bills['Type'].astype('category'),
    'bill_number': bills['Number'],
    'introduced_date': bills['IntroducedDate_dt'],
    'policy_area': bills['PolicyArea'].replace('', np.nan).astype('category'),
    'title': bills['Title'].astype(str),
    'latest_action_date': bills['LatestActionDate_dt'],
    'latest_action_text': bills['LatestActionText'].astype(str),
    'bill_status': bills['BillStatus'].astype('category'),
    'url': bills['Url'].astype(str),
})

var_labels_bills = {
    'bioguide_id': 'Congress.gov Bioguide ID (merge key to person_level.dta)',
    'name': 'Legislator name',
    'state': 'State represented',
    'congress': 'Congress number item was introduced in',
    'item_category': 'Bill/Resolution vs floor Amendment',
    'chamber': 'Chamber of origin (Unknown for amendments)',
    'bill_type': 'Item type: HR/S/HRES/SRES/HJRES/SJRES/HCONRES/SCONRES/AMDT',
    'bill_number': 'Number within its type and congress',
    'introduced_date': 'Date introduced (bills/res.) or offered (amendments)',
    'policy_area': 'Congress.gov Policy Area (blank for amendments, see notes)',
    'title': 'Official title (blank for amendments)',
    'latest_action_date': 'Date of most recent recorded legislative action',
    'latest_action_text': 'Text of most recent recorded legislative action',
    'bill_status': 'Standardized status, rule-classified from latest_action_text',
    'url': 'Canonical api.congress.gov URL (unique item identifier)',
}

bills_out.to_stata(
    'sponsored_legislation_full.dta',
    write_index=False,
    version=117,
    variable_labels=var_labels_bills,
    convert_dates={'introduced_date': 'td', 'latest_action_date': 'td'},
    convert_strl=['title', 'latest_action_text'],
    data_label='Full sponsored legislation (bills, resolutions, amendments), 910 legislators, 96th-119th Congress',
)
print('Wrote sponsored_legislation_full.dta:', len(bills_out), 'rows')

# =========================================================================
# 2) PERSON-LEVEL DATASET (one row per legislator)
# =========================================================================
people = pd.read_csv('person_level.csv', dtype=str, keep_default_na=False)
people['total_sponsored_items'] = pd.to_numeric(people['TotalSponsoredItems'].replace('', np.nan), errors='coerce').astype('Int64')

people_out = pd.DataFrame({
    'bioguide_id': people['BioguideId'].astype(str),
    'name': people['Name'].astype(str),
    'state': people['State'].astype('category'),
    'chambers': people['Chambers'].astype('category'),
    'state_leg_chamber': people['StateLegChamber'].astype(str),
    'state_leg_years': people['StateLegYears'].astype(str),
    'state_leg_terms': people['StateLegTerms'].astype(str),
    'senate_years': people['SenateYears'].astype(str),
    'senate_congresses': people['SenateCongresses'].astype(str),
    'senate_terms': people['SenateTerms'].astype(str),
    'house_years': people['HouseYears'].astype(str),
    'house_congresses': people['HouseCongresses'].astype(str),
    'house_terms': people['HouseTerms'].astype(str),
    'house_district': people['District'].astype(str),
    'total_sponsored_items': people['total_sponsored_items'],
    'bills_introduced_state_leg': people['BillsIntroducedStateLeg'].astype(str),
    'notes': people['Notes'].astype(str),
})

var_labels_people = {
    'bioguide_id': 'Congress.gov Bioguide ID (merge key to sponsored_legislation.dta)',
    'name': 'Legislator name',
    'state': 'State represented in Congress',
    'chambers': 'Chamber(s) of Congress served in',
    'state_leg_chamber': 'State legislature chamber(s) served in',
    'state_leg_years': 'Years of state legislature service',
    'state_leg_terms': 'State legislature terms served',
    'senate_years': 'Years of U.S. Senate service (blank if never Senator)',
    'senate_congresses': 'U.S. Senate Congresses served',
    'senate_terms': 'U.S. Senate terms served',
    'house_years': 'Years of U.S. House service (blank if never Rep.)',
    'house_congresses': 'U.S. House Congresses served',
    'house_terms': 'U.S. House terms served',
    'house_district': 'U.S. House district(s), where applicable',
    'total_sponsored_items': 'Lifetime sponsored items per api.congress.gov (see notes)',
    'bills_introduced_state_leg': 'Bills introduced in state legislature (mostly N/A)',
    'notes': 'Sourcing notes from original research',
}

people_out.to_stata(
    'person_level.dta',
    write_index=False,
    version=118,
    variable_labels=var_labels_people,
    data_label='U.S. legislators 1979-present who also served in a state legislature (910 people)',
)
print('Wrote person_level.dta:', len(people_out), 'rows')
