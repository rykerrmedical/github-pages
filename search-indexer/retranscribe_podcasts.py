"""Re-transcribe podcast episodes locally with the current Whisper setup.

Why local: a big Whisper model is far too slow for a GitHub runner (the
nightly job hung 3+ hours on the small model's first full pass). This
script does the transcription on your Mac against a fresh copy of the
live index; you then upload that DB, and only then push any config change.

SAFE ORDER (run from this folder, venv active):
  1. Make sure no "Rebuild search index" run is in progress on GitHub.
  2. Pull the live DB:
       scp root@96.30.197.162:/opt/rykerr-search/rykerr_index.db ./rykerr_index.db
  3. Preview:        python retranscribe_podcasts.py --model medium.en --dry
  4. Run:            python retranscribe_podcasts.py --model medium.en
     (resumable: Ctrl-C any time; re-running skips episodes already done.
      One episode only: --only fisher   Redo even if current: --only fisher --force)
  5. Upload the DB:
       scp ./rykerr_index.db root@96.30.197.162:/opt/rykerr-search/rykerr_index.db
  6. Then set the config (python retranscribe_podcasts.py --model medium.en --write-config
     does it for you) and commit/push, so CI sees matching signals and
     leaves the transcripts alone.

Transcript .txt/.srt files are written to transcripts/podcasts/ as usual.
"""
import argparse
import re
import sys
import time

import config
import hard_exit
import podcast_ingest
import podcast_transcribe as pt
import store

NEW_PIPELINE_VERSION = 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="Whisper model name, e.g. medium.en, turbo, large-v3")
    ap.add_argument("--only", help="only episodes whose title or audio URL contains this text")
    ap.add_argument("--force", action="store_true", help="with --only: redo even if already current")
    ap.add_argument("--dry", action="store_true", help="show what would be transcribed; write nothing")
    ap.add_argument("--write-config", action="store_true",
                    help="after a successful run, set PODCAST_WHISPER_MODEL_NAME and "
                         f"WHISPER_PIPELINE_VERSION={NEW_PIPELINE_VERSION} in config.py")
    args = ap.parse_args()

    # In-memory override: config.py itself is only changed by --write-config
    # (after the DB is uploaded), so a stray commit cannot make CI redo everything.
    config.PODCAST_WHISPER_MODEL_NAME = args.model
    config.WHISPER_PIPELINE_VERSION = NEW_PIPELINE_VERSION

    conn = store.connect()
    episodes = [e for e in podcast_ingest.fetch_episodes() if e.get("audio_url")]
    if args.only:
        episodes = [e for e in episodes
                    if args.only.lower() in e["title"].lower() or args.only.lower() in e["audio_url"].lower()]
    if not episodes:
        sys.exit("no matching episodes")

    if args.dry:
        for e in episodes:
            prev = store.get_source_signal(conn, e["audio_url"])
            remote = pt._get_remote_signal(e["audio_url"])
            current = remote is not None and pt._versioned(remote) == prev
            print(f"  {'up to date ' if current else 'TO DO      '} {e['title']}")
        return

    stats = {"seen": 0, "changed": 0, "unchanged": 0, "failed": 0}
    forced_substr = args.only.lower() if (args.only and args.force) else None
    t_all = time.time()
    for i, e in enumerate(episodes, 1):
        print(f"[{i}/{len(episodes)}] {e['title']}")
        t0 = time.time()
        stats["seen"] += 1
        try:
            pt._process_episode(conn, e, forced_substr, stats)
        except KeyboardInterrupt:
            print("\ninterrupted -- finished episodes are saved; re-run to resume")
            conn.commit()
            sys.exit(1)
        except Exception as ex:
            stats["failed"] += 1
            print(f"  ! failed: {ex}")
        print(f"  ({(time.time() - t0) / 60:.1f} min)")
    conn.commit()
    print(f"\nDone in {(time.time() - t_all) / 60:.0f} min: {stats}")

    if stats["failed"]:
        print("Some episodes failed -- re-run to retry them before uploading.")
        return
    if args.write_config:
        s = open("config.py").read()
        s = re.sub(r'^PODCAST_WHISPER_MODEL_NAME = ".*"$', f'PODCAST_WHISPER_MODEL_NAME = "{args.model}"', s, flags=re.M)
        s = re.sub(r"^WHISPER_PIPELINE_VERSION = \d+$", f"WHISPER_PIPELINE_VERSION = {NEW_PIPELINE_VERSION}", s, flags=re.M)
        open("config.py", "w").write(s)
        print("config.py updated. Upload the DB (step 5) BEFORE committing/pushing.")
    else:
        print("Next: upload the DB (step 5). Then run this again with --write-config: "
              "it finds everything up to date and only edits config.py.")

if __name__ == "__main__":
    hard_exit.install()
    try:
        main()
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
        hard_exit.finish(e.code if isinstance(e.code, int) else (0 if e.code is None else 1))
    hard_exit.finish(0)
