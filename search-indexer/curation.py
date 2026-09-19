"""
Lets you manually steer what gets indexed, without touching code —
right now, just "never index this" (see curation/excluded_urls.txt).
Content that's been superseded (an old draft of the vent book, say)
stays live on the site for anyone with the old link, but this keeps it
out of the search index entirely, so it can never get surfaced or cited
over the current version.
"""
import os

EXCLUDED_URLS_PATH = os.path.join(os.path.dirname(__file__), "curation", "excluded_urls.txt")


def load_excluded_patterns(path=None):
    path = path or EXCLUDED_URLS_PATH
    patterns = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    except FileNotFoundError:
        pass
    return patterns


def is_excluded(url, patterns):
    for pattern in patterns:
        if pattern.endswith("*"):
            if url.startswith(pattern[:-1]):
                return True
        elif url == pattern:
            return True
    return False


def filter_excluded(urls, patterns):
    """Returns (kept, excluded) — excluded is returned too so callers can
    log what got skipped and why, rather than silently dropping things."""
    kept, excluded = [], []
    for url in urls:
        (excluded if is_excluded(url, patterns) else kept).append(url)
    return kept, excluded
