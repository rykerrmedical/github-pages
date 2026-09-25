"""
Shared helpers for turning timed speech segments into deep-linkable
search chunks -- used by both podcast_transcribe.py (Whisper-transcribed
podcast audio) and youtube_transcribe.py (YouTube captions or, lacking
those, Whisper-transcribed video audio). Pulled out of podcast_
transcribe.py once youtube_transcribe.py needed the exact same windowing
logic, rather than risk the two drifting apart under separate copies.

Both callers hand this the same shape regardless of where the timing
came from -- Whisper's per-segment output or a parsed YouTube caption
track: [(start_seconds, end_seconds, text), ...], already trimmed of
empty text.
"""
import config


def format_timestamp(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def group_segments(segments, title):
    """Groups consecutive (start, end, text) segments into ~config.
    CHUNK_SIZE_WORDS-word windows with config.CHUNK_OVERLAP_WORDS words
    of overlap -- the same target size as every other chunk in the
    index (see chunker._word_windows), just windowed over TIMED segments
    instead of plain text, so each resulting chunk keeps a real start
    time to deep-link into the audio/video with, not just its words.
    Segment-level (not word-level) timing means every word inherits its
    own segment's start time -- precise enough for a "jump to roughly
    here" citation link, which is the actual use case.

    title: the episode/video title, led with on EVERY resulting chunk
    (not just the first), same pattern as chunker.chunk_structured_text
    for webpages/PDFs -- see that module's docstring for why this
    matters: a chunk with no idea what episode/video it's from is easy
    to outrank by something that happens to spell a key term correctly
    even once. Confirmed as a real problem, not a hypothetical one: a
    YouTube video titled "Perfusion Index Video" had its auto-generated
    captions mishear "perfusion" as "profusion"/"provision" in several
    places, and with nothing else in the chunk naming the actual topic,
    a webpage that merely mentioned "Perfusion Index" correctly (but
    wasn't really about it) outranked the video's own on-topic content
    for a "perfusion index" query.

    Returns [{"start": float, "text": str}, ...]."""
    words = []
    for start, _end, text in segments:
        for w in text.split():
            words.append((w, start))
    if not words:
        return []

    prefix = f"[{title}]\n\n"
    size = config.CHUNK_SIZE_WORDS
    overlap = config.CHUNK_OVERLAP_WORDS
    step = max(size - overlap, 1)

    pieces = []
    pos = 0
    while pos < len(words):
        window = words[pos : pos + size]
        if len(window) >= config.MIN_CHUNK_WORDS or pos == 0:
            pieces.append({
                "start": window[0][1],
                "text": prefix + " ".join(w for w, _ in window),
            })
        if pos + size >= len(words):
            break
        pos += step
    return pieces
