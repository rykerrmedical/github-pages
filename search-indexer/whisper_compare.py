"""Compare Whisper setups on a short clip of one podcast episode, so the
model for podcast transcription is chosen from real output on Ryan's own
audio instead of guessed.

Run from this folder, venv active:

    python whisper_compare.py                                  # defaults
    python whisper_compare.py --models small.en:old,medium.en,turbo
    python whisper_compare.py --episode fisher --start 600 --minutes 10

A model name alone = the new setup (medical initial_prompt, no
conditioning on previous text, loop filter). Add ":old" for the previous
setup (plain call, no prompt) -- "small.en:old" is today's baseline.
Candidates: small.en, medium.en, turbo (fast large-class), large-v3
(slowest, ~10 GB RAM -- skip it on a machine with 8 GB).

Writes whisper_compare_out/<variant>.txt (one line per segment, with
timestamps) so you can read/diff them, and prints a table: run time,
count of expected clinical terms found, count of known garbles found.
Nothing is written to the index."""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import time

import config
import podcast_ingest
import podcast_transcribe as pt

GOOD_TERMS = [
    "thoracostomy", "intubat", "ketamine", "rocuronium", "tranexamic", "TXA",
    "needle decompression", "REBOA", "whole blood", "hemorrhag", "resuscitat",
    "cricothyrotomy", "PEEP", "capnography", "POCUS", "etomidate", "fentanyl",
]
BAD_TERMS = ["innovate", "tort cost", "tort-cost", "in the bait", "ketamine's"]


def find_episode(substr):
    eps = podcast_ingest.fetch_episodes()
    hits = [e for e in eps if substr.lower() in e["title"].lower() and e.get("audio_url")]
    if not hits:
        sys.exit(f"no episode title contains {substr!r}")
    return hits[0]


def cut_clip(src, start, minutes):
    out = tempfile.mkstemp(suffix=".wav")[1]
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-t", str(int(minutes * 60)),
         "-i", src, "-ac", "1", "-ar", "16000", out],
        check=True,
    )
    return out


def count(text, terms):
    low = text.lower()
    return {t: len(re.findall(re.escape(t.lower()), low)) for t in terms}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="fisher", help="substring of the episode title")
    ap.add_argument("--start", type=int, default=300, help="clip start, seconds into the episode")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--models", default="small.en:old,small.en,medium.en,turbo")
    args = ap.parse_args()

    ep = find_episode(args.episode)
    print(f"Episode: {ep['title']}")
    audio = pt._download_audio(ep["audio_url"])
    if not audio:
        sys.exit("download failed")
    clip = cut_clip(audio, args.start, args.minutes)
    os.unlink(audio)
    outdir = "whisper_compare_out"
    os.makedirs(outdir, exist_ok=True)

    rows = []
    for variant in args.models.split(","):
        variant = variant.strip()
        legacy = variant.endswith(":old")
        name = variant.replace(":old", "")
        print(f"\n== {variant} ==")
        t0 = time.time()
        try:
            segs = pt._transcribe(clip, model_name=name, legacy=legacy)
        except Exception as e:
            print(f"  failed: {e}")
            rows.append((variant, None, None, None, None))
            continue
        secs = time.time() - t0
        text = " ".join(s[2] for s in segs)
        with open(os.path.join(outdir, variant.replace(":", "_") + ".txt"), "w") as f:
            for st, en, tx in segs:
                f.write(f"[{int(st + args.start) // 60:02d}:{int(st + args.start) % 60:02d}] {tx}\n")
        good = count(text, GOOD_TERMS)
        bad = count(text, BAD_TERMS)
        rows.append((variant, secs, sum(good.values()), sum(bad.values()), len(segs)))
        print(f"  {secs:.0f}s for {args.minutes:g} min of audio "
              f"({secs / (args.minutes * 60):.2f}x real time)")
        print("  clinical terms:", {k: v for k, v in good.items() if v})
        print("  garbles:", {k: v for k, v in bad.items() if v})
    os.unlink(clip)

    print("\nvariant           time(s)  good-terms  garbles  segments")
    for v, secs, g, b, n in rows:
        if secs is None:
            print(f"{v:<17} failed")
        else:
            print(f"{v:<17} {secs:7.0f}  {g:10d}  {b:7d}  {n:8d}")
    print(f"\nRead the files in {outdir}/ -- the term counts are only a rough guide.")
    print("Whole-episode time is roughly (episode minutes / clip minutes) x the time above.")


if __name__ == "__main__":
    main()
