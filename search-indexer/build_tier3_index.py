"""
Builds/refreshes tier 3's local title index — Deranged Physiology, WikEM,
and IBCC (see tier3_sources.py for what each site allows and why LITFL
isn't here: it has its own live search API instead).

Deliberately SEPARATE from build_index.py's normal nightly run: these
three sites' content doesn't change day to day the way Ryan's own site
does, and re-crawling them every night would be both pointless load on
someone else's server and a needless external-network dependency added
to every regular build. Run this occasionally by hand (or on your own
much slower schedule, e.g. monthly) instead:

    python build_tier3_index.py            # all 3 sites
    python build_tier3_index.py wikem       # just one, e.g. after tweaking
                                              # that site's discovery logic

Stores ONLY a title + URL per article (source_type='external', tagged
with which site it's from) — never the article's own body text. See
tier3_sources.py's docstring for why that boundary matters here in a way
it didn't for tiers 1/2. server/tier3.py does the actual live fetch of
one single winning page's real content, at real answer time.
"""
import sys

import embedder
import query_expansion
import store
import tier3_sources

BATCH_SIZE = 64  # titles are short; embedding a decent batch at a time is cheap and fast


def _index_site(conn, key, site):
    display_name = site["display_name"]
    print(f"\n=== {display_name} ({key}) ===")
    pairs = site["discover"]()  # [(title, url), ...]
    if not pairs:
        print(f"  nothing discovered for {display_name} — leaving its existing index entries untouched "
              f"(a discovery failure shouldn't silently wipe what was there before)")
        return 0

    # Full delete-then-reinsert for THIS site's tag only — see
    # delete_sources_by_type_and_tag's docstring for why a diff-based
    # prune (old vs new URLs) is wrong here: source_type='external' is
    # shared across all three tier-3 sites, told apart only by tag, so a
    # prune scoped just to source_type would (and, in a real run,
    # actually did) wipe every OTHER site's rows too.
    removed = store.delete_sources_by_type_and_tag(conn, "external", key)
    if removed:
        print(f"  cleared {removed} existing {display_name} entr{'y' if removed == 1 else 'ies'} before reinserting fresh")

    indexed = 0
    for start in range(0, len(pairs), BATCH_SIZE):
        batch = pairs[start:start + BATCH_SIZE]
        # Expand acronym/shorthand titles (e.g. "ARDS" -> "ARDS (acute
        # respiratory distress syndrome, ...)") before embedding, using
        # the SAME glossary query_expansion.py already applies to queries
        # at search time. This is the fix for bare-acronym titles (IBCC's
        # "ARDS" chapter, etc.) scoring poorly against spelled-out
        # queries — the cross-encoder simply has more shared vocabulary
        # to work with once both sides carry both phrasings. The
        # expanded text is used for embedding AND the chunk's "text"
        # field (reranker.rerank() matches on "text" too), but
        # source_title stays the original, clean, unexpanded title —
        # that's what's actually shown to a user, expansion is purely an
        # internal matching aid.
        expanded_titles = [query_expansion.expand_query(title) for title, _url in batch]
        embeddings = embedder.embed_documents(expanded_titles)
        for (title, url), expanded_title, vec in zip(batch, expanded_titles, embeddings):
            store.replace_source_chunks(
                conn,
                source_type="external",
                source_id=url,
                source_title=title,
                chunk_rows=[{
                    "locator": "",
                    "locator_url": url,
                    "chunk_index": 0,
                    "text": expanded_title,
                    "embedding": vec,
                }],
                content_signal=title,  # titles are the whole content here — if it changes, that IS a content change
                tags=[key],
            )
            indexed += 1
        conn.commit()
        print(f"  embedded + stored {min(start + BATCH_SIZE, len(pairs))}/{len(pairs)}...")

    print(f"  {display_name}: {indexed} title(s) indexed")
    return indexed


def main():
    keys = sys.argv[1:] or list(tier3_sources.SITES.keys())
    conn = store.connect()
    total = 0
    for key in keys:
        if key not in tier3_sources.SITES:
            print(f"Unknown site {key!r} — choices: {', '.join(tier3_sources.SITES)}")
            continue
        total += _index_site(conn, key, tier3_sources.SITES[key])
    conn.close()
    print(f"\nDone — {total} tier-3 title(s) indexed across {len(keys)} site(s).")


if __name__ == "__main__":
    main()
