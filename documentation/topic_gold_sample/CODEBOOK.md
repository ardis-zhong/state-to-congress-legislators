# Coding guide: state bill policy areas (Table 6 gold sample)

You are coding 400 state bills with the policy areas the Library of Congress assigns to federal bills on
Congress.gov, so that the classifier's labels for state bills can be checked against a person's judgment.

## The task

For each row in `gold_sample_coding.xlsx`, read the title and the text excerpt, then fill in:

| Column | What to enter |
|---|---|
| `policy_area` | The **one** policy area that best describes the bill's main purpose (dropdown) |
| `second_choice_if_unsure` | Only if a second area is nearly as good (dropdown); leave blank otherwise |
| `confidence` | High / Medium / Low |
| `honorary_or_commemorative` | Yes if the measure only honors, congratulates, mourns, designates a day/week/month, or names something; otherwise No |
| `notes` | Anything odd: excerpt cut off, text unreadable, bill spans several areas |

Leave `second_coder` as it is. Rows marked Yes there will also be coded independently by a second person, if one is
available, to measure agreement. Don't look up how the model or the committees classified a bill.

## Rules

1. **One area per bill, by its main purpose.** This follows the Library of Congress practice: each bill gets a single
   policy area for its predominant subject, even when it touches several. Ask: what is this bill mainly *for*?
2. **Judge from the title and text only.** The committee a bill went to is not shown on purpose.
3. **State institutions map to their federal counterparts.** Bills about the legislature itself (its rules,
   members, staff and sessions; for redistricting see rule 5) → **Congress**. Bills about state
   agencies, state employees, elections, local governments and the state constitution → **Government Operations
   and Politics**.
4. **Money bills.** A general appropriations or budget bill → **Economics and Public Finance**. A bill funding one
   program (e.g. school construction) → that program's area (Education). Tax bills → **Taxation**.
5. **Elections and redistricting** (including legislative districts) → **Government Operations and Politics**.
6. **Honorary and commemorative measures** (congratulations, memorials, special days): Congress.gov's separate
   "Commemorations" area appears in our data only through the 110th Congress (2007-2008). Since then these measures get
   the area of the subject honored. Code that subject, as Table 7 shows Congress.gov doing from the 111th Congress on:
   a championship team → Sports and Recreation (168 of 170); a military unit or veterans → Armed Forces and National
   Security (67 of 87); awareness days and months → the subject (Health is the most common); **an anniversary → the
   subject of the anniversary** (a university's → Education), not Social Sciences and History by default.
   A memorial or tribute to a person: a current or former legislator → Congress (27 of 29); anyone else → the field the
   person is known for (an athlete → Sports and Recreation, a police officer → Crime and Law Enforcement, an artist or
   member of the clergy → Arts, Culture, Religion). If no field is evident, use your best guess with Low confidence;
   there is no clear Congress.gov pattern for these. Always also mark `honorary_or_commemorative` = Yes.
7. **Claims against the state** for one named person or company → **Private Legislation**.
8. **Unclear or unreadable text:** pick the best area from the title, set confidence Low and explain in `notes`.

## The 33 policy areas (short descriptions, in our own words)

| Policy area | Covers |
|---|---|
| Agriculture and Food | Farming, crops, livestock, food safety and labeling, nutrition programs |
| Animals | Animal welfare, pets, wildlife protection as such, veterinary matters |
| Armed Forces and National Security | National Guard, veterans' benefits and services, military bases, security |
| Arts, Culture, Religion | Arts, museums, libraries, cultural institutions, religious organizations |
| Civil Rights and Liberties, Minority Issues | Discrimination, equal rights, disability rights, privacy, free speech |
| Commerce | Business regulation, consumer protection, occupational licensing, gaming, alcohol, tourism business |
| Congress | The legislature itself: its rules, members, staff, sessions, legislative ethics |
| Crime and Law Enforcement | Criminal law, sentencing, police, prisons, courts' criminal procedure, firearms crimes |
| Economics and Public Finance | Budgets, general appropriations, state debt, economic conditions |
| Education | Schools, colleges and universities, teachers, students, education funding |
| Emergency Management | Disasters, emergency services, fire protection, disaster relief |
| Energy | Electricity, utilities' energy supply, oil, gas, coal, renewables, energy efficiency |
| Environmental Protection | Pollution, waste, air and water quality, climate, environmental regulation |
| Families | Family law, marriage and divorce, child custody and support, adoption, child welfare services |
| Finance and Financial Sector | Banking, insurance regulation, securities, consumer credit |
| Foreign Trade and International Finance | Exports, imports, international trade |
| Government Operations and Politics | State agencies, public employees, elections, local governments, state constitution, open records |
| Health | Health care, public health, insurance coverage for care, hospitals, medical professions, drugs |
| Housing and Community Development | Housing, landlord-tenant law, homelessness, urban and community development |
| Immigration | Immigrants, citizenship, state rules about immigration status |
| International Affairs | Relations with other countries, international agreements |
| Labor and Employment | Wages, workplace rules, unions, unemployment insurance, workers' compensation, job training |
| Law | Civil law and courts generally: civil procedure, judges, legal profession, torts (not crime) |
| Native Americans | Tribes, tribal lands, Native Hawaiian affairs |
| Private Legislation | Relief for one named person or company (claims bills) |
| Public Lands and Natural Resources | Parks, state lands, forests, mining, fish and game management |
| Science, Technology, Communications | Research, technology, telecommunications, broadband, internet, data |
| Social Sciences and History | History, historic anniversaries, archives, social science research |
| Social Welfare | Public assistance, aging services, disability benefits, poverty programs |
| Sports and Recreation | Sports, recreation, outdoor recreation, athletic programs |
| Taxation | Taxes of every kind: income, sales, property, tax credits |
| Transportation and Public Works | Roads, motor vehicles, transit, aviation, public works and infrastructure |
| Water Resources Development | Water supply, dams, flood control, irrigation, waterways |

For more examples, search Congress.gov for a federal bill on a similar subject and look at its "Policy Area".
