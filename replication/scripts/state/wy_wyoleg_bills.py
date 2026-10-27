#!/usr/bin/env python3
"""
Wyoming Senate files and joint resolutions, 2003-2007, from the Wyoming Legislature's website
(wyoleg.gov), for John Barrasso (Wyoming Senate 2003-2007), the only population member who served in
the Legislature between its online archive (1997 on) and LegiScan's Wyoming coverage. Wyoming
state-text pilot (2026-10-27). The site has no robots.txt.

The site's bill pages are a JavaScript application, so the introduced texts are read directly
(/<year>/Introduced/SF0001.pdf, SJ0001.pdf, until 15 numbers in a row are missing). Each prints
"Sponsored by: Senator(s) Barrasso, ..."; items whose first sponsor is Barrasso are kept.

Polite: one request at a time, at least 2 seconds apart, a User-Agent naming the project, every
response cached under wy_wyoleg_cache/.

USAGE (from the repo root):
    python3 replication/scripts/state/wy_wyoleg_bills.py
"""

import csv
import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://wyoleg.gov"
CACHE = "wy_wyoleg_cache"
YEARS = range(2003, 2008)
TYPES = ["SF", "SJ"]
PERSON = {"bioguide_id": "B001261", "name": "John Barrasso", "surname": "Barrasso"}
TEXT_OUT = "wy_state_legislation_sponsored.csv"
UA = "state-to-congress-legislators/1.0 (research dataset; https://github.com/ardis-zhong/state-to-congress-legislators)"
DELAY = 2
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
    out = []
    for year in YEARS:
        for typ in TYPES:
            missing, num = 0, 0
            while missing < 15:
                num += 1
                bill = f"{typ}{num:04d}"
                txt = os.path.join(CACHE, "texts", f"{year}_{bill}.txt")
                if not os.path.exists(txt):
                    raw = fetch(f"{BASE}/{year}/Introduced/{bill}.pdf")
                    if raw is None:
                        continue
                    text = ""
                    if raw[:4] == b"%PDF":
                        local = os.path.join(CACHE, "pdf", f"{year}_{bill}.pdf")
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
                m = re.search(r"Sponsored by:\s*(?:Senators?\(s\)|Senators?|Representatives?\(s\)|Representatives?)?\s*([^\n]+)", text[:1500])
                names = " ".join(m.group(1).split()) if m else ""
                first = re.split(r",| and ", names)[0].strip()
                if re.sub(r"[^a-z]", "", first.lower()) == PERSON["surname"].lower():
                    title = re.search(rf"{typ[0]}\w+ (?:FILE|JOINT RESOLUTION) NO\. {bill}\n(.+)", text)
                    out.append({"BioguideId": PERSON["bioguide_id"], "Name": PERSON["name"],
                                "Session": f"{year} General Session" if year % 2 else f"{year} Budget Session",
                                "BillNumber": bill, "BillId": f"WY-{year}-{bill}",
                                "Title": title.group(1).strip() if title else "", "IntroducedDate": "",
                                "House": "SENATE", "AuthorName": first, "IntroducedBy": names[:200],
                                "IntroducedByMatch": "Yes", "TextVersion": "Introduced", "TextPath": txt})
            print(f"{year} {typ}: up to {num - missing}, {sum(1 for o in out if o['BillId'].startswith(f'WY-{year}-{typ}'))} kept", flush=True)
    with open(TEXT_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {TEXT_OUT}: {len(out)} rows")


if __name__ == "__main__":
    main()
