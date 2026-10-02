"""
Local sanity check for the index — no VPS, no LLM, just retrieval.

Usage:
    python query_test.py "how do I set PEEP for ARDS"
    python query_test.py "how do I set PEEP for ARDS" --top-k 15
    python query_test.py --sources                       # list every
                                                           # indexed source + chunk count
    python query_test.py --sources vent                  # filter by substring
    python query_test.py "how do I set PEEP for ARDS" --rank vent
        # shows where chunks from any source matching "vent" rank across
        # the WHOLE index for this query, not just the top-k — the tool
        # for "why doesn't my book show up": either it ranks low (a real
        # relevance problem) or it has no close-enough chunks at all (an
        # indexing problem, e.g. the content didn't extract as text).
    python query_test.py "..." --rank vent --rank-limit 100
        # --rank only prints the first 20 matches by default; raise this
        # to see the full picture when a source has many chunks.
    python query_test.py "..." --rank vent --page 45
        # narrows further to chunks whose locator also contains "45" —
        # use this once you know which page/chapter you're looking for
        # and want to see exactly where THAT specific content ranks,
        # rather than the source as a whole.
    python query_test.py "how do I set PEEP for ARDS transport" --find titrat peep
        # finds chunks by what they actually SAY, not by which source/page
        # they're filed under — every keyword must appear in the chunk's
        # text (any source, whole index), and each match is shown with its
        # rank for the query. Use this instead of --rank/--page when you
        # know a chapter exists (e.g. "there's a PEEP titration chapter")
        # but don't want to hunt down which page it's on yourself — that's
        # exactly the lookup the real search is supposed to do for you.

Prints the top matching chunks with their source URLs so you can eyeball
whether retrieval quality looks right before wiring up the LLM answer
step on the VPS. The default top-k view is deduped by citation (same
logic the real /api/search endpoint uses), so two chunks from the same
page don't both eat a result slot — pass --no-dedupe to see the raw
ranking instead.
"""
import argparse
import re
import sys

import numpy as np

import config
import embedder
import query_expansion
import reranker
import store


def _pool_by_cosine(scores, allowed_idx, pool_size):
    if len(allowed_idx) == 0:
        return np.array([], dtype=int)
    allowed_idx = np.asarray(allowed_idx)
    order = np.argsort(-scores[allowed_idx])[:pool_size]
    return allowed_idx[order]


def _rank_key(hit):
    # After reranking, hits carry a rerank_score that should govern
    # ordering (including dedup tie-breaking) — falls back to the plain
    # bi-encoder score when reranking wasn't used.
    return hit.get("rerank_score", hit["score"])


def _dedupe_by_citation(hits):
    """Same logic as server/retrieval.py's _dedupe_by_citation — collapses
    multiple chunks that point at the exact same citation (source_id +
    locator), keeping the best-scoring one, so results aren't just
    several fragments of the same page/PDF-page. Preserves the ORDER
    hits first appear in rather than re-sorting by score, so a tier-1-led
    result set stays ahead of a boosted tier-2 citation appended after
    it even though that citation scores higher by definition — see
    search() and server/retrieval.py's longer version of this note."""
    best = {}
    order = []
    for h in hits:
        key = (h["source_id"], h["locator"])
        if key not in best:
            best[key] = h
            order.append(key)
        elif _rank_key(h) > _rank_key(best[key]):
            best[key] = h
    return [best[key] for key in order]


# Mirrors server/retrieval.py's _SOURCE_TYPE_TIE_PRIORITY /
# _apply_source_type_tiebreak — see there for the full reasoning.
# Kept here too so this local preview tool shows the same ordering the
# real /api/search endpoint would, same as the rest of this file's
# mirrored tier logic.
_SOURCE_TYPE_TIE_PRIORITY = {"podcast_transcript": 1, "youtube_transcript": 2}
_SOURCE_TYPE_TIE_DEFAULT = 0
_TIE_EPSILON = 0.3

# Mirrors server/retrieval.py's _POINTER_PHRASE_RE / _looks_like_pointer_mention
# — see there for the full reasoning (2026-09-27, "intubation checklists":
# Wes Podcast's show notes page ranked #1 for namedropping "EmCrit
# Intubation Checklist(s)" as a pointer elsewhere, ahead of Ryan's own
# actual RFG checklist).
_POINTER_PHRASE_RE = re.compile(
    r"\b(?:see|check out|start(?:ing)?\s+(?:at|with)|refer(?:s|red)?\s+to|"
    r"linked\s+(?:to|from|here)|dig\s+in(?:to)?\s+(?:here|at)|"
    r"get\s+into\s+(?:the\s+details\s+of|it)\s+at|for\s+more,?\s+see|"
    r"as\s+mentioned[^.]{0,20}see)\s+(?:the\s+)?"
    r"[A-Z][\w&/’'\-]*(?:\s+[A-Z][\w&/’'\-]*){0,6}",
)


def _looks_like_pointer_mention(hit):
    if hit.get("source_type") != "webpage":
        return False
    return bool(_POINTER_PHRASE_RE.search(hit.get("text") or ""))


def _apply_source_type_tiebreak(hits):
    """A podcast/YouTube hit is only demoted when it's ACTUALLY tied
    (same score bucket) with another hit sharing its _group_key — a
    genuine same-episode duplicate. Mirrors server/retrieval.py's fix,
    2026-09-27 -- see there for the full reasoning (a real bug, not
    hypothetical: "Scripts Discussion with Richard" was landing below
    an unrelated, worse-scored PDF just for being a podcast).

    Also mirrors the independent "pointer mention" tiebreak dimension
    added the same day — see server/retrieval.py."""
    if len(hits) < 2:
        return hits

    def _bucket(h):
        return round(h["rerank_score"] / _TIE_EPSILON)

    has_tied_sibling = set()
    pointer_penalized = set()
    for i, h in enumerate(hits):
        for h2 in hits[i + 1:]:
            if _bucket(h) != _bucket(h2):
                continue
            if _group_key(h) == _group_key(h2):
                has_tied_sibling.add(id(h))
                has_tied_sibling.add(id(h2))
            h_ptr, h2_ptr = _looks_like_pointer_mention(h), _looks_like_pointer_mention(h2)
            if h_ptr and not h2_ptr:
                pointer_penalized.add(id(h))
            elif h2_ptr and not h_ptr:
                pointer_penalized.add(id(h2))

    def _tie_priority(h):
        source_type_priority = (
            _SOURCE_TYPE_TIE_PRIORITY.get(h["source_type"], _SOURCE_TYPE_TIE_DEFAULT)
            if id(h) in has_tied_sibling
            else _SOURCE_TYPE_TIE_DEFAULT
        )
        pointer_priority = 1 if id(h) in pointer_penalized else 0
        return (pointer_priority, source_type_priority)

    return sorted(
        hits,
        key=lambda h: (-_bucket(h), _tie_priority(h), -h["rerank_score"]),
    )


_NORMALIZE_TITLE_RE = re.compile(r"[^a-z0-9]+")
_AUDIO_PODCAST_TYPES = {"podcast", "podcast_transcript"}
_VIDEO_PODCAST_TYPES = {"youtube_transcript"}


def _normalize_episode_title(title):
    return _NORMALIZE_TITLE_RE.sub(" ", (title or "").lower()).strip()


def _group_key(hit):
    if hit["source_type"] in _AUDIO_PODCAST_TYPES or hit["source_type"] in _VIDEO_PODCAST_TYPES:
        return ("episode", _normalize_episode_title(hit["source_title"]))
    return ("source", hit["source_id"])


def _combine_citation_locators(locators):
    """Mirrors server/retrieval.py's _combine_citation_locators — see
    there for the full reasoning (2026-09-27, Ryan's rule: one card per
    third-party citation PDF, every distinct page range folded into the
    locator instead of a second unrelated "see also" card)."""
    if not locators:
        return ""
    first, rest = locators[0], locators[1:]
    if not rest:
        return first

    def _bare(loc):
        m = re.match(r"^(?:pages?|p\.)\s+(.*)$", loc, re.IGNORECASE)
        return m.group(1) if m else loc

    return first + "; see also " + ", ".join(_bare(loc) for loc in rest)


def _demote_pointer_mentions(hits):
    """Mirrors server/retrieval.py's _demote_pointer_mentions — see
    there for the full reasoning (2026-09-27: a pointer-mention hit can
    score far above everything else, nowhere near a tie, so the
    bucket-scoped tiebreak alone never demotes it)."""
    pointer_flags = [_looks_like_pointer_mention(h) for h in hits]
    if not any(pointer_flags) or all(pointer_flags):
        return hits
    non_pointer = [h for h, is_ptr in zip(hits, pointer_flags) if not is_ptr]
    pointer = [h for h, is_ptr in zip(hits, pointer_flags) if is_ptr]
    return non_pointer + pointer


def _group_by_source(hits):
    """Mirrors server/retrieval.py's _group_by_source — see there for the
    full reasoning, including why a podcast/YouTube pair groups by
    normalized title with the podcast always as primary, and why a
    third-party citation PDF folds every extra locator into the primary
    card instead of getting a second "see also" card. Kept here too so
    this local preview tool shows the same grouping the real
    /api/search endpoint applies."""
    groups = {}
    order = []
    for h in hits:
        key = _group_key(h)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(h)

    out = []
    for key in order:
        members = groups[key]
        primary = next((m for m in members if m["source_type"] in _AUDIO_PODCAST_TYPES), members[0])
        rest = [m for m in members if m is not primary]
        if not rest:
            out.append(primary)
            continue
        if primary["source_type"] == "citation":
            locators = []
            seen = set()
            for m in [primary] + rest:
                loc = m.get("locator")
                if loc and loc not in seen:
                    seen.add(loc)
                    locators.append(loc)
            out.append(dict(primary, locator=_combine_citation_locators(locators)))
        else:
            out.append(dict(primary, related=rest))
    return out


def _rerank_pool(query_text, metas, scores, allowed_idx, pool_size, dedupe):
    pool = _pool_by_cosine(scores, allowed_idx, pool_size)
    candidates = [{**metas[i], "score": float(scores[i])} for i in pool]
    if not candidates:
        return []
    ranked = reranker.rerank(query_text, candidates, len(candidates))
    if not dedupe:
        return ranked
    return _apply_source_type_tiebreak(_dedupe_by_citation(ranked))


# Mirrors server/retrieval.py's _is_tier1/_is_tier2 — see there for the
# full reasoning (2026-09-27: a linked-but-not-authored PDF no longer
# counts as tier 1 just for being source_type == "pdf").
_RYAN_AUTHORED_PDF_TAGS = {"book", "document"}


def _is_tier1(m):
    if m["source_type"] == "pdf":
        return bool(_RYAN_AUTHORED_PDF_TAGS & set(m.get("tags") or []))
    return m["source_type"] in config.TIER1_SOURCE_TYPES


def _is_tier2(m):
    if m["source_type"] == "pdf":
        return not (_RYAN_AUTHORED_PDF_TAGS & set(m.get("tags") or []))
    return m["source_type"] in config.TIER2_SOURCE_TYPES


def search(query_text, top_k=5, db_path=None, use_reranking=None, dedupe=True):
    """Mirrors server/retrieval.py's search() — two-stage retrieval (cheap
    cosine pool -> cross-encoder rerank) plus the same answer-priority
    tiers: tier 1 (webpage/pdf — Ryan's own content) and tier 2 (citation
    blurbs) are each reranked independently, then filtered to
    config.MIN_DISPLAY_SCORE.

    Ryan's call, 2026-10-02 (interim, while he works out a fuller
    score-margin design): config.TIER1_RESERVED_SLOTS of tier 1's own
    best results are shown unconditionally, regardless of how they'd
    otherwise compare to tier 2. The rest of top_k is then filled with
    whichever remaining results (from EITHER tier) score best overall,
    so tier 2 can fill every remaining slot when tier 1 doesn't have
    enough good content, rather than being capped by a fixed count.
    This always returns at most top_k results. config.TIER1_GOOD_ENOUGH_SCORE
    /TIER2_BOOST_SCORE/TIER2_BOOST_MAX still exist in config.py (real
    calibration data, possibly reused later) but nothing here reads
    them right now — see server/retrieval.py for the full note.

    dedupe=False (the CLI's --no-dedupe) skips collapsing same-citation
    chunks, for eyeballing the raw ranking — see server/retrieval.py for
    why this can't just re-sort by score afterwards without breaking the
    tier-1-reserved positioning.

    Before embedding, the query is run through query_expansion.expand_query
    so domain acronyms (ARDS, COPD, etc.) also match chunks that only use
    the spelled-out term or a clinical synonym — see query_expansion.py."""
    metas, matrix = store.load_all(db_path)
    if len(metas) == 0:
        print("Index is empty — run build_index.py first.")
        return []

    if use_reranking is None:
        use_reranking = config.ENABLE_RERANKING

    expanded_query = query_expansion.expand_query(query_text)
    query_vec = embedder.embed_query(expanded_query)
    # embeddings are normalized at index time, so dot product == cosine similarity
    scores = matrix @ query_vec

    if not use_reranking:
        top_idx = np.argsort(-scores)[:top_k]
        return [{**metas[i], "score": float(scores[i])} for i in top_idx]

    pool_size = max(config.RERANK_CANDIDATE_POOL, top_k)

    tier1_idx = [i for i, m in enumerate(metas) if _is_tier1(m)]
    tier1_ranked = _rerank_pool(expanded_query, metas, scores, tier1_idx, pool_size, dedupe)

    tier2_idx = [i for i, m in enumerate(metas) if _is_tier2(m)]
    tier2_ranked = _rerank_pool(expanded_query, metas, scores, tier2_idx, pool_size, dedupe)

    # Individual-result floor applied to each tier's own pool up front
    # (config.MIN_DISPLAY_SCORE) -- see server/retrieval.py's docstring.
    tier1_ranked = [r for r in tier1_ranked if r["rerank_score"] >= config.MIN_DISPLAY_SCORE]
    tier2_ranked = [r for r in tier2_ranked if r["rerank_score"] >= config.MIN_DISPLAY_SCORE]

    # See docstring (config.TIER1_RESERVED_SLOTS). Reserve tier 1's own
    # best first, unconditionally; fill whatever's left of top_k with
    # the best remaining results from either tier, by score.
    reserved = tier1_ranked[: config.TIER1_RESERVED_SLOTS]
    seen = {(r["source_id"], r["locator"]) for r in reserved}

    rest = sorted(
        (
            r
            for r in tier1_ranked[config.TIER1_RESERVED_SLOTS :] + tier2_ranked
            if (r["source_id"], r["locator"]) not in seen
        ),
        key=lambda r: r["rerank_score"],
        reverse=True,
    )

    results = list(reserved)
    for r in rest:
        if len(results) >= top_k:
            break
        key = (r["source_id"], r["locator"])
        if key in seen:
            continue
        results.append(r)
        seen.add(key)

    if dedupe:
        results = _demote_pointer_mentions(results)
        results = _group_by_source(results)
    return results


def _print_hit(rank, hit):
    where = f" — {hit['locator']}" if hit["locator"] else ""
    section = f" [{hit['section']}]" if hit.get("section") else ""
    if "rerank_score" in hit:
        score_label = f"rerank {hit['rerank_score']:.3f}, cosine {hit['score']:.3f}"
    else:
        score_label = f"{hit['score']:.3f}"
    tag = " [BOOSTED CITATION]" if hit.get("boosted") else ""
    print(f"{rank}. [{score_label}] ({hit['source_type']}) {hit['source_title']}{section}{where}{tag}")
    print(f"   {hit['locator_url']}")
    snippet = hit["text"][:220].replace("\n", " ")
    print(f"   {snippet}...")
    for rel in hit.get("related", []):
        rel_section = f" [{rel['section']}]" if rel.get("section") else ""
        rel_where = f" — {rel['locator']}" if rel["locator"] else ""
        print(f"   see also:{rel_section}{rel_where}")
    print()


def cmd_sources(db_path, filter_substr=None):
    metas, _matrix = store.load_all(db_path)
    if not metas:
        print("Index is empty — run build_index.py first.")
        return

    counts = {}
    for m in metas:
        key = (m["source_type"], m["source_title"], m["source_id"])
        counts[key] = counts.get(key, 0) + 1

    rows = sorted(counts.items(), key=lambda kv: -kv[1])
    if filter_substr:
        needle = filter_substr.lower()
        rows = [r for r in rows if needle in r[0][1].lower() or needle in r[0][2].lower()]

    if not rows:
        print(f"No indexed source matches {filter_substr!r}.")
        return

    total = sum(c for _, c in rows)
    print(f"{len(rows)} source(s), {total} chunk(s) total" + (f" matching {filter_substr!r}" if filter_substr else ""))
    print()
    for (source_type, title, source_id), count in rows:
        print(f"  {count:5d}  ({source_type}) {title}")
        print(f"          {source_id}")


def cmd_find(query_text, keywords, db_path, limit=20):
    """Finds content by what it actually SAYS rather than by which source
    it's filed under or what page it's on — the point being that you
    shouldn't have to already know where a chapter lives to check whether
    retrieval finds it. Every keyword must appear (case-insensitive,
    substring match) somewhere in a chunk's text for it to count as a
    match, across the WHOLE index regardless of source. For each match,
    shows its rank/score for query_text, so you can see directly whether
    the passage that actually discusses what you're asking about is
    ranking well or getting buried — no page numbers required."""
    metas, matrix = store.load_all(db_path)
    if not metas:
        print("Index is empty — run build_index.py first.")
        return

    # A bare substring match on a short stem like "vent" also matches
    # "prevent", "adventure", "inventory" — real false positives seen in
    # practice. Require a word boundary before the keyword (still allows
    # prefix stems: "vent" still matches "ventilator"/"ventilation", just
    # not mid-word); a multi-word phrase is specific enough on its own
    # that a plain substring match is fine.
    compiled = []
    for k in keywords:
        if " " in k.strip():
            compiled.append(("phrase", k.lower()))
        else:
            compiled.append(("word", re.compile(r"\b" + re.escape(k), re.IGNORECASE)))

    def content_matches(m):
        text_lower = m["text"].lower()
        for kind, needle in compiled:
            if kind == "phrase":
                if needle not in text_lower:
                    return False
            else:
                if not needle.search(m["text"]):
                    return False
        return True

    matching_idx = [i for i, m in enumerate(metas) if content_matches(m)]

    kw_label = " + ".join(f"{k!r}" for k in keywords)
    print(f'Chunks whose TEXT contains {kw_label} (any source), ranked for: "{query_text}"\n')

    if not matching_idx:
        print(f"No chunk anywhere in the index contains all of: {kw_label}")
        print("Either that content was never extracted as text (check build_index.py's warnings")
        print("for the source it should be in), or try fewer/different keywords — chunking can")
        print("split a passage so not every relevant word lands in the same chunk.")
        return

    expanded_query = query_expansion.expand_query(query_text)
    if expanded_query != query_text:
        print(f"(query expanded for ranking: {expanded_query})\n")
    query_vec = embedder.embed_query(expanded_query)
    scores = matrix @ query_vec
    order = np.argsort(-scores)  # rank position of every chunk in the index
    rank_of = {idx: r for r, idx in enumerate(order, 1)}

    print(f"{len(matching_idx)} matching chunk(s) found, out of {len(metas)} total in the index:\n")
    ranked = sorted(matching_idx, key=lambda i: rank_of[i])
    for i in ranked[:limit]:
        m = metas[i]
        where = f" — {m['locator']}" if m["locator"] else ""
        snippet = m["text"][:220].replace("\n", " ")
        print(f"rank #{rank_of[i]}  [{scores[i]:.3f}] ({m['source_type']}) {m['source_title']}{where}")
        print(f"   {m['locator_url']}")
        print(f"   {snippet}...\n")
    if len(ranked) > limit:
        print(f"(showing best-ranked {limit} of {len(ranked)} matching chunks — raise --limit to see more)")


def cmd_rank(query_text, filter_substr, db_path, limit=20, page_filter=None):
    metas, matrix = store.load_all(db_path)
    if not metas:
        print("Index is empty — run build_index.py first.")
        return

    expanded_query = query_expansion.expand_query(query_text)
    if expanded_query != query_text:
        print(f"(query expanded for ranking: {expanded_query})\n")
    query_vec = embedder.embed_query(expanded_query)
    scores = matrix @ query_vec
    order = np.argsort(-scores)  # full ranking, best first

    needle = filter_substr.lower()
    # A bare substring match on a page filter like "50" would also match
    # "Page 250" — same false-positive shape as the "vent"/"prevent" bug
    # in cmd_find. If the filter is purely a number, require it to be the
    # WHOLE number in the locator (word boundary on both sides), not just
    # a substring of a longer one.
    if page_filter and page_filter.strip().isdigit():
        page_re = re.compile(r"\b" + re.escape(page_filter.strip()) + r"\b")
        page_matches = lambda locator: bool(page_re.search(locator))
    elif page_filter:
        needle_page = page_filter.lower()
        page_matches = lambda locator: needle_page in locator.lower()
    else:
        page_matches = None

    def matches(m):
        if needle not in m["source_title"].lower() and needle not in m["source_id"].lower():
            return False
        if page_matches and not page_matches(m["locator"]):
            return False
        return True

    # Total count first, independent of the display cap below — this is
    # what tells you "the chapter exists but ranks off-screen" apart from
    # "only 3 chunks matched and you're seeing all of them".
    total_matches = sum(1 for m in metas if matches(m))

    label = filter_substr if not page_filter else f"{filter_substr!r} + page filter {page_filter!r}"
    print(f'Where chunks matching {label} rank for: "{query_text}"\n')
    print(f"(out of {len(metas)} total chunks; {total_matches} chunk(s) match the filter)\n")

    shown = 0
    for rank, i in enumerate(order, 1):
        m = metas[i]
        if matches(m):
            where = f" — {m['locator']}" if m["locator"] else ""
            snippet = m["text"][:180].replace("\n", " ")
            print(f"#{rank}  [{scores[i]:.3f}] {m['source_title']}{where}")
            print(f"      {snippet}...\n")
            shown += 1
            if shown >= limit:
                print(f"(stopping at {limit} matches — {total_matches - shown} more exist; raise --limit to see them)")
                break

    if shown == 0:
        print(f"No chunk from any source matching {label} exists in the index at all.")
        print("That means it either wasn't discovered/crawled, or produced zero usable chunks")
        print("during indexing (check the build_index.py output for warnings about that source).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", help='Search query, e.g. "how do I set PEEP for ARDS"')
    parser.add_argument("--top-k", type=int, default=5, help="How many results to show (default 5)")
    parser.add_argument("--no-dedupe", action="store_true", help="Show the raw ranking, not deduped by citation")
    parser.add_argument("--sources", nargs="?", const="", default=None, metavar="FILTER",
                         help="List indexed sources + chunk counts instead of searching, optionally filtered by substring")
    parser.add_argument("--rank", metavar="FILTER",
                         help="With a query: show where chunks matching FILTER rank across the whole index")
    parser.add_argument("--rank-limit", type=int, default=20,
                         help="With --rank: max matches to print (default 20, raise to see the whole picture)")
    parser.add_argument("--page", metavar="PAGE",
                         help="With --rank: also require this substring in the locator (e.g. --page 45), "
                              "to zero in on a specific chapter/page instead of the whole source")
    parser.add_argument("--find", nargs="+", metavar="KEYWORD",
                         help="With a query: finds chunks whose TEXT contains all given keywords "
                              "(case-insensitive, any source in the whole index) and shows where "
                              "each one ranks for the query — locates content by what it actually "
                              "says, no need to already know which source/page it's on")
    parser.add_argument("--find-limit", type=int, default=20,
                         help="With --find: max matches to print (default 20)")
    parser.add_argument("--no-rerank", action="store_true",
                         help="Skip the cross-encoder reranking stage — show plain cosine-similarity "
                              "results instead, same as before reranking existed. Useful for comparing "
                              "before/after on the same query.")
    parser.add_argument("--db", default=None, help="Path to the index db (defaults to config.OUTPUT_DB_PATH)")
    args = parser.parse_args()

    if args.sources is not None:
        cmd_sources(args.db, args.sources or None)
        sys.exit(0)

    if not args.query:
        print('Usage: python query_test.py "your question here"')
        print("       python query_test.py --sources [filter]")
        sys.exit(1)

    if args.find:
        cmd_find(args.query, args.find, args.db, limit=args.find_limit)
        sys.exit(0)

    if args.rank:
        cmd_rank(args.query, args.rank, args.db, limit=args.rank_limit, page_filter=args.page)
        sys.exit(0)

    # search() now handles dedup + tiering + the boost step internally
    # (reranking the full candidate pool either way, so nothing is lost
    # to an early cut before dedup gets to see it — see server/retrieval.py).
    use_reranking = not args.no_rerank
    hits = search(args.query, top_k=args.top_k, db_path=args.db,
                  use_reranking=use_reranking, dedupe=not args.no_dedupe)

    mode = "reranked" if use_reranking else "cosine similarity only, --no-rerank"
    expanded = query_expansion.expand_query(args.query)
    expansion_note = f" — expanded for search to: {expanded}" if expanded != args.query else ""
    print(f'\nTop results for: "{args.query}" ({mode}){expansion_note}\n')
    for rank, hit in enumerate(hits, 1):
        _print_hit(rank, hit)
