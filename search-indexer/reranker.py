"""
Cross-encoder reranking, stage 2 of a two-stage retrieval: the cheap
cosine-similarity search (embedder.py + a matrix multiply) pulls a wide
candidate pool fast, then this reranks just that pool with a much more
accurate — but much slower — model that scores the query and each chunk
TOGETHER rather than comparing independently-computed vectors.

Loaded lazily (only when reranking is actually used) and once per
process, same pattern as embedder.py's model caching.
"""
import config

_reranker = None


def get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        print(f"loading reranker model {config.RERANKER_MODEL_NAME} (first run downloads it, ~90MB)...")
        _reranker = CrossEncoder(config.RERANKER_MODEL_NAME)
    return _reranker


def rerank(query_text, candidates, top_k):
    """candidates: list of dicts, each with at least a 'text' key (plus
    whatever other metadata the caller wants preserved — it's carried
    through unchanged) and typically a 'score' key from the initial
    cosine-similarity search. Returns the best top_k candidates re-sorted
    by cross-encoder relevance, each with an added 'rerank_score' key —
    the original bi-encoder 'score' is left untouched so a caller can
    show or compare both."""
    if not candidates:
        return []
    if top_k >= len(candidates):
        top_k = len(candidates)

    model = get_reranker()
    pairs = [(query_text, c["text"]) for c in candidates]
    scores = model.predict(pairs)

    for c, s in zip(candidates, scores):
        c["rerank_score"] = float(s)

    ranked = sorted(candidates, key=lambda c: -c["rerank_score"])
    return ranked[:top_k]
