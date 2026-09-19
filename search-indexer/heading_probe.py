"""
One-off diagnostic — NOT part of the indexing pipeline. Reports the real
font-size/bold structure of a PDF so heading-detection thresholds can be
set from actual data instead of guessed. Point it at any PDF already
being indexed (defaults to the vent book).

Usage:
    python heading_probe.py
    python heading_probe.py --url https://archive.org/download/.../some-other.pdf
    python heading_probe.py --pages 1-20   # limit the page range scanned

What it prints:
  - the distribution of font sizes seen across the document (this tells
    us what "body text" size is, so a heading threshold can be set
    relative to it rather than as a magic number)
  - every line that's a heading CANDIDATE (larger than body-text size,
    or bold, and short — headings are rarely a full paragraph) along
    with its page number, size, and bold flag

Nothing here is wired into build_index.py yet — this is purely so real
numbers can come back before any heuristic gets built into the real
pipeline, same as every other fix this session has been verified
against real data before shipping.
"""
import argparse
from collections import Counter

import pymupdf

from crawl import SESSION

DEFAULT_URL = (
    "https://archive.org/download/vent-book-draft-1/"
    "Rykerr%20Medical%27s%20Vent%20Management%20Guide%20-%20Version%202%20"
    "Draft%20for%20Peer%20Review%20-%20Aug%202026.pdf"
)


def _parse_page_range(spec, num_pages):
    if not spec:
        return range(1, num_pages + 1)
    start, end = spec.split("-")
    return range(int(start), min(int(end), num_pages) + 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--pages", default=None, help="e.g. 1-20 (default: whole document)")
    args = parser.parse_args()

    print(f"downloading {args.url} ...")
    resp = SESSION.get(args.url, timeout=60)
    resp.raise_for_status()
    doc = pymupdf.open(stream=resp.content, filetype="pdf")
    print(f"opened, {len(doc)} page(s)\n")

    page_range = _parse_page_range(args.pages, len(doc))

    size_counts = Counter()
    candidates = []  # (page_number, size, bold, text)

    for page_number in page_range:
        page = doc[page_number - 1]
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                line_text = "".join(s["text"] for s in spans).strip()
                if not line_text:
                    continue
                max_size = max(s["size"] for s in spans)
                is_bold = any((s["flags"] & 2**4) or "bold" in s["font"].lower() for s in spans)
                size_counts[round(max_size, 1)] += 1
                # Heading candidates: short lines (headings aren't paragraphs)
                if len(line_text) <= 80:
                    candidates.append((page_number, max_size, is_bold, line_text))

    doc.close()

    print("=== font size distribution (size: line count) ===")
    for size, count in sorted(size_counts.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {size:>5}pt : {count}")

    if not size_counts:
        print("  (no text spans found at all — nothing to report)")
        return

    body_size = size_counts.most_common(1)[0][0]
    print(f"\nmost common size (likely body text): {body_size}pt\n")

    print("=== candidate heading lines (size > body OR bold, length <= 80 chars) ===")
    shown = 0
    for page_number, size, is_bold, text in candidates:
        if size > body_size + 0.5 or is_bold:
            print(f"  p{page_number:<4} {size:>5.1f}pt {'BOLD' if is_bold else '    '}  {text!r}")
            shown += 1
            if shown >= 150:
                print("  ... (stopping at 150, that's plenty to calibrate from)")
                break

    if shown == 0:
        print("  none found — this PDF may not use distinguishable heading formatting")
        print("  (all text roughly the same size/weight), which would mean font-based")
        print("  heading detection won't work for it and we'd need a different approach")
        print("  (e.g. a numbered/titled-line pattern specific to your book's style).")


if __name__ == "__main__":
    main()
