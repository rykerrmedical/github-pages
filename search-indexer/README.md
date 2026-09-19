# Rykerr Medical site indexer

Builds a local search index of rykerrmedical.com by crawling every page,
extracting the main text, splitting it into chunks, and embedding those
chunks with a small local AI model — no API keys, no per-run cost.

In production this runs automatically via GitHub Actions — every time
you publish (push to the site repo), and once a day as a backstop —
rather than depending on your Mac being on and you remembering to run
it. See `../DEPLOY.md` for that full pipeline. This folder is still the
right place to run things manually while developing or debugging
(`python build_index.py`, then `python query_test.py "..."` to sanity
check results) before trusting the automated version.

## One-time setup

```bash
cd rykerr-search/indexer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The first run downloads the embedding model (`BAAI/bge-small-en-v1.5`,
~130MB) from Hugging Face and caches it locally — only happens once.

## Running it

```bash
source venv/bin/activate
python build_index.py
```

This is incremental by default: every page and PDF is checked, but only
re-chunked and re-embedded if its content actually changed since the
last run — unchanged sources are skipped entirely (for a PDF, skipped
before even downloading it, via a cheap HEAD-request check). Anything
removed from the site, or newly added to `curation/excluded_urls.txt`,
gets pruned from the index automatically. A page/PDF that hasn't
changed costs essentially nothing to check, so this stays fast and
light even as the amount of content grows.

When it finishes you'll get a console summary like:

```
Done in 0.6 min
  Pages: 187 seen, 4 changed/new, 183 unchanged (skipped)
  PDFs:  3 seen, 0 changed/new, 3 unchanged (skipped)
  4 source(s) actually re-indexed this run, 0 removed
Index written to: rykerr_index.db
```

**Forcing a full rebuild:** `python build_index.py --full` wipes
everything and starts clean. You shouldn't normally need this — it
happens automatically if you change `EMBEDDING_MODEL_NAME` in
`config.py`, since embeddings from two different models aren't
comparable and silently mixing them would quietly degrade search
quality. Reach for `--full` yourself only if you suspect the index has
drifted from reality somehow and want to be certain.

## Checking the result before trusting it

```bash
python query_test.py "how do I set PEEP for ARDS transport"
```

This searches the index directly (no LLM involved yet — just "which
chunks are most relevant") and prints the top 5 matches with their
source URLs. Skim a few real questions you'd expect people to ask and
confirm the right pages come back. This is the same retrieval logic the
VPS query service will use, so if it looks right here, it'll look right
live.

## Running automatically (production)

This is handled by GitHub Actions, not your Mac — see `../DEPLOY.md` for
the full setup (workflow file, VPS deploy key, secrets). Short version:
the workflow checks out this folder, runs `build_index.py` on GitHub's
own servers (real internet access, no sandbox restrictions), and `scp`s
the resulting `rykerr_index.db` straight to the VPS. It fires on every
push to your site's main branch and once a day on a schedule as a
backstop, so the index reflects new content within minutes of
publishing rather than waiting on a fixed nightly window — and nothing
depends on your laptop being powered on.

## Keeping old drafts out of search

PDFs (and any other page) linked from the site get crawled and indexed
automatically — including old versions you've superseded but haven't
taken down (an earlier draft of the vent book, say). To keep one of
those out of search results entirely, add its URL to
`curation/excluded_urls.txt` (one per line — see that file for the
exact format, including wildcard prefixes for excluding a whole
folder). It's picked up fresh on the next rebuild, no code changes
needed. This is a hard exclude, not a "prefer the newer one" ranking —
an excluded URL is never crawled, chunked, or searchable, so there's no
chance of the old version getting cited by accident, even though the
page itself is still live and linked on the site.

## Blog post tags

Blog post tags come straight from each post's `tags:` front matter (the
same YAML block Jekyll itself reads) — not from guessing at HTML. This
is confirmed against a real post, not assumed. It works like this:

1. `frontmatter_tags.py` walks the site repo (from `config.POSTS_REPO_ROOT`,
   default `.` — the repo root, since the indexer runs from inside the
   site's own checkout in CI) looking for any `.md` file named
   `YYYY-MM-DD-slug.md`, which is the filename Jekyll itself requires for
   a post — wherever it lives, so nothing needs to know or guess your
   `_posts` folder path.
2. It reads that file's `tags:` front matter directly.
3. It matches that post back to the URL the crawler actually fetched, by
   checking whether the file's slug shows up as a path segment in the
   URL (works regardless of your permalink format), falling back to a
   normalized title match if not.

If a crawled page can't be matched to a post source file this way (a
non-post page, or an unusual permalink), tag extraction falls back to
`tags.py`'s best-effort HTML guessing, which may find nothing — that's
expected and fine, it just means that page goes in untagged. The build
summary breaks out how many changed/new pages got tags from front
matter vs. from HTML guessing, so you can see at a glance whether the
front-matter path is actually doing the work (it should be, for every
real post).

Podcast episode tags (categories) don't need any of this — they're
already available cleanly in `episodes.json` / the RSS feed's
`<category>` elements once the podcast ingestion pipeline is built, no
HTML scraping involved there either.

## Notes on scope

- Only rykerrmedical.com is crawled. references.rykerrmedical.com is
  deliberately excluded (see comment in `config.py`) since it's just
  citation pages linked from the main content — indexing it would
  mostly duplicate what's already captured.
- PDFs linked from any indexed page (your book, your med reference
  guide, etc.) are discovered and ingested automatically, page by page
  — see `pdf_ingest.py`. Scanned/image-only PDFs aren't handled (that
  needs OCR); a warning prints during the build if a PDF looks like it
  might be one.
- Podcast transcripts and YouTube are out of scope for this pass —
  next up once the website + PDF version is confirmed working well.
  Instagram is deferred indefinitely (no reliable automated way to pull
  post content without Meta's restricted Business API).
- If a URL discovery run finds 0 pages, it's almost always because
  `sitemap.xml` isn't reachable or doesn't exist and the fallback link
  crawl also came up empty — check that `https://rykerrmedical.com/sitemap.xml`
  loads in a browser, and check `config.SKIP_PATH_CONTAINS` isn't
  accidentally filtering out everything.
