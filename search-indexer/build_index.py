"""
Main entry point. Run this overnight (or manually) to update the search
index:

    python build_index.py               # incremental — the normal case, always
    python build_index.py --force vent  # incremental, but force-reprocess sources matching "vent"
    python build_index.py --full        # force a from-scratch rebuild (rare — see below)

Incremental is the default and does real work efficiently: it crawls
every site in config.SITES and checks every linked PDF, but only
re-chunks and re-embeds a source (a page or a PDF) when its content has
actually changed since the last run — unchanged sources are left alone
entirely, which means no download and no OCR for them. Anything removed
from the site (or newly added to curation/excluded_urls.txt, or no
longer discovered because a crawl-logic fix collapsed a duplicate URL)
gets pruned from the index automatically, same as a full rebuild would
do — so a fix to *discovery* logic (crawl.py) never needs --full, only
a plain incremental run. See store.py's module docstring for how the
change-detection is tracked.

A PDF's "has it changed" check is based on the PDF's own bytes on the
server (via get_remote_signal — a cheap HEAD request), combined with
pdf_ingest.PDF_PIPELINE_VERSION. That combination matters: a fix to how
THIS CODE extracts a PDF (OCR, the changelog-page detector, chunking,
etc.) doesn't change the PDF's own bytes, so without the version folded
in, incremental mode would silently keep serving stale chunks from
before the fix. Bumping PDF_PIPELINE_VERSION (in pdf_ingest.py) is how
you tell it "re-extract everything once" without paying for a full wipe
— on the very next incremental run every PDF reprocesses exactly once
(the OCR-heavy part, same cost as today), and then it's back to fast
until the next bump.

--force SUBSTR is for fast day-to-day iteration on one specific
document: it skips change detection for just the source(s) whose URL or
title contains SUBSTR (case-insensitive — e.g. "vent", "field reference"),
so you can test a fix against the one PDF you're actually working on
without waiting through the other ~20 unrelated ones on every run.

A full rebuild (--full) wipes everything and starts clean, including all
the change-detection history above. You shouldn't normally need it —
it happens automatically if config.EMBEDDING_MODEL_NAME has changed
since the last run, because embeddings from two different models aren't
comparable and mixing them would silently corrupt search quality. Use
--full yourself only if you suspect the index has drifted from reality
in some way neither of the above covers and want a clean slate.
"""
import argparse
import hashlib
import sys
import time

from tqdm import tqdm

import chunker
import config
import crawl
import curation
import embedder
import extract
import frontmatter_tags
import pdf_ingest
import podcast_ingest
import reference_citations
import store
import tags as tags_module


def _hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# A source whose chunk count collapses between runs is almost always a
# sign that extraction or cleanup broke, not that the actual document
# shrank that much. This is the safety net that a real bug slipped past
# undetected: an over-eager cleanup regex silently wiped 227 of 266 pages
# of a real PDF (67 chunks down to 19), and the only signal was a build
# warning worded as if the PDF might just be scanned images — plausible
# enough that it took a manual investigation to catch. This check is
# louder and more specific on purpose. It only fires once a real baseline
# exists for a source (a --full rebuild wipes history, so the very next
# build after one won't have anything to compare against yet — this
# protects future incremental runs, which is normal day-to-day operation
# whenever a document gets added or updated).
_CHUNK_REGRESSION_MIN_PREVIOUS = 5   # don't warn on tiny sources — too noisy to mean much
_CHUNK_REGRESSION_THRESHOLD = 0.5    # warn if the new count is under half the old one


def _check_chunk_regression(conn, title, source_id, new_count):
    previous = store.get_source_chunk_count(conn, source_id)
    if previous is None or previous < _CHUNK_REGRESSION_MIN_PREVIOUS:
        return
    if new_count < previous * _CHUNK_REGRESSION_THRESHOLD:
        pct = 100 * (1 - new_count / previous)
        print(
            f"\n  !!! CHUNK COUNT DROPPED: {title!r} went from {previous} to {new_count} chunks "
            f"(-{pct:.0f}%). This usually means extraction or cleanup broke for this source, NOT "
            f"that the actual document shrank — worth checking the warnings above (and the source "
            f"itself) before trusting this rebuild. ({source_id})\n"
        )


def index_webpages(conn, excluded_patterns, defer_overrides, force_substr=None):
    """Crawls every page in config.SITES, skipping re-chunk/re-embed for
    any page whose extracted text hasn't changed since last time — unless
    force_substr matches its URL or title, which reprocesses it
    regardless (see --force).

    defer_overrides: curation.load_defer_overrides()'s output — manual
    "cite something else for this chunk" rules, applied on top of
    extract.py's own auto-detected links_to (see curation.resolve_defer
    and curation/defer_to.txt) wherever a chunk's page+heading matches
    one.

    Returns (discovered_pdf_urls, current_page_source_ids, stats)."""
    stats = {
        "seen": 0, "changed": 0, "unchanged": 0, "chunks_written": 0,
        "with_tags": 0, "with_frontmatter_tags": 0,
    }
    discovered_pdfs = set()
    current_source_ids = set()

    post_index = frontmatter_tags.build_post_index(config.POSTS_REPO_ROOT)
    if post_index:
        print(
            f"Found {len(post_index)} blog post source file(s) with tag "
            f"front matter under {config.POSTS_REPO_ROOT!r}"
        )
    else:
        print(
            f"No post source files with tag front matter found under "
            f"{config.POSTS_REPO_ROOT!r} — falling back to HTML-guessed "
            f"tags only (see tags.py). If the indexer isn't running from "
            f"inside the site's own repo checkout, set config.POSTS_REPO_ROOT."
        )

    for site in config.SITES:
        print(f"\n=== {site} ===")
        urls = crawl.discover_urls(site)
        urls, skipped = curation.filter_excluded(urls, excluded_patterns)
        if skipped:
            print(f"  excluded {len(skipped)} page(s) per curation/excluded_urls.txt")

        for url in tqdm(urls, desc="checking pages"):
            html = crawl.fetch_html(url)
            if html is None:
                continue

            discovered_pdfs.update(pdf_ingest.find_pdf_links(html, url))

            page = extract.extract_page(html, url)
            if page is None:
                continue

            current_source_ids.add(url)
            stats["seen"] += 1

            forced = force_substr is not None and (
                force_substr in url.lower() or force_substr in page["title"].lower()
            )
            # Signal has to cover everything that can change what gets
            # embedded now that a page is title + blurb + structured
            # blocks rather than one flat text field — a blurb edit or a
            # heading change with the same body prose underneath should
            # still trigger a re-embed.
            content_repr = "\x1e".join([
                page["title"], page["blurb"] or "",
                *(f"{b['heading_path'] or ''}\x1f{b['text']}" for b in page["blocks"]),
            ])
            content_signal = _hash_text(content_repr)
            if not forced and store.get_source_signal(conn, url) == content_signal:
                stats["unchanged"] += 1
                continue

            pieces = chunker.chunk_structured_text(page["title"], page["blurb"], page["blocks"])
            if not pieces:
                continue

            fm_tags = frontmatter_tags.match_tags_for_page(post_index, url, page["title"])
            if fm_tags:
                page_tags = fm_tags
                stats["with_frontmatter_tags"] += 1
            else:
                # Fallback for pages that aren't Jekyll posts (or that we
                # couldn't match to a source file) — best-effort HTML
                # guessing, may find nothing. See tags.py.
                page_tags = tags_module.extract_tags(html)
            if page_tags:
                stats["with_tags"] += 1

            embeddings = embedder.embed_documents([p["text"] for p in pieces])
            chunk_rows = [
                # locator carries the section heading (e.g. "Anatomical
                # Differences"), same idea as a PDF's "Page N" — lets a
                # result show WHICH part of the page it's from, not just
                # the page as a whole. Empty for a page with no in-body
                # heading structure at all (most short posts).
                #
                # links_to: a manual override (curation/defer_to.txt)
                # takes precedence over extract.py's own auto-detected
                # links_to when both apply to the same chunk — an
                # explicit editorial call beats a heuristic. Either way
                # this is just metadata carried on the chunk; the actual
                # citation swap happens at query time (see retrieval.py
                # on the server), never here — the chunk's own text is
                # still exactly what gets embedded and matched.
                {
                    "locator": piece.get("heading_path") or "",
                    "locator_url": url, "chunk_index": i,
                    "text": piece["text"], "embedding": vec,
                    "links_to": (
                        curation.resolve_defer(url, piece.get("heading_path"), defer_overrides)
                        or piece.get("links_to")
                    ),
                }
                for i, (piece, vec) in enumerate(zip(pieces, embeddings))
            ]
            _check_chunk_regression(conn, page["title"], url, len(chunk_rows))
            store.replace_source_chunks(
                conn, "webpage", url, page["title"], chunk_rows, content_signal, tags=page_tags
            )
            conn.commit()
            stats["changed"] += 1
            stats["chunks_written"] += len(chunk_rows)

    return discovered_pdfs, current_source_ids, stats


def _versioned(signal):
    """Folds pdf_ingest.PDF_PIPELINE_VERSION into a raw content signal, so
    that bumping the version (after an extraction-logic change) makes
    every previously-stored signal stop matching — forcing exactly one
    reprocess per PDF on the next run — without needing a full wipe. See
    PDF_PIPELINE_VERSION's docstring in pdf_ingest.py."""
    return f"{signal}::pv{pdf_ingest.PDF_PIPELINE_VERSION}"


def _resolve_citation_entry(entry, by_permalink, by_author_year):
    """Returns a list of resolved targets for one citation-blurb entry —
    usually one, but two for a shared-blurb entry citing two works at
    once (confirmed real: "126 Murphy, 2017b; Macintyre, 2014 - ..." is
    one blurb, two separate links, two separate citation sources). Each
    target is {"citation_id", "title", "category"}.

    Tries every real hyperlink on the entry first (reference_citations.
    resolve_link — exact, no guessing, and immune to the visible label
    text itself being wrong). Only falls back to author/year + content
    matching (fuzzy_match_label, using the entry's own label/blurb text)
    when there's no usable link at all, or a references.rykerrmedical.com
    link that doesn't match anything in the repo (a stale/typo'd
    filename) — never for an entry that already resolved via a real
    link, however many pieces it has."""
    targets = []
    seen_ids = set()

    def _add(citation_id, title, category):
        if citation_id and citation_id not in seen_ids:
            seen_ids.add(citation_id)
            targets.append({"citation_id": citation_id, "title": title, "category": category})

    for uri in entry["links"]:
        citation_id, ref_entry = reference_citations.resolve_link(uri, by_permalink)
        if citation_id and ref_entry:
            _add(citation_id, ref_entry["title_guess"], ref_entry["category"])
        elif citation_id:
            # Direct link to the primary source (a journal, PMC, YouTube,
            # etc.) with no rykerr-references page in between — no repo
            # title to borrow, so the entry's own label is the best title
            # available (a future title/abstract pass could improve this).
            _add(citation_id, entry["label"], "")
        # else: a references.rykerrmedical.com link that matched nothing
        # in the repo — fall through below rather than leave this piece
        # unresolved just because one link was stale.

    if targets:
        return targets

    match = reference_citations.fuzzy_match_label(entry["label"], by_author_year, entry["blurb"])
    if match:
        _add(
            f"https://{reference_citations.REFERENCES_HOST}{match['permalink']}",
            match["title_guess"],
            match["category"],
        )
    return targets


def index_pdfs(conn, pdf_urls, by_permalink, by_author_year, force_substr=None):
    """Checks every discovered PDF, skipping the download entirely when
    a cheap HEAD-request signal (ETag/Last-Modified/size) matches what
    was stored last time AND pdf_ingest.PDF_PIPELINE_VERSION hasn't
    changed since. Only downloads, re-extracts, and re-embeds PDFs that
    are new, have actually changed, or fall on the wrong side of a
    pipeline-version bump — or that force_substr matches (see --force),
    which always reprocesses regardless of any signal.

    force_substr matches against the URL only, not the title — the whole
    point of --force is to skip the download for everything that ISN'T
    forced, so the match has to happen before anything is downloaded, and
    the title isn't known until after. In practice this is fine: PDFs
    here are almost always archive.org links, and archive.org URLs
    already carry a real item/file name (e.g. "vent-book-draft-1", or a
    filename like "Field Reference Guides Draft with Links.pdf"), not an
    opaque hash."""
    stats = {"seen": 0, "changed": 0, "unchanged": 0, "chunks_written": 0, "failed": 0}

    for pdf_url in tqdm(sorted(pdf_urls), desc="checking PDFs"):
        stats["seen"] += 1
        try:
            _index_one_pdf(conn, pdf_url, force_substr, stats, by_permalink, by_author_year)
        except Exception as e:
            # A single PDF's processing throwing is not a reason to lose
            # an entire run. Confirmed as a real, non-hypothetical risk
            # once the corpus grew from 21 PDFs to ~360 (the
            # rykerr-references citations): download_pdf already retries
            # network blips, but extraction/chunking/embedding could in
            # principle still hit something unexpected on any one PDF
            # (a malformed file, an OCR edge case, etc.), and at this
            # volume "unexpected" stops being rare. Everything already
            # committed for earlier PDFs in this run is unaffected either
            # way (each PDF commits independently) - this just means one
            # bad PDF costs a log line instead of the whole build.
            stats["failed"] += 1
            print(f"  ! unexpected error processing {pdf_url}, skipping: {e}")

    return stats


def _index_one_pdf(conn, pdf_url, force_substr, stats, by_permalink, by_author_year):
    forced = force_substr is not None and force_substr in pdf_url.lower()
    previous_signal = store.get_source_signal(conn, pdf_url)
    remote_signal = pdf_ingest.get_remote_signal(pdf_url)

    if not forced and remote_signal is not None and _versioned(remote_signal) == previous_signal:
        stats["unchanged"] += 1
        return

    pdf_bytes = pdf_ingest.download_pdf(pdf_url)
    if pdf_bytes is None:
        return

    title = pdf_ingest.pdf_title(pdf_bytes, pdf_url)

    # No usable HEAD signal from this server — fall back to hashing
    # the bytes we just downloaded. Still avoids re-embedding when
    # nothing changed; it just can't skip the download itself in
    # that case, since there was no cheaper way to check.
    content_signal = remote_signal or hashlib.sha256(pdf_bytes).hexdigest()
    if not forced and _versioned(content_signal) == previous_signal:
        stats["unchanged"] += 1
        return
    sections, citation_entries = pdf_ingest.extract_pdf_pages(pdf_bytes, pdf_url)

    # Resolve and store this PDF's citation-blurb mentions regardless of
    # whether `sections` ends up empty — this is the one point where we
    # actually have the PDF open and its blurbs extracted, so it has to
    # happen here even on a run where the surrounding body text produces
    # nothing to chunk. See store.replace_citation_mentions — this is
    # what durably records "PDF X currently cites these works", so
    # _write_citation_sources (called once after all PDFs are checked)
    # can assemble each citation's full chunk set from every PDF that's
    # ever cited it, not just ones reprocessed this run.
    mention_rows = []
    for entry in citation_entries:
        targets = _resolve_citation_entry(entry, by_permalink, by_author_year)
        if targets:
            for target in targets:
                mention_rows.append({
                    "page": entry["page"], "number": entry["number"], "label": entry["label"],
                    "blurb": entry["blurb"], "target_id": target["citation_id"],
                    "target_title": target["title"], "target_category": target["category"],
                })
        else:
            mention_rows.append({
                "page": entry["page"], "number": entry["number"], "label": entry["label"],
                "blurb": entry["blurb"], "target_id": None, "target_title": None, "target_category": None,
            })
    store.replace_citation_mentions(conn, pdf_url, title, mention_rows)
    conn.commit()
    if mention_rows:
        unresolved = sum(1 for m in mention_rows if not m["target_id"])
        print(
            f"  - {pdf_url}: {len(mention_rows)} citation blurb(s), "
            f"{len(mention_rows) - unresolved} resolved, {unresolved} unresolved"
        )

    if not sections:
        print(f"  ! no extractable text in {pdf_url}, skipping")
        return

    # chunk_structured_text needs "text" plus whatever pass-through
    # metadata each resulting chunk should carry — here that's
    # start_page/end_page, so a section split into several word-count
    # windows still knows which pages EVERY one of its pieces came from,
    # not just the section as a whole.
    blocks = [
        {
            "heading_path": s["heading_path"],
            "text": s["text"],
            "start_page": s["start_page"],
            "end_page": s["end_page"],
        }
        for s in sections
    ]
    pieces = chunker.chunk_structured_text(title, None, blocks)
    embeddings = embedder.embed_documents([p["text"] for p in pieces])
    chunk_rows = [
        {
            "locator": (
                f"Page {p['start_page']}" if p["start_page"] == p["end_page"]
                else f"Pages {p['start_page']}-{p['end_page']}"
            ),
            "locator_url": pdf_ingest.locator_url_for_page(pdf_url, p["start_page"]),
            "chunk_index": i,
            "text": p["text"],
            "embedding": vec,
        }
        for i, (p, vec) in enumerate(zip(pieces, embeddings))
    ]

    if not chunk_rows:
        return

    _check_chunk_regression(conn, title, pdf_url, len(chunk_rows))
    store.replace_source_chunks(conn, "pdf", pdf_url, title, chunk_rows, _versioned(content_signal))
    conn.commit()
    stats["changed"] += 1
    stats["chunks_written"] += len(chunk_rows)


def _write_citation_sources(conn):
    """Assembles every resolved citation-blurb mention (across every
    primary PDF ever indexed — see store.all_citation_mentions) into its
    own small "citation" source, one per cited work, grouping mentions
    by their resolved target so the same work cited from two different
    documents (or twice in one) ends up as multiple chunks under ONE
    source rather than two competing sources. Always recomputes from the
    current mentions table rather than trying to skip unchanged ones —
    there are at most a few hundred of these and each blurb is a
    sentence or two, so re-embedding all of them every run is cheap
    (nothing like re-OCRing a PDF) and keeps this step simple. Returns
    (stats, current_citation_source_ids) — the latter is folded into
    prune_missing_sources' current set so a citation source whose last
    mention disappears (e.g. the citing PDF was removed, or a footnote
    was edited out) gets cleaned up same as any other source."""
    stats = {"sources": 0, "chunks": 0, "unresolved_mentions": 0}
    mentions = store.all_citation_mentions(conn)

    by_target = {}
    for m in mentions:
        if not m["target_id"]:
            stats["unresolved_mentions"] += 1
            continue
        by_target.setdefault(m["target_id"], []).append(m)

    current_ids = set()
    for target_id, group in by_target.items():
        current_ids.add(target_id)
        title = next((m["target_title"] for m in group if m["target_title"]), group[0]["label"])
        category = next((m["target_category"] for m in group if m["target_category"]), "")

        texts = [f"{m['label']} — {m['blurb']}" for m in group]
        embeddings = embedder.embed_documents(texts)
        chunk_rows = [
            {
                "locator": f"Cited in {m['citing_title']}, Page {m['page']}",
                "locator_url": target_id,
                "chunk_index": i,
                "text": text,
                "embedding": vec,
            }
            for i, (m, text, vec) in enumerate(zip(group, texts, embeddings))
        ]
        content_signal = _hash_text("|".join(sorted(texts)))
        tags = [category] if category else None
        store.replace_source_chunks(conn, "citation", target_id, title, chunk_rows, content_signal, tags=tags)
        conn.commit()
        stats["sources"] += 1
        stats["chunks"] += len(chunk_rows)

    return stats, current_ids


def build(force_full=False, force_substr=None):
    start = time.time()
    conn = store.connect()

    last_model = store.get_meta(conn, "embedding_model")
    if force_full or (last_model and last_model != config.EMBEDDING_MODEL_NAME):
        if force_full:
            reason = "--full requested"
        else:
            reason = f"embedding model changed ({last_model} -> {config.EMBEDDING_MODEL_NAME})"
        print(f"Doing a full rebuild ({reason})")
        store.reset_all(conn)

    if force_substr:
        print(f"--force {force_substr!r}: reprocessing any source whose URL/title matches, regardless of change detection")

    excluded_patterns = curation.load_excluded_patterns()
    if excluded_patterns:
        print(f"Loaded {len(excluded_patterns)} exclusion rule(s) from curation/excluded_urls.txt")

    defer_overrides = curation.load_defer_overrides()
    if defer_overrides:
        print(f"Loaded {len(defer_overrides)} citation-override rule(s) from curation/defer_to.txt")

    discovered_pdfs, page_source_ids, page_stats = index_webpages(
        conn, excluded_patterns, defer_overrides, force_substr
    )
    discovered_pdfs = set(discovered_pdfs)

    # Resolves the citation blurbs pdf_ingest.py pulls out of your own
    # primary PDFs' footnotes (see pdf_ingest.extract_citation_blurbs) to
    # the real work each one cites — built once here from the
    # rykerr-references repo and threaded through to _index_one_pdf.
    # This REPLACES the earlier approach of feeding every cited PDF into
    # the same full page-by-page chunking pipeline as your own documents
    # (find_cited_pdfs / discovered_pdfs |= cited_pdfs) — confirmed with
    # real numbers that that produced excessive bulk data (5 whole-
    # textbook citations alone were ~12,600 of ~25,000 total PDF chunks,
    # more than every one of your own authored documents combined).
    # Citation sources are now small — your own blurb text plus a
    # resolved title, not the cited work's full content.
    by_permalink, by_author_year, ref_stats = reference_citations.build_reference_index(config.REFERENCES_REPO_ROOT)
    if ref_stats["pages_scanned"]:
        print(
            f"\nLoaded {len(by_permalink)} reference page(s) ({ref_stats['pages_scanned']} scanned) "
            f"under {config.REFERENCES_REPO_ROOT!r} for citation matching"
        )
    else:
        print(
            f"\nNo reference pages found under {config.REFERENCES_REPO_ROOT!r} — citation blurbs will be "
            f"extracted but left unresolved (check config.REFERENCES_REPO_ROOT if rykerr-references is "
            f"checked out somewhere else)"
        )

    discovered_pdfs, skipped_pdfs = curation.filter_excluded(discovered_pdfs, excluded_patterns)
    if skipped_pdfs:
        print(f"Excluded {len(skipped_pdfs)} linked PDF(s) per curation/excluded_urls.txt")

    superseded_pdfs = pdf_ingest.find_superseded_pdf_urls(discovered_pdfs)
    if superseded_pdfs:
        discovered_pdfs = [u for u in discovered_pdfs if u not in superseded_pdfs]
        print(f"Auto-excluded {len(superseded_pdfs)} superseded PDF version(s) (see notes above)")

    print(f"\nChecking {len(discovered_pdfs)} linked PDF(s)")
    pdf_stats = index_pdfs(conn, discovered_pdfs, by_permalink, by_author_year, force_substr)

    mentions_removed = store.prune_citation_mentions(conn, set(discovered_pdfs))
    if mentions_removed:
        print(f"Removed citation mentions from {mentions_removed} PDF(s) no longer present")

    citation_stats, citation_source_ids = _write_citation_sources(conn)
    if citation_stats["sources"]:
        print(
            f"Assembled {citation_stats['sources']} citation source(s) from {citation_stats['chunks']} "
            f"blurb(s) ({citation_stats['unresolved_mentions']} blurb(s) still unresolved — no matching "
            f"link or reference page found)"
        )

    podcast_source_ids, podcast_stats = podcast_ingest.index_podcast_episodes(conn, force_substr)
    if podcast_stats["seen"]:
        print(
            f"Podcasts: {podcast_stats['seen']} seen, {podcast_stats['changed']} changed/new, "
            f"{podcast_stats['unchanged']} unchanged (skipped)"
        )

    current_source_ids = page_source_ids | set(discovered_pdfs) | citation_source_ids | podcast_source_ids
    removed = store.prune_missing_sources(
        conn, current_source_ids, source_types=("webpage", "pdf", "citation", "podcast")
    )
    if removed:
        print(f"Removed {removed} source(s) no longer present (deleted, moved, or newly excluded)")

    total_docs_touched = page_stats["changed"] + pdf_stats["changed"]

    # num_chunks here is a meta-table display stat (retrieval reads the
    # chunks/sources tables directly, never this), so it should be the
    # actual corpus-wide total -- not a per-run delta of chunks written
    # this run. The delta undercounts whenever pages/PDFs have nothing
    # changed but citation sources (which are always fully rewritten
    # every run) still contribute their full count -- a no-op incremental
    # run would otherwise report just the citation chunk count as if it
    # were the whole index.
    total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    store.record_build_stats(
        conn,
        num_pages=page_stats["seen"],
        num_chunks=total_chunks,
        num_pdfs=pdf_stats["seen"],
    )
    conn.close()

    elapsed = time.time() - start
    print(f"\nDone in {elapsed/60:.1f} min")
    print(
        f"  Pages: {page_stats['seen']} seen, {page_stats['changed']} changed/new, "
        f"{page_stats['unchanged']} unchanged (skipped)"
    )
    if page_stats["changed"]:
        print(
            f"    of those changed/new, {page_stats['with_tags']} had tags "
            f"({page_stats['with_frontmatter_tags']} from post front matter, "
            f"{page_stats['with_tags'] - page_stats['with_frontmatter_tags']} from HTML guessing)"
        )
    print(
        f"  PDFs:  {pdf_stats['seen']} seen, {pdf_stats['changed']} changed/new, "
        f"{pdf_stats['unchanged']} unchanged (skipped)"
    )
    if pdf_stats.get("failed"):
        print(
            f"  ! {pdf_stats['failed']} PDF(s) failed unexpectedly and were skipped — see the "
            f"'unexpected error' lines above; safe to just re-run, since everything else in "
            f"this build already committed"
        )
    print(
        f"  Citations: {citation_stats['sources']} source(s), {citation_stats['chunks']} blurb chunk(s), "
        f"{citation_stats['unresolved_mentions']} still unresolved"
    )
    print(f"  {total_docs_touched} source(s) actually re-indexed this run, {removed} removed")
    print(f"Index written to: {config.OUTPUT_DB_PATH}")
    print("Sync this file to the VPS to make it live (see README.md).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full", action="store_true",
        help="Force a from-scratch rebuild instead of the normal incremental update.",
    )
    parser.add_argument(
        "--force", metavar="SUBSTR",
        help="Reprocess only the source(s) whose URL contains SUBSTR (case-insensitive), ignoring "
             "change detection for just those — e.g. --force vent to re-run extraction on the vent "
             "book alone while developing a fix, without waiting on every other PDF. Everything "
             "else still uses normal incremental skip logic. For a webpage, --sources in "
             "query_test.py shows you its exact URL if you're unsure what substring will match.",
    )
    args = parser.parse_args()

    try:
        build(force_full=args.full, force_substr=(args.force.lower() if args.force else None))
    except KeyboardInterrupt:
        print("\nInterrupted — partial progress from the last commit is preserved (safe to re-run).")
        sys.exit(1)
