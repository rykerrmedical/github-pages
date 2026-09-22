"""
SQLite storage for the chunk index.

Kept deliberately simple: one table for the actual searchable content,
embeddings stored as raw float32 blobs. At the scale of a single site's
content (low thousands of chunks, at most) brute-force cosine similarity
over an in-memory numpy array is fast — there's no need for a dedicated
vector database, which keeps both this script and the VPS query service
lighter to run and easier to debug.

The whole .db file is what you sync to the VPS after each nightly run.

Schema is source-agnostic on purpose: a "locator" is whatever precise
spot within a source a chunk came from — nothing for a webpage (the URL
is precise enough on its own), "Page 42" for a PDF, and later "14:32"
for a podcast/YouTube timestamp. This is what lets a citation say
"page 112 of the book" or "14:32 in the episode with Wes" instead of
just linking the whole document.

A second table, `sources`, is what makes rebuilds incremental: one row
per indexed document (a page or a PDF) recording a content fingerprint
from the last time it was processed. build_index.py compares a fresh
fingerprint against that stored one and skips re-chunking/re-embedding
entirely when nothing actually changed — see build_index.py for the
comparison logic. This table isn't wiped between runs; only `reset_all`
(used for a full rebuild) touches it.
"""
import json
import sqlite3
from datetime import datetime, timezone

import numpy as np

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,     -- 'webpage', 'pdf', later 'podcast'/'youtube'
    source_id TEXT NOT NULL,       -- stable identifier for the document itself
                                    -- (page URL, or PDF URL)
    source_title TEXT NOT NULL,    -- page title, or PDF/book title
    locator TEXT NOT NULL,         -- '' for a webpage; 'Page 42' for a PDF
    locator_url TEXT NOT NULL,     -- best deep link available — for a PDF,
                                    -- this includes a #page=N fragment, which
                                    -- most browser PDF viewers honor
    chunk_index INTEGER NOT NULL,  -- position within the source, for ordering
    text TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',  -- JSON list, e.g. your hand-placed
                                        -- post tags — '[]' for sources
                                        -- (like PDFs) that don't have any
    links_to TEXT,                     -- set only when this chunk is really
                                        -- just a pointer at something else
                                        -- (an index page's entry for one
                                        -- specific post, an overview
                                        -- section deferring to a better
                                        -- source) -- the URL of what to
                                        -- cite instead, resolved at query
                                        -- time (see the server's
                                        -- retrieval.py) against whatever's
                                        -- currently indexed under that URL.
                                        -- NULL for the overwhelming
                                        -- majority of chunks, which just
                                        -- cite their own page as always.
                                        -- See extract.py and curation.py
                                        -- (defer_to.txt) for how this gets
                                        -- set.
    embedding BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    content_signal TEXT NOT NULL,  -- hash of the content, or a cheap
                                    -- server-provided signal (ETag /
                                    -- Last-Modified) for PDFs — whatever
                                    -- was used to detect "did this change"
    chunk_count INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Raw citation blurbs pulled out of your own primary PDFs (see
-- pdf_ingest.extract_citation_blurbs), one row per blurb, BEFORE
-- embedding. A citation source (source_type='citation' in `chunks`,
-- keyed by the cited work's own URL — its references.rykerrmedical.com
-- page, or a direct external link when there's no page in between) can
-- be cited by several different primary PDFs, or from several pages of
-- the same one — but a PDF only gets re-extracted when its own content
-- changes (that's the whole point of incremental mode), so the blurbs
-- it contributed have to be kept somewhere durable rather than
-- recomputed from scratch every run. This table is that: replaced
-- wholesale for one citing_source_id whenever THAT PDF is reprocessed
-- (replace_citation_mentions, same replace-by-source-id pattern as
-- chunks), then build_index.py reads back EVERY row across every PDF
-- ever indexed (all_citation_mentions) to assemble each citation
-- source's full chunk set — so a citation source correctly reflects
-- blurbs from PDFs that weren't touched this run, not just this run's.
CREATE TABLE IF NOT EXISTS citation_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    citing_source_id TEXT NOT NULL,  -- the primary PDF this blurb came from
    citing_title TEXT NOT NULL,
    page INTEGER NOT NULL,
    number TEXT NOT NULL,
    label TEXT NOT NULL,             -- e.g. "Skrobik, 2012"
    blurb TEXT NOT NULL,
    target_id TEXT,                  -- resolved citation source_id, or NULL if unresolved
    target_title TEXT,
    target_category TEXT
);
CREATE INDEX IF NOT EXISTS idx_citation_mentions_citing ON citation_mentions(citing_source_id);
CREATE INDEX IF NOT EXISTS idx_citation_mentions_target ON citation_mentions(target_id);
"""


def connect(db_path=None):
    conn = sqlite3.connect(db_path or config.OUTPUT_DB_PATH)
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """CREATE TABLE IF NOT EXISTS (above) only helps a brand-new DB -- it's
    a no-op against the already-existing production chunks table, so a
    newly added column needs an explicit, idempotent ALTER TABLE here.
    Guarded by checking the existing columns first rather than a bare
    try/except, so this stays a clean no-op on every run after the first
    (and doesn't mask a real ALTER TABLE failure behind a swallowed
    exception)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
    if "links_to" not in existing:
        conn.execute("ALTER TABLE chunks ADD COLUMN links_to TEXT")
        conn.commit()


def reset_all(conn):
    """Wipes everything — chunks AND the sources fingerprint table — for
    a genuine from-scratch rebuild. Used when the embedding model has
    changed (old embeddings aren't comparable to new ones — see
    build_index.py) or when --full is passed explicitly. NOT called on
    an ordinary incremental run."""
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM sources")
    conn.execute("DELETE FROM citation_mentions")
    conn.commit()


def get_source_signal(conn, source_id):
    """Returns the content_signal stored from the last time this source
    was indexed, or None if it's never been seen before."""
    row = conn.execute(
        "SELECT content_signal FROM sources WHERE source_id=?", (source_id,)
    ).fetchone()
    return row[0] if row else None


def get_source_chunk_count(conn, source_id):
    """Returns how many chunks this source had as of the last time it was
    indexed, or None if it's never been seen before. Used to catch a
    source that suddenly produces far fewer chunks than before — usually
    a sign that extraction/cleanup broke, not that the document actually
    shrank (see build_index.py's chunk-count regression check, added
    after exactly that happening silently: an extraction bug wiped 227 of
    266 pages of a real PDF, and nothing flagged it until it was found by
    hand)."""
    row = conn.execute(
        "SELECT chunk_count FROM sources WHERE source_id=?", (source_id,)
    ).fetchone()
    return row[0] if row else None


def replace_source_chunks(conn, source_type, source_id, source_title, chunk_rows, content_signal, tags=None):
    """Deletes any existing chunks for this source and inserts the fresh
    set, then records the new content_signal — the atomic unit of an
    incremental update. chunk_rows is a list of dicts with keys locator,
    locator_url, chunk_index, text, embedding. tags (a list of strings,
    or None) applies to the whole source — stored on every chunk row for
    this source so the server can load everything from one flat table
    without a join."""
    tags_json = json.dumps(tags or [])
    conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
    for row in chunk_rows:
        conn.execute(
            "INSERT INTO chunks "
            "(source_type, source_id, source_title, locator, locator_url, chunk_index, text, tags, links_to, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_type, source_id, source_title, row["locator"], row["locator_url"],
                row["chunk_index"], row["text"], tags_json, row.get("links_to"),
                row["embedding"].astype(np.float32).tobytes(),
            ),
        )
    conn.execute(
        "INSERT INTO sources (source_id, source_type, content_signal, chunk_count, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(source_id) DO UPDATE SET "
        "content_signal=excluded.content_signal, chunk_count=excluded.chunk_count, updated_at=excluded.updated_at",
        (source_id, source_type, content_signal, len(chunk_rows), datetime.now(timezone.utc).isoformat()),
    )


def prune_missing_sources(conn, current_source_ids, source_types):
    """Removes chunks + the sources record for anything indexed
    previously that's no longer in the current crawl/PDF-discovery
    results — a page taken down, a PDF moved, or something newly added
    to curation/excluded_urls.txt. Returns how many sources were
    removed, for logging. This is what keeps incremental updates from
    silently accumulating stale content forever.

    source_types SCOPES this to only the source_type(s) this particular
    build run is actually authoritative for (e.g. build_index.py passes
    ('webpage', 'pdf', 'citation')). Without this, a run of build_index.py
    would treat tier 3's separately-maintained 'external' rows (see
    build_tier3_index.py) as "no longer present" and delete them, since
    they're never part of build_index.py's own current_source_ids — even
    though build_index.py knows nothing about tier 3 and has no business
    pruning it. Confirmed as a real bug (not hypothetical): surfaced when
    the automated deploy pipeline was extended to also seed tier 3 from a
    previously-downloaded live index."""
    placeholders = ",".join("?" for _ in source_types)
    known = {
        row[0] for row in conn.execute(
            f"SELECT source_id FROM sources WHERE source_type IN ({placeholders})",
            list(source_types),
        ).fetchall()
    }
    missing = known - set(current_source_ids)
    for source_id in missing:
        conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM sources WHERE source_id=?", (source_id,))
    if missing:
        conn.commit()
    return len(missing)


def replace_citation_mentions(conn, citing_source_id, citing_title, mentions):
    """Replaces ALL citation-blurb mentions previously recorded for this
    one citing PDF — the same replace-by-source-id pattern as
    replace_source_chunks, just for the raw blurb data rather than
    embedded chunks. Call this whenever a primary PDF is actually
    reprocessed (see build_index.py's _index_one_pdf), even if some or
    all of its blurbs didn't resolve to a target (target_id=None rows
    are kept too, for the "N unresolved" build summary — they just don't
    get aggregated into any citation source).

    mentions: list of dicts with keys page, number, label, blurb,
    target_id, target_title, target_category (the latter three may be
    None)."""
    conn.execute("DELETE FROM citation_mentions WHERE citing_source_id=?", (citing_source_id,))
    for m in mentions:
        conn.execute(
            "INSERT INTO citation_mentions "
            "(citing_source_id, citing_title, page, number, label, blurb, target_id, target_title, target_category) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                citing_source_id, citing_title, m["page"], m["number"], m["label"], m["blurb"],
                m.get("target_id"), m.get("target_title"), m.get("target_category"),
            ),
        )


def all_citation_mentions(conn):
    """Every citation-blurb mention across every primary PDF ever
    indexed — not just ones touched this run. This is what lets
    build_index.py assemble each citation source's full chunk set from
    every PDF that's ever cited it, even PDFs skipped this run because
    their own content hasn't changed."""
    rows = conn.execute(
        "SELECT citing_source_id, citing_title, page, number, label, blurb, "
        "target_id, target_title, target_category FROM citation_mentions"
    ).fetchall()
    return [
        {
            "citing_source_id": r[0], "citing_title": r[1], "page": r[2], "number": r[3],
            "label": r[4], "blurb": r[5], "target_id": r[6], "target_title": r[7], "target_category": r[8],
        }
        for r in rows
    ]


def delete_sources_by_type_and_tag(conn, source_type, tag):
    """Deletes every chunk (and its 'sources' fingerprint row) of this
    source_type that carries `tag` in its tags list — a full
    delete-then-reinsert for one tier-3 site's title set
    (build_tier3_index.py calls this, then inserts the freshly
    discovered titles), rather than diffing old vs new URLs the way
    prune_missing_sources does.

    That diff-based approach was tried first here and is WRONG for this
    case, confirmed against a real run: source_type='external' is shared
    by all three tier-3 sites (Deranged Physiology / WikEM / IBCC — told
    apart by `tag`, not source_type), so a prune scoped only to
    source_type still treated every OTHER site's rows as "missing" and
    deleted them. Real symptom: a real build showed WikEM's insert step
    reporting exactly as many "stale entries removed" as Deranged
    Physiology had just inserted (1625), and then IBCC's step removing
    exactly WikEM's count (3006) — each site's run was wiping the
    previous one's, so only the LAST site indexed actually survived.
    Deleting by (source_type, tag) up front, before reinserting that
    same site's fresh titles, avoids the cross-site diff entirely.

    Tags are stored as a JSON-encoded list (see replace_source_chunks) —
    matched here with a LIKE on the quoted tag string. Safe in practice:
    tier-3 tags are simple lowercase/underscore site keys with no
    characters that could produce a false-positive substring match."""
    needle = f'%"{tag}"%'
    rows = conn.execute(
        "SELECT DISTINCT source_id FROM chunks WHERE source_type=? AND tags LIKE ?",
        (source_type, needle),
    ).fetchall()
    source_ids = [r[0] for r in rows]
    for source_id in source_ids:
        conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM sources WHERE source_id=?", (source_id,))
    if source_ids:
        conn.commit()
    return len(source_ids)


def prune_citation_mentions(conn, current_citing_source_ids):
    """Removes every mention row belonging to a citing PDF that's no
    longer in the current discovered-PDF set (removed, moved, or newly
    excluded) — the citation_mentions equivalent of prune_missing_sources.
    Returns how many citing sources' mentions were removed, for logging."""
    known = {
        row[0] for row in conn.execute("SELECT DISTINCT citing_source_id FROM citation_mentions").fetchall()
    }
    missing = known - set(current_citing_source_ids)
    for source_id in missing:
        conn.execute("DELETE FROM citation_mentions WHERE citing_source_id=?", (source_id,))
    if missing:
        conn.commit()
    return len(missing)


def set_meta(conn, **kwargs):
    for k, v in kwargs.items():
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, json.dumps(v)),
        )
    conn.commit()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def record_build_stats(conn, num_pages, num_chunks, num_pdfs=0):
    set_meta(
        conn,
        embedding_model=config.EMBEDDING_MODEL_NAME,
        built_at=datetime.now(timezone.utc).isoformat(),
        num_pages=num_pages,
        num_chunks=num_chunks,
        num_pdfs=num_pdfs,
    )


def load_all(db_path=None):
    """Loads every chunk's embedding + metadata into memory. Used by
    query_test.py locally and by the VPS query service in production."""
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT source_type, source_id, source_title, locator, locator_url, "
        "chunk_index, text, tags, links_to, embedding FROM chunks"
    ).fetchall()
    conn.close()

    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32)

    metas = []
    vectors = []
    for source_type, source_id, source_title, locator, locator_url, chunk_index, text, tags_json, links_to, blob in rows:
        metas.append({
            "source_type": source_type,
            "source_id": source_id,
            "source_title": source_title,
            "locator": locator,
            "locator_url": locator_url,
            "chunk_index": chunk_index,
            "text": text,
            "tags": json.loads(tags_json) if tags_json else [],
            "links_to": links_to,
        })
        vectors.append(np.frombuffer(blob, dtype=np.float32))

    matrix = np.vstack(vectors)
    return metas, matrix
