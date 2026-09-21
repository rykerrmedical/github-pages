"""
Pulls the title, a short blurb, and the STRUCTURED body (heading path +
paragraph text, in document order) out of a raw HTML page, stripping nav
bars, footers, and other boilerplate.

Uses trafilatura, which is purpose-built for "give me the article, not the
chrome around it" and handles arbitrary site templates reasonably well
without per-site tuning. Asking it for markdown output (rather than the
previous plain-text mode) is what makes heading structure available at
all -- plain-text mode collapses "## Minute Volume for Pediatrics" down to
indistinguishable body prose, the exact "random batch of text" problem
pdf_ingest.py's font-size heading detection exists to avoid on the PDF
side. See chunker.py's chunk_structured_text for how the blocks this
produces turn into heading-aware, title/blurb-led chunks instead of blind
sliding windows.

Confirmed against real HTML (a synthetic article with a title, a meta
description, and an H1/H2/H2/H3 structure): trafilatura's markdown output
renders headings as literal "#"/"##"/"###" lines you can parse directly,
independent of whatever font-size/CSS the source site actually uses --
unlike pdf_ingest.py's PDF heading detection, HTML already tells you the
heading level explicitly, no relative-to-body-size guessing needed.
"""
import re

import trafilatura
from bs4 import BeautifulSoup

_HEADING_LINE_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_INLINE_EMPHASIS_RE = re.compile(r"(\*{1,2}|_{1,2})(\S(?:.*?\S)?)\1")
_BLURB_MAX_CHARS = 300


def extract_title(html, url):
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return url


def extract_blurb(html):
    """A short one-or-two-sentence description of the page, if the site
    provides one -- the same text a search engine or social share card
    would show. Returns None (not "") when neither meta tag is present,
    so callers can tell "no blurb" apart from "empty blurb" and skip the
    line entirely rather than embedding a blank one."""
    soup = BeautifulSoup(html, "lxml")
    for attrs in (
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content", "").strip():
            blurb = " ".join(tag["content"].split())  # collapse whitespace/newlines
            return blurb[:_BLURB_MAX_CHARS]
    return None


def _strip_inline_emphasis(text):
    # Markdown's **bold**/*italic*/__bold__/_italic_ markers are noise for
    # an embedding model, not signal -- unwrap them rather than leaving
    # stray asterisks/underscores in what actually gets embedded.
    return _INLINE_EMPHASIS_RE.sub(r"\2", text)


def _normalize_heading_text(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def _parse_structured_blocks(markdown_text, title):
    """Walks trafilatura's markdown output line by line, grouping body
    text under whichever heading is currently in effect. Returns a list
    of {"heading_path": str or None, "text": str} blocks, in document
    order -- one block per heading section, or a single block with
    heading_path=None for a page with no in-body headings at all (most
    short blog posts).

    Markdown heading level (the number of leading #'s) maps directly to
    a heading tier -- HTML already tells you the level explicitly, no
    relative-to-body-size guessing needed the way pdf_ingest.py has to
    for PDFs.

    A leading H1 that just repeats the page's own title (the common
    case -- trafilatura keeps the article's own <h1>, which is usually
    the headline itself) is dropped from the heading path rather than
    kept: chunk_structured_text already leads every chunk with the
    title on its own line, so repeating it inside the heading path too
    would just be noise, not distinguishing information."""
    blocks = []
    heading_stack = []  # [(level, text), ...] -- current path from top down
    current_lines = []
    normalized_title = _normalize_heading_text(title) if title else None

    def _flush():
        text = _strip_inline_emphasis("\n".join(current_lines).strip())
        if text:
            heading_path = " — ".join(h for _, h in heading_stack) or None
            blocks.append({"heading_path": heading_path, "text": text})
        current_lines.clear()

    for line in markdown_text.splitlines():
        m = _HEADING_LINE_RE.match(line.strip())
        if m:
            _flush()
            level = len(m.group(1))
            heading_text = re.sub(r"[*_`]", "", m.group(2)).strip()
            if not heading_text:
                continue
            if normalized_title and _normalize_heading_text(heading_text) == normalized_title:
                continue  # redundant with the title lead-in -- see docstring
            # Pop back to this level, then push -- keeps heading_stack a
            # proper current path (e.g. a new H2 replaces just the H3
            # under it, not the whole stack).
            heading_stack = [h for h in heading_stack if h[0] < level]
            heading_stack.append((level, heading_text))
        else:
            current_lines.append(line)
    _flush()
    return blocks


def extract_page(html, url):
    """
    Returns {"title": str, "blurb": str or None, "blocks": [...]} or None
    if the page has no meaningful extractable content (e.g. a redirect
    stub, an empty listing page). "blocks" is chunker.chunk_structured_
    text's input -- see _parse_structured_blocks above.
    """
    markdown = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        output_format="markdown",
    )
    if not markdown or len(markdown.split()) < 20:
        return None

    title = extract_title(html, url)
    blurb = extract_blurb(html)
    blocks = _parse_structured_blocks(markdown, title)
    return {"title": title, "blurb": blurb, "blocks": blocks}


if __name__ == "__main__":
    import sys
    import crawl

    url = sys.argv[1] if len(sys.argv) > 1 else "https://rykerrmedical.com"
    html = crawl.fetch_html(url)
    if html is None:
        print("failed to fetch")
    else:
        page = extract_page(html, url)
        if page is None:
            print("no meaningful content extracted")
        else:
            print("TITLE:", page["title"])
            print("BLURB:", page["blurb"])
            print(f"--- {len(page['blocks'])} block(s) ---")
            for b in page["blocks"][:8]:
                print("HEADING:", b["heading_path"])
                print(b["text"][:300])
                print()
