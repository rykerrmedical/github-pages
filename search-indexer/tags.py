"""
FALLBACK ONLY, for pages that aren't blog posts.

Blog post tags now come from frontmatter_tags.py, which reads the
`tags:` front matter straight out of each post's source .md file —
confirmed against a real post, no guessing. build_index.py tries that
first for every crawled page; this module only runs when that lookup
comes back empty (a page that isn't a Jekyll post, or one we couldn't
match back to a source file).

This was written by guessing at common Jekyll rendering patterns
without ever seeing real markup from a non-post page, so treat
anything it finds as a bonus, not something to rely on. It tries a few
common places a Jekyll site tends to expose tags in HTML, in order,
and stops at the first one that finds anything:

  1. <meta name="keywords" content="...">  — what the jekyll-seo-tag
     plugin emits automatically from front-matter `tags:`, if that
     plugin is in use.
  2. Links pointing at a /tag/ or /tags/ path near the post — the
     common Jekyll "tag chip" rendering pattern.
  3. A JSON-LD block's "keywords" field, if the theme emits structured
     data.

If none of these match, it quietly returns an empty list rather than
guessing wrong. If some non-post page type of yours has tags worth
surfacing, tell me what the markup looks like (view-source or a
snippet) and I'll add a real pattern for it instead of guessing here.
"""
import json

from bs4 import BeautifulSoup


def _from_meta_keywords(soup):
    tag = soup.find("meta", attrs={"name": "keywords"})
    if tag and tag.get("content"):
        return [t.strip() for t in tag["content"].split(",") if t.strip()]
    return []


def _from_tag_links(soup):
    tags = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if "/tag/" in href or "/tags/" in href:
            text = a.get_text(strip=True)
            if text and text.lower() not in seen:
                seen.add(text.lower())
                tags.append(text)
    return tags


def _from_json_ld(soup):
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            kw = item.get("keywords")
            if isinstance(kw, str):
                return [t.strip() for t in kw.split(",") if t.strip()]
            if isinstance(kw, list):
                return [str(t).strip() for t in kw if str(t).strip()]
    return []


def extract_tags(html):
    soup = BeautifulSoup(html, "lxml")
    for strategy in (_from_meta_keywords, _from_tag_links, _from_json_ld):
        found = strategy(soup)
        if found:
            return found
    return []
