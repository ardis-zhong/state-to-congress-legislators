# State legislature archive survey (2026-10-23)

First-pass survey of the 38 states not yet covered by a state-text pilot (the
pilots so far: California, Florida, Virginia, Ohio, Illinois, Michigan, West
Virginia, Maryland, Pennsylvania; Georgia and New York paused; Texas restricted).
For each state: Table 4's missing person-years for 1989-2008 (from researched
StateLegYears), the number of population members serving then, and what each
legislature's own website offers. "Verified" means a mid-1990s introduced bill
or bill page was fetched; "unconfirmed" means the archive exists but the text
location was not yet found. Probes were single requests with a project
User-Agent; nothing behind Cloudflare or a login was used.

| State | Missing person-years 1989-2008 | People | Earliest text found | Sponsor information | Access notes |
|---|---|---|---|---|---|
| New Jersey | 139 | 15 | 2000-01 session (verified) | Site JSON API marks each sponsor "as Primary Sponsor"; introduced text `/Bills/<year>/A0500/100_I1.HTM` | robots.txt allows all; 1996-99 only in bulk bill-tracking databases (no text found) |
| North Carolina | 96 | 13 | 1989 session (verified, Edition 1 PDF/RTF) | Bill page lists sponsors with "(Primary)" | robots.txt Crawl-delay 2; no per-member list found yet; 1985-88 bill pages have no text |
| Wisconsin | 95 | 10 | 1995 session (verified) | Text: "Introduced by Representatives ..." | 1993 and earlier: empty pages |
| Louisiana | 92 | 11 | 1997 regular session (verified bill page with documents) | Bill page | 1993 session page errors |
| Missouri | 78 | 12 | 1997 (Senate bill pages verified) | Senate pages: "Sponsor:" | House archive paths not found yet |
| Minnesota | 75 | 10 | 1995 (verified) | Bill page "Authors" (chief author first) | 1993: 404 |
| Colorado | 71 | 11 | not checked | | Old site leg.state.co.us is behind a Cloudflare challenge (not used); new site not yet checked |
| Washington | 66 | 12 | 1991-92 biennium (verified) | Text: "By Representatives Locke, ..."; public web service (wslwebservices.leg.wa.gov: GetSponsors, GetLegislationByYear) | Browsable directory of every bill PDF (lawfilesext.leg.wa.gov/biennium/), unsuffixed file = introduced |
| Nevada | 64 | 8 | unconfirmed | Session archive lists sessions back to 1985 with bill tracking pages | text location not found yet |
| Tennessee | 63 | 6 | 1995-96 (99th GA; verified) | Filed text: "By Arriola, Jr." | capitol.tn.gov/Bills/<GA>/Bill/<bill>.pdf |
| Hawaii | 59 | 8 | not checked | | capitol.hawaii.gov is behind Cloudflare (not used) |
| Kansas | 58 | 8 | none found | | current site's archive appears to start ~2011 |
| South Carolina | 56 | 8 | 1995-96 (111th session; verified) | Bill page "Sponsor:" / "All Sponsors:" | scstatehouse.gov/sess111_1995-1996/bills/<n>.htm |
| Oregon | 48 | 8 | unconfirmed | | archive URL not found yet |
| Arizona | 48 | 9 | 1997 (43rd Legislature; verified) | | azleg.gov/legtext/43leg/1r/bills/hb2001p.htm |
| Idaho | 46 | 6 | unconfirmed (session info from 1998) | | |
| Connecticut | 44 | 6 | unconfirmed (bill status from 1991) | | |
| New Hampshire | 42 | 7 | 1999 (final version verified; introduced unconfirmed) | | |
| Massachusetts | 41 | 7 | unconfirmed | | older sessions 404 on malegislature.gov |
| Kentucky | 36 | 5 | 1998 regular session (verified record page) | | apps.legislature.ky.gov/record/98rs/ |
| Wyoming | 36 | 5 | unconfirmed (1997 legislation page exists) | | |
| Mississippi | 33 | 5 | unconfirmed (sessions from 1997) | | |
| Oklahoma | 32 | 7 | unconfirmed (sessions from 1993) | | |
| Maine | 31 | 4 | 1995 (117th Legislature; verified) | "By Representative Libby of Buxton" | |
| Nebraska | 29 | 5 | unconfirmed | Bill pages name the "Introducer" | |
| Rhode Island | 28 | 5 | none found | | |
| Arkansas | 28 | 4 | 1995 regular session (verified PDF) | | arkleg.state.ar.us/assembly/1995/R/Bills/ |
| Alabama | 27 | 5 | none found | | |
| Indiana | 23 | 7 | not checked | | archive.iga.in.gov returns 403 |
| North Dakota | 20 | 1 | 1997 (55th assembly archive exists) | | |
| Iowa | 16 | 2 | 1995 (76th GA BillBook; verified) | | |
| Alaska | 14 | 2 | 1993 (18th Legislature; verified) | | |
| South Dakota | 13 | 2 | unconfirmed | | |
| Montana | 12 | 2 | none found | | |
| Utah | 9 | 2 | 1997 (verified) | Text: "Sponsor: Greg J. Curtis" | |
| Vermont | 8 | 1 | none found | | |
| New Mexico | 5 | 1 | 1996 (verified) | Text: "INTRODUCED BY GARY K. KING" | |
| Delaware | 0 | 0 | | | |

No archive found reaches before 1989 except Nevada's session list (1985 on, text
unconfirmed); North Carolina's bill pages from 1985 have no text.
