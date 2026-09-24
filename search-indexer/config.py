"""
Configuration for the Rykerr Medical site indexer.

Edit the values below to fit your setup. Nothing here needs an API key —
everything runs locally.
"""

# Sites to crawl. Each entry is a base URL; the crawler will try
# <base>/sitemap.xml first and fall back to a same-domain link crawl.
#
# references.rykerrmedical.com is deliberately left out: those pages are
# just citation/source pointers linked from the main content (and from
# documents), so indexing them would mostly duplicate what's already
# captured via the main site's pages. Add it back here if that changes.
SITES = [
    "https://rykerrmedical.com",
]

# URL path fragments to skip (feeds, assets, tag/category index pages, etc.)
# Matched as a simple substring test against the URL path.
SKIP_PATH_CONTAINS = [
    "/assets/",
    "/feed.xml",
    "/blog-feed.xml",
    "/tag/",
    "/tags/",
    "/category/",
    "/categories/",
    "/page/",  # paginator pages, e.g. /page/2/
    "/search/",
]

# File extensions to skip outright (non-HTML content the crawler can't read
# as a page — PDFs embedded via Google Docs Viewer are handled in a later
# phase, not this one).
SKIP_EXTENSIONS = [
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico",
    ".css", ".js", ".xml", ".json", ".zip", ".mp3", ".mp4", ".woff", ".woff2",
]

# Politeness delay between requests, in seconds. Keep this reasonable —
# this crawler is going to run against your own site, but there's no need
# to hammer it.
REQUEST_DELAY_SECONDS = 0.5

# Safety cap so a crawl gone wrong (e.g. sitemap missing, infinite link
# loop) can't run forever. Raise this once you've confirmed real page
# counts for your sites.
MAX_PAGES_PER_SITE = 2000

# HTTP User-Agent sent with every request. Identifies the bot as yours.
USER_AGENT = "RykerrMedicalIndexer/0.1 (+https://rykerrmedical.com; contact: ryan@rykerrmedical.com)"

REQUEST_TIMEOUT_SECONDS = 20

# --- Chunking ---
# Target chunk size and overlap, in words (word-based rather than
# token-based to avoid pulling in a tokenizer dependency just for this).
CHUNK_SIZE_WORDS = 220
CHUNK_OVERLAP_WORDS = 40
MIN_CHUNK_WORDS = 30  # drop tiny leftover chunks (e.g. a lone heading)

# --- PDF ingestion ---
# PDFs linked from pages in SITES are discovered automatically while
# crawling (no need to list them separately) and ingested page-by-page,
# so citations can point at a specific page rather than just the whole
# document.
PDF_MAX_BYTES = 150 * 1024 * 1024  # safety cap on how large a linked PDF we'll fetch

# If a page's extracted text falls below this many characters even after
# OCR (see PDF_ENABLE_OCR below), it's skipped with a warning rather than
# indexed as empty.
PDF_MIN_CHARS_PER_PAGE = 40

# Run Tesseract OCR on any page that contains an embedded image, folding
# recognized text in alongside the page's normal text layer. Confirmed
# real need: a "choosing initial vent settings" section exists only as a
# graphic/infographic in the vent book, invisible to plain text extraction
# no matter how good chunking or ranking is. Only costs time on pages that
# actually have images (most pages don't), and only at index-build time —
# never during a query, so it doesn't touch the VPS or per-search cost at
# all. Requires Tesseract installed wherever build_index.py runs (`brew
# install tesseract` on macOS, `apt install tesseract-ocr` on Linux/CI) —
# if it's missing, extraction just falls back to plain text and prints a
# warning rather than failing the build.
PDF_ENABLE_OCR = True

# --- Embedding model ---
# BAAI/bge-small-en-v1.5: small (~130MB), strong retrieval quality for its
# size, runs comfortably on CPU. Swap for another sentence-transformers
# model name if you prefer.
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# bge models are trained to expect this instruction prefix on QUERIES
# (not on the documents being indexed). The VPS query service must use
# the same prefix when embedding a user's search — see query_test.py.
QUERY_INSTRUCTION_PREFIX = "Represent this sentence for searching relevant passages: "

# --- Reranking ---
# Cosine similarity over independently-embedded query/chunk vectors (a
# bi-encoder) is fast enough to rank the whole index, but it's not very
# good at telling "this chunk specifically answers the question" apart
# from "this chunk is generally about the same topic". Confirmed on a
# real query: once a PDF-extraction bug was fixed and the vent book's
# real ~583 chunks were properly indexed, the one chunk that actually
# explains PEEP ranked ~35th out of 1516 by cosine similarity alone,
# buried under many other vent-related passages that just share
# vocabulary (ventilator, PEEP, ARDS, transport) without answering the
# question. A cross-encoder scores the query and a chunk TOGETHER
# (much more accurate, but too slow to run over the whole index), so the
# fix is two-stage: use cheap cosine similarity to pull a wide candidate
# pool, then rerank just that pool with the cross-encoder and keep the
# real top_k from there. See reranker.py.
ENABLE_RERANKING = True
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"  # ~90MB, fast enough on CPU for a candidate pool this size
# Comfortably wider than the rank-35 case above, so the true answer has
# real margin to still be IN the pool the cross-encoder gets to see —
# a reranker can't rescue a chunk that never made it into the pool.
RERANK_CANDIDATE_POOL = 75

# --- Answer-priority tiers ---
# Mirrors server/config.py's tier settings (query_test.py duplicates the
# real /api/search retrieval logic locally so results can be eyeballed
# before touching the VPS — see query_test.py's search()). Keep these two
# copies in sync by hand, same as EMBEDDING_MODEL_NAME/RERANKER_MODEL_NAME
# above. See server/config.py for the real-data calibration behind
# TIER1_GOOD_ENOUGH_SCORE.
TIER1_SOURCE_TYPES = {"webpage", "pdf", "podcast", "podcast_transcript", "youtube_transcript"}
TIER2_SOURCE_TYPES = {"citation"}
TIER1_GOOD_ENOUGH_SCORE = 2.0
TIER2_BOOST_SCORE = 4.0
TIER2_BOOST_MAX = 2

# --- Blog tags (front matter) ---
# Where to look for Jekyll post source files (named YYYY-MM-DD-slug.md,
# per Jekyll's own required convention) to read their `tags:` front
# matter directly, instead of guessing at how tags render into HTML.
# ".." because both the README's local instructions ("cd rykerr-search/
# indexer" / "cd .../search-indexer") and the GitHub Actions workflow
# (working-directory: search-indexer) always run build_index.py from
# INSIDE the indexer's own folder, one level below the site repo root
# where _posts/ actually lives — confirmed against a real run, which
# came back with 0 tagged pages until this was fixed. If you ever move
# the indexer to a different depth relative to the site repo root,
# update this to match.
POSTS_REPO_ROOT = ".."

# --- Cited references ---
# Where the rykerr-references repo is checked out (the site behind
# references.rykerrmedical.com - one markdown file per citation, e.g. the
# real "484 Yartsev, 2023d" footnote in the vent book resolves to
# references/vent-book-v2/Yartsev2023_Ketamine.md there). It's a sibling
# of this site's own repo checkout on disk
# (~/rykerrmedical/rykerr-references next to ~/rykerrmedical/github-pages),
# so from search-indexer/ that's two levels up and over. See
# reference_citations.py for how this gets read - it's parsed directly
# rather than crawled, since that repo has no sitemap and its citation
# pages aren't cross-linked to each other for a crawl to find.
#
# If this path doesn't exist (e.g. it isn't checked out yet wherever
# build_index.py is running), citation PDFs are just skipped with a
# warning rather than failing the build - update this to match your
# actual layout if it ever changes, same as POSTS_REPO_ROOT above.
REFERENCES_REPO_ROOT = "../../rykerr-references"

# --- Podcast episodes ---
# The real RSS feed powering the podcast, fetched fresh by
# podcast_ingest.py -- deliberately NOT podcast/episodes.json, which is
# only a build-time snapshot for the client-side podcast page (see
# podcast/build_episodes.sh) with no guarantee it's freshly regenerated
# whenever this indexer runs.
PODCAST_FEED_URL = "https://rykerrmedical.github.io/landing/feed.xml"

# --- Podcast transcription (Whisper) ---
# Fully local, fully automatic -- runs as part of the normal overnight
# build_index.py run (see podcast_transcribe.py), no manual export or
# per-episode action needed (Ryan: "avoid manually having to do stuff
# with each new one that goes out"). Real, non-trivial CPU time though
# -- this is why it belongs in the overnight run, not a quick iteration
# loop. Set to False to skip transcription entirely on a given run
# without removing the module (e.g. a night you need your Mac free).
PODCAST_TRANSCRIBE_ENABLED = True

# Standard openai-whisper (Ryan: "normal whisper is fine" -- not a
# specialized/"lite" reimplementation). ".en" variants are English-only
# and faster/slightly more accurate than the multilingual model of the
# same size -- appropriate here since the podcast is English. "small.en"
# is a reasonable starting point for clinical jargon-heavy speech; bump
# to "medium.en" (notably slower) if small's transcription of drug/
# procedure names isn't accurate enough in practice -- there's no way to
# calibrate this without listening to real output, so treat it as a
# starting point, not a measured choice. Requires a system ffmpeg install
# (`brew install ffmpeg` on macOS) -- openai-whisper shells out to it for
# audio decoding.
WHISPER_MODEL_NAME = "small.en"

# Folded into every transcript's content_signal (see
# podcast_transcribe._versioned) so bumping this -- or WHISPER_MODEL_NAME
# above -- forces every episode to be re-transcribed once on the next
# run, without a full index wipe. Same idea as pdf_ingest.
# PDF_PIPELINE_VERSION.
WHISPER_PIPELINE_VERSION = 1

# Safety cap on how large an episode's audio file will be downloaded --
# mirrors PDF_MAX_BYTES above. Generous headroom over any real episode
# length at typical podcast bitrates.
AUDIO_MAX_BYTES = 500 * 1024 * 1024

# --- Output ---
OUTPUT_DB_PATH = "rykerr_index.db"

# --- YouTube video transcription ---
# Mirrors podcast_transcribe.py's automatic pattern, extended to the
# YouTube channel (Ryan, 2026-09-24: "let's do [youtube]... set it up
# and I can run tonight" -- same "avoid manually having to do stuff
# with each new one that goes out" goal as the podcasts). Captions-first
# (see youtube_transcribe.py) -- only falls back to local Whisper
# transcription for a video with no caption track at all, so most of
# the 16 videos should be fast/free and only the caption-less ones cost
# real CPU time.
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@rykerrmedical"
YOUTUBE_TRANSCRIBE_ENABLED = True
YOUTUBE_WHISPER_FALLBACK_ENABLED = True

# Folded into every video's content_signal (see youtube_transcribe.
# _content_signal) so bumping this forces every video to be
# rechecked once on the next run, without a full index wipe. Same idea
# as WHISPER_PIPELINE_VERSION / PDF_PIPELINE_VERSION.
YOUTUBE_PIPELINE_VERSION = 1
