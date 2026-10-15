"""Saves local copies of indexed PDFs (matching lowercase URL substrings) into
../../pdf-probe/ so their structure can be inspected offline.
Run from search-indexer/:
    ./venv312/bin/python3 fetch_probe_pdfs.py                     # the default set
    ./venv312/bin/python3 fetch_probe_pdfs.py walas o%27shea      # named substrings"""
import os, sqlite3, sys, urllib.parse as up
import config, pdf_ingest
out = os.path.abspath(os.path.join("..", "..", "pdf-probe")); os.makedirs(out, exist_ok=True)
conn = sqlite3.connect(f"file:{config.OUTPUT_DB_PATH}?mode=ro", uri=True)
urls = [r[0] for r in conn.execute("select source_id from sources where source_type='pdf'")]
wanted = [w.lower() for w in sys.argv[1:]] or ["field%20reference%20guides", "ems%20drug%20guide", "vent%20management%20guide", "management%20of%20hyperkalemia", "12-lead%20ekg"]
for u in urls:
    if any(w in u.lower() for w in wanted):
        name = up.unquote(u.rsplit("/", 1)[-1]).replace("/", "_")
        dest = os.path.join(out, name)
        if os.path.exists(dest): print("have", name); continue
        data = pdf_ingest.download_pdf(u)
        if data: open(dest, "wb").write(data); print("saved", name, len(data))
        else: print("FAILED", u)
