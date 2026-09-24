"""
Indexes rykerrmedical's YouTube channel as a new tier-1
source_type='youtube_transcript'. Captions-first, Whisper only as a
fallback -- for each video, tries to pull YouTube's own caption track
(manual captions if the video has them, otherwise YouTube's
auto-generated ones) via yt-dlp, since that's free and near-instant.
Only when a video has NEITHER does this fall back to downloading its
audio and transcribing locally with the same openai-whisper setup
podcast_transcribe.py uses (see _transcribe there, reused directly here
rather than duplicated).

Fully unattended, by design (Ryan: "avoid manually having to do stuff
with each new one that goes out" -- said about podcasts originally, and
explicitly extended to the YouTube channel on 2026-09-24: "let's do
[this]... set it up and I can run tonight"). Every run re-lists the
channel's videos and processes whatever's new, same "skip if a stored
signal already matches" incremental pattern as every other source type
here.

Unlike podcast_transcribe.py, there's no cheap per-item HEAD signal to
check before doing any work (no direct audio URL exposed for a YouTube
video the way an RSS enclosure gives one for a podcast episode) --
change detection here is simply "have we already processed this exact
video_id at the current pipeline version", since a published YouTube
video's own content doesn't change after the fact. See
_content_signal / YOUTUBE_PIPELINE_VERSION.

Deliberately does NOT set links_to on these chunks, same reasoning as
podcast_transcribe.py's real transcript chunks (see its longer note):
this chunk IS the real spoken content, with a precise timestamped deep
link into the actual video -- it should show up as its own result, not
collapse into a show-notes page's citation.

Requires yt-dlp (see requirements.txt) and, only for the Whisper
fallback path, a system ffmpeg install -- the same one podcast_
transcribe.py already needs, so nothing new there if podcasts are
already transcribing locally.
"""
import os
import shutil
import tempfile

import config
import embedder
import podcast_transcribe
import store
import transcript_chunking


def _video_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def _content_signal(video_id):
    """"Have we already processed this video at the current pipeline
    version" -- folds in WHISPER_MODEL_NAME too (same idea as podcast_
    transcribe._versioned) so bumping either forces exactly one
    reprocess per video on the next run. Applies uniformly regardless of
    whether a given video ends up sourced from captions or Whisper --
    slightly wasteful for caption-sourced videos on a pure Whisper-model
    bump (they'll get re-checked for no real reason), but that recheck
    is just a caption re-fetch, not a re-transcribe -- cheap enough that
    keeping one simple signal beats tracking method-specific versions."""
    return f"yt:{video_id}::pv{config.YOUTUBE_PIPELINE_VERSION}::{config.WHISPER_MODEL_NAME}"


def _list_channel_videos():
    """Returns [{"id", "title"}, ...] for every video on config.
    YOUTUBE_CHANNEL_URL, via yt-dlp's flat-playlist mode (metadata only,
    no per-video network calls). Best-effort: a fetch/parse hiccup
    returns [] rather than raising, same as podcast_ingest.
    fetch_episodes -- a skipped listing this run just leaves existing
    youtube_transcript rows exactly as they were, nothing gets deleted
    (build_index.py's prune step only removes what current_source_ids
    says is gone, and an empty list here means "unknown", not "gone" --
    see index_youtube_transcripts below, which returns early before
    current_ids is touched)."""
    import yt_dlp

    channel_url = config.YOUTUBE_CHANNEL_URL.rstrip("/") + "/videos"
    opts = {"extract_flat": True, "quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
    except Exception as e:
        print(f"  ! could not list channel videos ({channel_url}): {e}")
        return []

    entries = info.get("entries") or [] if info else []
    videos = []
    for e in entries:
        if not e:
            continue
        video_id = e.get("id")
        if not video_id:
            continue
        videos.append({"id": video_id, "title": (e.get("title") or "Untitled").strip()})
    return videos


def _parse_json3(path):
    """Parses yt-dlp's json3 caption format (YouTube's own timed-text
    event structure) into [(start_seconds, end_seconds, text), ...].
    Used for both manual and auto-generated captions -- yt-dlp requests
    the same json3 shape from YouTube's timedtext API either way, which
    is far easier to parse correctly than YouTube's auto-caption VTT
    (that format repeats overlapping "karaoke" cue lines that would need
    their own dedup logic; json3's discrete events don't)."""
    import json

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    segments = []
    for event in data.get("events", []):
        start_ms = event.get("tStartMs")
        if start_ms is None:
            continue
        text = "".join(seg.get("utf8", "") for seg in (event.get("segs") or []))
        text = text.replace("\n", " ").strip()
        if not text:
            continue
        dur_ms = event.get("dDurationMs", 0)
        segments.append((start_ms / 1000, (start_ms + dur_ms) / 1000, text))
    return segments


def _fetch_captions(video_id, video_url):
    """Tries to pull an English caption track (manual first, falling
    back to YouTube's auto-generated one -- yt-dlp's own preference
    order when both writesubtitles and writeautomaticsub are set and
    only a manual track exists, or only an auto one does). Returns
    parsed segments, or None if the video has no captions in English at
    all."""
    import yt_dlp

    tmpdir = tempfile.mkdtemp()
    try:
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "json3",
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([video_url])
        except Exception as e:
            print(f"  ! caption fetch failed for {video_id}: {e}")
            return None

        candidates = [f for f in os.listdir(tmpdir) if f.startswith(video_id) and f.endswith(".json3")]
        if not candidates:
            return None
        segments = _parse_json3(os.path.join(tmpdir, candidates[0]))
        return segments or None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _download_audio_and_transcribe(video_id, video_url, title):
    """Whisper fallback for a video with no usable captions: downloads
    just the audio (yt-dlp's own best-audio format selection + ffmpeg
    extraction, capped at config.AUDIO_MAX_BYTES same as podcast
    episodes) and transcribes it with podcast_transcribe._transcribe --
    the exact same openai-whisper call podcasts use, reused rather than
    duplicated so the two stay identical in behavior. Returns segments,
    or None on any download/transcription failure."""
    import yt_dlp

    print(f"  - no captions for {title!r}, falling back to Whisper (downloading audio)...")
    tmpdir = tempfile.mkdtemp()
    try:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "max_filesize": config.AUDIO_MAX_BYTES,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([video_url])
        except Exception as e:
            print(f"  ! audio download failed for {video_id}: {e}")
            return None

        candidates = [f for f in os.listdir(tmpdir) if f.startswith(video_id) and f.endswith(".mp3")]
        if not candidates:
            print(f"  ! no audio file produced for {video_id}, skipping")
            return None

        print(f"  - transcribing {title!r}...")
        return podcast_transcribe._transcribe(os.path.join(tmpdir, candidates[0])) or None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _get_segments(video_id, video_url, title):
    """Returns (segments, method) -- method is "captions" or "whisper",
    for the log line only. (None, None) if neither path produced
    anything usable."""
    segments = _fetch_captions(video_id, video_url)
    if segments:
        return segments, "captions"

    if not config.YOUTUBE_WHISPER_FALLBACK_ENABLED:
        return None, None

    segments = _download_audio_and_transcribe(video_id, video_url, title)
    return (segments, "whisper") if segments else (None, None)


def _process_video(conn, video, force_substr, stats):
    video_id = video["id"]
    title = video["title"]
    video_url = _video_url(video_id)

    forced = force_substr is not None and (
        force_substr in video_id.lower() or force_substr in title.lower()
    )
    signal = _content_signal(video_id)
    if not forced and store.get_source_signal(conn, video_url) == signal:
        stats["unchanged"] += 1
        return

    segments, method = _get_segments(video_id, video_url, title)
    if not segments:
        stats["failed"] += 1
        print(f"  ! could not get captions or transcribe {title!r}, skipping")
        return

    pieces = transcript_chunking.group_segments(segments)
    if not pieces:
        return

    embeddings = embedder.embed_documents([p["text"] for p in pieces])
    chunk_rows = [
        {
            "locator": transcript_chunking.format_timestamp(p["start"]),
            "locator_url": f"{video_url}&t={int(p['start'])}s",
            "chunk_index": i,
            "text": p["text"],
            "embedding": vec,
        }
        for i, (p, vec) in enumerate(zip(pieces, embeddings))
    ]
    store.replace_source_chunks(conn, "youtube_transcript", video_url, title, chunk_rows, signal)
    conn.commit()
    stats["changed"] += 1
    print(f"  - {title!r}: {len(pieces)} transcript chunk(s) (via {method})")


def index_youtube_transcripts(conn, force_substr=None):
    """Mirrors podcast_transcribe.index_podcast_transcripts' shape.
    Returns (current_source_ids, stats) for build()'s prune step."""
    stats = {"seen": 0, "changed": 0, "unchanged": 0, "failed": 0}
    current_ids = set()

    if not config.YOUTUBE_TRANSCRIBE_ENABLED:
        print("  YouTube transcription disabled (config.YOUTUBE_TRANSCRIBE_ENABLED = False)")
        return current_ids, stats

    videos = _list_channel_videos()
    if not videos:
        print("  no YouTube videos found -- leaving existing youtube_transcript rows as-is")
        return current_ids, stats

    for video in videos:
        current_ids.add(_video_url(video["id"]))
        stats["seen"] += 1
        try:
            _process_video(conn, video, force_substr, stats)
        except Exception as e:
            stats["failed"] += 1
            print(f"  ! unexpected error transcribing {video['title']!r}, skipping: {e}")

    return current_ids, stats
