import csv, re, sys, glob, os
S = sys.argv[1]
uni = {u["bioguide"]: u for u in csv.DictReader(open(S + "/universe.csv"))}
cands = {r["bioguide"]: r for r in csv.DictReader(open(S + "/candidates.csv"))}
LEG = re.compile(r"(House of Representatives|House of Delegates|State Senate|Senate|Assembly|Legislature|Unicameral|General Court)", re.I)
NOT = re.compile(r"United States|U\.S\.|\bUS\b|Congress", re.I)
out = []
for f in sorted(glob.glob(S + "/wiki/*.txt")):
    b = os.path.basename(f)[:-4]
    t = open(f).read()
    title = t.split("\n")[0]
    info, _, text = t.partition("=== TEXT")
    offices = []
    for m in re.finditer(r"\|\s*office(\d*)\s*=\s*([^\n]+)", info):
        o = m.group(2)
        if LEG.search(o) and not NOT.search(o):
            k = m.group(1)
            ts = re.search(rf"\|\s*term_start{k}\s*=\s*([^\n|]+)", info); te = re.search(rf"\|\s*term_end{k}\s*=\s*([^\n|]+)", info)
            st = re.search(rf"\|\s*state_(?:senate|house|assembly|delegate)\d*\s*=\s*([^\n]+)", info)
            clean = re.sub(r"[\[\]]", "", o).strip(); a = (ts.group(1).strip() if ts else "?")[:25]; z = (te.group(1).strip() if te else "?")[:25]
            offices.append(f"{clean} ({a} - {z})")
    for m in re.finditer(r"\|\s*(state_(?:senate|house|assembly|delegate)\d*)\s*=\s*([^\n]+)", info):
        v = re.sub(r"[\[\]]", "", m.group(2)).strip()[:60]; offices.append(f"{m.group(1)}={v}")
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if LEG.search(s) and not re.search(r"United States (House|Senate)|U\.S\. (House|Senate)|to Congress", s)]
    sents = [s for s in sents if re.search(r"\b(elected|served|member|represent|won|appointed|sworn|seat)", s, re.I)][:4]
    u = uni[b]
    out.append([b, u["name"], u["state"], f"{u['first_fed']}-{u['last_fed']}", cands.get(b, {}).get("n_sources", "0"), title,
                " || ".join(offices)[:400], " || ".join(x[:220] for x in sents)])
w = csv.writer(open(S + "/wiki_evidence.csv", "w")); w.writerow(["bioguide", "name", "state", "fed", "n_sources", "wiki_title", "infobox_state_offices", "text_sentences"]); w.writerows(out)
for o in out:
    print(f"\n## {o[0]} {o[1]} ({o[2]}, {o[3]}) src={o[4]} [{o[5]}]\n  INFOBOX: {o[6][:300]}\n  TEXT: {o[7][:500]}")
