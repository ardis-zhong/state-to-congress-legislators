# Replication

Everything needed to reproduce the tables in [`datasets/`](../datasets/).
Run every command from the **repo root**.

```
replication/
  build_tables.py      -- the one script that writes the 7 tables into datasets/
  scripts/             -- pipeline steps that fetch and prepare the inputs
    population/        -- who is in the dataset (Bioguide IDs, career years, party, gender)
    federal/           -- Congress.gov: sponsored bills, status, bill text
    state/             -- LegiScan: matching people, sponsored bills, bill text
    bill_text/         -- combines federal + state bill text per legislator
  data/                -- inputs the scripts read and write
    source/            -- hand-researched biographical records (original research, not regenerable)
    population/        -- person_level.csv (the population) + billcount_FINAL.csv (name -> Bioguide ID crosswalk)
    targets/           -- who each fetch script runs on
    reference/         -- LegiScan coverage start dates per state, per-person coverage gaps
    processed/         -- intermediate outputs (party/gender, filtered federal bills, bill-text corpus)
```

## API keys

- Congress.gov: register at https://api.congress.gov/sign-up/
- LegiScan: register at https://legiscan.com/legiscan-register (free tier: 30,000 queries/month)

Keep keys in environment variables (`CONGRESS_API_KEY`, `LEGISCAN_API_KEY`)
and pass them on the command line, e.g. `"$LEGISCAN_API_KEY"`. The fetch
scripts cache raw API responses in gitignored folders at the repo root
(`legiscan_session_cache/`, `legiscan_dataset_cache/`,
`legiscan_billtext_cache/`, `federal_billtext_cache/`), so an interrupted
run can resume without re-fetching.

## Steps

**1. Population** (no API key needed)

```
python3 replication/scripts/population/build_final_datasets.py
python3 replication/scripts/population/fetch_legislator_party_gender.py
python3 replication/scripts/population/fetch_race_lists.py
python3 replication/scripts/population/fetch_congressional_directory.py --api-key "$CONGRESS_API_KEY"   # ~1.9 GB into cdir_cache/
python3 replication/scripts/population/extract_veterans.py
```

`fetch_congressional_directory.py` uses an api.data.gov key (the same key as
Congress.gov). Veteran status is flagged with keyword rules; cases the rules
flag for review are decided in `replication/data/reference/veteran_review.csv`.

**1b. Legislative effectiveness scores (Table 3; no API key needed)**

```
python3 replication/scripts/effectiveness/fetch_cel_scores.py      # ~23 MB into cel_cache/
python3 replication/scripts/effectiveness/match_sles.py
```

`match_sles.py` links CEL's state scores to Bioguide IDs; cases it can't
settle by rule are decided in `replication/data/reference/sles_review.csv`.

**2. Federal (Congress.gov)**

```
python3 replication/scripts/federal/fetch_all_sponsored_legislation.py --api-key "$CONGRESS_API_KEY"
python3 replication/scripts/federal/fetch_all_sponsored_legislation.py --api-key "$CONGRESS_API_KEY" \
    --queue replication/data/targets/extraction_queue_pending.csv \
    --output sponsored_legislation_pending.csv --log fetch_log_pending.csv
python3 replication/scripts/federal/gap_fill_missing_items.py "$CONGRESS_API_KEY"   # re-fetch people whose totals came up short (reads gapfill_targets.csv)
python3 replication/scripts/federal/merge_sponsored_legislation.py  # combine + de-duplicate on (bioguide_id, url)
python3 replication/scripts/federal/classify_status.py              # passed / failed status from latest action
python3 replication/scripts/federal/fetch_federal_bill_text.py "$CONGRESS_API_KEY" sponsored_legislation_full_status.csv \
    --min-congress 111 --delay 0.8   # ~15 h for the 111th Congress on; resumable
```

**3. State (LegiScan)**

```
python3 replication/scripts/state/legiscan_coverage_check.py "$LEGISCAN_API_KEY"
python3 replication/scripts/state/legiscan_match_people.py "$LEGISCAN_API_KEY" replication/data/targets/state_bill_targets_full.csv
python3 replication/scripts/state/legiscan_fetch_state_bills.py "$LEGISCAN_API_KEY" replication/data/targets/state_bill_targets_full.csv
python3 replication/scripts/state/legiscan_fetch_bill_text.py "$LEGISCAN_API_KEY"   # add --all-sponsor-types to go beyond primary sponsors
```

**4. Bill text corpus**

```
python3 replication/scripts/bill_text/build_bill_text_corpus.py
```

**5. Build the tables**

```
python3 replication/build_tables.py
```

Check each script's own header for options before running it.

## Which steps feed which table

| Table | Built from |
|---|---|
| 1. State-to-federal legislators | step 1 (`person_level.csv`) |
| 2. Demographics | step 1 (party, gender, race lists, Congressional Directory veteran status) |
| 3. Effectiveness scores | step 1b (Center for Effective Lawmaking LES and SLES) |
| 4. State bill text | steps 3-4 |
| 5. Federal bill text | step 2 (bill-text fetch) |
| 6. State bill topics | step 3, plus a topic-mapping method (not yet designed) |
| 7. Federal bill topics | step 2 (all federal steps except the bill-text fetch) |
