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
python3 replication/scripts/population/fetch_congressional_directory.py   # ~1.9 GB into cdir_cache/
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
python3 replication/scripts/federal/fetch_all_sponsored_legislation.py
python3 replication/scripts/federal/fetch_all_sponsored_legislation.py \
    --queue replication/data/targets/extraction_queue_pending.csv \
    --output sponsored_legislation_pending.csv --log fetch_log_pending.csv
python3 replication/scripts/federal/gap_fill_missing_items.py   # re-fetch people whose totals came up short (reads gapfill_targets.csv)
python3 replication/scripts/federal/merge_sponsored_legislation.py  # combine + de-duplicate on (bioguide_id, url)
python3 replication/scripts/federal/classify_status.py              # passed / failed status from latest action
python3 replication/scripts/federal/fetch_federal_bill_text.py sponsored_legislation_full_status.csv \
    --min-congress 101 --delay 0.8   # ~33 h for the 101st Congress (1989) on; resumable
python3 replication/scripts/federal/fetch_laws.py                   # Congress.gov law lists (passed = on the list), ~2 min
python3 replication/scripts/federal/fetch_resolution_actions.py     # resolutions' vote histories (passed), ~3 h, resumable
python3 replication/scripts/federal/fetch_statutes_enacted.py       # Statutes metadata 1989-2024 (cross-check of passed), ~3 min
python3 replication/scripts/federal/fetch_committees.py             # committee referrals (Bill Status bulk 108th on; API before), ~5 h, resumable
python3 replication/scripts/federal/cbp_bills_1969_1972.py          # 91st-92nd Congress bills, Congressional Bills Project file
python3 replication/scripts/federal/fetch_statutes_text.py --mods --texts   # enacted text 1969-1988, Statutes at Large; ~4 h, resumable
```

The Congressional Bills Project file (`US-Legislative-congressional_bills_19.3.csv`, from
https://compagendas.la.utexas.edu/project/us/datasets) goes in `congressional_bills_project/`.

**3. State (LegiScan)**

```
python3 replication/scripts/state/legiscan_coverage_check.py   # every LegiScan script reads LEGISCAN_API_KEY from the environment
python3 replication/scripts/state/legiscan_match_people.py replication/data/targets/state_bill_targets_full.csv
python3 replication/scripts/state/legiscan_fetch_state_bills.py replication/data/targets/state_bill_targets_full.csv
python3 replication/scripts/state/legiscan_fetch_bill_text.py   # reads LEGISCAN_API_KEY from the environment; sponsors only by default; --all-sponsor-types adds co-sponsors
python3 replication/scripts/state/legiscan_committees.py   # committee referrals from the LegiScan datasets
python3 replication/scripts/state/archive_committees.py    # committee referrals from the state archives' saved files
```

**3b. Table 6 topic classifier (RoBERTa; training on a GPU)**

```
python3 replication/scripts/topics/build_topic_data.py      # model inputs into topics_data/ (committee references stripped)
python3 replication/scripts/topics/topic_proxies.py         # committee / subject-term / CA-heading evidence (keyword crosswalk)
python3 replication/scripts/topics/draw_gold_sample.py      # 400-bill hand-coding sample (documentation/topic_gold_sample/)
python3 replication/scripts/topics/make_topic_runs.py       # the 26 runs: training-set size and time windows
pip install -r replication/scripts/topics/requirements_topics.txt          # on the GPU machine
sbatch replication/scripts/topics/run_topic_array.sbatch    # one job per run (or: finetune_topics.py --run-id <id>)
python3 replication/scripts/topics/evaluate_topics.py       # learning curves, calibration, estimated + gold accuracy
```

Labels are the 33 current Congress.gov policy areas (Table 7). `topic_keyword_crosswalk.csv` maps committee names and
legislatures' subject terms to policy areas; federal bills, whose true labels are known, calibrate that check.

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
| 4. State bill text | step 3 |
| 5. Federal bill text | step 2 (bill-text fetch) |
| 6. State bill topics | step 3, plus a topic-mapping method (not yet designed) |
| 7. Federal bill topics | step 2 (all federal steps except the bill-text fetch) |
