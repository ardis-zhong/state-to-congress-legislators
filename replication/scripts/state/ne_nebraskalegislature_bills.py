#!/usr/bin/env python3
"""
Nebraska legislative bills, 1999-2010 (96th-101st Legislatures), from the Nebraska Legislature's
website (nebraskalegislature.gov), for population members who served in the Legislature before
their first LegiScan bills with a sponsor role (LegiScan's 2009-2010 Nebraska data carries none).
Nebraska state-text pilot (2026-10-27). robots.txt asks for 3 seconds between requests and closes
/bills/search_by_introducer.php, so every introduced bill text is read by number instead
(/FloorDocs/<legislature>/PDF/Intro/LB<n>.pdf, until 25 numbers in a row are missing). Each prints
"Introduced by Smith, 48; ..." (surname and district); bills whose first introducer is a reviewed
(legislature, surname, district) in replication/data/reference/ne_introducers_1999_2010.csv are kept.
Resolutions are not covered (simple resolutions have no introduced PDF).

Polite: one request at a time, at least 3 seconds apart, a User-Agent naming the project, every
response cached under ne_legislature_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/ne_nebraskalegislature_bills.py
"""

import csv
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://nebraskalegislature.gov/FloorDocs"
CACHE = "ne_legislature_cache"
LEGISLATURES = {96: (1999, 2000), 97: (2001, 2002), 98: (2003, 2004), 99: (2005, 2006), 100: (2007, 2008), 101: (2009, 2010)}
NAMES = "replication/data/reference/ne_introducers_1999_2010.csv"
TEXT_OUT = "ne_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 3
_last = [0.0]


def fetch(url):
    """One polite request (no cache): the body as bytes, b'' for a 404, None if it keeps failing."""
    for attempt in range(4):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            time.sleep(30 * (attempt + 1))
        except Exception:
            time.sleep(30 * (attempt + 1))
    print(f"  could not fetch {url}", flush=True)
    return None


def main():
    import pdfplumber
    with open(NAMES, newline="", encoding="utf-8") as f:
        names = {(int(r["legislature"]), r["surname"].upper(), r["district"]): r for r in csv.DictReader(f) if r["bioguide_id"]}
    out = []
    for leg, (y0, y1) in LEGISLATURES.items():
        missing, num = 0, 0
        while missing < 25:
            num += 1
            bill = f"LB{num}"
            txt = os.path.join(CACHE, "texts", f"{leg}_{bill}.txt")
            if not os.path.exists(txt):
                raw = fetch(f"{BASE}/{leg}/PDF/Intro/{bill}.pdf")
                if raw is None:
                    continue
                text = ""
                if raw[:4] == b"%PDF":
                    local = os.path.join(CACHE, "pdf", f"{leg}_{bill}.pdf")
                    os.makedirs(os.path.dirname(local), exist_ok=True)
                    with open(local, "wb") as f:
                        f.write(raw)
                    with pdfplumber.open(local) as pdf:
                        text = "\n".join((p.extract_text(x_tolerance=1.5) or "") for p in pdf.pages)
                os.makedirs(os.path.dirname(txt), exist_ok=True)
                with open(txt, "w", encoding="utf-8") as f:
                    f.write(text)
            with open(txt, encoding="utf-8") as f:
                text = f.read()
            if not text.strip():
                missing += 1
                continue
            missing = 0
            m = re.search(r"Introduced by\s+(.+?)(?:\n\s*Read first time|\nRead first time)", text[:2000], re.S)
            names_line = " ".join(m.group(1).split()) if m else ""
            first = re.match(r"([A-Za-z'\-. ]+?),\s*(\d+)", names_line)
            if first:
                key = (leg, re.sub(r"[^A-Z]", "", first.group(1).upper()), first.group(2))
                r = names.get(key)
                if r:
                    d = re.search(r"Read first time\s+([A-Za-z]+ \d{1,2}, \d{4})", text)
                    date = time.strftime("%Y-%m-%d", time.strptime(d.group(1), "%B %d, %Y")) if d else ""
                    # "A BILL\n1 FOR AN ACT relating to ...;\n2 ... original section.\n5 Be it enacted": drop line numbers
                    t = re.search(r"A BILL\s+(?:\d+\s+)?(FOR AN ACT\s.+?)\s*(?:Be it enacted|-1-)", text, re.S)
                    t = re.sub(r"(?m)^\s*\d+\s+", "", t.group(1)) if t else ""
                    out.append({"BioguideId": r["bioguide_id"], "Name": r["name"],
                                "Session": f"{y0}-{y1} ({leg}{'st' if leg % 10 == 1 else 'th'} Legislature)", "BillNumber": bill,
                                "BillId": f"NE-{leg}-{bill}", "Title": " ".join(t.split())[:300],
                                "IntroducedDate": date, "House": "SENATE", "AuthorName": first.group(1).strip(),
                                "IntroducedBy": names_line[:200], "IntroducedByMatch": "Yes",
                                "TextVersion": "Introduced", "TextPath": txt})
        print(f"{leg}{'st' if leg % 10 == 1 else 'th'} Legislature: LB up to {num - missing}, {sum(1 for o in out if o['BillId'].startswith(f'NE-{leg}-'))} kept",
              flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows")


if __name__ == "__main__":
    main()
