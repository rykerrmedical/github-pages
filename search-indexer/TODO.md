# Rykerr AI Search — TODO / Backlog

Running list of known-good-enough-for-now shortcuts we want to eventually
replace with the real thing. Add to this as new ones come up.

## Search indexer

- **Auto-detect show-notes-page -> YouTube-video pairing.** Right now
  (as of 2026-09-27, `link_show_notes.py` + `curation/show_notes_videos.txt`)
  a new YouTube-notes page needs one line added to
  `curation/show_notes_videos.txt` by hand before it'll defer to its
  video. Podcasts already auto-detect fine, via the RSS feed.
  Auto-detecting the YouTube case the same way needs the RAW page HTML
  (to find a self-referencing youtube.com/youtu.be link like
  show-notes-pedi-video.md has) -- the already-extracted chunk text
  strips hrefs down to anchor wording, so it can't be recovered from
  what's already indexed. Likely needs a small hook in crawl.py itself
  (same shape as podcast_ingest's own show-notes detection), not just
  a post-process pass over the finished DB like link_show_notes.py is
  today. Low priority while there are only ~6 of these pages total.
