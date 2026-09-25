"""
Saves human-readable transcript files (.txt and .srt) for every podcast
episode and YouTube video, alongside (but independent of) what actually
gets embedded into the search index. Built straight from the ORIGINAL
per-segment transcript -- never chunker.py/transcript_chunking.py's
overlapping word-windows, which are shaped for embedding, not reading,
and would repeat ~40 words of every window in the next one.

Ryan, 2026-09-25: "let's save the .txt and .srt files... at least save
that data while we are re-running the whole thing" -- wants this data
saved without committing yet to how it'll be used (candidates raised:
pasting YouTube chapter timestamps into a video description, a
Podcasting 2.0 <podcast:chapters> JSON feed, show notes, etc.). This
module only produces the raw material; nothing here decides or builds
any of those uses.

Written fresh every time an episode/video is (re)transcribed -- same
"reflects the most recent transcription" guarantee as the search index
itself, since both are produced from the same transcribe() call in the
same run.
"""
import os
import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(title):
    """"Perfusion Index Video" -> "perfusion-index-video". A title with
    no alphanumeric characters at all (never happens in practice, but a
    filename can't be empty) falls back to "untitled"."""
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    return slug or "untitled"


def _srt_timestamp(seconds):
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _as_srt(segments):
    lines = []
    for i, (start, end, text) in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _as_txt(segments, paragraph_gap_seconds=2.0):
    """Joins segment text into readable prose -- a blank line wherever
    there's a real pause (more than paragraph_gap_seconds between one
    segment's end and the next one's start), a single space otherwise.
    Reads like natural paragraphs instead of either one giant run-on
    block or one line per Whisper segment (which can be as short as a
    few words)."""
    parts = []
    prev_end = None
    for start, end, text in segments:
        if prev_end is not None and start - prev_end > paragraph_gap_seconds:
            parts.append("\n\n")
        elif parts:
            parts.append(" ")
        parts.append(text)
        prev_end = end
    return "".join(parts).strip() + "\n"


def save_transcript_files(segments, title, out_dir):
    """Writes <out_dir>/<slug(title)>.txt and .srt, overwriting any
    previous version for this title. out_dir is created if it doesn't
    exist yet. Returns (txt_path, srt_path)."""
    os.makedirs(out_dir, exist_ok=True)
    base = slugify(title)
    txt_path = os.path.join(out_dir, f"{base}.txt")
    srt_path = os.path.join(out_dir, f"{base}.srt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(_as_txt(segments))
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(_as_srt(segments))
    return txt_path, srt_path
