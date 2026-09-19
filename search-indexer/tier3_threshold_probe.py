"""
One-off diagnostic — NOT part of the pipeline. Gathers real cross-encoder
rerank_score data for tier 3's LOCAL title matches (Deranged Physiology /
WikEM / IBCC — see tier3_sources.py) across a spread of real queries, so
config.TIER3_LOCAL_GOOD_ENOUGH_SCORE (server/config.py) can be set from
real numbers instead of the provisional guess it started as — same
discipline as tier_threshold_probe.py used for TIER1_GOOD_ENOUGH_SCORE
and TIER2_BOOST_SCORE.

Run this AFTER build_tier3_index.py has populated the tier-3 title index
(python query_test.py --sources external will show non-zero if it has).

Usage (from search-indexer/, in your normal venv):
    python tier3_threshold_probe.py
"""
import numpy as np

import config
import embedder
import query_expansion
import reranker
import store

TIER3_SITE_KEYS = ["deranged_physiology", "wikem", "ibcc"]

# A mix: queries a title-only match should plausibly nail (specific
# named conditions/procedures a WikEM/IBCC/Deranged-Physiology chapter
# is likely titled almost exactly after), a couple of vaguer/phrased-
# as-a-question queries (closer to how a real user actually searches,
# titles are terser than that), and one off-domain control.
QUERIES = [
    "acute respiratory distress syndrome",
    "how do I titrate PEEP for ARDS",
    "diabetic ketoacidosis management",
    "absorption atelectasis mechanism",
    "how do I change a car tire",
]


def run_query(query_text):
    metas, matrix = store.load_all()
    expanded_query = query_expansion.expand_query(query_text)
    query_vec = embedder.embed_query(expanded_query)
    scores = matrix @ query_vec

    print(f'=== "{query_text}" ===')
    for site_key in TIER3_SITE_KEYS:
        idx = [i for i, m in enumerate(metas) if m["source_type"] == "external" and site_key in m["tags"]]
        if not idx:
            print(f"  {site_key}: no titles indexed yet")
            continue
        idx = np.asarray(idx)
        pool_size = min(len(idx), config.RERANK_CANDIDATE_POOL)
        order = np.argsort(-scores[idx])[:pool_size]
        pool = idx[order]
        candidates = [{**metas[i], "score": float(scores[i])} for i in pool]
        ranked = reranker.rerank(expanded_query, candidates, 3)
        print(f"  {site_key} ({len(idx)} titles indexed):")
        for hit in ranked:
            print(f"    rerank={hit['rerank_score']:7.3f}  {hit['source_title']!r}  ({hit['locator_url']})")
    print()


def main():
    for q in QUERIES:
        run_query(q)


if __name__ == "__main__":
    main()
