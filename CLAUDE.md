# CLAUDE.md — State-to-Congress Legislators Dataset (Ardis's SDSU MA thesis)

## What this project is

Data for an MA Political Science thesis (SDSU, target completion ~June 2027; advisor: Prof. Goggin):
**do effective state legislators become effective members of Congress?** The closest precedent is
Bucchianeri, Volden & Wiseman, "Do Effective State Legislators Become Effective Lawmakers in
Congress?" (CEL working paper, 2020). Effectiveness will be measured with CEL's SLES (state) and
LES (federal) scores, plus full bill text (state and federal).

**Population:** every person who served in the U.S. House or Senate at any point from Jan 3, 1979
(96th Congress) to present AND held a seat in any state legislature (state house/assembly or state
senate; not governor, not other statewide/local office) at any point in their career.
Current count: **1019 people** (`person_level.csv`), keyed on **Bioguide ID**.

How it got to 1019:
- 910 original people from hand research (136 Senate + 823 House person-chamber rows; 49 served in
  both chambers).
- +109 people found by a completeness check: every Congress member since 1979
  (`@unitedstates/congress-legislators`) cross-referenced against Klarner's state legislative
  election returns (ICPSR 34297, 1967–2010), then **every candidate individually verified on
  Wikipedia** (91/113 strong matches confirmed, 18/320 weak matches confirmed).

## How Ardis works — read this first

- Ardis makes the content and research-design decisions. Claude handles execution and formatting.
  When a choice affects the data (what counts, how to classify, what to include), **lay out the
  options and ask**; don't decide silently.
- Prefer concrete, copy-pasteable outputs. For anything to paste into Google Sheets, use
  tab-separated plain text in a code block (markdown pipe tables don't split into columns).
- Citations use APSA style, e.g.: Alizadeh, Meysam, Maël Kubli, ... and Fabrizio Gilardi. 2025.
  "Open-source LLMs for text annotation: a practical guide for model setting and fine-tuning."
  Journal of Computational Social Science 8(1):17.
- Ardis uses Stata for analysis, so final tables should also be exportable as `.dta`.

## The goal: 9 tables

The finished dataset is **9 tables**, all keyed on Bioguide ID, written to a single `tables/`
folder by **one build script** that regenerates them from the ingredient files. Everything else in
the folder (fetch outputs, caches, logs, target lists, source batch files) is an ingredient, not a
deliverable. Ardis plans to finish roughly one table per week in this order.

| # | Table | Columns | Status (as of 2026-09-30) | Built from |
|---|---|---|---|---|
| 1 | State-to-federal legislators | Bioguide ID, Name, State, Years in state legislature, Years in federal legislature, Federal chamber | Ready — reshape only | `person_level.csv` (1019 rows) |
| 2 | Demographics | Bioguide ID, Name, Gender, Veteran, Political affiliation, Race | Partial — gender + party available; veteran + race have no source yet | `legislators-current/historical` (@unitedstates/congress-legislators) |
| 3 | Legislative effectiveness scores | Bioguide ID, Name, Year, LES, State or federal | Not started — needs download | thelawmakers.org/data-download: federal LES 93rd–118th Congress; state SLES 1987–2017 |
| 4 | State bill counts | Bioguide ID, Name, State, Year, Number of state bills | Partial — 237 people | `state_legislation_sponsored.csv` (LegiScan), aggregated by year |
| 5 | Federal bill counts | Bioguide ID, Name, Federal chamber, Year, Number of federal bills | Mostly ready — original 910 done; 109 added people pending | `sponsored_legislation_full` files, aggregated by introduced year + chamber |
| 6 | State bill text | Bioguide ID, Name, Bill ID, Bill name, Year, State, Full bill text | Unknown — `legiscan_billtext_cache/` exists (Sept 2); completeness not checked | LegiScan getBillText |
| 7 | Federal bill text | Bioguide ID, Name, Bill ID, Bill name, Year, House or Senate, Full bill text | Unknown — `federal_billtext_cache/` + `federal_bill_text_manifest.csv` exist (Aug 31); completeness not checked | Congress.gov text endpoint |
| 8 | State bill topics | Bioguide ID, Name, Bill ID, Bill name, Year, Congress.gov topic, Whether bill passed | Design question (see below) | LegiScan status (passed = status 4) + topic source TBD |
| 9 | Federal bill topics | Bioguide ID, Name, Bill ID, Bill name, Year, Congress.gov topic, Whether bill passed | Mostly ready for original 910 | `policy_area` + `bill_status` from `classify_status.py` |

### Open decisions — Ardis's call, not Claude's

1. **Table 8 topics.** Ardis's stated plan is to map state bills onto Congress.gov's policy-area
   categories so Tables 8 and 9 are comparable. Method (and a validation sample) still to be designed.
2. **"Year" in Table 3.** LES is scored per 2-year Congress; SLES per session/term. Store the
   Congress/session, or repeat the score for each calendar year it covers?
3. **Veteran and race (Table 2).** No source in the project yet. Candidates: history.house.gov's
   official lists (Black, Hispanic, Asian and Pacific Islander Americans in Congress) for
   race/ethnicity; CRS "Membership of the Nth Congress: A Profile" reports for military service.

## Immediate next steps (these need real internet access, which is why we're in Claude Code)

The earlier cloud sandbox could not reach api.congress.gov or LegiScan; this Mac can.

1. **Inventory first.** Before fetching anything, check what's actually in this folder. Several
   files were produced in a cloud workspace and delivered as downloads on 2026-09-05; confirm
   they made it here: `billcount_FINAL.csv`, the 4 completeness-gap source files
   (`house_batch6_completeness_gap.csv`, `house_batch7_completeness_gap2.csv`,
   `senate_batch2_completeness_gap.csv`, `senate_batch3_completeness_gap2.csv`), the 16 original
   senate/house source batch files, `state_bill_targets_full.csv`, `extraction_queue_new109.csv`,
   `merge_new109_billcounts.py`, `organize_dataset_folder.sh`, and the updated build scripts.
   Confirm `person_level.csv` has 1019 rows and no duplicate Bioguide IDs.
2. **Check bill-text cache completeness** (Tables 6–7) against the manifests.
3. **Federal bill counts for the 109 added people** via `fetch_all_sponsored_legislation.py`
   with `extraction_queue_new109.csv`, then merge.
4. **Full-population LegiScan fetch:**
   `legiscan_match_people.py <KEY> state_bill_targets_full.csv` then
   `legiscan_fetch_state_bills.py <KEY> state_bill_targets_full.csv`.
5. Re-run `apply_billcounts.py` → `apply_state_billcounts.py` → `build_final_datasets.py`.
6. Write the single 9-table build script.

Long fetches: ask Ardis before starting one, estimate how long it will take, and make it resumable
(the Congress.gov metadata fetch runs ~900 calls/hour).

## Data rules learned the hard way

- **Namesakes are the #1 error source.** Fathers/sons/unrelated same-name people (Kean Jr./Sr.,
  Paul Broun, Harold Ford Jr., Connie Mack III/IV, Walter Jones Sr./Jr., Menendez Sr./Jr., etc.)
  caused most false positives. Never add or change a person based on a name+state match alone;
  confirm it's the same individual.
- **Key on Bioguide ID, never Name+State.** Name matching once split Schumer, Menendez, and Inhofe
  into two people each.
- **Dedupe sponsored items on `(bioguide_id, url)`**, not `(congress, type, number)`; House and
  Senate amendments have overlapping numbering.
- **No LLM in the data path.** Bulk extraction is plain HTTP + `json.loads` with a per-person
  self-check (collected count vs. the API's reported total). Don't classify or extract records
  by summarizing them with a model.
- **Flag uncertainty instead of guessing.** e.g., `StateLegTerms` for the 109 added people reads
  "not independently term-counted"; missing counts are marked pending, not filled in. Keep that
  convention.
- **Known, accepted limitations (don't re-investigate unless asked):** 41 of the original 910 are
  1–2% short of Congress.gov's stated total (a real API pagination quirk, confirmed by re-fetch);
  amendments have no title or policy area in Congress.gov's schema; ~1.9% of bills from the
  93rd–95th Congresses use legacy subject terms; LegiScan coverage only starts ~2007–2013 by state,
  so earlier state service gives lower-bound counts.
- **Watch free-text fields.** An unescaped comma once shifted columns in 6 rows while keeping the
  right column count. Parse CSVs with a real CSV parser and spot-check after rebuilds.
- Federal years for the 109 added people come from YAML term boundaries and can be off by up to a
  year for special-election members (e.g., Walter B. Jones Sr.).

## Repo hygiene

- This repo is **private**. API keys live in environment variables (`CONGRESS_API_KEY`,
  `LEGISCAN_API_KEY`); never hard-code them or commit them. If a script takes a key as a command
  line argument, pass it from the environment variable.
- GitHub rejects files over 100 MB. Keep bill-text caches and very large CSVs out of git via
  `.gitignore` (check sizes before the first big commit) and ask Ardis how she wants those backed up.
- Commit after each completed step with a clear message, so progress is recoverable.

## Background reference

- Klarner validation: 619/910 originals confirmed against ICPSR 34297; 135 flagged
  `NEEDS_MANUAL_REVIEW` (`data/processed/klarner_validation_person_summary.csv`); 4 corrections
  made (Buddy Leach, Ed Pease, James Rogan, Linda Smith).
- Related literature/data: CEL SLES/LES (thelawmakers.org), Klarner state election returns
  (Harvard Dataverse), Makse's state legislator occupations (1993–2012), Carnes (2013)
  *White-Collar Government*, CongressData/CSPP, LegiScan bulk datasets.
