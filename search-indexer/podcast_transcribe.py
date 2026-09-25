"""
Transcribes podcast episodes locally with openai-whisper and indexes the
result as a new tier-1 source_type='podcast_transcript' -- separate from
podcast_ingest.py's lightweight 'podcast' metadata chunk (title,
categories, description), which stays indexed independently under its
own source_id (the episode's archive.org DETAILS page). This module's
chunks are keyed on the episode's AUDIO FILE url instead, so the two
never collide or overwrite each other, and both stay independently
searchable -- the metadata chunk still matches on things like a guest's
name that might not get said verbatim in the episode itself, while these
chunks match on what was actually said, with a real deep link to the
moment it was said.

Fully unattended, by design (Ryan: "avoid manually having to do stuff
with each new one that goes out"). Every run re-fetches the episode list
(podcast_ingest.fetch_episodes) and transcribes whatever's new, same
"skip if a stored signal already matches" incremental pattern as every
other source type here (see _versioned / index_podcast_transcripts). The
one genuinely manual part is running build_index.py at all -- meant to
happen overnight (see build_index.py's own docstring), since
transcribing a real episode is real CPU time, and that cost only grows
as more episodes get published.

Uses the standard `openai-whisper` package (see requirements.txt) --
Ryan's own call: "normal whisper is fine," not a specialized/"lite"
reimplementation, so this deliberately doesn't reach for faster-whisper
or any other variant. Needs a system ffmpeg install (`brew install
ffmpeg` on macOS) -- openai-whisper shells out to it for audio decoding.
First real use downloads its model file to a local cache
(~/.cache/whisper by default); after that it's fully offline.
"""
import hashlib
import os
import tempfile
import time

import requests

import config
import embedder
import podcast_ingest
import store
import transcript_chunking

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": config.USER_AGENT})

_model = None


def _get_model():
    global _model
    if _model is None:
        import whisper
        print(f"  loading Whisper model {config.WHISPER_MODEL_NAME} -- first run downloads it...")
        _model = whisper.load_model(config.WHISPER_MODEL_NAME)
    return _model


def _get_remote_signal(audio_url):
    """Same idea as pdf_ingest.get_remote_signal, just for an episode's
    audio file -- a cheap HEAD request's ETag/Last-Modified/Content-
    Length, so an unchanged episode never gets re-downloaded, let alone
    re-transcribed (transcription is the expensive part here, well
    beyond a PDF's OCR -- worth avoiding even more aggressively)."""
    try:
        resp = SESSION.head(audio_url, timeout=config.REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return None
    etag = resp.headers.get("ETag")
    last_modified = resp.headers.get("Last-Modified")
    if etag or last_modified:
        return f"etag:{etag}|modified:{last_modified}"
    content_length = resp.headers.get("Content-Length")
    if content_length:
        return f"len:{content_length}"
    return None


def _versioned(signal):
    """Folds WHISPER_MODEL_NAME + WHISPER_PIPELINE_VERSION into a raw
    signal, so changing either forces exactly one re-transcribe per
    episode on the next run -- same idea as pdf_ingest._versioned /
    PDF_PIPELINE_VERSION."""
    return f"{signal}::wv{config.WHISPER_PIPELINE_VERSION}::{config.WHISPER_MODEL_NAME}"


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(1024 * 1024), b""):
            h.update(piece)
    return h.hexdigest()


def _download_audio(audio_url):
    """Streams the episode's audio to a temp file, retrying once on a
    mid-download failure -- same resilience pattern as pdf_ingest.
    download_pdf. Returns the temp file path (caller deletes it), or
    None on failure or over config.AUDIO_MAX_BYTES."""
    for attempt in range(2):
        path = None
        try:
            resp = SESSION.get(audio_url, timeout=config.REQUEST_TIMEOUT_SECONDS, stream=True)
            resp.raise_for_status()
            fd, path = tempfile.mkstemp(suffix=".mp3")
            total = 0
            with os.fdopen(fd, "wb") as f:
                for piece in resp.iter_content(chunk_size=1024 * 256):
                    total += len(piece)
                    if total > config.AUDIO_MAX_BYTES:
                        print(f"  ! {audio_url} exceeds AUDIO_MAX_BYTES, skipping")
                        os.unlink(path)
                        return None
                    f.write(piece)
            return path
        except Exception as e:
            if path and os.path.exists(path):
                os.unlink(path)
            if attempt == 0:
                print(f"  ! audio download hiccup for {audio_url}, retrying once: {e}")
                time.sleep(2)
                continue
            print(f"  ! could not download {audio_url}, skipping: {e}")
            return None


def _transcribe(audio_path):
    """Returns [(start_seconds, end_seconds, text), ...] in order, text
    already stripped, empty segments dropped. fp16=False since this runs
    on CPU (openai-whisper defaults to fp16, which only helps on a GPU
    and prints a noisy warning + silently falls back on CPU anyway --
    setting it explicitly just skips that)."""
    model = _get_model()
    result = model.transcribe(audio_path, language="en", fp16=False)
    return [
        (seg["start"], seg["end"], seg["text"].strip())
        for seg in result["segments"] if seg["text"].strip()
    ]


def _process_episode(conn, ep, force_substr, stats):
    audio_url = ep["audio_url"]
    forced = force_substr is not None and (
        force_substr in audio_url.lower() or force_substr in ep["title"].lower()
    )

    previous_signal = store.get_source_signal(conn, audio_url)
    remote_signal = _get_remote_signal(audio_url)

    if not forced and remote_signal is not None and _versioned(remote_signal) == previous_signal:
        stats["unchanged"] += 1
        return

    audio_path = _download_audio(audio_url)
    if audio_path is None:
        return  # already logged

    try:
        # No usable HEAD signal -- fall back to hashing the bytes just
        # downloaded. Still avoids the (much more expensive)
        # transcription step when nothing actually changed; it just
        # can't skip the download itself in that case, same tradeoff as
        # pdf_ingest.py's PDF handling.
        content_signal = remote_signal or _hash_file(audio_path)
        if not forced and _versioned(content_signal) == previous_signal:
            stats["unchanged"] += 1
            return

        print(f"  - transcribing {ep['title']!r}...")
        segments = _transcribe(audio_path)
    finally:
        os.unlink(audio_path)

    if not segments:
        print(f"  ! no speech detected in {ep['title']!r}, skipping")
        return

    pieces = transcript_chunking.group_segments(segments, ep["title"])
    if not pieces:
        return

    # Deliberately does NOT set links_to to the episode's show-notes
    # page here, unlike podcast_ingest.py's thin per-episode metadata
    # chunk. That deferral makes sense for a chunk with nothing but a
    # title/description to offer -- the show-notes page is genuinely
    # richer. It does NOT make sense here: this chunk IS the real
    # spoken content, with a precise timestamped deep link into the
    # actual audio. A show-notes page is usually just a bare list of
    # external reference links (confirmed on a real one -- no write-up,
    # just citations), so swapping the citation to it would trade a
    # precise, substantive answer for a thin reference list. Ryan's
    # call (2026-09-24): podcast/video content should cite itself so it
    # shows up as its own distinct result, with the show-notes page
    # (still indexed as an ordinary webpage) only surfacing separately,
    # ranked on its own actual relevance -- see retrieval.py's
    # _apply_source_type_tiebreak for the matching ranking-order change.
    embeddings = embedder.embed_documents([p["text"] for p in pieces])
    chunk_rows = [
        {
            "locator": transcript_chunking.format_timestamp(p["start"]),
            "locator_url": f"{audio_url}#t={int(p['start'])}",
            "chunk_index": i,
            "text": p["text"],
            "embedding": vec,
        }
        for i, (p, vec) in enumerate(zip(pieces, embeddings))
    ]
    store.replace_source_chunks(
        conn, "podcast_transcript", audio_url, ep["title"], chunk_rows,
        _versioned(content_signal), tags=ep["categories"],
    )
    conn.commit()
    stats["changed"] += 1
    print(f"  - {ep['title']!r}: {len(pieces)} transcript chunk(s)")


def index_podcast_transcripts(conn, force_substr=None):
    """Mirrors podcast_ingest.index_podcast_episodes' shape. Returns
    (current_source_ids, stats) for build()'s prune step."""
    stats = {"seen": 0, "changed": 0, "unchanged": 0, "failed": 0}
    current_ids = set()

    if not config.PODCAST_TRANSCRIBE_ENABLED:
        print("  podcast transcription disabled (config.PODCAST_TRANSCRIBE_ENABLED = False)")
        return current_ids, stats

    episodes = podcast_ingest.fetch_episodes()
    if not episodes:
        print("  no podcast episodes fetched -- leaving existing transcript rows as-is")
        return current_ids, stats

    for ep in episodes:
        audio_url = ep["audio_url"]
        if not audio_url:
            continue  # no audio to transcribe -- podcast_ingest's metadata chunk still covers this episode
        current_ids.add(audio_url)
        stats["seen"] += 1
        try:
            _process_episode(conn, ep, force_substr, stats)
        except Exception as e:
            stats["failed"] += 1
            print(f"  ! unexpected error transcribing {ep['title']!r}, skipping: {e}")

    return current_ids, stats
