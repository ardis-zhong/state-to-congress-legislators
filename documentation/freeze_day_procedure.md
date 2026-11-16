# Freeze-day procedure (Friday, December 4, 2026)

The dataset is frozen at the state of Congress.gov, LegiScan and CEL on this day, then rebuilt, validated and
published on Harvard Dataverse (DOI 10.7910/DVN/GBGZCI). Every step below was dry-run on 2026-11-15 against the
cached data: each reproduced the existing files byte for byte (or, for the network steps, worked on a two-member
sample). Run everything from the repo root with the T9 drive connected and both keys in the environment
(`CONGRESS_API_KEY`, `LEGISCAN_API_KEY`); no script takes a key on the command line.

Allow about four hours: most of it is the LegiScan text step (~40 min even when nothing is new) and the federal
refresh (258 members at ~900 calls an hour).

## 1. Members (15 min)

1. Back up, then replace `legislators-current.json` and `legislators-historical.json` with fresh copies from
   https://unitedstates.github.io/congress-legislators/ (`fetch_legislator_party_gender.py` skips the download when a
   copy exists, so replace them by hand).
2. **New-member check.** List the Bioguide IDs in the fresh files that were not in the old ones. For each, check
   whether the person ever held a state legislative seat (Wikipedia, Ballotpedia, official bio); never add on a name
   alone. Each addition gets a row in `replication/data/source/house/house_batch10_new_members.csv` (or a Senate
   batch), `replication/data/population/billcount_FINAL.csv`, `replication/data/targets/state_bill_targets_full.csv`,
   and `documentation/completeness_check/new_members_2026-11-15.csv` (candidate, verdict, evidence). The 2026-11-15
   dry run found one: Aisha Wahab (W000832, California State Senate 2022-2026, U.S. House from 2026-09-02).
3. `python3 replication/scripts/population/build_final_datasets.py` (rebuilds `person_level.csv` and applies
   `state_years_corrections.csv`).

## 2. Federal (Congress.gov; ~20 min for the bill lists, plus text)

```
python3 replication/scripts/federal/refresh_queue.py
python3 replication/scripts/federal/fetch_all_sponsored_legislation.py --queue replication/data/targets/extraction_queue_refresh.csv --output sponsored_legislation_refresh.csv --log fetch_log_refresh.csv --delay 0.8
python3 replication/scripts/federal/merge_sponsored_legislation.py
python3 replication/scripts/federal/classify_status.py
python3 replication/scripts/federal/fetch_federal_bill_text.py sponsored_legislation_full_status.csv --min-congress 119 --delay 0.8
```

Check: every member's `ItemsMatch` is True in `fetch_log_refresh.csv`; the merge prints per-person shortfalls (a few
long-serving members are 2 items short of Congress.gov's count, which includes duplicates: accepted).

Then refresh the law list (Table 7's `passed` also counts every bill on it): delete the 119th Congress's cached pages
so they are fetched again, and rerun (about 30 seconds):

```
rm federal_laws_cache/119_*.json
python3 replication/scripts/federal/fetch_laws.py
```

And the resolutions' vote histories (Table 7's `passed` for simple and concurrent resolutions): delete the 119th
Congress's cached histories so they are read again (a few hundred requests, ~5 min; earlier Congresses come from cache):

```
rm federal_actions_cache/119_*.json
python3 replication/scripts/federal/fetch_resolution_actions.py
```

The 1969-1988 sources do not change and need no refresh; if a member was added in step 1 who served then, rerun
(from cache, only new files are fetched):

```
python3 replication/scripts/federal/cbp_bills_1969_1972.py          # Congressional Bills Project, 1969-1972 (Table 7)
python3 replication/scripts/federal/fetch_statutes_text.py --texts  # Statutes at Large, enacted text 1969-1988 (Table 5)
```

A new 1969-1972 member also needs rows in `replication/data/reference/cbp_sponsor_names_1969_1972.csv`.

## 3. State (LegiScan; ~1 hour)

1. Delete the bulk datasets of sessions still in progress, so they are downloaded again:
   `legiscan_dataset_cache/{OH_2190,FL_2135,FL_2204,FL_2212,TX_2160,TX_2223,GA_2167,GA_2268,CA_2172,VA_2149,NJ_2125,IA_2177,NY_2188}.zip`,
   and `legiscan_session_cache/datasetlist_*.json` / `sessionlist_*.json` for those states (new 2026 sessions; stale
   access keys otherwise fail with "Invalid access key").
2. In order:

```
python3 replication/scripts/state/legiscan_match_people.py replication/data/targets/state_bill_targets_full.csv
python3 replication/scripts/state/legiscan_fetch_state_bills.py replication/data/targets/state_bill_targets_full.csv   # ~2 min from cache
python3 replication/scripts/state/legiscan_fetch_bill_text.py replication/data/targets/state_bill_targets_full.csv     # ~40 min
python3 replication/scripts/state/legiscan_sponsor_check.py
python3 replication/scripts/state/legiscan_roleless_check.py --fetch
python3 replication/scripts/state/legiscan_session_chambers.py
python3 replication/scripts/state/legiscan_primary_counts.py                                                          # ~2 min
```

Check: `legiscan_session_chambers.py` must report no REVIEW rows (decide any in `legiscan_chamber_overrides.csv`);
look at person-sessions whose chamber rests on one or two bills (special sessions: Houchin, Pettersen were wrong).

## 4. Demographics and scores (5 min)

```
python3 replication/scripts/population/fetch_legislator_party_gender.py
python3 replication/scripts/population/fetch_race_lists.py
python3 replication/scripts/population/extract_veterans.py
python3 replication/scripts/effectiveness/match_sles.py
```

Check the diff of `replication/data/reference/house_historian_race_lists.csv`: on 2026-11-15 the live House Historian
page parsed two Inouye rows without state or party (no effect on `race_by_bioguide.csv`); keep the committed copy if
a change is only a parsing loss. Check thelawmakers.org/data-download for new CEL files (a new LES release, or a
re-upload like `sles_all_50_states_202609-1.dta`, Oct 2026, district fixes only): new file names go in
`fetch_cel_scores.py`, `match_sles.py` and `build_tables.py`.

## 5. Build, validate, publish

```
python3 replication/build_tables.py          # ~4 min
python3 replication/validate_tables.py
python3 replication/coverage_report.py
```

Then update the counts in `datasets/README.md` (commit the DOI-free copy until Dataverse publishes), the two
Dataverse codebooks, `dataverse_upload/DATAVERSE_METADATA.md`; regenerate the `.gz` files (`gzip -n -c`) and
`CHECKSUMS.md5`; commit; Ardis uploads the six files and publishes; then commit the README lines with the DOI.
