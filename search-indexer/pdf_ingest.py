"""
Discovers and ingests PDFs linked from crawled pages (your book, your med
reference guide, anything else you link as a PDF download). Unlike
webpage text, a PDF is indexed page-by-page, so a citation can point at
"page 42" instead of just the document as a whole.

Content baked into an image (an infographic, a table exported as a
picture, a diagram with the actual numbers in it) is invisible to plain
text extraction — confirmed as a real gap: a "choosing initial settings"
section in the vent book wasn't showing up in search at all because it
lives in a graphic, not in extractable text, no matter how good chunking
or ranking is. Pages that contain an embedded image are run through
Tesseract OCR (see _ocr_available/_page_text below) to pull in whatever
text is drawn inside that image, folded in alongside the page's normal
text layer — see config.PDF_ENABLE_OCR. Pages with too little extractable
text even after that are skipped with a warning rather than silently
indexed as empty.
"""
import glob
import os
import re
import time
import urllib.parse as urlparse
from collections import Counter

import pymupdf  # formerly imported as `fitz` — that alias is now deprecated
from bs4 import BeautifulSoup

import config
from crawl import SESSION, _normalize  # reuse the same session/User-Agent

# Bump this whenever a change in THIS FILE would produce different chunks
# for a PDF that hasn't itself changed on the server — e.g. the OCR
# support and the changelog-page detector added here both change what
# gets extracted from the exact same bytes. build_index.py's incremental
# mode normally skips a PDF whose remote content (ETag/Last-Modified/size)
# hasn't changed, which is the whole point of incremental mode — but that
# same shortcut means a pure extraction-logic fix would otherwise sit
# unapplied to every already-indexed PDF until someone thinks to run
# --full. Folding this version into the stored signal (see
# build_index.py's index_pdfs) makes that automatic instead: bump the
# number, and the next incremental run reprocesses every PDF exactly
# once — no full wipe, no re-crawling pages, no re-touching anything
# that didn't need it — and then goes back to skipping unchanged PDFs
# until the next bump.
PDF_PIPELINE_VERSION = 2

# archive.org serves the same file from several hostnames: the canonical
# archive.org/download/<item>/<file> URL, and per-node mirrors like
# ia601001.us.archive.org/N/items/<item>/<file> or
# dn720707.ca.archive.org/N/items/<item>/<file>. Confirmed against a real
# build: left uncanonicalized, the same PDF gets linked via two different
# mirror URLs from different pages, so it's downloaded, embedded, and
# indexed twice under two different source_ids — wasted work, and the
# same page shows up twice in search results.
#
# /details/<item>/<file> is a third real shape, found while wiring up
# rykerr-references: 8 of its 345 "View PDF on Archive.org" links use
# this form instead of /download/. Confirmed directly (fetched one of
# them) that /details/... is archive.org's HTML item-landing page, not
# the file itself — download_pdf() would have fetched a webpage and
# either failed outright or, worse, silently indexed nothing useful.
# Same tail-preserving rewrite as /items/ fixes it, since archive.org
# serves the identical file at /download/ for the same item/filename tail.
_ARCHIVE_ORG_TAIL_RE = re.compile(r"/(?:items|download|details)/(.+)$")


def _canonicalize_pdf_url(url):
    parsed = urlparse.urlsplit(url)
    host = parsed.netloc.lower()
    if host != "archive.org" and not host.endswith(".archive.org"):
        return url
    m = _ARCHIVE_ORG_TAIL_RE.search(parsed.path)
    if not m:
        return url
    return f"https://archive.org/download/{m.group(1)}"


def find_pdf_links(html, page_url):
    """Returns absolute URLs of every .pdf link found on this page."""
    soup = BeautifulSoup(html, "lxml")
    found = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().split("?")[0].split("#")[0].endswith(".pdf"):
            found.append(_canonicalize_pdf_url(_normalize(href, page_url)))
    return found


# --- Auto-superseding old drafts ---
# Ryan publishes revised drafts of the same document (the vent book, for
# instance) as new files under the same archive.org item, and wants the
# newest one to always win automatically rather than hand-maintaining
# curation/excluded_urls.txt every time he publishes a new version.
# Confirmed real case: "...Vent Management Guide - Version 1.pdf" and
# "...Vent Management Guide - Version 2 Draft for Peer Review - Aug
# 2026.pdf" both live under the archive.org item "vent-book-draft-1" and
# both showed up in the same search results.
_ARCHIVE_ITEM_RE = re.compile(r"^/download/([^/]+)/")
_VERSION_NUM_RE = re.compile(r"\bversion\s*(\d+)\b", re.IGNORECASE)
_MONTH_YEAR_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\b", re.IGNORECASE
)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_MONTH_INDEX = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _archive_item_id(url):
    parsed = urlparse.urlsplit(url)
    if parsed.netloc.lower() != "archive.org":
        return None
    m = _ARCHIVE_ITEM_RE.match(parsed.path)
    return m.group(1) if m else None


def _version_sort_key(url):
    """(date_key, version_num) — higher sorts as more current. Both
    default to zero/blank when nothing is found, so a file with no
    version/date signal at all never outranks one that has either."""
    name = urlparse.unquote(url)
    version_num = 0
    m = _VERSION_NUM_RE.search(name)
    if m:
        version_num = int(m.group(1))

    date_key = (0, 0)
    m = _MONTH_YEAR_RE.search(name)
    if m:
        date_key = (int(m.group(2)), _MONTH_INDEX[m.group(1)[:3].lower()])
    else:
        m = _YEAR_RE.search(name)
        if m:
            date_key = (int(m.group(1)), 0)

    return (date_key, version_num)


# Sharing an archive.org item is NOT, on its own, evidence that two PDFs
# are different drafts of the SAME document — confirmed as a real, live
# bug: the real "papers-peds-airway-video" item bundles a dozen entirely
# different papers by different authors (Gray, Lepa, Driver, Lee,
# Bonnette, Berisha, Latimer, Sakhuja, Walas, O'Shea, Komasawa), each
# just named "Surname YYYY.pdf" for its own real publication year — a
# normal citation-collection convention, not a version history. Without
# a title check, every one of those bare years matched _YEAR_RE, so this
# was picking "most recent year" as if it were "most current draft" and
# discarding the other ~10 as superseded — real, distinct citations
# silently dropped from the index. Worse, since pdf_urls is a Python set
# (iteration order isn't stable across processes), WHICH one survived
# was effectively random from run to run: two real consecutive runs kept
# 'Gray 2021.pdf' and then 'Lepa 2021.pdf', with everything else in the
# item dropped either way.
#
# A first fix attempt gated on a title stem taken from ANY of
# _VERSION_NUM_RE/_MONTH_YEAR_RE/_YEAR_RE, whichever matched — but that
# still isn't enough: the same real item ALSO has two entirely different
# papers by the same lead author two years apart, "Driver 2018.pdf" and
# "Driver 2021.pdf" — same surname, different real papers, and a bare
# year match alone can't tell that apart from an actual version bump.
# (That attempt also accidentally took the stem from the whole URL
# rather than just the filename, which happened not to matter for THIS
# item since every file shares the same URL prefix, but was fragile.)
#
# The one signal that's actually safe to group on is an explicit
# "Version N" marker — that's a deliberate signal Ryan puts in his own
# document filenames when he uploads a new draft (the real
# "...Version 1.pdf" / "...Version 2 Draft for Peer Review...pdf" vent
# book case), never something that shows up by coincidence on an
# unrelated paper. _title_stem() only returns a real value when
# _VERSION_NUM_RE matches; anything without an explicit version marker
# is left alone entirely, however similar its filename looks otherwise —
# "same surname" or "same year" alone is never enough.
_TITLE_STEM_MIN_CHARS = 4


def _title_stem(url):
    """The filename text before an explicit "Version N" marker,
    normalized (lowercased, non-alphanumeric collapsed to spaces) — or
    None if the filename has no such marker at all. Only two URLs that
    both return a real (non-None) stem, and whose stems match, are ever
    considered possible versions of the same document."""
    name = urlparse.unquote(url).rsplit("/", 1)[-1]  # filename only, not the whole URL
    m = _VERSION_NUM_RE.search(name)
    if not m:
        return None
    stem = re.sub(r"[^a-z0-9]+", " ", name[:m.start()].lower()).strip()
    return stem or None


def find_superseded_pdf_urls(pdf_urls):
    """Groups discovered PDFs by shared archive.org item, then — within
    any group of 2+ files — further splits by title stem (see
    _title_stem) and only applies version-picking within a sub-group
    whose filenames actually agree on what document they are. Picks the
    most current by version number / date found in the filename, and
    returns the URLs of the rest so build_index.py can drop them
    automatically — same effect as adding them to
    curation/excluded_urls.txt, without you having to maintain that list
    by hand every time a new draft goes up. A sub-group where nothing
    has a usable version/date signal, or whose shared stem is too short
    to trust, is left alone rather than guessed at — you'll still see
    all of those in results, same as today, and can exclude by hand if
    needed."""
    groups = {}
    for url in pdf_urls:
        item = _archive_item_id(url)
        if item is None:
            continue
        groups.setdefault(item, []).append(url)

    superseded = set()
    for item, urls in groups.items():
        if len(urls) < 2:
            continue

        stem_groups = {}
        for url in urls:
            stem_groups.setdefault(_title_stem(url), []).append(url)

        for stem, stem_urls in stem_groups.items():
            if stem is None or len(stem_urls) < 2 or len(stem) < _TITLE_STEM_MIN_CHARS:
                continue
            ranked = sorted(stem_urls, key=_version_sort_key, reverse=True)
            if _version_sort_key(ranked[0]) == ((0, 0), 0):
                continue  # no signal anywhere in this sub-group — don't guess
            kept, rest = ranked[0], ranked[1:]
            print(f"  archive.org item '{item}': keeping {urlparse.unquote(kept).rsplit('/', 1)[-1]!r} as current (title match: {stem!r})")
            for dropped in rest:
                print(f"    superseding {urlparse.unquote(dropped).rsplit('/', 1)[-1]!r}")
            superseded.update(rest)

    return superseded


def get_remote_signal(pdf_url):
    """A cheap way to check "did this PDF change" without downloading it
    — a HEAD request's ETag/Last-Modified/Content-Length. Returns None
    if the server gives us nothing useful (some hosts omit all three),
    in which case build_index.py falls back to actually downloading and
    hashing the bytes to decide."""
    try:
        resp = SESSION.head(pdf_url, timeout=config.REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return None

    etag = resp.headers.get("ETag")
    last_modified = resp.headers.get("Last-Modified")
    if etag or last_modified:
        return f"etag:{etag}|modified:{last_modified}"

    content_length = resp.headers.get("Content-Length")
    if content_length:
        # Weakest signal — a same-size edit wouldn't be caught, but it's
        # still far better than nothing and costs one HEAD request.
        return f"len:{content_length}"

    return None


def download_pdf(pdf_url, _retry=True):
    """Returns the PDF's raw bytes, or None if it couldn't be fetched or
    exceeded the size cap.

    A real, unhandled crash from wiring up the ~340 rykerr-references
    PDFs: the streaming read loop (`resp.iter_content(...)`) used to sit
    OUTSIDE the try/except below, on the assumption that once
    raise_for_status() passes, the rest is just local buffering. It
    isn't — iter_content does its actual network reads lazily, during
    iteration, so a connection reset or stall partway through a download
    raises from inside that loop. At 21 PDFs that apparently never came
    up; at ~360, archive.org reset a connection mid-download and the
    whole build crashed with an unhandled ChunkedEncodingError, taking
    the run's summary output down with it (the DB rows already committed
    for earlier PDFs were safe, but the process itself died instead of
    just logging and moving to the next PDF like every other fetch
    failure in this codebase does). The whole download is inside the
    try/except now, and retries once after a short pause before giving
    up — a mid-stream reset is exactly the kind of failure a moment
    later usually succeeds at, and one retry is cheap next to redoing
    OCR on an otherwise-good PDF on the next full run."""
    try:
        resp = SESSION.get(
            pdf_url, timeout=config.REQUEST_TIMEOUT_SECONDS, stream=True
        )
        resp.raise_for_status()

        chunks = []
        total = 0
        for piece in resp.iter_content(chunk_size=1024 * 256):
            total += len(piece)
            if total > config.PDF_MAX_BYTES:
                print(f"  ! {pdf_url} exceeds PDF_MAX_BYTES, skipping")
                return None
            chunks.append(piece)
        return b"".join(chunks)
    except Exception as e:
        if _retry:
            time.sleep(2)
            return download_pdf(pdf_url, _retry=False)
        print(f"  ! failed to fetch PDF {pdf_url}: {e}")
        return None


def _clean_page_text(text):
    # Collapse the excess whitespace/line-break noise PDF extraction
    # tends to produce.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Some of Ryan's PDFs carry a "Return to Contents" navigation header
# followed by a running abbreviations glossary on every page (e.g. "Return
# to Contents ARDS – acute respiratory distress syndrome; AutoPEEP –
# ..."). Confirmed by a real retrieval test: pages consisting mostly of
# this glossary were outranking pages with actual clinical guidance for
# queries like "how do I set PEEP", because the glossary is dense with
# the exact abbreviations being searched for without actually answering
# the question. The list of abbreviations shown varies page to page
# (only the ones used on that page), so it can't be caught by exact-text
# repetition — but the "Return to Contents" anchor phrase itself is
# stable, so strip from there to the end of that line/block.
#
# The original version matched unboundedly to the next blank line OR
# end-of-string. That end-of-string fallback was a real, confirmed bug:
# the vent book also uses "Return to Contents" (as a plain one-line nav
# link at the top of nearly every content page — no glossary follows at
# all), and since those pages usually have no blank line anywhere after
# it, the unbounded match fell through to "end of string" and wiped the
# ENTIRE rest of the page. Verified directly against the real vent book:
# 227 of 266 pages contain the phrase, and every one of them came back
# as empty text after cleanup — while page 237 (no phrase present) kept
# 3726 of 3749 chars correctly, isolating the bug to exactly this regex.
# Capping the match length means it can still strip a short glossary
# block that genuinely follows within a reasonable span, but can never
# again consume real page content just because no blank line shows up
# nearby — if nothing closes the match within the cap, it simply doesn't
# match, and the bare marker phrase (harmless either way) is removed by
# a separate, unconditional second pass below.
_TOC_GLOSSARY_HEADER_RE = re.compile(r"Return to Contents\b.{0,300}?(?=\n\n|\Z)", re.IGNORECASE | re.DOTALL)
_TOC_MARKER_RE = re.compile(r"Return to Contents\b[ \t]*\n?", re.IGNORECASE)


# The vent book stamps its own page number at the bottom of every page
# as "-N-". Confirmed via real citation-blurb data: nearly half (161 of
# 338) of all extracted citation blurbs ran straight through this stamp
# into whatever comes after it in the extraction order — which is never
# more real content, always either nothing or leftover OCR noise from a
# nearby diagram/waveform image ("...Section 22.4) -16- Te i; :",
# "...already in the Appendix -41- | i 1 QQ , AW"). Since the actual
# page number is already known at the call site (extract_pdf_pages has
# it as the loop variable), this targets THIS SPECIFIC page's own
# stamp rather than a generic "-N-" shape, so it can only ever match
# this page's real footer, never something that coincidentally looks
# similar inside real prose (a dose range, a temperature, etc.).
def _page_footer_re(page_number):
    return re.compile(rf"[\s​]*-{page_number}-.*", re.DOTALL)


def _strip_known_boilerplate(text, page_number=None):
    text = _TOC_GLOSSARY_HEADER_RE.sub("", text)
    text = _TOC_MARKER_RE.sub("", text)
    if page_number is not None:
        text = _page_footer_re(page_number).sub("", text)
    return text.strip()


# A references/bibliography page is dense with APA-style entries —
# "Lastname, F. (YYYY)." possibly with more authors before the date.
# Confirmed by a real retrieval test: for the vent book specifically,
# bibliography pages (citations mentioning "PEEP", "ARDS" etc. in their
# titles) were ranking alongside the book's actual instructional content
# for clinical questions, purely on keyword overlap, without ever being
# able to answer the question themselves. Indexing them as if they were
# regular prose just adds competing noise, so drop any page that looks
# like mostly a reference list rather than something a citation should
# ever point a reader at.
#
# NOTE: confirmed against the real vent book that this specific shape
# ("Lastname, F. (2020).") never actually occurs there — its real
# footnote style is entirely different (see _ENTRY_RE below) and this
# regex correctly finds zero matches on every real page checked. Left in
# place for any other PDF that genuinely does use APA-style end-of-
# document bibliography pages; harmless (and untested as a no-op) where
# it doesn't apply.
_CITATION_ENTRY_RE = re.compile(r"[A-Z][A-Za-z'-]+,\s*[A-Z]\.(?:\s*[A-Z]\.)?.{0,120}?\(\d{4}[a-z]?\)\.")


def _looks_like_references_page(text, min_matches=3):
    return len(_CITATION_ENTRY_RE.findall(text)) >= min_matches


# --- Inline citation blurbs ---
# Confirmed against real pages (211, 64, 66, 67, 70, 85) of the vent
# book, pulled straight from the live index: your actual footnote style
# isn't a separate references page at all — it's numbered blurbs sitting
# right at the bottom of the same content page they support, mixed into
# the same block of extracted text as the body prose above them, e.g.:
#
#   "...their contribution to ICU delirium.487 487 Skrobik, 2012 - This
#   opinion piece is in favor of benzodiazepines for sedation of
#   mechanically ventilated patients... 486 Adams & friends, 1985 -
#   Older paper that first investigated this idea..."
#
# Left alone, that whole block gets chunked as one blob of prose — the
# blurbs (your own good, citable content) get diluted into a huge
# mixed-topic chunk, and a query about Skrobik's delirium paper has to
# compete with everything else on that page. This pulls each blurb OUT
# as its own labeled entry — see extract_pdf_pages, which removes the
# matched span from the page's body text before chunking and returns
# the entries separately for build_index.py to resolve and index as
# their own small, individually-retrievable "citation" sources.
#
# Confirmed real label shapes: "Skrobik, 2012" (single author), "Adams &
# friends, 1985" / "Fuller & friends, 2019" (Ryan's own "et al."
# shorthand), "Kallet & Branson, 2016" / "Laghi & Goyal, 2012" (two
# named authors), "Murphy, 2017b" (a letter suffix disambiguating
# multiple same-year citations of the same author), and
# "Murphy, 2017b; Macintyre, 2014" (two different works cited together
# under one shared blurb — see _split_label_pieces).
#
# Also confirmed real: plenty of numbered footnotes are NOT citations at
# all, just plain notes ("139 Airway Pressure Release Ventilation (APRV)
# is about as close as we can get to this idea, see discuss...", "185
# And more on this in Vent Graphics later"). Those don't have the
# Author, YEAR - shape immediately after the number, so this pattern
# naturally leaves them alone — nothing extra needed to exclude them.
_LABEL_PIECE_RE = (
    r"[A-Z][A-Za-z’'\-]*"
    r"(?:\s*(?:&|and)\s*(?:friends|[A-Z][A-Za-z’'\-]*))?"
    r"\s*,\s*\d{4}[a-z]?"
)
_LABEL_RE = rf"{_LABEL_PIECE_RE}(?:\s*;\s*{_LABEL_PIECE_RE})*"
# Must reuse the full (possibly semicolon-chained) _LABEL_RE here, not
# just one _LABEL_PIECE_RE — confirmed as a real bug against real text:
# a shared two-citation entry like "126 Murphy, 2017b; Macintyre, 2014 -
# ..." wasn't recognized as the START of the next entry (the hyphen
# only follows the SECOND piece, not the first), so the previous
# entry's blurb silently swallowed it whole instead of stopping there.
_ENTRY_START_RE_TEXT = rf"(?<!\d)\d{{2,4}}(?!\d)\s+{_LABEL_RE}\s*[-–—]"
_CITATION_BLURB_RE = re.compile(
    rf"(?<!\d)(?P<num>\d{{2,4}})(?!\d)\s+(?P<label>{_LABEL_RE})\s*[-–—]\s*"
    rf"(?P<blurb>.+?)(?=\s*(?:{_ENTRY_START_RE_TEXT})|\Z)",
    re.DOTALL,
)
_LABEL_SPLIT_RE = re.compile(r"\s*;\s*")


def _split_label_pieces(label):
    return [p.strip() for p in _LABEL_SPLIT_RE.split(label) if p.strip()]


def extract_citation_blurbs(text):
    """Finds every inline citation-blurb entry in a page's text (see
    _CITATION_BLURB_RE above) and returns (clean_text, entries) —
    clean_text has each matched entry removed (so normal chunking
    doesn't also index it as undifferentiated body prose), and entries
    is a list of {"number", "label", "label_pieces", "blurb"} in the
    order found. Matching the real Skrobik/Adams/Fuller example above
    yields three separate entries here, each with its own label and
    blurb, not one blob."""
    entries = []
    spans = []
    for m in _CITATION_BLURB_RE.finditer(text):
        label = m.group("label").strip()
        blurb = re.sub(r"\s+", " ", m.group("blurb")).strip()
        if not blurb:
            continue
        entries.append({
            "number": m.group("num"),
            "label": label,
            "label_pieces": _split_label_pieces(label),
            "blurb": blurb,
        })
        spans.append((m.start(), m.end()))

    if not spans:
        return text, entries

    clean_parts = []
    prev_end = 0
    for start, end in spans:
        clean_parts.append(text[prev_end:start])
        prev_end = end
    clean_parts.append(text[prev_end:])
    clean_text = _clean_page_text("".join(clean_parts))

    return clean_text, entries


def _normalize_link_label(text):
    return re.sub(r"\s+", " ", text or "").strip().rstrip(";").strip()


def extract_page_links(page):
    """Every external hyperlink on this page, as (normalized label text
    under that link, target URI) pairs — used to resolve a citation
    blurb's label ("Skrobik, 2012") to the real work it points at.
    Confirmed via citation_link_probe.py against the real vent book:
    almost every footnote label is itself a live link, either straight
    to the matching references.rykerrmedical.com page or, for a
    handful, straight to the primary source (a journal site, PMC, a
    YouTube video) with no references.rykerrmedical.com page in
    between. get_textbox(rect) is used (rather than a looser "any word
    overlapping this rect" scan) specifically so a link's label text
    doesn't pick up unrelated neighboring text — confirmed necessary:
    the probe's looser method occasionally pulled in trailing text past
    the actual linked words."""
    found = []
    for link in page.get_links():
        if link.get("kind") != pymupdf.LINK_URI or not link.get("uri"):
            continue
        rect = pymupdf.Rect(link["from"])
        label = _normalize_link_label(page.get_textbox(rect))
        if label:
            found.append((label, link["uri"]))
    return found


def resolve_entry_links(entry, page_links):
    """Matches a citation entry's label piece(s) against this page's
    link list, returning the list of target URI(s) — usually one, but
    two for a shared-blurb entry like "Murphy, 2017b; Macintyre, 2014"
    (confirmed real: that's TWO separate links on the same page, one
    per piece, both under one blurb). Tries an exact normalized match
    first, then falls back to substring containment either direction
    (link text and regex-captured label piece don't always line up to
    the character — e.g. a trailing semicolon on one side). A piece
    with no matching link at all (plain-text label, no hyperlink) is
    just omitted — build_index.py falls back to author/year + content
    matching for those, same as for a link that doesn't resolve to
    anything in the references repo."""
    uris = []
    for piece in entry["label_pieces"]:
        norm_piece = _normalize_link_label(piece)
        match = None
        for label, uri in page_links:
            if label == norm_piece:
                match = uri
                break
        if match is None:
            for label, uri in page_links:
                if norm_piece in label or label in norm_piece:
                    match = uri
                    break
        if match:
            uris.append(match)
    return uris


# A "what's changed in this version" / revision-history page is a flat
# list of short edit notes ("- updated our recommendation on X", "-
# clarified Y", "- removed Z"). Confirmed by a real retrieval test: this
# kind of page (near the front of a draft document, listing edits made
# since the last version) was outranking genuine clinical content for
# queries like "how do I set PEEP for ARDS" — it's dense with exactly the
# same vocabulary (PEEP, recommendation, management) without ever
# answering anything itself, and unlike the references-page case, cosine
# similarity alone didn't flag it as obviously off-topic (it scored
# comparably to real content) — only the reranker's very negative score
# gave it away, and that's per-query, not a fix. Detected structurally (a
# run of dash-led edit-verb entries) rather than by keyword alone, since
# real clinical prose legitimately uses these same verbs in ordinary
# sentences ("we previously said...", "we updated our approach based
# on...") without being a changelog — requiring the dash-prefixed list
# shape is what keeps this from misfiring on that kind of real content.
#
# First version used "-\s*" between the dash and the verb and matched
# zero real bullets in the actual page — confirmed via a raw-text dump:
# the PDF's bullets are "-​ updated..." (a zero-width space, U+200B,
# right after the dash), and ​ is NOT part of Python re's \s under
# Unicode matching (it's a formatting character, not whitespace), so the
# dash and the verb never lined up. "-[^A-Za-z]*" — any run of non-letter
# characters, not just whitespace — closes that gap and is robust to
# whatever invisible separator a given PDF export happens to use.
_CHANGELOG_ENTRY_RE = re.compile(
    r"-[^A-Za-z]*(?:updated|added|removed|clarified|changed|revised|corrected|fixed|adjusted|"
    r"expanded|reworded|rewrote|rewrite|deleted|renamed|improved|refined|created|reviewed|redid)\b",
    re.IGNORECASE,
)
_CHANGELOG_MIN_MATCHES = 3


def _looks_like_changelog_page(text, min_matches=_CHANGELOG_MIN_MATCHES):
    return len(_CHANGELOG_ENTRY_RE.findall(text)) >= min_matches


def _strip_repeated_boilerplate(pages):
    """Catches the more generic case: a header/footer line (page number,
    site URL, doc title) that's byte-for-byte identical across most
    pages of a PDF. Left in, a short repeated line doesn't usually hurt
    much on its own, but on a short page it can be a large fraction of
    the chunk — worth stripping cheaply since we're already here."""
    if len(pages) < 6:
        return pages  # too few pages for frequency to mean anything

    line_counts = Counter()
    for _, text in pages:
        for line in {ln.strip() for ln in text.split("\n") if ln.strip()}:
            line_counts[line] += 1

    threshold = max(3, int(len(pages) * 0.4))
    boilerplate = {line for line, count in line_counts.items() if count >= threshold}
    if not boilerplate:
        return pages

    cleaned = []
    for page_number, text in pages:
        kept = [ln for ln in text.split("\n") if ln.strip() not in boilerplate]
        text = _clean_page_text("\n".join(kept))
        if len(text) >= config.PDF_MIN_CHARS_PER_PAGE:
            cleaned.append((page_number, text))
    return cleaned


# --- Heading detection ---
# Many of Ryan's PDFs (confirmed via a real font-size probe against the
# vent book: 266 pages, clean 16pt-bold chapter / 13pt-bold section
# hierarchy over 12pt body text) have a genuine, consistent heading
# structure the PDF's own formatting already encodes. Retrieval embeds
# each page's raw prose, so a passage about PEEP that never repeats the
# word "titrate" — because that's literally what its section heading is
# for — won't semantically match a query using that word. Prepending the
# chapter/section heading currently in effect to each page's text fixes
# this directly, using signal the document already provides, rather than
# guessing at query synonyms.
#
# Thresholds are relative to each document's own body-text size (found
# per-document, not a fixed point size, since that varies by PDF) rather
# than hardcoded points — tier1 (chapter) and tier2 (section) cutoffs
# were both confirmed against real data: body text sized around 12pt,
# chapter headings ~4pt larger, section headings ~1pt larger, and bold
# footnote text staying close to body size (so the tier2 cutoff already
# excludes it without needing separate footnote-specific logic).
_HEADING_LEADING_NUM_RE = re.compile(r"^\d+\s")  # footnote refs like "45 Discussed in..."
_HEADING_TIER1_OFFSET = 3.0
_HEADING_TIER2_OFFSET = 0.5
_HEADING_MAX_CHARS = 80  # headings are short lines; longer bold text is usually just emphasis


# --- OCR for image-embedded content ---
# Only attempted on pages that actually contain an image (page.get_images()
# — cheap to check, and most pages in a normal document have none), so
# text-only pages take the same fast path as before and pay no OCR cost at
# all. full=False runs pymupdf/Tesseract in "mixed" mode: it OCRs only the
# image regions that don't already have their own text layer and merges
# that into the page's normal extracted text, rather than re-OCRing text
# that was already extracted correctly (confirmed against a synthetic
# mixed page: real text + an image both came through in one call, neither
# duplicated nor lost). Heading detection is untouched by any of this — it
# reads span font-size/bold data from get_text("dict") on the real text
# layer only, which OCR'd text never has, so a graphic can't accidentally
# get treated as a heading.
_OCR_AVAILABLE = None  # cached probe result — checked once per process, not once per page

# pymupdf's OCR doesn't shell out to a `tesseract` binary on PATH — it
# needs TESSDATA_PREFIX pointing at Tesseract's trained-data directory
# directly. Confirmed as a real gap: Ryan's machine has Tesseract properly
# installed via Homebrew (the `tesseract` command works fine), but
# get_textpage_ocr still failed with "Tesseract is not installed" because
# TESSDATA_PREFIX was never set — Homebrew doesn't set it globally on its
# own. Rather than making Ryan discover and export that env var by hand,
# try the install locations Tesseract actually uses first and set it
# automatically when one of them has real data files in it.
_TESSDATA_CANDIDATE_PATHS = [
    os.environ.get("TESSDATA_PREFIX", ""),
    "/opt/homebrew/share/tessdata",  # Homebrew, Apple Silicon
    "/usr/local/share/tessdata",     # Homebrew, Intel Mac (also common on Linux)
    "/usr/share/tessdata",
    *sorted(glob.glob("/usr/share/tesseract-ocr/*/tessdata")),  # Debian/Ubuntu apt package
]


def _find_tessdata_dir():
    for path in _TESSDATA_CANDIDATE_PATHS:
        if path and os.path.isdir(path) and glob.glob(os.path.join(path, "*.traineddata")):
            return path
    return None


def _probe_ocr():
    probe_doc = pymupdf.open()
    probe_page = probe_doc.new_page(width=100, height=100)
    probe_page.get_textpage_ocr(flags=0, full=False)
    probe_doc.close()


def _ocr_available():
    global _OCR_AVAILABLE
    if _OCR_AVAILABLE is None:
        try:
            _probe_ocr()
            _OCR_AVAILABLE = True
        except Exception as first_error:
            tessdata_dir = _find_tessdata_dir()
            if tessdata_dir and tessdata_dir != os.environ.get("TESSDATA_PREFIX"):
                os.environ["TESSDATA_PREFIX"] = tessdata_dir
                try:
                    _probe_ocr()
                    _OCR_AVAILABLE = True
                    print(f"  - OCR: found Tesseract data at {tessdata_dir}, using it")
                except Exception as second_error:
                    _OCR_AVAILABLE = False
                    print(
                        f"  ! OCR unavailable even after trying {tessdata_dir} ({second_error}) — "
                        f"pages with content baked into images/graphics won't be searchable. Find "
                        f"your tessdata folder (`brew --prefix tesseract`, then look for tessdata/ "
                        f"inside it) and run with TESSDATA_PREFIX=<that path> python build_index.py --full"
                    )
            else:
                _OCR_AVAILABLE = False
                print(
                    f"  ! OCR unavailable ({first_error}) — pages with content baked into "
                    f"images/graphics won't be searchable. Tesseract being on your PATH isn't "
                    f"enough by itself — pymupdf needs TESSDATA_PREFIX pointing at its data "
                    f"folder. Find it with `brew --prefix tesseract` (look for a tessdata/ "
                    f"subfolder inside), then run with "
                    f"TESSDATA_PREFIX=<that path> python build_index.py --full"
                )
    return _OCR_AVAILABLE


def _page_text(page):
    """Plain extracted text, with OCR folded in for any embedded image
    content when config.PDF_ENABLE_OCR is on and Tesseract is available.
    Returns (text, ocr_attempted, ocr_failed) so the caller can tally
    summary counts rather than printing per-page noise across a
    200+-page document."""
    if not (config.PDF_ENABLE_OCR and page.get_images()):
        return page.get_text(), False, False
    if not _ocr_available():
        return page.get_text(), False, False
    try:
        ocr_textpage = page.get_textpage_ocr(flags=0, full=False)
        return page.get_text("text", textpage=ocr_textpage), True, False
    except Exception:
        return page.get_text(), True, True


def _bold_flag(span):
    return bool(span.get("flags", 0) & 2**4) or "bold" in span.get("font", "").lower()


def _heading_candidates_from_dict(page_dict):
    """(size, text) for every bold line on this page short enough to
    plausibly be a heading, in reading order — no size filtering yet,
    that happens once body_size is known (see extract_pdf_pages). Pulled
    out as its own step so the page only needs to be visited once: this
    runs against a dict already fetched for the page, rather than
    re-fetching it."""
    found = []
    for block in page_dict.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text or len(text) > _HEADING_MAX_CHARS:
                continue
            if not any(_bold_flag(s) for s in spans):
                continue
            if _HEADING_LEADING_NUM_RE.match(text):
                continue
            size = max(s["size"] for s in spans)
            found.append((size, text))
    return found


def extract_pdf_pages(pdf_bytes, pdf_url):
    """Returns (pages, citations).

    pages is a list of (page_number, text) for every page with enough
    extractable text to be worth indexing. page_number is 1-based, to
    match what a human would actually call it in a citation. Each page's
    text is prefixed with the chapter/section heading currently in
    effect (e.g. "[Vent Parameters Round One — Positive End-Expiratory
    Pressure]"), detected from the PDF's own font formatting.

    citations is a flat list of every inline citation blurb found across
    the whole document (see extract_citation_blurbs) — each entry is
    {"page", "number", "label", "label_pieces", "blurb", "links"},
    already stripped out of the corresponding page's text in `pages` so
    it isn't double-indexed as undifferentiated body prose. build_index.py
    is responsible for resolving each entry's links (or falling back to
    author/year + content matching when there are none) and indexing it
    as its own small "citation" source.

    Visits each page exactly once (dict extraction for headings, plain
    extraction for body text, link extraction, all pulled together)
    rather than scanning the whole document twice — an earlier version
    computed body-text size in a separate full pre-pass, which meant
    re-visiting every page a second time while the same Document stayed
    open throughout. That version caused the real vent-book PDF to have
    227 of 266 pages misidentified as having no extractable text on a
    real build, despite those pages genuinely having substantial text
    (confirmed separately via heading_probe.py against the same
    download) — the exact mechanism wasn't pinned down (not reproducible
    with synthetic PDFs even at matching page count and pymupdf
    version), but doubling the per-page pymupdf calls across a
    266-page document while holding one Document open is the clear
    structural risk, so this rewrite removes it rather than patching
    around an unconfirmed cause. Needs re-verifying against the real PDF
    before trusting it. Link extraction is folded into this same pass
    for the same reason — page.get_links()/get_textbox() both need the
    page open, and it's already open here exactly once per page."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        print(f"  ! could not open PDF {pdf_url}: {e}")
        return [], []

    # Single pass: pull dict + plain text + links together per page,
    # then close the document — nothing below this needs pymupdf again.
    raw_pages = []  # (page_number, heading_candidates, plain_text, page_links)
    size_counts = Counter()
    ocr_attempted = 0
    ocr_failed = 0
    for i, page in enumerate(doc, start=1):
        page_dict = page.get_text("dict")
        plain_text, attempted, failed = _page_text(page)
        ocr_attempted += attempted
        ocr_failed += failed
        candidates = _heading_candidates_from_dict(page_dict)
        page_links = extract_page_links(page)
        raw_pages.append((i, candidates, plain_text, page_links))
        for block in page_dict.get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if spans:
                    size_counts[round(max(s["size"] for s in spans), 1)] += 1
    doc.close()

    body_size = size_counts.most_common(1)[0][0] if size_counts else None
    tier1_min = (body_size + _HEADING_TIER1_OFFSET) if body_size is not None else None
    tier2_min = (body_size + _HEADING_TIER2_OFFSET) if body_size is not None else None

    pages = []
    citations = []
    skipped_scanned = 0
    skipped_references = 0
    skipped_changelog = 0
    current_h1 = None
    current_h2 = None
    for i, candidates, plain_text, page_links in raw_pages:
        if tier2_min is not None:
            for size, heading_text in candidates:
                if size < tier2_min:
                    continue  # bold but body-sized — not a real heading (e.g. emphasis)
                if size >= tier1_min:
                    current_h1, current_h2 = heading_text, None
                else:
                    current_h2 = heading_text

        text = _clean_page_text(plain_text)
        text = _strip_known_boilerplate(text, page_number=i)

        text, blurb_entries = extract_citation_blurbs(text)
        for entry in blurb_entries:
            citations.append({
                "page": i,
                "number": entry["number"],
                "label": entry["label"],
                "label_pieces": entry["label_pieces"],
                "blurb": entry["blurb"],
                "links": resolve_entry_links(entry, page_links),
            })

        if len(text) < config.PDF_MIN_CHARS_PER_PAGE:
            skipped_scanned += 1
            continue
        if _looks_like_references_page(text):
            skipped_references += 1
            continue
        if _looks_like_changelog_page(text):
            skipped_changelog += 1
            continue

        heading_path = " — ".join(h for h in (current_h1, current_h2) if h)
        if heading_path:
            text = f"[{heading_path}]\n\n{text}"

        pages.append((i, text))

    if ocr_attempted:
        note = f", {ocr_failed} failed" if ocr_failed else ""
        print(f"  - {pdf_url}: ran OCR on {ocr_attempted} page(s) with embedded images{note}")

    if skipped_scanned:
        frac = skipped_scanned / max(skipped_scanned + len(pages), 1)
        note = " (this PDF may be scanned images — check config.PDF_ENABLE_OCR is on)" if frac > 0.5 else ""
        print(f"  ! {pdf_url}: skipped {skipped_scanned} page(s) with little/no extractable text{note}")

    if skipped_references:
        print(
            f"  ! {pdf_url}: skipped {skipped_references} page(s) that look like reference/bibliography "
            f"lists (citation entries, not instructional content — would just add keyword-overlap noise)"
        )

    if skipped_changelog:
        print(
            f"  ! {pdf_url}: skipped {skipped_changelog} page(s) that look like a version/changelog "
            f"list (edit notes, not instructional content — outranked real content on shared vocabulary)"
        )

    before = len(pages)
    pages = _strip_repeated_boilerplate(pages)
    dropped = before - len(pages)
    if dropped:
        print(f"  ! {pdf_url}: {dropped} page(s) were nothing but repeated header/footer text once stripped, dropped")

    if citations:
        with_links = sum(1 for c in citations if c["links"])
        print(
            f"  - {pdf_url}: found {len(citations)} inline citation blurb(s) across the document "
            f"({with_links} with a resolvable link, {len(citations) - with_links} plain-text only)"
        )

    return pages, citations


def pdf_title(pdf_bytes, fallback_url):
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        title = (doc.metadata or {}).get("title", "").strip()
        doc.close()
        if title:
            return title
    except Exception:
        pass
    # Fall back to the filename
    name = urlparse.urlsplit(fallback_url).path.rsplit("/", 1)[-1]
    return name or fallback_url


def locator_url_for_page(pdf_url, page_number):
    """Most browser PDF viewers (Chrome, Firefox, Edge, Safari) honor a
    #page=N fragment and jump straight there — so this is a genuinely
    clickable deep link, not just a label."""
    return f"{pdf_url}#page={page_number}"
