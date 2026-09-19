"""
Resolves your inline citation blurbs (the "487 Skrobik, 2012 - ..."
footnotes pdf_ingest.py pulls out of your own primary PDFs) to the real
work each one is citing, read straight from the rykerr-references repo's
markdown source rather than crawled — that repo has no sitemap and its
~435 citation pages aren't cross-linked to each other, so a normal crawl
would find almost none of them. Reading the source directly (same idea
as frontmatter_tags.py for blog tags) sidesteps that entirely.

Confirmed via citation_link_probe.py against the real vent book PDF:
almost every footnote label is itself a live hyperlink — either straight
at the matching references.rykerrmedical.com page (exact, no guessing
needed, and immune to the visible label text itself being off — a real
case had the label reading "Yartsev, 2023h" while the link actually
pointed at Yartsev2019Oxygen.html) or, for a handful of entries, straight
at the primary source itself (a journal site, PMC, a YouTube video) with
no references.rykerrmedical.com page in between at all. resolve_link()
below is what tells those two cases apart.

For the remainder — a footnote with no link at all, or a link whose
references.rykerrmedical.com path doesn't match anything in the repo
(Ryan: "when I first made the ref pages, there were some typos") — the
label's Author+Year is matched against the repo by filename, and, per
Ryan's direction ("some of the citations... will require matching... for
the ones that don't match 1:1, just look into the text of the reference
itself"), falls back to comparing the blurb's own wording against each
same-surname candidate's filename-derived title when the strict match is
ambiguous (e.g. the four real Yartsev2023_*.md files, which all share
the same author+year and can only be told apart by what they're about)
or comes up empty. See fuzzy_match_label().

Each reference page ends up in one of three buckets, same as before:
  - Has a "View PDF on Archive.org" link: recorded as this entry's
    pdf_link, for a future lightweight title/abstract pass — but no
    longer fed into full page-by-page PDF chunking (that was the
    abandoned approach: 5 whole-textbook citations alone produced
    ~12,600 of ~25,000 total PDF chunks, more than every one of Ryan's
    own authored documents combined).
  - Has a "Link to Paper via SciHub" link but no archive.org PDF:
    recorded as has_scihub=True and nothing else — this tool will never
    fetch from or index a SciHub mirror, however it's phrased or asked
    for, regardless of framing.
  - Neither (audio/video-only citation, like the real Bishop2025_
    Dyssynchrony.md — an Instagram series with self-hosted mp4s, no PDF
    at all): still indexed, just with no pdf_link — the permalink page
    itself (which lists the video links) is still a real, useful
    citation target, so this is no longer treated as "nothing to index".
"""
import re
from pathlib import Path
from urllib.parse import urlsplit

_SKIP_DIR_NAMES = {".git", "_site", "node_modules", "vendor", ".jekyll-cache", ".github"}

_PERMALINK_RE = re.compile(r"^permalink:\s*(\S+)\s*$", re.MULTILINE)

# Matched by their exact label text, not by domain-sniffing for any
# archive.org/scihub-looking href on the page — so a SciHub link sitting
# right next to a "Link to Original Website" link can never be picked up
# by accident under the wrong key.
_ORIGINAL_LINK_RE = re.compile(
    r'<a\s+href="([^"]+)"[^>]*>\s*Link to Original Website\s*</a>', re.IGNORECASE
)
_PDF_LINK_RE = re.compile(
    r'<a\s+href="([^"]+)"[^>]*>\s*View PDF on Archive\.org\s*</a>', re.IGNORECASE
)
_SCIHUB_LINK_RE = re.compile(
    r'<a\s+href="([^"]+)"[^>]*>\s*Link to Paper via SciHub\s*</a>', re.IGNORECASE
)

# Real filenames are Author+Year_Description.md (e.g.
# "Skrobik2012_Benzos_Vented_Pts.md", "Bishop2025_Dyssynchrony.md").
_FILENAME_AUTHOR_YEAR_RE = re.compile(r"^([A-Za-z]+)(\d{4})")

REFERENCES_HOST = "references.rykerrmedical.com"


def build_reference_index(repo_root):
    """Walks repo_root/references/**/*.md once. Returns
    (by_permalink, by_author_year, stats):

      by_permalink: {"/Skrobik2012_Benzos_Vented_Pts.html": entry, ...}
      by_author_year: {("skrobik", "2012"): [entry, ...], ...} — a list,
        since several files can share one surname+year (the four real
        Yartsev2023_*.md files, all ("yartsev", "2023")).

    entry = {"path", "permalink", "category", "title_guess",
              "original_link", "pdf_link", "has_scihub"}

    Returns ({}, {}, stats-with-zeros) if repo_root doesn't exist, same
    graceful-fallback shape as frontmatter_tags.build_post_index for a
    missing posts repo, so a checkout that doesn't have rykerr-references
    alongside it (e.g. CI, until that's wired up) degrades instead of
    breaking the build."""
    stats = {"pages_scanned": 0, "with_permalink": 0}
    root = Path(repo_root)
    refs_dir = root / "references"
    by_permalink = {}
    by_author_year = {}
    if not refs_dir.is_dir():
        return by_permalink, by_author_year, stats

    for path in refs_dir.rglob("*.md"):
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        stats["pages_scanned"] += 1

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue

        m = _PERMALINK_RE.search(raw)
        if not m:
            continue
        stats["with_permalink"] += 1
        permalink = m.group(1).strip()

        try:
            category = path.relative_to(refs_dir).parts[0]
        except (ValueError, IndexError):
            category = ""

        stem = path.stem
        title_guess = stem
        surname = year = None
        am = _FILENAME_AUTHOR_YEAR_RE.match(stem)
        if am:
            surname = am.group(1).lower()
            year = am.group(2)
            rest = stem[am.end():].lstrip("_")
            if rest:
                title_guess = rest.replace("_", " ").replace("&", " & ")

        original_m = _ORIGINAL_LINK_RE.search(raw)
        pdf_m = _PDF_LINK_RE.search(raw)
        scihub_m = _SCIHUB_LINK_RE.search(raw)

        entry = {
            "path": str(path),
            "permalink": permalink,
            "category": category,
            "title_guess": title_guess,
            "original_link": original_m.group(1).strip() if original_m else None,
            "pdf_link": pdf_m.group(1).strip() if pdf_m else None,
            "has_scihub": bool(scihub_m),
        }
        by_permalink[permalink] = entry
        if surname and year:
            by_author_year.setdefault((surname, year), []).append(entry)

    return by_permalink, by_author_year, stats


def resolve_link(uri, by_permalink):
    """Given a real hyperlink target pulled from a primary PDF, returns
    (citation_id, entry_or_None):

      - If the link points at references.rykerrmedical.com and its path
        matches a page in the repo: (that page's canonical
        https://references.rykerrmedical.com/... URL, its entry) — exact,
        no guessing.
      - If it points at references.rykerrmedical.com but nothing in the
        repo matches that path (a stale/typo'd filename from when the
        page was first made): (None, None) — caller falls back to
        fuzzy_match_label using the blurb's own label text instead.
      - Otherwise it's a direct link to the primary source itself (a
        journal, PMC, YouTube, etc.) with no rykerr-references page in
        between: (that URL as-is, None)."""
    parsed = urlsplit(uri)
    host = parsed.netloc.lower()
    if host == REFERENCES_HOST or host.endswith("." + REFERENCES_HOST):
        entry = by_permalink.get(parsed.path)
        if entry is None:
            for permalink, candidate in by_permalink.items():
                if permalink.lower() == parsed.path.lower():
                    entry = candidate
                    break
        if entry is not None:
            return f"https://{REFERENCES_HOST}{entry['permalink']}", entry
        return None, None
    return uri, None


_LABEL_SURNAME_RE = re.compile(r"\s*([A-Z][A-Za-z'\-]+)")
_LABEL_YEAR_RE = re.compile(r"(\d{4})")
_WORD_RE = re.compile(r"[a-z]{4,}")


def fuzzy_match_label(label, by_author_year, blurb_text=""):
    """Fallback for a citation entry with no usable link (see
    resolve_link above). label is the blurb's own text, e.g.
    "Skrobik, 2012" or "Yartsev, 2023h" (the letter suffix, when
    present, is Ryan's own disambiguator and is never in the repo's
    filenames, so it's ignored here rather than matched against).

    Tries a strict surname+year match first. If that's ambiguous (2+
    files share the surname+year — the real Yartsev2023 case) or empty
    (typo'd surname/year, or a letter-suffixed year that doesn't equal
    any real filename year), widens to every file sharing just the
    surname and scores each by how much the blurb's own wording
    overlaps with that file's filename-derived title — deliberately
    simple word-overlap, not a real semantic model, since by this point
    the candidate pool is always small (one surname's files). Returns
    the entry, or None if nothing can be resolved with real confidence
    rather than guessing (a tie between two equally-plausible
    candidates is exactly that "typo, can't tell which" case — left
    unmatched, not guessed)."""
    sm = _LABEL_SURNAME_RE.match(label)
    if not sm:
        return None
    surname = sm.group(1).lower()
    ym = _LABEL_YEAR_RE.search(label)
    year = ym.group(1) if ym else None

    candidates = by_author_year.get((surname, year), []) if year else []
    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        candidates = [
            entry
            for (entry_surname, _entry_year), entries in by_author_year.items()
            if entry_surname == surname
            for entry in entries
        ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    blurb_words = set(_WORD_RE.findall(blurb_text.lower()))
    if not blurb_words:
        return None

    scored = []
    for entry in candidates:
        title_words = set(_WORD_RE.findall(entry["title_guess"].lower()))
        overlap = len(blurb_words & title_words)
        if overlap:
            scored.append((overlap, entry))

    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score = scored[0][0]
    tied = [entry for score, entry in scored if score == best_score]
    if len(tied) > 1:
        return None  # genuine tie — don't guess
    return tied[0]


if __name__ == "__main__":
    # Quick manual check: python reference_citations.py [repo_root]
    import sys
    repo_root = sys.argv[1] if len(sys.argv) > 1 else "../../rykerr-references"
    by_permalink, by_author_year, stats = build_reference_index(repo_root)
    print(f"Scanned {stats['pages_scanned']} .md file(s) under {repo_root!r}")
    print(f"  {stats['with_permalink']} had a permalink (usable as a reference page)")
    print(f"  {len(by_permalink)} unique permalink(s)")
    dup_keys = [k for k, v in by_author_year.items() if len(v) > 1]
    print(f"  {len(dup_keys)} author+year combo(s) shared by 2+ files (need content matching to disambiguate):")
    for surname, year in sorted(dup_keys)[:10]:
        titles = [e["title_guess"] for e in by_author_year[(surname, year)]]
        print(f"    {surname} {year}: {titles}")
