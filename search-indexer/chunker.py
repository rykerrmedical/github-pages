"""
Splits page content into embeddable chunks.

Two entry points:
  chunk_text(text) -- the original flat, structure-blind word-window
    splitter. Still used directly for citation-blurb text (a sentence or
    two, no heading structure to speak of) and as the low-level word-
    window splitter chunk_structured_text below builds on.
  chunk_structured_text(title, blurb, blocks) -- the heading-aware entry
    point for webpages and PDF sections. Every chunk it returns leads
    with the page/document title and blurb (when present), then the
    current section heading path (when the source has real heading
    structure), and only then the actual body text -- see extract.py's
    _parse_structured_blocks (webpages) and pdf_ingest.py's
    extract_pdf_pages (PDF sections) for how "blocks" gets built.

    This replaces blindly slicing a whole page/document into arbitrary
    word-count windows with no idea what section (or even what
    page/post) a given window came from. Confirmed as a real retrieval
    problem on the live vent book: a short, sharply-on-topic section
    ("Minute Volume for Pediatrics") lost to a same-vocabulary but less
    relevant neighboring page simply because retrieval had no way to
    tell a page's random middle slice apart from a chunk that's actually
    ABOUT the thing being asked -- both looked like undifferentiated
    prose. Leading every chunk with title/blurb/heading context gives
    the embedding model real structural signal to match against, the
    same fix pdf_ingest.py's font-size heading detection already applied
    on the PDF side -- this extends it to also govern the actual
    CHUNKING boundary (not just a label glued onto a page-sized chunk),
    and to webpages, which previously got no structural signal at all.
"""
import config


def _word_windows(text):
    """The low-level split: text -> overlapping word-count windows, no
    prefix, no structure awareness. Returns [] for empty/whitespace-only
    text."""
    words = text.split()
    if not words:
        return []

    size = config.CHUNK_SIZE_WORDS
    overlap = config.CHUNK_OVERLAP_WORDS
    step = max(size - overlap, 1)

    windows = []
    start = 0
    while start < len(words):
        piece = words[start : start + size]
        if len(piece) >= config.MIN_CHUNK_WORDS or start == 0:
            windows.append(" ".join(piece))
        if start + size >= len(words):
            break
        start += step
    return windows


def chunk_text(text):
    """Original flat entry point -- unchanged behavior, still used for
    citation blurbs and anywhere else with no title/blurb/heading
    structure to lead with."""
    return _word_windows(text)


def chunk_structured_text(title, blurb, blocks):
    """title: page/document title, always led with, in every chunk.
    blurb: short description, or None/empty -- omitted entirely when
        absent rather than embedding a blank line.
    blocks: [{"heading_path": str or None, "text": str, **extra}, ...],
        in document order. Any extra keys (e.g. pdf_ingest.py's
        start_page/end_page) are passed through unchanged onto every
        chunk produced from that block, so a caller that needs
        page-range or other per-block metadata to build a locator
        string still has it even after a long block gets split into
        several word-count windows.

    Returns a list of {"heading_path": ..., "text": <prefixed chunk>,
    **extra} dicts, one per resulting chunk, in the same order as
    `blocks` -- a block that itself needs splitting into multiple
    word-count windows produces multiple consecutive entries, ALL
    carrying the same lead-in and the same passed-through extra
    metadata as their source block. That "every chunk, not just the
    first" part matters: a version that prepended the lead-in once to
    the whole block's text before splitting would only have the FIRST
    resulting window actually carry it -- silently reintroducing
    unlabeled, context-free chunks for anything past the first window
    of a long section.
    """
    lead_lines = [f"[{title}]"]
    if blurb:
        lead_lines.append(blurb)

    chunks = []
    for block in blocks:
        block_lead = list(lead_lines)
        if block.get("heading_path"):
            block_lead.append(f"[{block['heading_path']}]")
        prefix = "\n".join(block_lead) + "\n\n"

        extra = {k: v for k, v in block.items() if k != "text"}
        for window in _word_windows(block["text"]):
            chunks.append({**extra, "text": prefix + window})
    return chunks


if __name__ == "__main__":
    sample = "word " * 500
    result = chunk_text(sample.strip())
    print(f"{len(result)} chunks from 500 words")
    for i, c in enumerate(result):
        print(i, len(c.split()), "words")

    print()
    print("=== chunk_structured_text ===")
    blocks = [
        {"heading_path": None, "text": "Intro paragraph. " * 5},
        {"heading_path": "Anatomical Differences", "text": "word " * 300},
        {"heading_path": "Sizing Equipment — ET Tube Size", "text": "A short formula section."},
    ]
    out = chunk_structured_text("Managing Pediatric Airways", "A field guide for EMS.", blocks)
    for c in out:
        print("---")
        print(c["heading_path"], "|", len(c["text"].split()), "words")
        print(c["text"][:200])
