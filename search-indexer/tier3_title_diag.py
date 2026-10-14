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
_CANDIDATES_PER_SITE = 2  # mirrors server config.TIER3_CANDIDATES_PER_SITE
_EXTRA_LIVE_FETCHES = 2  # mirrors server config.TIER3_EXTRA_LIVE_FETCHES
_TITLE_COVERAGE_BONUS = 1.5  # mirrors server config.TIER3_TITLE_COVERAGE_BONUS

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


# --- Title-coverage bonus (Ryan's call, 2026-10-07) -------------------------
# The cross-encoder scores a title against the whole query, so a one-word
# exact-topic page ("Hyperkalemia") loses to longer titles that merely share
# the query's generic words ("ECG changes in Pulmonary Embolism" matches
# "ECG" + "changes" and none of the actual disease). A title whose every
# meaningful word already appears in the query is a "this page IS that
# topic" match, so it gets a flat bonus (config.TIER3_TITLE_COVERAGE_BONUS).
# Deliberately NOT "reward more matching words" -- that would favor the
# wrong pages above, which match more words, not fewer.
_COVERAGE_STOPWORDS = frozenset(
    "a an the of in on for and or to with without by from at as is are vs versus "
    "management treatment approach overview introduction".split()
)
_SPELLING_VARIANTS = [
    ("aemia", "emia"), ("aemic", "emic"), ("oedema", "edema"), ("haem", "hem"),
    ("paed", "ped"), ("oesoph", "esoph"), ("ischaem", "ischem"), ("anaes", "anes"),
    ("oeso", "eso"), ("foetal", "fetal"), ("diarrhoea", "diarrhea"),
]


def _norm_words(text):
    words = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        for old, new in _SPELLING_VARIANTS:
            w = w.replace(old, new)
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        words.add(w)
    return words


def title_coverage_bonus(expanded_query, title, bonus):
    """`bonus` if every meaningful word of `title` appears in the query
    (and at least one is 4+ letters, so "T-Z"-style stubs never qualify);
    else 0."""
    content = {w for w in _norm_words(title) if w not in _COVERAGE_STOPWORDS}
    if not content or not any(len(w) >= 4 for w in content):
        return 0.0
    return bonus if content <= _norm_words(expanded_query) else 0.0


def pool_by_cosine(scores, allowed_idx, pool_size):
    if not allowed_idx:
        return []
    sub_scores = scores[allowed_idx]
    order = sub_scores.argsort()[::-1][:pool_size]
    return [allowed_idx[i] for i in order]


def local_title_candidates(site_key, metas, scores, expanded_query, n):
    """Up to n best title matches for one site that clear the title
    floor, plus the number of titles indexed for it (mirrors tier3.py's
    _local_title_candidates)."""
    idx = [i for i, m in enumerate(metas) if m.get("source_type") == "external" and site_key in (m.get("tags") or [])]
    if not idx:
        return [], 0
    pool_size = min(len(idx), config.RERANK_CANDIDATE_POOL)
    pool = pool_by_cosine(scores, idx, pool_size)
    candidates = [{**metas[i], "score": float(scores[i])} for i in pool]
    ranked = reranker.rerank(expanded_query, candidates, n)
    return [r for r in ranked if r["rerank_score"] >= _LOCAL_GOOD_ENOUGH], len(idx)


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
    slots = int(sys.argv[2]) if len(sys.argv) > 2 else 1  # how many empty slots tier 3 is asked to fill
    metas, matrix = store.load_all()
    expanded_query = query_expansion.expand_query(query_text)
    query_vec = embedder.embed_query(expanded_query)
    scores = matrix @ query_vec

    print(f"Query: {query_text!r}  (expanded: {expanded_query!r})  slots to fill: {slots}")
    print(f"title floor = {_LOCAL_GOOD_ENOUGH}, content gate = {_SNIPPET_GOOD_ENOUGH}, "
          f"candidates/site = {_CANDIDATES_PER_SITE}, fetch budget = {slots + _EXTRA_LIVE_FETCHES}")
    print()

    print("=== Stage 1+2: per-site top title matches + combined (score + bonus) rank ===")
    candidates = []
    seen_urls, seen_titles = set(), set()
    for site in _SITE_PRIORITY:
        kept_for_site = 0
        found, n_indexed = local_title_candidates(site["key"], metas, scores, expanded_query, _CANDIDATES_PER_SITE)
        if n_indexed == 0:
            print(f"  {site['display_name']:28s}  nothing indexed locally yet")
            continue
        if not found:
            print(f"  {site['display_name']:28s}  {n_indexed} titles indexed, none clear the title floor")
            continue
        for c in found:
            title_key = (site["key"], c["source_title"].strip().lower())
            if c["locator_url"] in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(c["locator_url"])
            seen_titles.add(title_key)
            # Bonus applies to each site's BEST match only (mirrors server tier3.py).
            bonus = site["bonus"] if kept_for_site == 0 else 0
            kept_for_site += 1
            cov = title_coverage_bonus(expanded_query, c["source_title"], _TITLE_COVERAGE_BONUS)
            combined = c["rerank_score"] + bonus + cov
            print(f"  {site['display_name']:28s}  title_score={c['rerank_score']:7.3f}  "
                  f"bonus=+{bonus} cover=+{cov}  combined={combined:7.3f}  -> {c.get('source_title')!r}")
            c["_site"] = site
            c["_combined"] = combined
            candidates.append(c)

    candidates.sort(key=lambda c: c["_combined"], reverse=True)
    print()
    print("=== Stage 3: walking combined-score order, live-fetch + content rescore ===")
    if not candidates:
        print("  no candidates cleared the title floor at all.\n")
        return

    accepted = []
    leftovers = []
    fetch_budget = slots + _EXTRA_LIVE_FETCHES
    fetches = 0
    for position, candidate in enumerate(candidates):
        site = candidate["_site"]
        if len(accepted) >= slots:
            print(f"  (slots full -- {len(candidates) - position} lower-ranked candidate(s) not fetched)\n")
            break
        if fetches >= fetch_budget:
            leftovers.extend((c, c["source_title"]) for c in candidates[position:])
            print(f"  (fetch budget of {fetch_budget} used up -- {len(candidates) - position} candidate(s) left for backfill)\n")
            break
        fetches += 1
        rank = position + 1
        print(f"  #{rank} {site['display_name']} (combined={candidate['_combined']:.3f}) "
              f"{candidate['source_title']!r}: fetching {candidate['locator_url']} ...")
        title, snippet, err = live_snippet(candidate["locator_url"], candidate["source_title"])
        if err:
            print(f"      {err} (empty snippet -- ACCEPTED anyway, skips the rescore gate)\n")
            accepted.append((candidate, title, "(fetch failed)"))
            continue
        if not snippet:
            print("      fetched OK but no usable paragraph -- ACCEPTED anyway (empty snippet skips the rescore gate)\n")
            accepted.append((candidate, title, "(no snippet)"))
            continue
        print(f"      live snippet: {snippet[:180]!r}...")
        rescored = reranker.rerank(expanded_query, [{"text": snippet}], 1)
        final_score = rescored[0]["rerank_score"] if rescored else None
        passes = final_score is not None and final_score >= _SNIPPET_GOOD_ENOUGH
        print(f"      content rescore: {final_score:.3f}  "
              f"[{'PASSES' if passes else 'BELOW GATE -- held back for backfill'}]\n")
        if passes:
            accepted.append((candidate, title, snippet[:80]))
        else:
            leftovers.append((candidate, title))

    print("=== What the live server would return for these slots ===")
    n = 0
    for candidate, title, note in accepted[:slots]:
        n += 1
        print(f"  {n}. [passed gates] {candidate['_site']['display_name']}: {title!r}")
    for candidate, title in leftovers:
        if n >= slots:
            break
        n += 1
        print(f"  {n}. [BACKFILL, title only] {candidate['_site']['display_name']}: {title!r}")
    if n < slots:
        print(f"  ({slots - n} slot(s) left empty -- fewer candidates than slots cleared the title floor)")
    print()


if __name__ == "__main__":
    main()
