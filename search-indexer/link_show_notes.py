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
    auto-detect these from, and confirmed against the real page files,
    only one of the six YouTube-notes pages (show-notes-pedi-video.md)
    even links its own video anywhere in its body -- the rest (Oxygen
    Haterz, Perfusion Index, all three SFCEBM tutoring pages) don't
    mention it at all, so there's nothing reliable on the page to
    detect from either way. Manual mapping in
    curation/show_notes_videos.txt instead, same "fallback for what
    can't be auto-detected" spirit as curation.py's own defer_to.txt.

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

import podcast_ingest

_TIMESTAMP_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")

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


def link_show_notes_to_videos(conn):
    """YouTube half: curation/show_notes_videos.txt -> video URL. See
    module docstring for why this can't be auto-detected the way the
    podcast half is. Returns the number of chunks updated."""
    mapping = _load_manual_video_map()
    return _link_media_to_transcripts(conn, mapping, "youtube_transcript")
