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
are too large for GitHub and are published on Harvard Dataverse:
https://doi.org/10.7910/DVN/GBGZCI

**Status:** Tables 1–5 and 7 are final as of the November 18–19, 2026 data
freeze; Table 6 (state bill topics) is pending. `datasets/README.md` describes each table.

## Data coverage and limitations

**State bill text** comes from LegiScan for roughly 2009 on, and for earlier
sessions from each legislature's own records (archived websites, bill-status
systems and published databases; for some states, copies kept by the
Internet Archive). How far back that reaches depends on the state: from
1969 in Pennsylvania, from the late 1980s or 1990s in most states, and not at
all where the legislature's old records are print-only or closed to
automated access. `documentation/coverage_report.md` gives coverage by state
and decade, with the reason for each gap; state service before a state's
records begin has no bill text, so those people's state bill data is a
lower bound rather than a complete career record.

**Federal bills** (Table 7) come from Congress.gov from the 93rd Congress
(1973) on, and from the Congressional Bills Project for the 91st-92nd
(1969-1972). **Federal bill text** (Table 5) is the text as introduced from
Congress.gov from 1989 on; for 1969-1988, Congress.gov has no digital text,
so only bills that became law (and concurrent resolutions) have text, as
printed in the Statutes at Large.

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

**Federal bills before 1973** (Table 7, 91st-92nd Congresses): E. Scott
Adler and John Wilkerson, Congressional Bills Project, distributed by the
Comparative Agendas Project
(https://compagendas.la.utexas.edu/project/us/datasets, file
`US-Legislative-congressional_bills_19.3.csv`). **Enacted federal text
before 1989** (Table 5): United States Statutes at Large, volumes 83-102,
from the Government Publishing Office's GovInfo service (U.S. government
work).

**State legislatures' own records** (Table 4 rows whose `text_source` is a
legislature): bill text and sponsor records published by the state
legislatures; see `datasets/README.md` for each source.

**Legislative effectiveness scores** (Table 3) come from the Center for
Effective Lawmaking (thelawmakers.org) and are republished here with the
citations CEL requests; see `datasets/README.md`.

**This project's own code** (everything under `replication/`) is released
under the MIT License -- see `LICENSE`. See `CITATION.cff` for how to cite
this project.
