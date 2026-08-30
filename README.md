# state-to-congress-legislators

Research project (SDSU MA Political Science) tracking U.S. legislators who
served in a state legislature before or during their time in Congress,
1979-present. Builds a linked dataset of federal sponsored legislation
(via Congress.gov) and state sponsored legislation (via LegiScan) for the
same set of people, matched across both data sources.

## Status

This repo currently contains **pipeline code and methodology**, plus
derived data as it becomes available. State (LegiScan) data is published
here under the CC BY 4.0 attribution described in "Data sources and
licensing" below. This repo is currently **private**; it will be made
public once the full pipeline and dataset are further along.

## Pipeline overview

Two parallel tracks -- federal and state -- that get matched together by
legislator (Bioguide ID).

### Federal (Congress.gov)

| Script | Purpose |
|---|---|
| `scripts/federal/fetch_all_sponsored_legislation.py` | Pull sponsored-legislation records per legislator from `api.congress.gov` |
| `scripts/federal/apply_billcounts.py` | Attach bill counts to the legislator roster |
| `scripts/federal/classify_status.py` | Classify each bill's outcome status |
| `scripts/federal/gap_fill_missing_items.py` | Backfill records missed in the initial pull |
| `scripts/federal/build_combined.py` | Merge federal legislator + bill data |
| `scripts/federal/build_final_datasets.py` | Produce final federal output tables |
| `scripts/federal/build_stata_files.py` | Export Stata-format files for analysis |

### State (LegiScan)

| Script | Purpose |
|---|---|
| `scripts/state/legiscan_coverage_check.py` | Check how far back each state's LegiScan archive goes |
| `scripts/state/legiscan_match_people.py` | Match target legislators to LegiScan `people_id`s by name (with nickname/legal-name overrides) |
| `scripts/state/legiscan_fetch_state_bills.py` | Bulk-download state session datasets, extract every bill our matched legislators sponsored |
| `scripts/state/legiscan_fetch_bill_text.py` | Fetch and extract full text (Introduced version) for sponsored bills |

Exploratory API probes (`legiscan_probe2.py`, `legiscan_probe3.py`,
`legiscan_coverage_check.py`) are kept for provenance -- they document how
the LegiScan API's actual response shapes were confirmed before the real
pipeline was built against them.

## Reproducing this pipeline

You'll need your own API keys:
- Congress.gov: register at https://api.congress.gov/sign-up/
- LegiScan: register at https://legiscan.com/legiscan-register (free tier: 30,000 queries/month)

Scripts take the API key as a command-line argument and cache raw API
responses to disk (`legiscan_session_cache/`, `legiscan_dataset_cache/`,
`legiscan_billtext_cache/` -- all gitignored) so re-runs after an
interruption don't re-fetch anything already downloaded. Run the state
scripts in order:

```
python3 legiscan_coverage_check.py YOUR_KEY
python3 legiscan_match_people.py YOUR_KEY
python3 legiscan_fetch_state_bills.py YOUR_KEY
python3 legiscan_fetch_bill_text.py YOUR_KEY   # scope: Primary Sponsor bills by default,
                                                 # pass --all-sponsor-types to widen
```

## Data sources and licensing

**Federal data** (Congress.gov / `api.congress.gov`): bill text and
metadata produced by the U.S. Congress are U.S. government works and not
subject to copyright under 17 U.S.C. §105, so redistribution isn't
copyright-restricted. The API itself has its own access terms via
api.data.gov (rate limits, no-abuse) -- see
https://www.congress.gov/help/using-data-offsite for the Library of
Congress's current guidance before large-scale republishing.

**State data** (LegiScan / `api.legiscan.com`): LegiScan's API page states
"LegiScan API by LegiScan LLC is licensed under CC BY 4.0 Creative Commons
Attribution" (https://legiscan.com/legiscan), so data derived from the API
is published here under that license, with attribution:

> Bill sponsorship data and bill text derived from the LegiScan API,
> © LegiScan LLC, licensed under CC BY 4.0
> (https://creativecommons.org/licenses/by/4.0/). Retrieved via
> https://legiscan.com.

Note: LegiScan's Terms of Service (https://legiscan.com/terms-of-service)
separately state that users "will not reproduce, duplicate, copy, sell,
trade or resell the Services for any purpose" without a separate written
agreement, which isn't fully reconciled with the CC BY 4.0 statement above.
This project has not received explicit confirmation from LegiScan on
redistribution of derived bulk data, and is proceeding on the CC BY 4.0
basis in the meantime. The repo is kept private for now as a precaution,
and this section will be updated if LegiScan responds with different
guidance.

## Repo structure

```
scripts/federal/    -- Congress.gov pipeline
scripts/state/       -- LegiScan pipeline
data/processed/      -- published derived/summary tables (see "Data sources and licensing" above)
data/raw/             -- never committed; regenerate locally with your own API keys
```

The large raw-text caches (`legiscan_billtext_cache/`, etc.) stay local/gitignored
for now regardless of licensing -- they're tens of thousands of individual files,
which isn't a great fit for a git repo. Once the full pipeline is done, we'll
package the actual bill full text into a more repo-friendly form (e.g. one
combined file per state or per Congress) before publishing it here.
