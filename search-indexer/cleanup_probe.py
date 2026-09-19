"""
One-off diagnostic — NOT part of the indexing pipeline. extract_order_probe.py
already showed raw page.get_text() is fine on every sampled page (163 to
3749 chars, all comfortably over the 40-char minimum) — so the 227-page
loss isn't in extraction itself. This checks the next step: the cleanup
pipeline that runs on that raw text before the length check
(_clean_page_text, then _strip_known_boilerplate).

_strip_known_boilerplate was built and verified only against the Field
Reference Guide's "Return to Contents [glossary]" pattern. Its regex
(`Return to Contents\\b.*?(?=\\n\\n|\\Z)`, DOTALL) matches from that
phrase up to the next blank line OR, if there isn't one, all the way to
the end of the text — so if the vent book also contains "Return to
Contents" (plausible: a long cross-referenced document with in-document
navigation) and doesn't have a blank line soon after it on a given page,
this could silently eat most of that page's real content before the
length check ever sees it. This script tests that directly: runs the
REAL cleanup functions from pdf_ingest.py against real pages and shows
before/after lengths, and flags whether "Return to Contents" is present.

Usage:
    python cleanup_probe.py
    python cleanup_probe.py --pages 1,50,51,52,77,100,150,200,237
"""
import argparse

import pymupdf

from crawl import SESSION
import pdf_ingest

DEFAULT_URL = (
    "https://archive.org/download/vent-book-draft-1/"
    "Rykerr%20Medical%27s%20Vent%20Management%20Guide%20-%20Version%202%20"
    "Draft%20for%20Peer%20Review%20-%20Aug%202026.pdf"
)
DEFAULT_SAMPLE = [1, 9, 50, 51, 52, 77, 87, 100, 150, 200, 237]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--pages", default=None)
    parser.add_argument("--scan-all", action="store_true",
                         help="check every page in the document instead of just the sample, "
                              "and report the total count that would fail the 40-char minimum "
                              "after cleanup — directly comparable to the 227 from the real build")
    args = parser.parse_args()

    print(f"downloading {args.url} ...")
    resp = SESSION.get(args.url, timeout=60)
    resp.raise_for_status()
    pdf_bytes = resp.content
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    print(f"opened, {len(doc)} page(s)\n")

    if args.scan_all:
        total_pages = len(doc)
        below_threshold = 0
        contains_marker = 0
        worst = []  # (page_number, raw_len, cleaned_len, has_marker)
        for i, page in enumerate(doc, start=1):
            raw = page.get_text()
            has_marker = "return to contents" in raw.lower()
            if has_marker:
                contains_marker += 1
            cleaned = pdf_ingest._strip_known_boilerplate(pdf_ingest._clean_page_text(raw))
            if len(cleaned) < 40:
                below_threshold += 1
                worst.append((i, len(raw), len(cleaned), has_marker))
        doc.close()
        print(f"pages containing 'return to contents' (case-insensitive): {contains_marker} of {total_pages}")
        print(f"pages that fall under 40 chars AFTER cleanup: {below_threshold} of {total_pages} "
              f"(compare to the 227 reported by the real build)")
        if worst:
            print("\nfirst 15 such pages (page, raw_len, cleaned_len, had 'return to contents'):")
            for row in worst[:15]:
                print(f"  {row}")
        return

    sample = DEFAULT_SAMPLE
    if args.pages:
        sample = [int(p.strip()) for p in args.pages.split(",")]

    print(f"{'page':>5} | {'raw len':>8} | {'cleaned len':>11} | {'has marker?':>11} | note")
    print("-" * 70)
    for page_number in sample:
        raw = doc[page_number - 1].get_text()
        has_marker = "return to contents" in raw.lower()
        cleaned = pdf_ingest._strip_known_boilerplate(pdf_ingest._clean_page_text(raw))
        note = "BELOW 40-CHAR MINIMUM AFTER CLEANUP" if len(cleaned) < 40 else ""
        print(f"{page_number:>5} | {len(raw):>8} | {len(cleaned):>11} | {str(has_marker):>11} | {note}")
        if len(cleaned) < 40 and len(raw) >= 40:
            print(f"      raw text (first 400 chars): {raw[:400]!r}")
            print(f"      cleaned text: {cleaned!r}")

    doc.close()


if __name__ == "__main__":
    main()
