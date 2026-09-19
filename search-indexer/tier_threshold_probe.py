"""
One-off diagnostic — NOT part of the pipeline. Gathers real cross-encoder
rerank_score data, broken out by source_type, across a spread of real
queries against the real live index. This is what calibrates the "good
enough" threshold for the 3-tier strict-fallback framework (tier 1 =
your own webpage/pdf content, tier 2 = citation blurbs, tier 3 = other/
external, not yet built) in server/retrieval.py — rather than guessing a
cutoff on the cross-encoder's raw, unbounded score scale, this prints
real scores for real queries so the threshold is picked from actual
data, same discipline as every other decision this build.

Usage (from search-indexer/, in your normal venv):
    python tier_threshold_probe.py
"""
import numpy as np

import config
import embedder
import query_expansion
import reranker
import store

# Deliberately mixed: some queries should land squarely in your own
# webpage/pdf content (tier 1 should clearly "win"), some are narrow
# enough that a citation blurb might be the best/only real match (to see
# how tier-2-only content scores), and one is off-domain entirely (to
# see what a "nothing good" score floor looks like).
QUERIES = [
    "how do I titrate PEEP for ARDS",
    "ventilator dyssynchrony types",
    "RSI induction agent choice",
    "absorption atelectasis mechanism oxygen",
    "benzodiazepine use in mechanically ventilated ICU patients",
    "how do I change a car tire",
]

POOL_SIZE = 20


def run_query(query_text):
    metas, matrix = store.load_all()
    expanded_query = query_expansion.expand_query(query_text)
    query_vec = embedder.embed_query(expanded_query)
    scores = matrix @ query_vec

    pool_size = max(config.RERANK_CANDIDATE_POOL, POOL_SIZE)
    pool_idx = np.argsort(-scores)[:pool_size]
    candidates = [{**metas[i], "score": float(scores[i])} for i in pool_idx]
    ranked = reranker.rerank(expanded_query, candidates, POOL_SIZE)

    print(f'=== "{query_text}" ===')
    if expanded_query != query_text:
        print(f"    (expanded to: {expanded_query})")

    tier1_scores = []
    tier2_scores = []
    for rank, hit in enumerate(ranked, 1):
        tier = "TIER1" if hit["source_type"] in ("webpage", "pdf") else (
            "TIER2" if hit["source_type"] == "citation" else "TIER?"
        )
        if tier == "TIER1":
            tier1_scores.append(hit["rerank_score"])
        elif tier == "TIER2":
            tier2_scores.append(hit["rerank_score"])
        where = f" — {hit['locator']}" if hit["locator"] else ""
        print(f"  {rank:2d}. [{tier}] rerank={hit['rerank_score']:7.3f}  "
              f"cosine={hit['score']:.3f}  ({hit['source_type']}) {hit['source_title']}{where}")

    best_t1 = max(tier1_scores) if tier1_scores else None
    best_t2 = max(tier2_scores) if tier2_scores else None
    print(f"    best TIER1 rerank_score: {best_t1}")
    print(f"    best TIER2 rerank_score: {best_t2}")
    print()
    return best_t1, best_t2


def main():
    print(f"RERANK_CANDIDATE_POOL={config.RERANK_CANDIDATE_POOL}, "
          f"showing top {POOL_SIZE} of the pool per query, reranker={config.RERANKER_MODEL_NAME}\n")
    summary = []
    for q in QUERIES:
        best_t1, best_t2 = run_query(q)
        summary.append((q, best_t1, best_t2))

    print("=== Summary ===")
    for q, best_t1, best_t2 in summary:
        print(f"  best_t1={best_t1!s:>8}  best_t2={best_t2!s:>8}   {q}")


if __name__ == "__main__":
    main()
