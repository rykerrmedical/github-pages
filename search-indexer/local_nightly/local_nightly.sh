#!/bin/bash
# Nightly index rebuild on Ryan's Mac (replaces the GitHub nightly cron).
#
# RULE: runs ONLY if the Mac is awake at the scheduled time. launchd runs a
# job that was missed during sleep as soon as the Mac wakes; this script
# detects that (it fires more than WINDOW_MIN minutes after START_HOUR) and
# exits without doing anything. So: laptop on and awake at 1 am -> it runs;
# asleep, closed or off -> that night is skipped, and waking it later in the
# day does nothing.
#
# Steps: pull the live DB -> build_index.py -> build_tier3_index.py (this
# also refreshes WikEM / Deranged Physiology, which block GitHub's IPs) ->
# sanity check -> upload. Podcast/YouTube transcription happens here, with
# the model set in config.py.
#
# Manual test:   bash local_nightly/local_nightly.sh --now --no-upload
# Real run now:  bash local_nightly/local_nightly.sh --now
# Log:           ~/Library/Logs/rykerr-search-nightly.log

START_HOUR=1          # scheduled hour (must match the plist), 24 h clock
WINDOW_MIN=30         # how late a start may be and still count as "on time"
VPS="root@96.30.197.162"
REMOTE_DB="/opt/rykerr-search/rykerr_index.db"
MIN_KEEP_RATIO=85     # abort the upload if the new DB has < this % of the live chunk count

HERE="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$HOME/Library/Logs/rykerr-search-nightly.log"
exec >>"$LOG" 2>&1

NOW_FLAG=0; NO_UPLOAD=0
for a in "$@"; do
  [ "$a" = "--now" ] && NOW_FLAG=1
  [ "$a" = "--no-upload" ] && NO_UPLOAD=1
done

echo "=== $(date '+%Y-%m-%d %H:%M:%S') nightly start (now=$NOW_FLAG no_upload=$NO_UPLOAD)"

notify() { osascript -e "display notification \"$1\" with title \"Rykerr search nightly\"" >/dev/null 2>&1; }
fail() { echo "FAILED: $1"; notify "Failed: $1 (see log)"; exit 1; }

# --- on-time guard ---------------------------------------------------------
if [ $NOW_FLAG -eq 0 ]; then
  now_s=$(( 10#$(date +%H) * 3600 + 10#$(date +%M) * 60 + 10#$(date +%S) ))
  late=$(( now_s - START_HOUR * 3600 ))
  if [ $late -lt 0 ] || [ $late -gt $(( WINDOW_MIN * 60 )) ]; then
    echo "skipped: started $(( late / 60 )) min after ${START_HOUR}:00 (the Mac was asleep or off at the scheduled time); window is ${WINDOW_MIN} min"
    exit 0
  fi
fi

# --- single instance -------------------------------------------------------
LOCK="${TMPDIR:-/tmp}/rykerr-search-nightly.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  # stale if older than 8 h
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +480 2>/dev/null)" ]; then
    rm -rf "$LOCK"; mkdir "$LOCK" || fail "could not take lock"
  else
    echo "skipped: another run is in progress (lock $LOCK)"; exit 0
  fi
fi
PULLED="${TMPDIR:-/tmp}/rykerr_index_pulled.db"
trap 'rm -rf "$LOCK" "$PULLED"' EXIT

# keep the Mac awake for the length of the run (lid-closed sleep still wins)
caffeinate -i -w $$ &

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$HERE" || fail "cannot cd to $HERE"
[ -f venv/bin/activate ] || fail "no venv in $HERE"
source venv/bin/activate
export TESSDATA_PREFIX="$(brew --prefix tesseract 2>/dev/null)/share/tessdata"

# --- don't collide with a GitHub run (best effort; private repos just skip this) ----
slug="$(git remote get-url origin 2>/dev/null | sed -E 's#.*github\.com[:/]##; s#\.git$##')"
if [ -n "$slug" ]; then
  runs="$(curl -fsS -m 20 "https://api.github.com/repos/$slug/actions/workflows/rebuild-search-index.yml/runs?status=in_progress&per_page=1" 2>/dev/null)"
  if echo "$runs" | grep -Eq '"total_count": *[1-9]'; then
    echo "skipped: a GitHub 'Rebuild search index' run is in progress"; exit 0
  fi
fi

# --- pull live DB ----------------------------------------------------------
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=20"
scp -q $SSH_OPTS "$VPS:$REMOTE_DB" "$PULLED" || fail "could not download the live index (ssh key not available to launchd?)"
cp "$PULLED" rykerr_index.db || fail "could not copy the pulled DB into place"
python - <<'PY' || fail "pulled DB is not a valid sqlite file"
import sqlite3
c = sqlite3.connect("rykerr_index.db")
assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
PY
OLD_CHUNKS="$(python -c "import sqlite3;print(sqlite3.connect('$PULLED').execute('select count(*) from chunks').fetchone()[0])")"
echo "live index: $OLD_CHUNKS chunks"

# --- build -----------------------------------------------------------------
python build_index.py || fail "build_index.py failed"
python build_tier3_index.py || fail "build_tier3_index.py failed"

NEW_CHUNKS="$(python -c "import sqlite3;print(sqlite3.connect('rykerr_index.db').execute('select count(*) from chunks').fetchone()[0])")"
echo "new index: $NEW_CHUNKS chunks"
if [ $(( NEW_CHUNKS * 100 )) -lt $(( OLD_CHUNKS * MIN_KEEP_RATIO )) ]; then
  fail "new index has $NEW_CHUNKS chunks vs $OLD_CHUNKS live (< ${MIN_KEEP_RATIO}%) -- NOT uploaded"
fi
python -c "import sqlite3,sys;sys.exit(0 if sqlite3.connect('rykerr_index.db').execute('PRAGMA quick_check').fetchone()[0]=='ok' else 1)" || fail "new DB failed integrity check -- NOT uploaded"

# --- upload (to a temp name, then rename, so the server never sees a half-copied file) ----
if [ $NO_UPLOAD -eq 1 ]; then
  echo "done (--no-upload): not uploading"; exit 0
fi
scp -q $SSH_OPTS rykerr_index.db "$VPS:$REMOTE_DB.new" || fail "upload failed"
ssh $SSH_OPTS "$VPS" "chown --reference='$REMOTE_DB' '$REMOTE_DB.new' && chmod --reference='$REMOTE_DB' '$REMOTE_DB.new' && mv '$REMOTE_DB.new' '$REMOTE_DB'" || fail "could not move the uploaded DB into place"
echo "uploaded: $NEW_CHUNKS chunks live"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') nightly done"
