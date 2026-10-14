import pdfplumber, sys, os
src = "bioguide2005_cache"
for i in range(1, 26):
    pdf_path = f"{src}/GPO-CDOC-108hdoc222-4-{i}.pdf"
    out = pdf_path.replace(".pdf", ".txt")
    if os.path.exists(out):
        continue
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            w, h = page.width, page.height
            for box in ((0, 0, w / 2, h), (w / 2, 0, w, h)):
                parts.append(page.crop(box).extract_text() or "")
    open(out + ".tmp", "w").write("\n".join(parts))
    os.rename(out + ".tmp", out)
    print(i, len(parts), flush=True)
