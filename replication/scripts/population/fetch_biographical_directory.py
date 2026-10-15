#!/usr/bin/env python3
"""
Download the *Biographical Directory of the United States Congress, 1774-2005*
(H. Doc. 108-222, GovInfo package GPO-CDOC-108hdoc222) and extract its
biographies as plain text. extract_veterans.py uses it for members with no
Congressional Directory biography (members whose service since 1979 ended
before 1981, and a few who never submitted one, e.g. William Proxmire).

GovInfo publishes the biography section as 25 PDF granules (AANDAHL to AYRES,
... ZABLOCKI to ZWACH). Pages are set in two columns, so each page is cropped
into a left and a right half before text extraction (pdfplumber).

OUTPUT (gitignored, at the repo root):
    bioguide2005_cache/GPO-CDOC-108hdoc222-4-<n>.pdf   the granule PDFs
    bioguide2005_cache/GPO-CDOC-108hdoc222-4-<n>.txt   extracted text, column by column

USAGE (from the repo root; the key is an api.data.gov key, the same one used
for Congress.gov):
    python3 replication/scripts/population/fetch_biographical_directory.py --api-key "$CONGRESS_API_KEY"
Re-running skips files already downloaded or extracted.
"""

import argparse
import os
import time
import urllib.request

import pdfplumber

PACKAGE = "GPO-CDOC-108hdoc222"
GRANULES = range(1, 26)  # GPO-CDOC-108hdoc222-4-1 ... -4-25: the biographies, A to Z
CACHE_DIR = "bioguide2005_cache"


def download(url, path):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                data = r.read()
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.rename(path + ".tmp", path)
            return
        except Exception as e:  # network hiccup: wait and retry
            print(f"  retry {attempt + 1}: {e}")
            time.sleep(10 * (attempt + 1))
    raise SystemExit(f"could not download {path}")


def extract(pdf_path, txt_path):
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            w, h = page.width, page.height
            for box in ((0, 0, w / 2, h), (w / 2, 0, w, h)):
                parts.append(page.crop(box).extract_text() or "")
    with open(txt_path + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    os.rename(txt_path + ".tmp", txt_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", required=True)
    args = ap.parse_args()
    os.makedirs(CACHE_DIR, exist_ok=True)
    for i in GRANULES:
        gid = f"{PACKAGE}-4-{i}"
        pdf_path = os.path.join(CACHE_DIR, gid + ".pdf")
        txt_path = os.path.join(CACHE_DIR, gid + ".txt")
        if not os.path.exists(pdf_path):
            download(f"https://api.govinfo.gov/packages/{PACKAGE}/granules/{gid}/pdf?api_key={args.api_key}",
                     pdf_path)
        if not os.path.exists(txt_path):
            extract(pdf_path, txt_path)
        print(f"{gid}: ok")


if __name__ == "__main__":
    main()
