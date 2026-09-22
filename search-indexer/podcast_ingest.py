"""
Indexes podcast episodes as lightweight tier-1 sources.

Every episode gets ONE chunk (title + categories + cleaned description --
no chunker.py splitting, same pattern as _write_citation_sources in
build_index.py for a source this short) so at least topic/title search
can find and point at the right episode, even for episodes that don't
have a hand-written show-notes page (see github-pages/not-linked/
show-notes-*.md) or a real transcript yet -- those get indexed for
real, full-text, through the NORMAL webpage pipeline (show notes) or
podcast_transcribe.py (transcripts) once available; nothing special
needed here for them, this module only ever writes the one thin
metadata chunk per episode.

Reads the real RSS feed directly (config.PODCAST_FEED_URL) rather than
podcast/episodes.json -- that file is a build-time snapshot for the
client-side podcast page (see podcast/build_episodes.sh) with no
guarantee it's freshly regenerated whenever THIS indexer runs, so this
goes straight to the source, mirroring build_episodes.sh's own field
extraction (already proven correct in production) rather than trusting
a second-hand copy.

The one bit of real interlinking: when an episode's description links to
one of your own show-notes pages (rykerrmedical.com/show-notes-*), this
chunk's links_to is set to that page -- so if a query matches on episode
title/description text, the citation shown resolves (via the server's
_resolve_citation_targets, same mechanism as any other links_to chunk)
to the richer show-notes page instead of the thin archive.org listing.
Generic on purpose: any FUTURE show-notes page picks this up automatically
just by being linked from its own episode's description, no hardcoded
episode list here.
"""
import hashlib
import re
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

import config
import embedder
import store

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": config.USER_AGENT})

# Matches a link to one of your own show-notes pages, on either host
# spelling (www or bare) -- see _config.yml's url + the real pages'
# permalinks (/show-notes-<name>-podcast/). Deliberately just "starts
# with /show-notes-", not a hardcoded list of the 3 that exist today, so
# a 4th show-notes page picked up by a future episode links up for free.
#
# The optional "/not-linked" prefix matters: confirmed against the real
# feed that the Dan Taylor episode's description links to
# ".../not-linked/show-notes-dan-taylor-podcast/" -- the page's OLD
# source-file location, which the page's own front matter now redirects
# from (redirect_from:) but which the crawler will never index content
# UNDER, since it discovers the page at its real permalink instead. Both
# path spellings get normalized to the canonical (no "/not-linked")
# form below, so links_to always matches the URL this page is actually
# indexed under, however the podcast description happens to link it.
_SHOWNOTES_HREF_RE = re.compile(
    r"^https?://(?:www\.)?rykerrmedical\.com(?:/not-linked)?(/show-notes-[^\s\"'?#]*)", re.IGNORECASE
)


def _hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_episodes():
    """Returns a list of episode dicts (title, link, audio_url, pub_date,
    description_html, categories), or [] on any fetch/parse failure --
    best-effort, same as the rest of the indexer: a hiccup fetching the
    feed shouldn't fail the whole build, just leave podcast content
    exactly as it was last run (store.get_source_signal comparisons are
    per-episode, so a skipped fetch here doesn't touch any existing
    'podcast' rows at all)."""
    try:
        resp = SESSION.get(config.PODCAST_FEED_URL, timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError) as e:
        print(f"  ! could not fetch/parse podcast feed ({config.PODCAST_FEED_URL}): {e}")
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    episodes = []
    for item in channel.findall("item"):
        link = (item.findtext("link") or "").strip()
        if not link:
            continue  # no stable identifier to key this episode on -- skip rather than guess one
        enc = item.find("enclosure")
        episodes.append({
            "title": (item.findtext("title") or "Untitled").strip(),
            "link": link,
            "audio_url": enc.get("url", "") if enc is not None else "",
            "pub_date": (item.findtext("pubDate") or "").strip(),
            "description_html": item.findtext("description") or "",
            "categories": [c.text.strip().lower() for c in item.findall("category") if c.text],
        })
    return episodes


def _clean_description(html):
    """Plain, readable text for embedding -- strips tags, the odd
    leading BOM characters real entries carry (confirmed: one real
    episode's raw description starts with three literal '\\ufeff'
    characters), and collapses whitespace."""
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return text.replace("﻿", "").strip()


def _find_shownotes_link(html):
    for href in re.findall(r'href="([^"]+)"', html):
        m = _SHOWNOTES_HREF_RE.match(href.strip())
        if m:
            # Normalize to the canonical host (_config.yml's url =
            # https://www.rykerrmedical.com) so this matches whatever
            # source_id the webpage pipeline actually indexed that page
            # under, regardless of which host spelling the podcast
            # description happened to use.
            return f"https://www.rykerrmedical.com{m.group(1)}"
    return None


def index_podcast_episodes(conn, force_substr=None):
    """Mirrors index_webpages/index_pdfs' shape: one chunk per episode,
    skip re-embedding when nothing about the episode changed since last
    run. Returns (current_source_ids, stats) for build()'s prune step."""
    stats = {"seen": 0, "changed": 0, "unchanged": 0}
    current_ids = set()

    episodes = fetch_episodes()
    if not episodes:
        print("  no podcast episodes fetched -- leaving existing podcast index rows as-is")
        return current_ids, stats

    for ep in episodes:
        source_id = ep["link"]
        current_ids.add(source_id)
        stats["seen"] += 1

        desc_text = _clean_description(ep["description_html"])
        shownotes_url = _find_shownotes_link(ep["description_html"])

        forced = force_substr is not None and (
            force_substr in source_id.lower() or force_substr in ep["title"].lower()
        )

        # Signal has to cover the show-notes link too, not just the
        # visible text -- a description's anchor TEXT ("show notes")
        # can stay identical while its href is added or changed, which
        # would otherwise leave a stale (or missing) links_to
        # undetected forever under a text-only signal.
        content_repr = "\x1e".join([
            ep["title"], desc_text, "|".join(ep["categories"]), shownotes_url or "",
        ])
        content_signal = _hash_text(content_repr)
        if not forced and store.get_source_signal(conn, source_id) == content_signal:
            stats["unchanged"] += 1
            continue

        parts = [ep["title"]]
        if ep["categories"]:
            parts.append("Topics: " + ", ".join(ep["categories"]))
        if desc_text:
            parts.append(desc_text)
        text = "\n\n".join(parts)

        embedding = embedder.embed_documents([text])[0]
        chunk_rows = [{
            "locator": "",
            "locator_url": source_id,
            "chunk_index": 0,
            "text": text,
            "embedding": embedding,
            "links_to": shownotes_url,
        }]
        store.replace_source_chunks(
            conn, "podcast", source_id, ep["title"], chunk_rows, content_signal, tags=ep["categories"]
        )
        conn.commit()
        stats["changed"] += 1

    return current_ids, stats
