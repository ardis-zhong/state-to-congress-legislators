#!/usr/bin/env python3
"""
Fill in BillsIntroducedStateLeg from state_legislation_sponsored.csv (the
LegiScan-derived state bill sponsorship data, already fetched -- see
legiscan_fetch_state_bills.py / legiscan_match_people.py).

WHY THIS SCRIPT EXISTS:
person_level.csv's BillsIntroducedStateLeg column has been "N/A - not
digitized/available" for 908/910 people since it was first built, because
at that time no state-level sponsorship data existed yet. It does now
(state_legislation_sponsored.csv, 116,970 rows / 237 people, built by the
LegiScan pipeline), but nothing ever counted it back into person_level.csv.
This mirrors what apply_billcounts.py already does for the federal side.

COUNTING RULE: counts rows where SponsorType is "Primary Sponsor" or
"Sponsor" (LegiScan's two labels for an actual bill sponsor, used
inconsistently across states -- some states report a granular Primary vs.
plain Sponsor, others only ever use "Sponsor"). "Co-Sponsor" and "Joint
Sponsor" rows are excluded, matching the federal convention (Congress.gov's
sponsored-legislation endpoint counts only primary sponsorship, not
cosponsorship).

COVERAGE CAVEAT: this only reflects LegiScan's own historical depth, which
starts ~2007-2013 depending on state (see legiscan_state_coverage.csv). For
the 133 people whose state legislative service predates that window (see
legiscan_coverage_gap_analysis.csv), this count is a LOWER BOUND, not a
complete career total -- the Notes column is annotated accordingly rather
than presented as a bare number, so it isn't mistaken for a verified total
the way TotalSponsoredItems (federal, cross-checked against the API's own
reported count) is.

USAGE:
    python3 apply_state_billcounts.py
    (reads state_legislation_sponsored.csv + the Senate/House source CSVs,
    writes updated BillsIntroducedStateLeg + Notes/Sources back into those
    same source files, then rebuild person_level.csv with
    build_final_datasets.py)
"""
import argparse
import csv
from collections import Counter

csv.field_size_limit(10_000_000)

SPONSOR_TYPES_COUNTED = {'Primary Sponsor', 'Sponsor'}

HOUSE_FIELDS = ['Name', 'State', 'District', 'StateLegChamber', 'StateLegYears', 'StateLegTerms',
                'HouseYears', 'HouseCongresses', 'HouseTerms', 'BillsIntroducedHouse',
                'BillsIntroducedStateLeg', 'Notes/Sources']
NCOL = len(HOUSE_FIELDS)

HOUSE_FILES = [
    'house_batch1_group1.csv', 'house_batch1_california.csv', 'house_batch1_group3.csv',
    'house_batch2_groupA.csv', 'house_batch2_groupB.csv', 'house_batch2_groupC.csv',
    'house_batch3_groupA.csv', 'house_batch3_groupB.csv', 'house_batch3_groupC.csv',
    'house_batch4_FINAL.csv',
    'house_batch5_texas.csv', 'house_batch5_groupB.csv', 'house_batch5_groupC.csv',
    'house_batch6_completeness_gap.csv', 'house_batch7_completeness_gap2.csv',
]
SENATE_FILES = ['senators_A.csv', 'senators_B.csv', 'senators_C.csv', 'senate_batch2_completeness_gap.csv', 'senate_batch3_completeness_gap2.csv']


def load_repair(f):
    rows = []
    with open(f, newline='', encoding='utf-8') as fh:
        reader = csv.reader(fh)
        next(reader)
        for raw in reader:
            if len(raw) < NCOL:
                raw = raw + [''] * (NCOL - len(raw))
            elif len(raw) > NCOL:
                head = raw[:NCOL - 1]
                tail = ','.join(raw[NCOL - 1:])
                raw = head + [tail]
            rows.append(dict(zip(HOUSE_FIELDS, raw)))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--state-sponsored', default='state_legislation_sponsored.csv')
    ap.add_argument('--senate-dir', default='data/source/senate')
    ap.add_argument('--house-dir', default='data/source/house')
    ap.add_argument('--coverage-gap', default='data/processed/legiscan_coverage_gap_analysis.csv')
    args = ap.parse_args()

    print('Counting sponsored state bills per BioguideId...')
    counts = Counter()
    seen_bg_state = {}
    with open(args.state_sponsored, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            bg = r.get('BioguideId', '').strip()
            if not bg:
                continue
            seen_bg_state[bg] = r.get('StateAbbr', '')
            if r.get('SponsorType', '') in SPONSOR_TYPES_COUNTED:
                counts[bg] += 1
    print(f'  {len(counts)} people have at least one counted sponsorship')

    partial_coverage_bg = set()
    try:
        with open(args.coverage_gap, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r.get('GapCategory') == 'partially_before_coverage':
                    partial_coverage_bg.add(r['BioguideId'])
        print(f'  {len(partial_coverage_bg)} of those have service predating LegiScan\'s coverage '
              f'(count will be annotated as a lower bound, not a full-career total)')
    except FileNotFoundError:
        print(f'  (no {args.coverage_gap} found -- skipping the lower-bound annotation)')

    def make_label(bg):
        if bg not in counts:
            return None  # no change -- leave existing "N/A" text as-is
        n = counts[bg]
        if bg in partial_coverage_bg:
            return (f"{n} (LOWER BOUND: LegiScan-sourced state bill sponsorships since its "
                     f"coverage begins for {seen_bg_state.get(bg,'this state')}; this person's state "
                     f"legislative service started before that window, see legiscan_coverage_gap_analysis.csv)")
        return f"{n} (state bill sponsorships, primary/sponsor only, via LegiScan)"

    updated = {'senate': 0, 'house': 0}

    # Neither Senate nor House source files carry BioguideId directly
    # (build_final_datasets.py joins that in from billcount_FINAL.csv by
    # Name+State+Chamber), do the same join here so we can look counts up by
    # BioguideId and write back by Name+State.
    bc_rows = []
    with open('billcount_FINAL.csv', newline='', encoding='utf-8') as f:
        bc_rows = list(csv.DictReader(f))
    bg_lookup = {(r['Name'], r['State'], r['Chamber']): r['BioguideId'] for r in bc_rows}

    print('\nUpdating Senate source files (by Name+State+Senate join)...')
    for fname in SENATE_FILES:
        path = f'{args.senate_dir}/{fname}'
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
        changed = 0
        for r in rows:
            bg = bg_lookup.get((r['Name'], r['State'], 'Senate'), '')
            label = make_label(bg) if bg else None
            if label:
                r['BillsIntroducedStateLeg'] = label
                changed += 1
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
        updated['senate'] += changed
        print(f'  {fname}: {changed} row(s) updated')

    print('\nUpdating House source files (by Name+State+House join)...')
    for fname in HOUSE_FILES:
        path = f'{args.house_dir}/{fname}'
        rows = load_repair(path)
        changed = 0
        for r in rows:
            bg = bg_lookup.get((r['Name'], r['State'], 'House'), '')
            label = make_label(bg) if bg else None
            if label:
                r['BillsIntroducedStateLeg'] = label
                changed += 1
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=HOUSE_FIELDS, lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
        updated['house'] += changed
        print(f'  {fname}: {changed} row(s) updated')

    print(f"\nDone. Senate rows updated: {updated['senate']}, House rows updated: {updated['house']}")
    print('Now rebuild person_level.csv with build_final_datasets.py to pick these up.')


if __name__ == '__main__':
    main()
