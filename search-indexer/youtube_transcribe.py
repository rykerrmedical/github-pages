"""
Indexes rykerrmedical's YouTube channel as a new tier-1
source_type='youtube_transcript'. Always transcribes locally with the
same openai-whisper setup podcast_transcribe.py uses (see _transcribe
there, reused directly here rather than duplicated) -- deliberately
does NOT use YouTube's own caption tracks, even when a video has them.

That was the original design (captions-first, Whisper only as a
fallback, since captions are free/instant) -- reversed on 2026-09-25
after a real, confirmed failure: YouTube's auto-generated captions for
"Perfusion Index Video" repeatedly mis-heard "perfusion" as "profusion"/
"provision", and since that's the exact term the video is about, the
mis-transcription measurably hurt its own ranking for the query it
should have been the best answer to. Ryan's call, and the more
defensible one anyway: "if we went thru all the work to transcribe with
whisper [for podcasts], why aren't we using that?" -- there's no real
reason to trust YouTube's auto-captions over a model already proven
accurate enough for this same jargon-heavy medical content. This also
drops the manual-vs-auto-caption distinction entirely, since it no
longer matters -- every video gets the same treatment regardless of
what captions YouTube does or doesn't have.

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

Requires yt-dlp (see requirements.txt, for listing the channel and
downloading audio) and a system ffmpeg install -- the same one
podcast_transcribe.py already needs, so nothing new there if podcasts
are already transcribing locally.
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
    reprocess per video on the next run."""
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


def _download_audio_and_transcribe(video_id, video_url, title):
    """Downloads just the audio (yt-dlp's own best-audio format
    selection + ffmpeg extraction, capped at config.AUDIO_MAX_BYTES same
    as podcast episodes) and transcribes it with podcast_transcribe.
    _transcribe -- the exact same openai-whisper call podcasts use,
    reused rather than duplicated so the two stay identical in behavior.
    Returns segments, or None on any download/transcription failure."""
    import yt_dlp

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

    segments = _download_audio_and_transcribe(video_id, video_url, title)
    if not segments:
        stats["failed"] += 1
        print(f"  ! could not transcribe {title!r}, skipping")
        return

    pieces = transcript_chunking.group_segments(segments, title)
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
    print(f"  - {title!r}: {len(pieces)} transcript chunk(s)")


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
