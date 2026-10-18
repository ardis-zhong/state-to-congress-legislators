#!/bin/sh
# Download the California Legislature's session database archives used by ca_pubinfo_bills.py
# (1999-2000 through 2007-08 sessions; ~1.2 GB) into ca_pubinfo_cache/. Resumable (curl -C -).
# Source: https://downloads.leginfo.legislature.ca.gov/ (public domain, Cal. Gov. Code 10248.5).
# Usage (from the repo root): sh replication/scripts/state/ca_fetch_pubinfo.sh
mkdir -p ca_pubinfo_cache
for y in 1999 2001 2003 2005 2007; do
  curl -s -C - --retry 5 -o "ca_pubinfo_cache/pubinfo_$y.zip" "https://downloads.leginfo.legislature.ca.gov/pubinfo_$y.zip" \
    && echo "pubinfo_$y.zip: $(wc -c < ca_pubinfo_cache/pubinfo_$y.zip) bytes"
done
