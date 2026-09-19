"""
One-off diagnostic — NOT part of the pipeline.

The big open question before writing the citation-blurb matcher: when a
footnote blurb says "487 Skrobik, 2012 - ...", is that plain text (in
which case matching it back to the right references.rykerrmedical.com
page has to be done by fuzzy author/year text-matching, which breaks
down for duplicate-year citations like "Yartsev, 2023h" since the
references repo's filenames don't carry the letter suffix), OR is it
actually a clickable hyperlink in the PDF pointing straight at the
right references.rykerrmedical.com URL (in which case matching is
exact and free - just read the link annotation)?

This downloads the real vent book PDF and, for a handful of pages
known (from real indexed chunk text) to contain footnote blurbs,
prints every link annotation pymupdf finds on that page - its target
URI and the nearby text - so we can see directly whether footnote
numbers/labels are wrapped in real hyperlinks.

Usage (from search-indexer/, in your normal venv):
    python citation_link_probe.py
"""
import fitz  # pymupdf

import config
import pdf_ingest

# Real pages confirmed (via dump_page_text.py / live DB query) to
# contain footnote citation blurbs mixed into body text.
PROBE_PAGES = [64, 66, 67, 70, 85, 211]

VENT_BOOK_URL = (
    "https://archive.org/download/vent-book-draft-1/"
    "Rykerr%20Medical%27s%20Vent%20Management%20Guide%20-%20Version%202%20"
    "Draft%20for%20Peer%20Review%20-%20Aug%202026.pdf"
)


def main():
    print(f"Downloading {VENT_BOOK_URL} ...")
    pdf_bytes = pdf_ingest.download_pdf(VENT_BOOK_URL)
    if pdf_bytes is None:
        print("Download failed - see error above.")
        return

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    print(f"Opened, {doc.page_count} pages.\n")

    for page_num in PROBE_PAGES:
        idx = page_num - 1  # pymupdf pages are 0-indexed
        if idx < 0 or idx >= doc.page_count:
            print(f"=== Page {page_num}: out of range, skipping ===\n")
            continue

        page = doc[idx]
        links = page.get_links()
        ext_links = [
            l for l in links
            if l.get("kind") == fitz.LINK_URI and l.get("uri")
        ]

        print(f"=== Page {page_num}: {len(links)} total link annotation(s), "
              f"{len(ext_links)} external URI link(s) ===")

        if not ext_links:
            print("  (no external links on this page)\n")
            continue

        words = page.get_text("words")  # list of (x0,y0,x1,y1,word,...)

        for link in ext_links:
            rect = fitz.Rect(link["from"])
            # Grab words whose bbox overlaps the link's rect, in reading order.
            nearby = [
                w[4] for w in words
                if fitz.Rect(w[:4]).intersects(rect)
            ]
            snippet = " ".join(nearby) if nearby else "(no overlapping text found)"
            print(f"  -> {link['uri']}")
            print(f"     text under link: {snippet!r}")
        print()

    doc.close()


if __name__ == "__main__":
    main()
