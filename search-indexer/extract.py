"""
v5: two fixes found running v4 against Ryan's real pages.

1. clinical-resources' cards aren't a <ul>/<ol> at all -- confirmed
   against the real built page: <h3 id="airway"><a href="...">Airway
   Stuff</a></h3> followed by a plain <p> description, repeated per
   card, no list wrapper in sight. _heading_is_link_only already
   detected "this heading is nothing but a link" correctly, but the
   previous version just SKIPPED such headings entirely -- a workaround
   for trafilatura duplicating a <ul>'s first item (see the version
   before this one), which no longer applies now that
   _extract_link_list_blocks strips <ul>/<ol> content out before
   trafilatura ever runs. Skipping was therefore actively wrong for
   this real, non-list pattern: it discarded the one signal (the
   heading's own link) that tells us what each card's paragraph is
   about. Fixed: a link-only heading is now pushed as a real heading
   (so the paragraph(s) under it still group together as before) AND
   its link is attached as links_to to whatever block is flushed next
   under it -- same idea as a link-list item, just for a heading/
   paragraph pair instead of a <li>. A same-page anchor (href="#...",
   confirmed present here too, as a little in-page table of contents)
   is explicitly excluded -- "#airway" is not a real citable target.

2. The RSS-feed paragraph came back with its own text duplicated INSIDE
   one block ("...blog-feed.xml also, if you're the nerdy type...").
   Root cause: _dedupe_redundant_blocks only drops a block that's a
   STRICT substring of a longer one, so two separately-emitted blocks
   with EXACTLY EQUAL text (which is what actually happened here --
   confirmed by the real blog run) both survived and then got joined
   together by a later _flush() call that accumulated both into
   current_lines before flushing. Fixed at the source: current_lines
   is deduped (order-preserving) before joining, so an exact-duplicate
   line never gets concatenated with itself regardless of why it
   appeared twice.
"""
import re

import trafilatura
from bs4 import BeautifulSoup
from urllib.parse import urljoin

_BLURB_MAX_CHARS = 300
_HEADING_TAGS = {"head"}
_LIST_TAGS = {"list"}
_ITEM_TAGS = {"item"}

_LINK_LIST_MIN_FRACTION = 0.5
_LINK_LIST_MIN_ITEMS = 2
_BOILERPLATE_ANCESTORS = {"nav", "header", "footer"}


def _normalize_heading_text(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def _has_boilerplate_ancestor(tag):
    return any(p.name in _BOILERPLATE_ANCESTORS for p in tag.parents)


def _li_link_and_heading(li):
    heading = li.find(re.compile(r"^h[1-6]$"))
    links = li.find_all("a", href=True)
    if not links:
        return None

    if heading is not None:
        heading_links = heading.find_all("a", href=True)
        if len(heading_links) == 1:
            link = heading_links[0]
        elif len(links) == 1:
            link = links[0]
        else:
            return None
    elif len(links) == 1:
        link = links[0]
    else:
        return None

    link_text = link.get_text(strip=True)
    full_text = re.sub(r"\s+", " ", li.get_text(separator=" ", strip=True)).strip()
    return link_text, link["href"], full_text


def _find_link_list_regions(soup):
    regions = []
    for lst in soup.find_all(["ul", "ol"]):
        if _has_boilerplate_ancestor(lst):
            continue
        items = lst.find_all("li", recursive=False)
        if len(items) < _LINK_LIST_MIN_ITEMS:
            continue
        parsed = [_li_link_and_heading(li) for li in items]
        matched = [p for p in parsed if p is not None]
        if len(matched) / len(items) >= _LINK_LIST_MIN_FRACTION:
            regions.append((lst, matched))
    return regions


def _extract_link_list_blocks(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    regions = _find_link_list_regions(soup)
    blocks = []
    for lst, items in regions:
        for link_text, url, full_text in items:
            if not full_text:
                continue
            blocks.append({
                "heading_path": link_text or full_text,
                "text": full_text,
                "links_to": urljoin(base_url, url),
            })
        lst.decompose()
    return blocks, str(soup)


def _collect_text_and_refs(node):
    if node is None:
        return "", []
    text = re.sub(r"\s+", " ", node.get_text(separator=" ", strip=True)).strip()
    refs = []
    for ref in node.find_all("ref"):
        target = ref.get("target", "").strip()
        if target:
            refs.append((ref.get_text(strip=True), target))
    return text, refs


def _is_link_list(list_node):
    items = list_node.find_all("item", recursive=False)
    if not items:
        return False
    single_ref_items = sum(1 for item in items if len(item.find_all("ref")) == 1)
    return single_ref_items / len(items) >= _LINK_LIST_MIN_FRACTION


def _heading_link_only_target(head_node, base_url):
    """Returns the absolute URL when a heading's entire content is one
    <ref> and nothing else -- the "card title IS the link" shape (e.g.
    clinical-resources' <h3><a href="...">Airway Stuff</a></h3>) -- or
    None otherwise. Excludes a same-page anchor (href starting with
    "#"): confirmed real on clinical-resources itself, a little in-page
    table of contents ("Airway Stuff" -> "#airway") that looks
    identical in shape but isn't a real citable target."""
    refs = head_node.find_all("ref")
    if len(refs) != 1:
        return None
    heading_text = _normalize_heading_text(head_node.get_text(strip=True))
    ref_text = _normalize_heading_text(refs[0].get_text(strip=True))
    if heading_text != ref_text or heading_text == "":
        return None
    target = refs[0].get("target", "").strip()
    if not target or target.startswith("#"):
        return None
    return urljoin(base_url, target)


def _dedupe_redundant_blocks(blocks):
    texts = [b["text"] for b in blocks]
    return [
        b for i, b in enumerate(blocks)
        if not any(
            i != j and b["text"] and b["text"] in other and len(b["text"]) < len(other)
            for j, other in enumerate(texts)
        )
    ]


def _parse_structured_blocks(xml_root, title, base_url):
    """Handles whatever's left after _extract_link_list_blocks has
    already pulled out and removed any qualifying <ul>/<ol> link-lists.
    Also handles a link-only heading NOT wrapped in a list at all (see
    _heading_link_only_target) -- attaches its link as links_to to
    whatever block is flushed next under it, same idea as a list item's
    links_to, just for a heading/paragraph pair. And, as a narrower
    third layer, a link-list pattern that isn't <ul>/<ol> at all but
    that trafilatura still preserves as <list>/<item>/<ref> in its own
    XML (via _is_link_list)."""
    blocks = []
    heading_stack = []
    current_lines = []
    pending_links_to = [None]
    normalized_title = _normalize_heading_text(title) if title else None

    def _flush():
        # De-dupe exact-repeat lines before joining -- see module
        # docstring point 2. Order-preserving.
        unique_lines = list(dict.fromkeys(current_lines))
        text = re.sub(r"\s+", " ", " ".join(unique_lines)).strip()
        if text:
            heading_path = " — ".join(h for _, h in heading_stack) or None
            block = {"heading_path": heading_path, "text": text}
            if pending_links_to[0]:
                block["links_to"] = pending_links_to[0]
            blocks.append(block)
        current_lines.clear()
        pending_links_to[0] = None

    def _heading_level(node):
        m = re.match(r"h(\d)", node.get("rend", "h6"))
        return int(m.group(1)) if m else 6

    def _walk(node):
        for child in node.find_all(recursive=False):
            tag = child.name
            if tag in _HEADING_TAGS:
                link_target = _heading_link_only_target(child, base_url)
                _flush()
                heading_text = child.get_text(strip=True)
                if not heading_text:
                    continue
                if normalized_title and _normalize_heading_text(heading_text) == normalized_title:
                    continue
                level = _heading_level(child)
                heading_stack[:] = [h for h in heading_stack if h[0] < level]
                heading_stack.append((level, heading_text))
                pending_links_to[0] = link_target
            elif tag in _LIST_TAGS:
                if _is_link_list(child):
                    _flush()
                    for item in child.find_all("item", recursive=False):
                        item_text, item_refs = _collect_text_and_refs(item)
                        if not item_text:
                            continue
                        distinct_targets = {url for _, url in item_refs}
                        if len(distinct_targets) == 1:
                            ref_text = item_refs[0][0] or item_text
                            item_heading = " — ".join([*(h for _, h in heading_stack), ref_text])
                            blocks.append({
                                "heading_path": item_heading, "text": item_text,
                                "links_to": next(iter(distinct_targets)),
                            })
                        else:
                            heading_path = " — ".join(h for _, h in heading_stack) or None
                            blocks.append({"heading_path": heading_path, "text": item_text})
                else:
                    item_text, _refs = _collect_text_and_refs(child)
                    if item_text:
                        current_lines.append(item_text)
            elif tag in _ITEM_TAGS:
                continue
            else:
                text, _refs = _collect_text_and_refs(child)
                if text:
                    current_lines.append(text)

    _walk(xml_root)
    _flush()
    return _dedupe_redundant_blocks(blocks)


def extract_title(html, url):
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return url


def extract_blurb(html):
    soup = BeautifulSoup(html, "lxml")
    for attrs in (
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content", "").strip():
            blurb = " ".join(tag["content"].split())
            return blurb[:_BLURB_MAX_CHARS]
    return None


def extract_page(html, url):
    title = extract_title(html, url)
    blurb = extract_blurb(html)

    link_list_blocks, remaining_html = _extract_link_list_blocks(html, url)

    xml = trafilatura.extract(
        remaining_html, url=url, include_comments=False, include_tables=True,
        favor_recall=True, output_format="xml", include_links=True,
    )
    rest_blocks = []
    if xml:
        soup = BeautifulSoup(xml, "lxml-xml")
        main = soup.find("main") or soup.find("doc")
        if main is not None:
            rest_blocks = _parse_structured_blocks(main, title, url)

    blocks = link_list_blocks + rest_blocks
    total_words = sum(len(b["text"].split()) for b in blocks)
    if total_words < 20:
        return None

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
            for b in page["blocks"][:30]:
                print("HEADING:", b["heading_path"])
                if b.get("links_to"):
                    print("LINKS_TO:", b["links_to"])
                print(b["text"][:300])
                print()
