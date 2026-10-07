# state-to-congress-legislators

Research data for an SDSU MA Political Science thesis on whether effective
state legislators become effective members of Congress. It covers every
person who served in the U.S. House or Senate at any point from January 3,
1979 (96th Congress) to the present **and** held a seat in a state
legislature at some point in their career, about 1,000 people, all keyed on
their congressional **Bioguide ID**.

The repo has two parts:

| Folder | What it is |
|---|---|
| [`datasets/`](datasets/) | **The finished data: 7 tables.** Start here if you want to use the data. |
| [`replication/`](replication/) | Everything needed to reproduce the tables: the build script, the pipeline scripts, and the input data they read. |
| [`documentation/`](documentation/) | Records of how the data was checked: completeness-check evidence and early API probes. Not needed to use or rebuild the data. |

## The 7 tables

| # | Table | One row per |
|---|---|---|
| 1 | Legislators who moved from state to federal office | legislator |
| 2 | Legislator demographics | legislator |
| 3 | Legislative effectiveness scores (state and federal) | legislator × session |
| 4 | State bill text | bill |
| 5 | Federal bill text | bill |
| 6 | State bill topics and passage | bill |
| 7 | Federal bill topics and passage | bill |

Column definitions, sources, and build status for each table are in
[`datasets/README.md`](datasets/README.md). Tables 4 and 5 (full bill text)
are too large for GitHub and will be published on Harvard Dataverse.

**Status:** work in progress. The tables are being built one at a time;
`datasets/README.md` shows which are finished.

## Data coverage and limitations

**State data starts around 2007.** LegiScan, the source for state bills,
has no digitized sessions before roughly 2007-2010, depending on the state
(per-state start dates:
`replication/data/reference/legiscan_state_coverage.csv`). Many people in
the population served in their state legislature entirely before that, so
no state bill data exists for them. Others are partly covered, and their
state bill data is a lower bound rather than a complete career record (see
`replication/data/reference/legiscan_coverage_gap_analysis.csv`). Federal
data from Congress.gov covers the full 1979-present period.

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

**This project's own code** (everything under `replication/`) is released
under the MIT License -- see `LICENSE`. See `CITATION.cff` for how to cite
this project.
