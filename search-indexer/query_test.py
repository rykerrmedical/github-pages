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


def _rerank_pool(query_text, metas, scores, allowed_idx, pool_size, dedupe):
    pool = _pool_by_cosine(scores, allowed_idx, pool_size)
    candidates = [{**metas[i], "score": float(scores[i])} for i in pool]
    if not candidates:
        return []
    ranked = reranker.rerank(query_text, candidates, len(candidates))
    return _dedupe_by_citation(ranked) if dedupe else ranked


def search(query_text, top_k=5, db_path=None, use_reranking=None, dedupe=True):
    """Mirrors server/retrieval.py's search() — two-stage retrieval (cheap
    cosine pool -> cross-encoder rerank) plus the same answer-priority
    tiers: tier 1 (webpage/pdf — Ryan's own content) is searched and
    reranked first; if its best result clears config.TIER1_GOOD_ENOUGH_SCORE,
    it leads the results, trimmed to top_k. Otherwise the pool widens to
    include tier 2 (citation blurbs) and reranks the combined set. Either
    way, any tier-2 citation clearing the much higher
    config.TIER2_BOOST_SCORE bar gets appended on top (up to
    config.TIER2_BOOST_MAX), even when tier 1 already led — see
    server/config.py for how both thresholds were calibrated against
    real queries.

    dedupe=False (the CLI's --no-dedupe) skips collapsing same-citation
    chunks, for eyeballing the raw ranking — see server/retrieval.py for
    why this can't just re-sort by score afterwards without breaking the
    tier-1-leads positioning.

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

    tier1_idx = [i for i, m in enumerate(metas) if m["source_type"] in config.TIER1_SOURCE_TYPES]
    tier1_ranked = _rerank_pool(expanded_query, metas, scores, tier1_idx, pool_size, dedupe)

    tier2_idx = [i for i, m in enumerate(metas) if m["source_type"] in config.TIER2_SOURCE_TYPES]
    tier2_ranked = _rerank_pool(expanded_query, metas, scores, tier2_idx, pool_size, dedupe)

    if tier1_ranked and tier1_ranked[0]["rerank_score"] >= config.TIER1_GOOD_ENOUGH_SCORE:
        results = tier1_ranked[:top_k]
    else:
        combined_idx = tier1_idx + tier2_idx
        results = _rerank_pool(expanded_query, metas, scores, combined_idx, pool_size, dedupe)[:top_k]

    seen = {(r["source_id"], r["locator"]) for r in results}
    boosted = 0
    for hit in tier2_ranked:
        if hit["rerank_score"] < config.TIER2_BOOST_SCORE:
            break
        key = (hit["source_id"], hit["locator"])
        if key in seen:
            continue
        hit = dict(hit, boosted=True)
        results.append(hit)
        seen.add(key)
        boosted += 1
        if boosted >= config.TIER2_BOOST_MAX:
            break

    return results


def _print_hit(rank, hit):
    where = f" — {hit['locator']}" if hit["locator"] else ""
    if "rerank_score" in hit:
        score_label = f"rerank {hit['rerank_score']:.3f}, cosine {hit['score']:.3f}"
    else:
        score_label = f"{hit['score']:.3f}"
    tag = " [BOOSTED CITATION]" if hit.get("boosted") else ""
    print(f"{rank}. [{score_label}] ({hit['source_type']}) {hit['source_title']}{where}{tag}")
    print(f"   {hit['locator_url']}")
    snippet = hit["text"][:220].replace("\n", " ")
    print(f"   {snippet}...\n")


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
