"""One-off survey (2026-10-14): which indexed PDFs carry a usable table of
contents, and in what form? For every PDF source in the local index it
downloads the file (same downloader the indexer uses) and records
  - the embedded outline/bookmarks (PyMuPDF get_toc): entry count + depth
  - whether one of the first few pages looks like a PRINTED ToC (lines
    ending in dot/ellipsis leaders + page numbers, or many "Title 12" runs)
Results go to toc_probe_out.json (read by a human/Claude to decide how
ToC-guided chunking should work) and a summary table is printed.
Run from search-indexer/:  ./venv312/bin/python3 toc_probe.py
Optional: pass a lowercase substring to survey only matching URLs."""
import json, re, sqlite3, sys, time
import pymupdf
import config
import pdf_ingest

LEADER_RE = re.compile(r"(?:\.\s*){2,}\d{1,3}\b|…\s*\d{1,3}\b|\.{2,}\s*\d{1,3}\b")
only = sys.argv[1].lower() if len(sys.argv) > 1 else None

conn = sqlite3.connect(f"file:{config.OUTPUT_DB_PATH}?mode=ro", uri=True)
rows = conn.execute(
    "select s.source_id, (select source_title from chunks c where c.source_id=s.source_id limit 1) "
    "from sources s where s.source_type='pdf' order by s.source_id").fetchall()
rows = [r for r in rows if not only or only in r[0].lower()]
print(f"{len(rows)} PDF source(s) to survey", flush=True)

results = []
for i, (url, title) in enumerate(rows, 1):
    rec = {"url": url, "title": title}
    t0 = time.time()
    try:
        data = pdf_ingest.download_pdf(url)
        if data is None:
            rec["error"] = "download failed / not a PDF"
        else:
            doc = pymupdf.open(stream=data, filetype="pdf")
            rec["pages"] = len(doc)
            outline = doc.get_toc(simple=True)  # [level, title, page]
            rec["outline_entries"] = len(outline)
            rec["outline_max_level"] = max((o[0] for o in outline), default=0)
            rec["outline_head"] = outline[:60]
            best = (0, None)
            for pno in range(min(8, len(doc))):
                n = len(LEADER_RE.findall(doc[pno].get_text()))
                if n > best[0]:
                    best = (n, pno + 1)
            rec["printed_toc_matches"] = best[0]
            rec["printed_toc_page"] = best[1]
            doc.close()
    except Exception as e:
        rec["error"] = repr(e)[:200]
    results.append(rec)
    print(f"[{i}/{len(rows)}] {time.time()-t0:4.1f}s outline={rec.get('outline_entries','-'):>4} "
          f"printedToC={rec.get('printed_toc_matches','-'):>3} pages={rec.get('pages','-'):>4}  {(title or url)[:60]}", flush=True)

with open("toc_probe_out.json", "w") as f:
    json.dump(results, f, indent=1)
ok = [r for r in results if "error" not in r]
print("\nSUMMARY")
print(f"  surveyed: {len(results)}   errors: {len(results)-len(ok)}")
print(f"  with embedded outline: {sum(1 for r in ok if r['outline_entries']>0)}")
print(f"  with printed-ToC page (>=5 leader lines in first 8 pages): {sum(1 for r in ok if r['printed_toc_matches']>=5)}")
print("Wrote toc_probe_out.json")
