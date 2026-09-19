"""
Blog post tags, read straight from the source .md files' YAML front
matter instead of guessed at from rendered HTML.

Confirmed from a real post (2026-08-15-mechanical-ventilation-with-
cardiac-defects.md):

    ---
    layout: post
    title: ...
    date: 2026-08-15
    image: ...
    tags: [cardiology, hemodynamics, mechanical ventilation, pathophysiology, pediatrics]
    blurb: ...
    ---

No assumption is made about which folder posts live in (e.g. `_posts/`)
or how the site's permalinks are structured — both are things we
haven't been shown and won't guess at. Instead this leans on the one
thing Jekyll *requires* for a post to be built at all: the filename
itself must be `YYYY-MM-DD-title.md`. So we walk the whole repo
checkout looking for files matching that pattern, wherever they are,
and read their front matter directly.

The harder problem is matching a front-matter entry back to the *URL*
build_index.py crawled, since we don't know the permalink format.
match_url() uses two independent signals and takes either:

  1. Slug match: the filename's slug (date prefix and .md stripped,
     e.g. "mechanical-ventilation-with-cardiac-defects") appears as a
     full path segment in the crawled URL.
  2. Title match: the front-matter `title:` and the page's extracted
     <title>/<h1> normalize to the same slug-like string.

If neither matches for a given crawled page, we simply don't attach
front-matter tags to it (falls back to whatever tags.py's HTML-guessing
finds, which may be nothing) rather than force a wrong guess.
"""
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

POST_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")

# Directories not worth walking looking for post source files.
_SKIP_DIR_NAMES = {
    ".git", "_site", "node_modules", "vendor", ".jekyll-cache", ".github",
}


def _slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def find_post_files(repo_root="."):
    """Walks repo_root for any *.md file matching Jekyll's required
    post filename convention (YYYY-MM-DD-slug.md), regardless of which
    directory it's in."""
    root = Path(repo_root)
    found = []
    for path in root.rglob("*.md"):
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        m = POST_FILENAME_RE.match(path.name)
        if m:
            found.append((path, m.group(2)))  # (path, raw-slug-from-filename)
    return found


def _parse_front_matter(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.startswith("---"):
        return None
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _normalize_tags(value):
    if not value:
        return []
    if isinstance(value, str):
        # Rare but possible: "tags: cardiology, hemodynamics"
        items = value.split(",")
    else:
        items = value
    return [str(t).strip() for t in items if str(t).strip()]


def build_post_index(repo_root="."):
    """Returns a list of dicts: {"slug": ..., "title": ..., "tags": [...]}
    for every post-like .md file found under repo_root."""
    entries = []
    for path, filename_slug in find_post_files(repo_root):
        fm = _parse_front_matter(path)
        if fm is None:
            continue
        tags = _normalize_tags(fm.get("tags"))
        if not tags:
            continue
        entries.append({
            "slug": _slugify(filename_slug),
            "title_slug": _slugify(str(fm.get("title", ""))) if fm.get("title") else "",
            "tags": tags,
            "path": str(path),
        })
    return entries


def match_tags_for_page(post_index, url, page_title=None):
    """Looks up front-matter tags for a crawled page, by URL path
    segment first, then by normalized title. Returns [] if no post
    entry matches — never guesses."""
    raw_segments = [seg for seg in urlparse(url).path.split("/") if seg]
    # Strip a trailing .html/.htm from the last segment before slugifying,
    # so a permalink like /blog/some-post.html still matches the bare
    # filename slug (slugify would otherwise turn the dot into a dash).
    if raw_segments:
        raw_segments[-1] = re.sub(r"\.html?$", "", raw_segments[-1], flags=re.I)
    path_segments = {_slugify(seg) for seg in raw_segments}
    page_title_slug = _slugify(page_title) if page_title else ""

    for entry in post_index:
        if entry["slug"] and entry["slug"] in path_segments:
            return entry["tags"]

    if page_title_slug:
        for entry in post_index:
            if entry["title_slug"] and entry["title_slug"] == page_title_slug:
                return entry["tags"]

    return []
