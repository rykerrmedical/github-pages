"""One-off diagnostic (2026-10-02, updated for the bonus-scoring
redesign): runs tier 3's FULL pipeline end to end for a given query --
each site's local title match, the priority-bonus combined ranking,
then the live page fetch + content rescore gate -- and prints every
stage's real number. Mirrors tier3.py's search_tier3 exactly, just
instrumented to show every candidate instead of only the winners.

Three constants (TIER3_LOCAL_GOOD_ENOUGH_SCORE, TIER3_SNIPPET_GOOD_
ENOUGH_SCORE, the priority bonuses) only live in the SERVER's config.py
(rykerr-search-server/config.py) -- search-indexer's config.py never
needed them before this diagnostic, so they're hardcoded below, mirrored
from there. Keep in sync if those values are ever recalibrated
server-side.

Run from search-indexer/ with the real venv (needs a LITFL local index
-- i.e. after running `python build_tier3_index.py litfl` at least once
-- or LITFL just won't have any candidate to show here, same as any
other site with nothing indexed yet):
    ./venv312/bin/python3 tier3_title_diag.py "drug guide"
"""
import re
import sys

import requests
from bs4 import BeautifulSoup

import config
import embedder
import query_expansion
import reranker
import store

_LOCAL_GOOD_ENOUGH = -4.0
_SNIPPET_GOOD_ENOUGH = -3.0  # mirrors server's MIN_DISPLAY_SCORE / TIER3_SNIPPET_GOOD_ENOUGH_SCORE
_FETCH_TIMEOUT = 8  # generous for a one-off manual run; server uses 5s

# Mirrors server config.py's TIER3_SITE_PRIORITY -- keep in sync.
_SITE_PRIORITY = [
    {"key": "deranged_physiology", "display_name": "Deranged Physiology", "bonus": 3},
    {"key": "litfl", "display_name": "Life in the Fast Lane", "bonus": 2},
    {"key": "wikem", "display_name": "WikEM", "bonus": 1},
    {"key": "ibcc", "display_name": "Internet Book of Critical Care", "bonus": 0},
]

_STRIP_TAGS = ["script", "style", "nav", "header", "footer", "aside", "form"]
_CONTENT_CONTAINER_SELECTORS = ["#mw-content-text", ".mw-parser-output"]
_PROMO_SNIPPET_RE = re.compile(
    r"\b(app store|download our|get the app|subscribe|sign up|newsletter|cookie)\b", re.IGNORECASE
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "RykerrMedicalSearch/0.1 (+https://rykerrmedical.com; contact: ryan@rykerrmedical.com) [diag script]"
})


def pool_by_cosine(scores, allowed_idx, pool_size):
    if not allowed_idx:
        return []
    sub_scores = scores[allowed_idx]
    order = sub_scores.argsort()[::-1][:pool_size]
    return [allowed_idx[i] for i in order]


def local_title_candidate(site_key, metas, scores, expanded_query):
    idx = [i for i, m in enumerate(metas) if m.get("source_type") == "external" and site_key in (m.get("tags") or [])]
    if not idx:
        return None, 0
    pool_size = min(len(idx), config.RERANK_CANDIDATE_POOL)
    pool = pool_by_cosine(scores, idx, pool_size)
    candidates = [{**metas[i], "score": float(scores[i])} for i in pool]
    ranked = reranker.rerank(expanded_query, candidates, 1)
    if not ranked or ranked[0]["rerank_score"] < _LOCAL_GOOD_ENOUGH:
        return None, len(idx)
    return ranked[0], len(idx)


def live_snippet(url, fallback_title):
    """Copy of tier3.py's _live_snippet -- see that file for the real
    comments/history behind each choice here."""
    try:
        resp = SESSION.get(url, timeout=_FETCH_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        return fallback_title, "", f"FETCH FAILED: {e}"

    soup = BeautifulSoup(resp.text, "lxml")
    for tag_name in _STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    title = fallback_title
    if soup.title and soup.title.string and soup.title.string.strip():
        title = soup.title.string.strip()
    elif soup.h1:
        title = soup.h1.get_text(strip=True) or title

    content_root = soup
    for selector in _CONTENT_CONTAINER_SELECTORS:
        found = soup.select_one(selector)
        if found is not None:
            content_root = found
            break

    paragraphs = [p.get_text(" ", strip=True) for p in content_root.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) > 60]
    paragraphs = [p for p in paragraphs if not _PROMO_SNIPPET_RE.search(p)]
    snippet = paragraphs[0] if paragraphs else ""
    return title, snippet[:400], None


def main():
    query_text = sys.argv[1] if len(sys.argv) > 1 else "drug guide"
    metas, matrix = store.load_all()
    expanded_query = query_expansion.expand_query(query_text)
    query_vec = embedder.embed_query(expanded_query)
    scores = matrix @ query_vec

    print(f"Query: {query_text!r}  (expanded: {expanded_query!r})")
    print(f"TIER3_LOCAL_GOOD_ENOUGH_SCORE (mirrored) = {_LOCAL_GOOD_ENOUGH}")
    print(f"TIER3_SNIPPET_GOOD_ENOUGH_SCORE (mirrored) = {_SNIPPET_GOOD_ENOUGH}")
    print()

    print("=== Stage 1+2: per-site title match + combined (score + bonus) rank ===")
    candidates = []
    for site in _SITE_PRIORITY:
        winner, n_indexed = local_title_candidate(site["key"], metas, scores, expanded_query)
        if n_indexed == 0:
            print(f"  {site['display_name']:28s}  nothing indexed locally yet")
            continue
        if winner is None:
            print(f"  {site['display_name']:28s}  {n_indexed} titles indexed, none clear the local gate")
            continue
        combined = winner["rerank_score"] + site["bonus"]
        print(f"  {site['display_name']:28s}  title_score={winner['rerank_score']:7.3f}  "
              f"bonus=+{site['bonus']}  combined={combined:7.3f}  -> {winner.get('source_title')!r}")
        winner["_site"] = site
        winner["_combined"] = combined
        candidates.append(winner)

    candidates.sort(key=lambda c: c["_combined"], reverse=True)
    print()
    print("=== Stage 3: walking combined-score order, live-fetch + content rescore ===")
    if not candidates:
        print("  no candidates cleared the local-title gate at all.\n")
        return

    for rank, candidate in enumerate(candidates, 1):
        site = candidate["_site"]
        print(f"  #{rank} {site['display_name']} (combined={candidate['_combined']:.3f}): "
              f"fetching {candidate['locator_url']} ...")
        title, snippet, err = live_snippet(candidate["locator_url"], candidate["source_title"])
        if err:
            print(f"      {err} (empty snippet -- ACCEPTED anyway, skips the rescore gate)\n")
            continue
        if not snippet:
            print("      fetched OK but no usable paragraph -- ACCEPTED anyway (empty snippet skips the rescore gate)\n")
            continue
        print(f"      live snippet: {snippet[:180]!r}...")
        rescored = reranker.rerank(expanded_query, [{"text": snippet}], 1)
        final_score = rescored[0]["rerank_score"] if rescored else None
        passes = final_score is not None and final_score >= _SNIPPET_GOOD_ENOUGH
        print(f"      content rescore: {final_score:.3f}  "
              f"[{'PASSES -- this is what would show live' if passes else 'BELOW GATE -- rejected, moves to next candidate'}]\n")


if __name__ == "__main__":
    main()
