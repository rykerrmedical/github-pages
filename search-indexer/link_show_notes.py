"""
Links each show-notes page's own chunks to the real media (podcast
episode or YouTube video) they're notes FOR, so a search match on the
notes leads with the actual recording as the card, not the show-notes
page -- Ryan's call, 2026-09-27, using the Wes Podcast show notes as
the concrete example, extended the same day to the YouTube case too
("same concept should apply"): still fine for the notes to be
findable, but the real recording is what the notes are actually ABOUT,
so it needs to be the focus. The notes' own snippet text often names
the moment better than the raw transcript would ("HOP Killers - ...
see the EmCrit Intubation Checklist(s)..."), so that text is kept as
the displayed snippet even after the card's identity resolves to the
episode/video -- only the source_type/source_id/source_title/locator
swap (server/retrieval.py's _resolve_citation_targets does the actual
swap at query time, same mechanism as any other links_to chunk; this
module only ever sets which target chunk a links_to points at).

Runs as a post-process pass, after every source type has been fully
(re)indexed for this build -- deliberately NOT wired into the webpage
crawl itself, since it needs the real podcast_transcript/
youtube_transcript chunks to already be in the DB (to find the nearest
one by timestamp, or at least confirm the target is actually
transcribed), and crawl order isn't something worth depending on.
Cheap either way: this is a handful of small, targeted UPDATEs, not a
re-embed.

Two ways a show-notes page's target gets identified:
  - podcasts (link_show_notes_to_episodes): auto-detected from the live
    RSS feed, via the exact same fetch + regex podcast_ingest.py
    already uses to link a THIN podcast chunk's citation to its own
    show-notes page (see podcast_ingest.fetch_episodes/
    _find_shownotes_link) -- just walked the other direction here:
    show-notes chunk -> real episode, instead of thin-podcast-chunk ->
    show-notes page.
  - YouTube videos (link_show_notes_to_videos): no feed exists to
    auto-detect these the way podcasts do, but build_index.py now
    scans each show-notes page's own raw HTML for a self-referencing
    youtube.com/youtu.be link (find_self_video_link, added 2026-09-28)
    -- confirmed real that show-notes-pedi-video.md links its own
    video inline mid-sentence, not in a list or a link-only heading,
    so this is a whole-page scan, not extract.py's block-level link
    detection. Most of today's real pages (Oxygen Haterz, Perfusion
    Index, all three SFCEBM tutoring pages) still don't link their own
    video anywhere on the page at all, though, so curation/
    show_notes_videos.txt remains a real, load-bearing fallback for
    those -- not just a safety net -- same "fallback for what can't be
    auto-detected, and an override for what can" spirit as curation.py's
    own defer_to.txt. See link_show_notes_to_videos's docstring for the
    merge precedence.

Within one mapped page, matching gets as precise as the data allows: a
notes chunk whose own text starts with a real "MM:SS" timestamp
(confirmed format across every show-notes-*.md page that uses them)
links to its nearest real transcript chunk's exact locator_url. A
chunk with no timestamp of its own -- some show-notes pages (Combat
Midwife, Dan Taylor, all three SFCEBM tutoring pages) are just
categorized reference lists with no per-bullet timestamps at all --
still defers to the target media, just without a specific moment: its
links_to is set to the target's bare source_id, which
_resolve_citation_targets resolves to that source's first chunk. Either
way the real recording leads, only the precision differs. A target
that isn't transcribed/indexed yet is left alone entirely (its
show-notes chunks keep citing themselves, same as before this module
existed) rather than pointing at nothing real.
"""
import os
import re

import crawl
import podcast_ingest

_TIMESTAMP_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")

# Extracts the bare 11-char video ID from any YouTube URL shape Ryan's
# pages actually use or might plausibly use -- confirmed real that
# show-notes-pedi-video.md links its own video as a youtu.be SHORT
# link ("via this link"), which is NOT the same string as the
# https://www.youtube.com/watch?v=<id> form youtube_transcribe.py's
# own _video_url canonicalizes every known_video_urls source_id to.
# Caught this mismatch during end-to-end verification, 2026-09-28,
# before it shipped: an exact-string set intersection (the first
# draft) would have silently matched nothing, ever, on the one real
# page this was built for. See _canonical_youtube_url.
_YOUTUBE_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/)|youtu\.be/)([\w-]{11})",
    re.IGNORECASE,
)

MANUAL_VIDEO_MAP_PATH = os.path.join(os.path.dirname(__file__), "curation", "show_notes_videos.txt")


def _first_timestamp_seconds(text):
    """First "MM:SS" or "H:MM:SS" found in text, as a plain integer
    seconds count, or None if there isn't one. A show-notes page's own
    timestamped bullets are consistently written this way (confirmed
    across every show-notes-*.md file that uses them) -- this is a
    locate-the-nearest-real-chunk heuristic, not shown to the user
    directly, so an occasional false match (some other number that
    happens to look like MM:SS) just means a chunk links to a
    slightly-off point in the same episode/video, never a wrong
    episode or broken link."""
    m = _TIMESTAMP_RE.search(text or "")
    if not m:
        return None
    hh_or_mm, mm_or_ss, ss = m.groups()
    if ss is not None:
        return int(hh_or_mm) * 3600 + int(mm_or_ss) * 60 + int(ss)
    return int(hh_or_mm) * 60 + int(mm_or_ss)


def _youtube_video_id(url):
    """The bare 11-char video ID out of any recognizable YouTube URL
    shape, or None if `url` isn't one. See _YOUTUBE_VIDEO_ID_RE."""
    m = _YOUTUBE_VIDEO_ID_RE.search(url or "")
    return m.group(1) if m else None


def _canonical_youtube_url(url):
    """Normalize any YouTube video URL to the exact
    https://www.youtube.com/watch?v=<id> form youtube_transcribe.py's
    own _video_url canonicalizes every known_video_urls source_id to
    -- so a youtu.be short link (confirmed real on
    show-notes-pedi-video.md) matches by video identity, not exact
    string. Returns None for anything that isn't a YouTube video
    link."""
    video_id = _youtube_video_id(url)
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else None


def find_mentioned_video_urls(html, base_url, known_video_urls):
    """Which of `known_video_urls` (source_ids already indexed under
    source_type='youtube_transcript' -- i.e. one of Ryan's OWN videos,
    already confirmed real by having been transcribed) are linked
    anywhere on this page's raw HTML. Added 2026-09-28.

    Deliberately checked against known_video_urls rather than matching
    ANY youtube.com/youtu.be link: confirmed real on
    show-notes-pedi-video.md, which links its own video AND a totally
    unrelated third-party reference ("EmCrit #253 Kovacs Kata on
    YouTube") -- a bare youtube.com regex match can't tell those apart,
    and picking "the first one found" over an unordered set of hrefs
    would be a coin flip between the real video and a random citation.
    Restricting to already-indexed videos of Ryan's own makes a false
    match require linking to a DIFFERENT one of his own videos, a much
    narrower failure mode -- and correctly returns nothing (not a
    wrong guess) for a video that hasn't been transcribed yet, same
    "target isn't there yet" grace as _link_media_to_transcripts.

    Confirmed real that show-notes-pedi-video.md links its video
    inline mid-sentence ("found on the YouTubes or via this link") as
    a youtu.be SHORT link -- not the https://www.youtube.com/watch?v=
    form known_video_urls' source_ids are in, and not a list item or
    link-only heading either, so this needs both the whole-page scan
    (same as find_mentioned_audio_urls, not extract.py's block-level
    detection) AND URL canonicalization (_canonical_youtube_url) before
    comparing, or a youtu.be link would never match at all -- caught
    during end-to-end verification, 2026-09-28. Returns a (possibly
    empty) set -- callers should only trust a single unambiguous
    match; more than one means the page links to several of Ryan's own
    videos and there's no reliable way to tell which is the page's own
    subject, so the caller should leave it to the manual curation file
    instead of guessing."""
    if not known_video_urls:
        return set()
    canonical_hrefs = {_canonical_youtube_url(href) for href in crawl.find_hrefs(html, base_url)}
    canonical_hrefs.discard(None)
    return canonical_hrefs & known_video_urls


def find_mentioned_audio_urls(html, base_url, audio_urls):
    """Which of `audio_urls` (curation/audio_sources.txt's own URLs)
    are linked anywhere on this one page's raw HTML. Added 2026-09-28
    for the same reason as find_self_video_link: confirmed real that
    all four current audio_sources.txt entries are each their own
    standalone single-link paragraph in "Reflecting on the Air Medical
    New Hire Process" -- not a list or a link-only heading, so this
    needs the same whole-page scan, not extract.py's block-level
    detection. Returns a (possibly empty) set, never None, so callers
    can always do `mapping.update(...)`-style merging without a None
    check."""
    if not audio_urls:
        return set()
    return crawl.find_hrefs(html, base_url) & audio_urls


def _load_manual_video_map(path=None):
    """SHOW_NOTES_URL | VIDEO_URL, one per line -- see module docstring.
    Malformed/blank/comment lines are skipped rather than raising, same
    tolerance as curation.py's own loaders, so one bad edit doesn't take
    the whole build down."""
    path = path or MANUAL_VIDEO_MAP_PATH
    mapping = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "|" not in line:
                    continue
                page_url, video_url = (p.strip() for p in line.split("|", 1))
                if page_url and video_url:
                    mapping[page_url] = video_url
    except FileNotFoundError:
        pass
    return mapping


def _link_media_to_transcripts(conn, mapping, target_source_type):
    """Shared core for both the podcast and YouTube passes. mapping is
    {show_notes_url: target_source_id}, all pointing at the same
    target_source_type ('podcast_transcript' or 'youtube_transcript').
    Returns the number of chunks whose links_to got set (or updated)
    this run."""
    if not mapping:
        return 0

    cur = conn.cursor()
    updated = 0
    for shownotes_url, target_source_id in mapping.items():
        notes_rows = cur.execute(
            "SELECT id, text FROM chunks WHERE source_type = 'webpage' AND source_id = ?",
            (shownotes_url,),
        ).fetchall()
        if not notes_rows:
            continue  # this show-notes page isn't indexed (yet) -- nothing to link

        transcript_rows = cur.execute(
            "SELECT locator, locator_url FROM chunks WHERE source_type = ? AND source_id = ?",
            (target_source_type, target_source_id),
        ).fetchall()
        transcript_points = []
        for locator, locator_url in transcript_rows:
            secs = _first_timestamp_seconds(locator)
            if secs is not None and locator_url:
                transcript_points.append((secs, locator_url))
        if not transcript_points:
            continue  # target isn't transcribed yet -- nothing real to link to

        for chunk_id, text in notes_rows:
            notes_secs = _first_timestamp_seconds(text)
            if notes_secs is not None:
                links_to = min(transcript_points, key=lambda p: abs(p[0] - notes_secs))[1]
            else:
                # No timestamp of its own (a categorized reference-list
                # page, not a "MM:SS" index) -- still defer to the real
                # media, just without a specific moment: resolves to
                # the target's first chunk (_resolve_citation_targets'
                # by_source path).
                links_to = target_source_id
            cur.execute("UPDATE chunks SET links_to = ? WHERE id = ?", (links_to, chunk_id))
            updated += 1

    conn.commit()
    return updated


def link_show_notes_to_episodes(conn):
    """Podcast half: RSS feed -> show-notes URL -> episode audio_url.
    Returns the number of chunks updated."""
    episodes = podcast_ingest.fetch_episodes()
    mapping = {}
    for ep in episodes:
        shownotes_url = podcast_ingest._find_shownotes_link(ep.get("description_html") or "")
        if shownotes_url and ep.get("audio_url"):
            mapping[shownotes_url] = ep["audio_url"]
    return _link_media_to_transcripts(conn, mapping, "podcast_transcript")


def link_show_notes_to_videos(conn, auto_detected=None):
    """YouTube half: {show_notes_url: video_url}, built from two
    sources -- auto_detected (build_index.py's own whole-page scan via
    find_self_video_link, see its docstring) is the base, and
    curation/show_notes_videos.txt is layered on top, overriding any
    page it also covers (same manual-beats-auto-detected precedence as
    curation.resolve_defer/defer_to.txt). Most of today's real pages
    (Oxygen Haterz, Perfusion Index, all three SFCEBM tutoring pages)
    don't link their own video anywhere on the page at all, so the
    manual file is still doing real work here, not just acting as a
    safety net -- auto-detection only helps the pages that DO embed a
    self-link, like show-notes-pedi-video.md. Returns the number of
    chunks updated."""
    mapping = {**(auto_detected or {}), **_load_manual_video_map()}
    return _link_media_to_transcripts(conn, mapping, "youtube_transcript")
