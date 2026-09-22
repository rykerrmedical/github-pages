"""
Lets you manually steer what gets indexed, without touching code.

Two independent mechanisms:
  excluded_urls.txt -- "never index this" (see load_excluded_patterns/
    is_excluded/filter_excluded). Content that's been superseded (an old
    draft of the vent book, say) stays live on the site for anyone with
    the old link, but this keeps it out of the search index entirely, so
    it can never get surfaced or cited over the current version.
  defer_to.txt -- "index this, but if it's what matches, cite something
    else" (see load_defer_overrides/resolve_defer). For a chunk that IS
    findable and SHOULD be, but whose own page isn't really the best
    thing to point someone at -- an overview page's section that's
    really about a specific resource elsewhere. extract.py's own
    link-based auto-detection (see its module docstring) already covers
    the common case of this (an index/card page whose entry links
    straight to the thing it's about) automatically; this file is the
    manual fallback for the cases that can't be auto-detected -- a
    section linking to several different things at once, or the actual
    best source not being linked from the page at all yet (e.g. a video
    that isn't indexed here yet). Nothing here removes the deferring
    page's own content from the index -- it stays exactly as searchable
    as before; only which citation gets SHOWN changes, and only when
    that specific chunk is what matched. See retrieval.py for where the
    resolution actually happens, at query time.
"""
import os

EXCLUDED_URLS_PATH = os.path.join(os.path.dirname(__file__), "curation", "excluded_urls.txt")
DEFER_TO_PATH = os.path.join(os.path.dirname(__file__), "curation", "defer_to.txt")


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


def load_defer_overrides(path=None):
    """One rule per non-comment, non-blank line, pipe-separated:
        PAGE_URL | HEADING_SUBSTRING | TARGET_URL
    PAGE_URL must match a chunk's source page exactly. HEADING_SUBSTRING
    is matched case-insensitively as a substring of that chunk's own
    heading path -- leave it blank (empty string between the pipes) to
    match every chunk on that page, regardless of section. TARGET_URL is
    what gets cited instead, when it resolves (see resolve_defer) --
    resolution happens at query time against whatever's currently
    indexed, so a target that isn't indexed yet just means no override
    fires yet, not an error here.

    Returns a list of {"page_url", "heading_substring", "target_url"}
    dicts, in file order (first match wins in resolve_defer -- put a
    more specific rule for one section above a page-wide catch-all for
    the same page, if you ever need both)."""
    path = path or DEFER_TO_PATH
    overrides = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) != 3:
                    continue
                page_url, heading_substring, target_url = parts
                if page_url and target_url:
                    overrides.append({
                        "page_url": page_url,
                        "heading_substring": heading_substring,
                        "target_url": target_url,
                    })
    except FileNotFoundError:
        pass
    return overrides


def resolve_defer(page_url, heading_path, overrides):
    """Returns the target_url of the first matching override for this
    chunk (page_url exact match, heading_substring empty or found
    case-insensitively within heading_path), or None if nothing
    matches -- the normal case for the overwhelming majority of chunks,
    which just cite their own page as always."""
    heading_lower = (heading_path or "").lower()
    for o in overrides:
        if o["page_url"] != page_url:
            continue
        if not o["heading_substring"] or o["heading_substring"].lower() in heading_lower:
            return o["target_url"]
    return None
