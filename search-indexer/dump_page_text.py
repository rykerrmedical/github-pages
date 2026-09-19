"""
One-off diagnostic — NOT part of the pipeline. Dumps the FULL raw text
(repr'd, so exact characters like unicode dashes/bullets are visible
instead of looking like a plain "-") of every indexed chunk matching a
source + locator filter, so a regex like _looks_like_changelog_page can
be checked against the real extracted text instead of guessed at from a
truncated terminal snippet.

Usage:
    python dump_page_text.py vent "Page 2"
"""
import sys

import store


def main():
    if len(sys.argv) < 3:
        print('Usage: python dump_page_text.py <source filter> <locator filter>')
        sys.exit(1)
    source_filter = sys.argv[1].lower()
    locator_filter = sys.argv[2].lower()

    metas, _matrix = store.load_all()
    matches = [
        m for m in metas
        if source_filter in m["source_id"].lower() or source_filter in m["source_title"].lower()
        if locator_filter in m["locator"].lower()
    ]

    if not matches:
        print(f"No chunk found matching source={source_filter!r} locator={locator_filter!r}")
        return

    for i, m in enumerate(matches, 1):
        print(f"=== match {i}: {m['source_title']} — {m['locator']} (chunk_index {m['chunk_index']}) ===")
        print(repr(m["text"]))
        print()


if __name__ == "__main__":
    main()
