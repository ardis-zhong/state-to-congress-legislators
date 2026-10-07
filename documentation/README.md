# Documentation

Records of how the data was checked and built. You don't need these files to
use the datasets or to rerun the replication scripts.

## `completeness_check/`

Evidence for the people added by the 2026-09 completeness check. Every
member of Congress since 1979 was cross-referenced against Klarner's state
legislative election returns (ICPSR 34297, 1967-2010), and each candidate
match was then checked by hand on Wikipedia.

| File | Contents |
|---|---|
| `completeness_check_verified_113.csv` | The 113 strong candidate matches, each with a verdict (`CONFIRMED`, `FALSE_POSITIVE`, ...) and notes |
| `completeness_check_verified_320_weaker.csv` | The 320 weaker candidate matches, same format |

Confirmed people were written into
`replication/data/source/house/house_batch6_completeness_gap.csv`,
`house_batch7_completeness_gap2.csv`,
`replication/data/source/senate/senate_batch2_completeness_gap.csv`, and
`senate_batch3_completeness_gap2.csv`.

## `api_probes/`

`legiscan_probe2.py` and `legiscan_probe3.py` are exploratory scripts that
confirmed the actual shape of LegiScan's API responses before the real state
pipeline was written against them. Kept for provenance; they don't produce
any input to the tables.
