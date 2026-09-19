"""
Discovers (title, url) pairs from three trusted external FOAMEd sites —
Deranged Physiology, WikEM, and the Internet Book of Critical Care —
for tier 3 of the answer-priority framework (see server/retrieval.py /
server/tier3.py): when Ryan's own content and his citation blurbs don't
have a good answer, these are the sources he wants checked next.

Deliberately lightweight: this stores ONLY a title + URL per article,
never the article's own body text — the real content is fetched live,
for one single winning page, at actual answer time (see server/tier3.py),
never bulk-crawled and stored. That's a real distinction from tiers 1/2:
those only ever store short blurbs Ryan personally wrote about a cited
work; this touches someone else's site directly, so it's scoped as
narrowly as the source's own robots.txt allows.

LITFL is deliberately NOT here — it has its own free, open live search
API (litfl.com/wp-json/wp/v2/search), so there's nothing to pre-crawl or
store for it; server/tier3.py calls that API directly at query time.

Each site's real, confirmed (2026-09-18, against the live sites) access
rules:

  Deranged Physiology (derangedphysiology.com, a Drupal site): robots.txt
  disallows /search/ and admin paths, but individual articles are open,
  and it publishes a real sitemap.xml — one file, no titles in it though
  (just <loc>), so titles here are DERIVED from the URL's last path
  segment. Filtered to URLs containing a "Chapter NNN" marker (in either
  "Chapter-310" or "Chapter 3101"/"Chapter%203101" form — both appear in
  the real sitemap), which real spot-checking confirmed reliably
  separates actual content chapters from admin/meta/SAQ-list pages that
  don't belong in an answer index.

  WikEM (wikem.org, MediaWiki): robots.txt disallows all of /w/ and
  /wiki/Special: — meaning both Special:AllPages (the obvious "list
  every article" page) and MediaWiki's own category-pagination links
  (which go through /w/index.php) are off limits. There's no
  sitemap.xml either (confirmed: 404). The real path in here is Ryan's
  own suggestion: start from /wiki/Portal:Categories (an ordinary,
  allowed /wiki/ page) and walk each /wiki/Category:X page it links to
  — each one lists its member articles as plain /wiki/ links, no /w/
  involved. The one real limitation: a category with more than 200
  articles can't be paginated further without hitting the disallowed
  /w/index.php, so large categories (Infectious Disease: 746 real pages,
  Pharmacology: 766) only contribute their first 200 here. Still a large,
  real, useful set — just not exhaustive for the biggest categories.

  IBCC (emcrit.org/ibcc/): emcrit.org's robots.txt fully disallows
  "ClaudeBot" by name, but real testing showed that block applies to
  their /wp-json/ REST API specifically, not ordinary article pages —
  /ibcc/toc/ and individual chapter pages (e.g. /ibcc/ards/) both loaded
  real content in direct testing. /ibcc/toc/ links every chapter with
  its real title as the link text, so no sitemap or per-page title fetch
  is needed at all here — one page fetch gives the whole title index.

Usage (from search-indexer/, in your normal venv):
    python tier3_sources.py            # prints a discovery summary for all 3 sites
    python tier3_sources.py wikem      # just one site, by key
"""
import re
import sys
import time
import urllib.parse as urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

import config

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": config.USER_AGENT})

# Matches WikEM's own stated Crawl-delay (5s, the most conservative of
# the three real robots.txt files checked) — applied uniformly to all
# three sites' requests here, not just WikEM's, since it's a small,
# infrequent, occasional crawl (see build_tier3_index.py), not something
# that needs to be fast.
REQUEST_DELAY_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 20


def _get(url):
    try:
        resp = SESSION.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        time.sleep(REQUEST_DELAY_SECONDS)
        if resp.status_code == 200:
            return resp
        print(f"  ! {resp.status_code} for {url}")
    except requests.RequestException as e:
        print(f"  ! request failed for {url}: {e}")
    return None


# --- WikEM ---

_WIKEM_BASE = "https://wikem.org"
# Only real article pages: /wiki/<Title> with no namespace prefix
# (Category:, Special:, Template:, File:, User:, Talk:, etc. all contain
# a colon in the title portion and are excluded).
_WIKEM_ARTICLE_RE = re.compile(r"^/wiki/([^:]+)$")
_WIKEM_CATEGORY_RE = re.compile(r"^/wiki/Category:")


def _wikem_category_articles(category_url):
    """One category page's real member articles — first 200 only (see
    module docstring: pagination beyond that needs the disallowed
    /w/index.php). Returns [(title, absolute_url), ...]."""
    resp = _get(category_url)
    if resp is None:
        return []
    soup = BeautifulSoup(resp.text, "lxml")
    container = soup.find(id="mw-pages") or soup.find(class_="mw-category") or soup

    seen = set()
    out = []
    for a in container.find_all("a", href=True):
        href = a["href"]
        parsed = urlparse.urlsplit(href)
        path = parsed.path
        if _WIKEM_CATEGORY_RE.match(path):
            continue  # a sub-category link, not an article
        m = _WIKEM_ARTICLE_RE.match(path)
        if not m:
            continue
        title = a.get_text(strip=True) or urlparse.unquote(m.group(1)).replace("_", " ")
        url = urlparse.urljoin(_WIKEM_BASE, path)
        if url in seen:
            continue
        seen.add(url)
        out.append((title, url))
    return out


def discover_wikem_titles():
    print("WikEM: fetching Portal:Categories...")
    resp = _get(f"{_WIKEM_BASE}/wiki/Portal:Categories")
    if resp is None:
        print("  ! couldn't load Portal:Categories, skipping WikEM entirely")
        return []
    soup = BeautifulSoup(resp.text, "lxml")

    category_urls = []
    seen_cats = set()
    for a in soup.find_all("a", href=True):
        path = urlparse.urlsplit(a["href"]).path
        if _WIKEM_CATEGORY_RE.match(path) and path not in seen_cats:
            seen_cats.add(path)
            category_urls.append(urlparse.urljoin(_WIKEM_BASE, path))

    print(f"  found {len(category_urls)} categories")

    articles = {}  # url -> title, deduped (a page can be in several categories)
    for i, cat_url in enumerate(category_urls, 1):
        cat_articles = _wikem_category_articles(cat_url)
        print(f"  [{i}/{len(category_urls)}] {cat_url}: {len(cat_articles)} article(s)")
        for title, url in cat_articles:
            articles[url] = title

    print(f"WikEM: {len(articles)} unique real article(s) discovered")
    return [(title, url) for url, title in articles.items()]


# --- Deranged Physiology ---

_DP_SITEMAP = "https://derangedphysiology.com/main/sitemap.xml"
# Real chapter URLs use both "Chapter-310" and "Chapter 3101" (the
# latter appearing URL-encoded as "Chapter%203101") — confirmed against
# real sitemap entries. Anything without a chapter marker is an
# admin/meta/SAQ-list page, not real reference content.
_DP_CHAPTER_RE = re.compile(r"chapter[\s%-]*\d+", re.IGNORECASE)


def _dp_title_from_url(url):
    slug = urlparse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = urlparse.unquote(slug).replace("-", " ").replace("_", " ").strip()
    return slug[:1].upper() + slug[1:] if slug else url


def discover_deranged_physiology_titles():
    print(f"Deranged Physiology: fetching sitemap {_DP_SITEMAP}...")
    resp = _get(_DP_SITEMAP)
    if resp is None:
        print("  ! couldn't load sitemap.xml, skipping Deranged Physiology entirely")
        return []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"  ! couldn't parse sitemap.xml: {e}")
        return []

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    all_urls = [loc.text.strip() for loc in root.findall("sm:url/sm:loc", ns) if loc.text]
    chapter_urls = [u for u in all_urls if _DP_CHAPTER_RE.search(u)]
    print(f"  {len(all_urls)} total URL(s) in sitemap, {len(chapter_urls)} look like real chapters")

    return [(_dp_title_from_url(u), u) for u in chapter_urls]


# --- IBCC ---

_IBCC_TOC = "https://emcrit.org/ibcc/toc/"
_IBCC_CHAPTER_RE = re.compile(r"^https?://(www\.)?emcrit\.org/ibcc/[^/]+/?$", re.IGNORECASE)


def discover_ibcc_titles():
    print(f"IBCC: fetching {_IBCC_TOC}...")
    resp = _get(_IBCC_TOC)
    if resp is None:
        print("  ! couldn't load /ibcc/toc/, skipping IBCC entirely")
        return []
    soup = BeautifulSoup(resp.text, "lxml")

    seen = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = urlparse.urljoin(_IBCC_TOC, a["href"])
        href, _frag = urlparse.urldefrag(href)
        if not _IBCC_CHAPTER_RE.match(href):
            continue
        if href.rstrip("/") == _IBCC_TOC.rstrip("/"):
            continue  # a link back to the toc page itself
        title = a.get_text(strip=True)
        if not title:
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append((title, href))

    print(f"IBCC: {len(out)} unique real chapter(s) discovered")
    return out


SITES = {
    "deranged_physiology": {
        "display_name": "Deranged Physiology",
        "discover": discover_deranged_physiology_titles,
    },
    "wikem": {
        "display_name": "WikEM",
        "discover": discover_wikem_titles,
    },
    "ibcc": {
        "display_name": "Internet Book of Critical Care",
        "discover": discover_ibcc_titles,
    },
}


if __name__ == "__main__":
    keys = sys.argv[1:] or list(SITES.keys())
    for key in keys:
        if key not in SITES:
            print(f"Unknown site {key!r} — choices: {', '.join(SITES)}")
            continue
        site = SITES[key]
        print(f"\n=== {site['display_name']} ({key}) ===")
        results = site["discover"]()
        for title, url in results[:15]:
            print(f"  {title!r}  ->  {url}")
        if len(results) > 15:
            print(f"  ... and {len(results) - 15} more")
