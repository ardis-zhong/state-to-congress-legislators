# Population recheck, 2026-10-12

Scripts behind `../completeness_recheck_2026-10-12.csv`. They look for members of
Congress serving since 1979-01-03 who held a state legislative seat but were
missing from `replication/data/population/person_level.csv` (then 1,017 people).
Run from the repo root; each takes a scratch working folder (`WORKDIR`) where
intermediate CSVs are written. No language model is used anywhere: keyword
rules, ID joins, and name/state/birth-year matching produce candidates, and
every candidate was then checked by hand against Wikipedia.

| Step | Script | Source | Output (in WORKDIR) |
|---|---|---|---|
| 1 | `universe.py` | congress-legislators JSON | `universe.csv` (2,319 members; 1,302 not in the population) |
| 2 | `scan_cdir.py` (rules in `scan_cdir_rules.py`) | Congressional Directory biographies, 1979–2026 (`cdir_cache/`) | `cdir_hits.csv` |
| 3 | `bio2005_text.py`, `scan_bio2005.py` | *Biographical Directory of the United States Congress, 1774–2005* (GovInfo GPO-CDOC-108hdoc222, `bioguide2005_cache/`) | `bio2005_hits.csv` |
| 4 | `wikidata.py`, `wikidata_classify.py` | Wikidata positions held (P39) | `wikidata_hits.csv` |
| 5 | (inline in the session) CEL name match | CEL SLES file (`cel_cache/`) | `cel_hits.csv` |
| 6 | `legiscan_ids.py` | LegiScan session people (`legiscan_session_cache/`), joined on VoteSmart/OpenSecrets/Bioguide IDs | `legiscan_hits.csv` |
| 7 | `openstates_parse.py` | Open States people repository (current + retired) | `openstates_hits.csv` |
| 8 | `union.py` | steps 2–7 | `candidates.csv` (96 candidates) + members with no biography anywhere |
| 9 | `wiki_fetch.py`, `wiki_evidence.py` | English Wikipedia (API) | per-person evidence |
| 10 | `verdicts.py` | hand-checked verdicts | `../completeness_recheck_2026-10-12.csv` |
| 11 | `make_rows.py` | congress-legislators JSON | `house_batch9_recheck.csv`, `senate_batch5_recheck.csv`, crosswalk and target rows |

Recall on the known population: all sources together found 1,015 of 1,017; the
two misses (Daniel Inouye, Spark Matsunaga) served only in Hawaii's territorial
legislature, which the keyword rules don't count.

Result (approved by Ardis 2026-10-12): 25 people added; current-territory
legislators (Guam, Puerto Rico, American Samoa) excluded; rejected candidates
are listed with reasons in the verdict file.
