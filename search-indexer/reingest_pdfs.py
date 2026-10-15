"""
Re-ingest selected PDFs into the DB in the current directory (rykerr_index.db),
without running the whole crawl/index build.

Why this exists: `build_index.py --force X` still crawls every page and checks
every PDF's HEAD signal, and on a Mac that re-extracts dozens of unrelated PDFs
(archive.org hands different signals to a Mac and to the GitHub runner), which
takes the better part of an hour. This touches ONLY the PDFs you name.

It also keeps each PDF's previous `sources.content_signal`, so the GitHub
Action's change detection still matches afterwards and does NOT re-extract the
PDF without OCR. (A PDF that really changed on archive.org will still be picked
up by CI, as before.)

Usage (from search-indexer/, with the project's venv):
    python reingest_pdfs.py --dry own            # extract + chunk only, no writes
    python reingest_pdfs.py own                  # re-ingest Ryan's own PDFs
    python reingest_pdfs.py --dry mapped         # which PDFs have a ToC section map?
    python reingest_pdfs.py 'o%27shea' 'panos'   # any lowercase URL substrings

Selectors: 'own' = the clinical-guides + vent-book-draft-1 archive.org items
(config.PDF_ARCHIVE_ITEM_CONTENT_TYPE); 'external' = every other PDF source;
'mapped' = every PDF (checked in --dry only, since it must download each one)
-- or any lowercase substring of the PDF URL. Run against a FRESH copy of the
live DB:  scp root@96.30.197.162:/opt/rykerr-search/rykerr_index.db .
"""
import argparse
import contextlib
import io
import re
import sys

import chunker
import config
import pdf_ingest
import store


def select_urls(conn, selectors):
    urls = [r[0] for r in conn.execute("SELECT source_id FROM sources WHERE source_type='pdf' ORDER BY source_id")]
    own_items = tuple(f"/download/{item}/" for item in config.PDF_ARCHIVE_ITEM_CONTENT_TYPE)
    chosen = []
    for u in urls:
        low = u.lower()
        is_own = any(m in low for m in own_items)
        for sel in selectors:
            if (sel == "own" and is_own) or (sel in ("external",) and not is_own) or sel == "mapped" or (
                sel not in ("own", "external", "mapped") and sel.lower() in low
            ):
                chosen.append(u)
                break
    return chosen


def plan_noncanonical(conn):
    """PDF sources stored under a URL that is not in canonical form (a literal
    space instead of %20: the same archive.org file linked two ways). Returns
    [(old, canonical, "duplicate"|"rename")]. "duplicate": the canonical twin
    is already indexed, so the old row is just dropped. "rename": only the odd
    form exists, so the canonical URL gets ingested and the old row dropped."""
    ids = [r[0] for r in conn.execute("SELECT source_id FROM sources WHERE source_type='pdf'")]
    present = set(ids)
    plan = []
    for u in ids:
        c = pdf_ingest._canonicalize_pdf_url(u)
        if c != u:
            plan.append((u, c, "duplicate" if c in present else "rename"))
    return plan


def drop_source(conn, source_id):
    conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
    conn.execute("DELETE FROM sources WHERE source_id=?", (source_id,))
    conn.execute("DELETE FROM citation_mentions WHERE citing_source_id=?", (source_id,))
    conn.commit()


def dry_run(conn, url, show=False):
    pdf_bytes = pdf_ingest.download_pdf(url)
    if pdf_bytes is None:
        print("   (download failed)")
        return None
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sections, citations, total_pages = pdf_ingest.extract_pdf_pages(pdf_bytes, url)
    log = buf.getvalue()
    m = re.search(r"sectioned by its (\w+) table of contents \((\d+) entries\)", log)
    blocks = [
        {"heading_path": s["heading_path"], "text": s["text"], "start_page": s["start_page"], "end_page": s["end_page"]}
        for s in sections
    ]
    pieces = chunker.chunk_structured_text("x", None, blocks)
    old = conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id=?", (url,)).fetchone()[0]
    own = pdf_ingest.content_type_tag(url) is not None
    cite = "section + pages" if own or total_pages > 25 else "whole document (<=25 pages)"
    src = f"{m.group(1)} ToC, {m.group(2)} entries" if m else "font-heuristic fallback"
    words = sorted(len(s["text"].split()) for s in sections) or [0]
    print(
        f"   {total_pages:>4}p  map: {src:<28} sections {len(sections):>3} (median {words[len(words)//2]}w)  "
        f"chunks {old} -> {len(pieces)}  citation: {cite}"
    )
    if show:
        for sec in sections:
            print(f"      p{sec['start_page']}-{sec['end_page']} {len(sec['text'].split()):>5}w  {sec['heading_path']}")
    return m is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("selectors", nargs="+")
    ap.add_argument("--dry", action="store_true", help="extract and chunk only; write nothing")
    ap.add_argument("--show", action="store_true", help="with --dry: list every section (pages, words, heading path)")
    args = ap.parse_args()

    if "mapped" in args.selectors and not args.dry:
        sys.exit("'mapped' is for --dry only (it selects every PDF); name 'own', 'external' or URL substrings to write")
    conn = store.connect()
    urls = select_urls(conn, args.selectors)
    if not urls:
        sys.exit("no PDF sources matched")
    plan = plan_noncanonical(conn)
    for old, canon, kind in plan:
        print(f"non-canonical PDF URL ({kind}): {old}\n    -> {canon}")
    renames = {canon: old for old, canon, kind in plan if kind == "rename"}
    dups = {o for o, _, k in plan if k == "duplicate"}
    urls = [u for u in urls if u not in dups]
    if not args.dry:
        for old in sorted(dups):
            drop_source(conn, old)
            print(f"   dropped duplicate source {old.rsplit('/', 1)[-1]}")
    # a "rename" is ingested under its canonical URL (selected even if no selector named it)
    for old, canon, kind in plan:
        if kind == "rename" and canon not in urls and (not args.dry):
            urls.append(canon)
        if kind == "rename" and old in urls:
            urls.remove(old)
    print(f"{len(urls)} PDF(s) selected{' (dry run)' if args.dry else ''}")

    if args.dry:
        mapped = 0
        for i, u in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {u.rsplit('/', 1)[-1][:70]}")
            try:
                if dry_run(conn, u, args.show):
                    mapped += 1
            except Exception as e:
                print(f"   ! error: {e}")
        print(f"\n{mapped}/{len(urls)} have a ToC section map")
        return

    import build_index
    import reference_citations
    by_permalink, by_author_year, _ = reference_citations.build_reference_index(config.REFERENCES_REPO_ROOT)
    stats = {"seen": 0, "changed": 0, "unchanged": 0, "chunks_written": 0, "failed": 0}
    for i, u in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {u.rsplit('/', 1)[-1][:70]}", flush=True)
        prev = conn.execute("SELECT content_signal FROM sources WHERE source_id=?", (u,)).fetchone()
        if prev is None and u in renames:  # inherit the old row's signal so CI sees it as unchanged
            prev = conn.execute("SELECT content_signal FROM sources WHERE source_id=?", (renames[u],)).fetchone()
        old = conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id=?", (u,)).fetchone()[0]
        before_changed = stats["changed"]
        try:
            # force_substr="" is a substring of every URL, so this always reprocesses
            build_index._index_one_pdf(conn, u, "", stats, by_permalink, by_author_year)
        except Exception as e:
            stats["failed"] += 1
            print(f"   ! error, left as it was: {e}")
            continue
        if stats["changed"] > before_changed and prev is not None:
            conn.execute("UPDATE sources SET content_signal=? WHERE source_id=?", (prev[0], u))
            conn.commit()
        new = conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id=?", (u,)).fetchone()[0]
        print(f"   chunks {old} -> {new}")
        if u in renames and new > 0:
            drop_source(conn, renames[u])
            print(f"   dropped old-form source {renames[u].rsplit('/', 1)[-1]}")
    print(f"\nre-ingested {stats['changed']}, failed {stats['failed']}")
    print("integrity:", conn.execute("PRAGMA integrity_check").fetchone()[0])
    print("total chunks:", conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])


if __name__ == "__main__":
    main()
