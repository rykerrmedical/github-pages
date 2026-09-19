"""
Discovers the set of page URLs to index for a site.

Strategy:
1. Try <base>/sitemap.xml (jekyll-sitemap plugin output — most Jekyll/GitHub
   Pages sites have this). Recurses into sitemap index files if present.
2. If no sitemap is found, fall back to a same-domain breadth-first link
   crawl starting from the homepage.

Either way, URLs are filtered against config.SKIP_PATH_CONTAINS /
SKIP_EXTENSIONS and capped at config.MAX_PAGES_PER_SITE.
"""
import time
import urllib.parse as urlparse
import xml.etree.ElementTree as ET
from collections import deque

import requests
from bs4 import BeautifulSoup

import config

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": config.USER_AGENT})


def _get(url):
    try:
        resp = SESSION.get(url, timeout=config.REQUEST_TIMEOUT_SECONDS)
        if resp.status_code == 200:
            return resp
    except requests.RequestException as e:
        print(f"  ! request failed for {url}: {e}")
    return None


def _should_skip(url):
    path = urlparse.urlsplit(url).path.lower()
    if any(frag in path for frag in config.SKIP_PATH_CONTAINS):
        return True
    if any(path.endswith(ext) for ext in config.SKIP_EXTENSIONS):
        return True
    return False


def _normalize(url, base):
    url = urlparse.urljoin(base, url)
    url, _frag = urlparse.urldefrag(url)  # drop #fragments
    # drop trailing index.html for de-dup purposes
    if url.endswith("/index.html"):
        url = url[: -len("index.html")]
    return url


def _bare_domain(netloc):
    """Strips a leading 'www.' so 'www.example.com' and 'example.com'
    compare as the same site."""
    netloc = netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def _canonicalize_domain(url, canonical_netloc, canonical_scheme=None):
    """Rewrites url's host (and, if given, scheme) to the canonical form
    when it's the same site under a www/non-www or http/https variant, so
    the same page is never discovered/indexed twice under two different
    URLs, and so a same-domain check against canonical_netloc doesn't
    silently reject it.

    Real bug this fixes, in two parts, both confirmed against the live
    site and the actual index contents (not guessed):

    1. www/non-www: config.SITES lists the site as
       "https://rykerrmedical.com" (no www), but the site's own page
       templates link internally as "https://www.rykerrmedical.com/..."
       A specific blog post, "International Opportunities for EMS", was
       missing from the index because of exactly this: discover_via_crawl's
       same-domain filter did an exact string comparison of netlocs, so
       every www-prefixed internal link silently failed the check and was
       dropped before ever being queued — not just one missing post, but
       systematic under-crawling of the whole site (discovered page count
       went from ~28 to 64 once this was fixed).

    2. http/https: fixing #1 surfaced a second, same-shape gap — some
       older content (from before the site moved to HTTPS) links with
       absolute "http://rykerrmedical.com/..." URLs. Since the same-domain
       filter never looked at scheme either, those passed the check
       untouched and got crawled as a SEPARATE page from the https://
       version, producing duplicate source_ids in the index for the same
       real page — confirmed directly against rykerr_index.db, where
       "International Opportunities for EMS People", the Austere Medicine
       page, and a case-report post each had both an http:// and an
       https:// row. Duplicate rows mean duplicate (and instance-fresh,
       so undeduped) chunks competing for the same result slots in search.

    Mirrors the earlier fix for archive.org PDF-mirror URLs
    (_canonicalize_pdf_url in pdf_ingest.py) — same shape of bug
    (multiple URL spellings of one real page), different layer.
    """
    parsed = urlparse.urlsplit(url)
    if not parsed.netloc or _bare_domain(parsed.netloc) != _bare_domain(canonical_netloc):
        return url
    changed = False
    if parsed.netloc != canonical_netloc:
        parsed = parsed._replace(netloc=canonical_netloc)
        changed = True
    if canonical_scheme and parsed.scheme != canonical_scheme:
        parsed = parsed._replace(scheme=canonical_scheme)
        changed = True
    return urlparse.urlunsplit(parsed) if changed else url


def _urls_from_sitemap(sitemap_url, seen_sitemaps=None):
    if seen_sitemaps is None:
        seen_sitemaps = set()
    if sitemap_url in seen_sitemaps:
        return []
    seen_sitemaps.add(sitemap_url)

    resp = _get(sitemap_url)
    if resp is None:
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = []

    # Sitemap index (points at other sitemaps)
    sub_sitemaps = root.findall("sm:sitemap/sm:loc", ns)
    if sub_sitemaps:
        for loc in sub_sitemaps:
            urls.extend(_urls_from_sitemap(loc.text.strip(), seen_sitemaps))
        return urls

    for loc in root.findall("sm:url/sm:loc", ns):
        if loc.text:
            urls.append(loc.text.strip())
    return urls


def discover_via_sitemap(base_url):
    sitemap_url = urlparse.urljoin(base_url, "/sitemap.xml")
    print(f"  trying sitemap: {sitemap_url}")
    urls = _urls_from_sitemap(sitemap_url)
    return urls


def discover_via_crawl(base_url, max_pages):
    print(f"  no sitemap found, falling back to link crawl from {base_url}")
    base_parts = urlparse.urlsplit(base_url)
    domain = base_parts.netloc
    scheme = base_parts.scheme

    seen = set()
    queue = deque([base_url])
    found = []

    while queue and len(found) < max_pages:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)

        resp = _get(url)
        time.sleep(config.REQUEST_DELAY_SECONDS)
        if resp is None:
            continue
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            continue

        found.append(url)

        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.find_all("a", href=True):
            link = _normalize(a["href"], url)
            link = _canonicalize_domain(link, domain, scheme)
            if urlparse.urlsplit(link).netloc != domain:
                continue
            if _should_skip(link):
                continue
            if link not in seen:
                queue.append(link)

    return found


def discover_urls(base_url):
    """Returns a deduped, filtered list of page URLs for one site."""
    canonical_parts = urlparse.urlsplit(base_url)
    canonical_netloc = canonical_parts.netloc
    canonical_scheme = canonical_parts.scheme
    urls = discover_via_sitemap(base_url)
    if not urls:
        urls = discover_via_crawl(base_url, config.MAX_PAGES_PER_SITE)

    # Canonicalize here too (defense in depth): a sitemap can list URLs
    # under a different hostname or scheme, and without this a www/non-www
    # or http/https duplicate could slip past de-dup and get indexed twice
    # under two different URLs.
    cleaned = []
    seen = set()
    for u in urls:
        u = _normalize(u, base_url)
        u = _canonicalize_domain(u, canonical_netloc, canonical_scheme)
        if _should_skip(u):
            continue
        if u in seen:
            continue
        seen.add(u)
        cleaned.append(u)

    cleaned = cleaned[: config.MAX_PAGES_PER_SITE]
    print(f"  discovered {len(cleaned)} candidate page(s) for {base_url}")
    return cleaned


def fetch_html(url):
    """Fetches one page's raw HTML, or None on failure."""
    resp = _get(url)
    time.sleep(config.REQUEST_DELAY_SECONDS)
    if resp is None:
        return None
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        return None
    return resp.text


if __name__ == "__main__":
    # Quick manual check: python crawl.py
    for site in config.SITES:
        print(f"\n{site}")
        found = discover_urls(site)
        for u in found[:20]:
            print(" ", u)
        if len(found) > 20:
            print(f"  ... and {len(found) - 20} more")
