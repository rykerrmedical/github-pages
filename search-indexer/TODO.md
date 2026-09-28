# Rykerr AI Search — TODO / Backlog

Running list of known-good-enough-for-now shortcuts we want to eventually
replace with the real thing. Add to this as new ones come up.

## Search indexer

Nothing outstanding right now (2026-09-28). Both known manual-shortcut
items -- show-notes-page -> YouTube-video pairing, and
audio_sources.txt's "mentioned on" field -- are now auto-detected by a
whole-page link scan in index_webpages (crawl.find_hrefs +
link_show_notes.find_mentioned_video_urls / find_mentioned_audio_urls),
with the existing manual curation files (curation/show_notes_videos.txt,
audio_sources.txt's 3rd field) kept as an override/fallback for what
auto-detection can't reach -- most show-notes pages (Oxygen Haterz,
Perfusion Index, all three SFCEBM tutoring pages) still don't link
their own video anywhere on the page, so those manual entries stay
load-bearing, not just a safety net.
