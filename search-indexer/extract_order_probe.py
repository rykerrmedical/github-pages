"""
One-off diagnostic — NOT part of the indexing pipeline. Two full rebuilds
have now shown 227 of 266 vent-book pages getting misidentified as
having no extractable text, identically both times (once with a
double-pass structure, once with a single-pass rewrite) — meaning it's a
deterministic bug, not a resource/memory flake, and NOT caused by
scanning the document twice (both versions gave the exact same number).

That leaves the other thing both versions share: calling
page.get_text("dict") before page.get_text() on the same page, for
every page (needed for heading detection). This script tests that
directly against the real file — three extraction approaches per
sampled page, side by side:

  (a) baseline  — get_text() only, nothing else touches the page first
  (b) dict-then-text — get_text("dict") called first, then get_text()
      (this is the order currently shipped in pdf_ingest.py)
  (c) text-then-dict — get_text() called first, then get_text("dict")

If (a) and (c) agree but (b) is short/empty, that pins the bug on
extraction order specifically, and the fix is just reordering the two
calls in extract_pdf_pages. If all three agree, the bug is somewhere
else entirely and this rules out extraction order as the cause.

Usage:
    python extract_order_probe.py
    python extract_order_probe.py --pages 1,50,51,52,77,100,150,200,237
"""
import argparse

import pymupdf

from crawl import SESSION

DEFAULT_URL = (
    "https://archive.org/download/vent-book-draft-1/"
    "Rykerr%20Medical%27s%20Vent%20Management%20Guide%20-%20Version%202%20"
    "Draft%20for%20Peer%20Review%20-%20Aug%202026.pdf"
)
DEFAULT_SAMPLE = [1, 9, 50, 51, 52, 77, 87, 100, 150, 200, 237]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--pages", default=None, help="comma-separated 1-based page numbers to sample")
    args = parser.parse_args()

    sample = DEFAULT_SAMPLE
    if args.pages:
        sample = [int(p.strip()) for p in args.pages.split(",")]

    print(f"downloading {args.url} ...")
    resp = SESSION.get(args.url, timeout=60)
    resp.raise_for_status()
    pdf_bytes = resp.content
    print(f"downloaded {len(pdf_bytes)} bytes\n")

    print(f"{'page':>5} | {'(a) baseline':>14} | {'(b) dict-then-text':>19} | {'(c) text-then-dict':>19} | agree?")
    print("-" * 90)

    mismatches = 0
    for page_number in sample:
        # Fresh document open per approach per page, so nothing from one
        # test can carry state into another.
        doc_a = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        text_a = doc_a[page_number - 1].get_text()
        doc_a.close()

        doc_b = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        page_b = doc_b[page_number - 1]
        _ = page_b.get_text("dict")
        text_b = page_b.get_text()
        doc_b.close()

        doc_c = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        page_c = doc_c[page_number - 1]
        text_c = page_c.get_text()
        _ = page_c.get_text("dict")
        doc_c.close()

        len_a, len_b, len_c = len(text_a), len(text_b), len(text_c)
        agree = "yes" if len_a == len_b == len_c else "NO — MISMATCH"
        if agree != "yes":
            mismatches += 1
        print(f"{page_number:>5} | {len_a:>14} | {len_b:>19} | {len_c:>19} | {agree}")

    print()
    if mismatches:
        print(f"{mismatches} page(s) showed a mismatch between approaches — extraction order matters.")
        print("Showing full text for the first mismatching page found, all three approaches:")
        for page_number in sample:
            doc_a = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            text_a = doc_a[page_number - 1].get_text()
            doc_a.close()
            doc_b = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            page_b = doc_b[page_number - 1]
            _ = page_b.get_text("dict")
            text_b = page_b.get_text()
            doc_b.close()
            if len(text_a) != len(text_b):
                print(f"\n--- page {page_number}, approach (a) baseline, {len(text_a)} chars ---")
                print(repr(text_a[:300]))
                print(f"\n--- page {page_number}, approach (b) dict-then-text, {len(text_b)} chars ---")
                print(repr(text_b[:300]))
                break
    else:
        print("All three approaches agree on every sampled page — extraction order is NOT the cause.")
        print("The bug is somewhere else; don't reorder the calls based on this result.")


if __name__ == "__main__":
    main()
