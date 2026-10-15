"""
Table-of-contents / outline driven section map for PDFs.

Why this exists: the original PDF pipeline found headings from font size
alone, so (a) bold-italic headings set at body size (Field Reference
Guides) were invisible, (b) sections were page-granular, and (c) a PDF's
own, authoritative structure -- its outline or printed table of contents --
was ignored in favour of guessing. This module recovers that structure and
tells pdf_ingest.extract_pdf_pages WHERE each section starts (page + the
exact line on that page), so a section can start mid-page.

Two sources, in priority order:
  1. the PDF's embedded outline (bookmarks), cleaned and quality-gated
  2. a printed table of contents (dot/ellipsis-leader lines near the front),
     whose titles are located in the body text IN ORDER. The printed page
     numbers are only a hint -- they are stale in some of Ryan's guides
     (about 12 pages off in Field Reference Guides).
If neither yields a trustworthy map this returns None and the caller keeps
the legacy font-size heuristic.

Everything here works on `page_lines` -- a per-page list of line records
built by lines_from_page_dict() from the same get_text("dict") call the
caller already makes, so no extra pymupdf passes are needed.
"""
import re
import statistics

_BULLET_CHARS = set("•o▪◦●■-–—·*")
_FOOTNOTE_SIZE_RATIO = 0.8  # same idea as pdf_ingest._FOOTNOTE_SPAN_SIZE_RATIO

# Leader: an ellipsis character, or 2+ dots (possibly space separated,
# e.g. ". .. 10"), optionally followed by a page number, at end of line.
_LEADER_RE = re.compile(r"(?:…|\.\s*\.)[\s.…]*(\d{1,4})?\s*$")
_LEADER_ANYWHERE_RE = re.compile(r"(?:…|\.\s*\.)[\s.…]*")
_TRAILING_DIGITS_RE = re.compile(r"\d{1,3}$")
_ZERO_WIDTH_RE = re.compile("[​‌‍⁠﻿]")


def norm(s):
    """Lowercase alphanumerics only -- robust to spacing/punctuation/
    zero-width characters ("Acetaminophen/ Paracetamol" vs
    "Acetaminophen/Paracetamol")."""
    return re.sub(r"[^a-z0-9]", "", _ZERO_WIDTH_RE.sub("", s).lower())


def clean_title(s):
    s = _ZERO_WIDTH_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# --------------------------------------------------------------------------
# line records
# --------------------------------------------------------------------------

def _is_bold(span):
    return bool(span.get("flags", 0) & 16) or "bold" in span.get("font", "").lower()


def lines_from_page_dict(page_dict):
    """List of {"y","x","text","size","bold","list_item","order"} in the
    dict's own (content-stream / block) order -- the same order
    get_text("text") emits, which is what lets split_page_text map an
    anchor line back into plain text by occurrence index."""
    out = []
    bullet_ys = []
    for block in page_dict.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            max_size = max(s["size"] for s in spans)
            kept = [
                sp for sp in spans
                if not (sp["text"].strip().isdigit() and sp["size"] < max_size * _FOOTNOTE_SIZE_RATIO)
            ]
            text = "".join(sp["text"] for sp in kept).strip()
            if not text:
                continue
            x0, y0 = line["bbox"][0], line["bbox"][1]
            if text in _BULLET_CHARS or (len(text) == 1 and not text.isalnum()):
                bullet_ys.append((y0, x0))
                continue
            out.append({
                "y": y0, "x": x0, "text": text, "size": max_size,
                "bold": any(_is_bold(s) for s in kept), "list_item": False,
                "order": len(out),
            })
    # A line that sits on the same baseline as a bullet glyph (and to its
    # right) is a list item, not a heading -- the "Specific Considerations"
    # bullet list at the top of a Field Reference Guides chapter repeats
    # every sub-heading title verbatim and must not be mistaken for them.
    for rec in out:
        for by, bx in bullet_ys:
            if abs(rec["y"] - by) <= 5 and rec["x"] > bx:
                rec["list_item"] = True
                break
    return out


def body_font_size(page_lines):
    from collections import Counter
    c = Counter()
    for lines in page_lines:
        for ln in lines:
            c[round(ln["size"], 1)] += len(ln["text"])
    return c.most_common(1)[0][0] if c else None


# --------------------------------------------------------------------------
# title <-> line matching
# --------------------------------------------------------------------------

def _title_matches_text(title_norm, text):
    """True if `text` is (modulo spacing and trailing footnote digits) the
    title."""
    tn = norm(text)
    if not tn or not title_norm:
        return False
    if tn == title_norm:
        return True
    if tn.startswith(title_norm) and tn[len(title_norm):].isdigit() and len(tn) - len(title_norm) <= 3:
        return True
    return False


def _runin_re(title):
    words = title.split()
    if not words:
        return None
    return re.compile(r"^\s*" + r"\s*".join(re.escape(w) for w in words) + r"\s*[:\uff1a]\s*", re.IGNORECASE)


def _line_match(title, title_norm, ln):
    """None, "full" (the line is the title) or "runin" (a bold line that
    OPENS with "Title:" and carries body text after it -- the style used
    for most Field Reference Guides sub-headings, e.g. "Epiglottitis:
    patients of any age ...")."""
    if _title_matches_text(title_norm, ln["text"]):
        return "full"
    if ln["bold"]:
        rx = _runin_re(title)
        if rx and rx.match(ln["text"]):
            return "runin"
    return None


def find_title_line(title, lines, start_idx=0, want_bold=None, body_size=None, allow_two_line=True):
    """Returns (idx, span_len, kind) of the first line at/after start_idx
    that is the title (kind "full"/"runin"; a two-line wrapped title has
    span_len 2), else None. want_bold: True = emphasised lines only;
    False = any non-list line; None = both, emphasised first."""
    tn = norm(title)
    if not tn:
        return None

    def emphasised(ln):
        return ln["bold"] or (body_size is not None and ln["size"] >= body_size + 0.4)

    def scan(pred):
        for i in range(start_idx, len(lines)):
            ln = lines[i]
            if ln["list_item"] or not pred(ln):
                continue
            kind = _line_match(title, tn, ln)
            if kind:
                return i, 1, kind
            if allow_two_line and i + 1 < len(lines):
                nxt = lines[i + 1]
                if not nxt["list_item"] and pred(nxt) and _title_matches_text(tn, ln["text"] + " " + nxt["text"]):
                    return i, 2, "full"
        return None

    if want_bold is True:
        return scan(emphasised)
    if want_bold is False:
        return scan(lambda ln: True)
    return scan(emphasised) or scan(lambda ln: True)


# --------------------------------------------------------------------------
# source 1: embedded outline
# --------------------------------------------------------------------------

_GLUED_FOOTNOTE_RE = re.compile(r"([A-Za-z\)\?!…])\d{1,3}(?:[ ,]\d{1,3})*$")


def _strip_footnote_digits(title):
    """"Hypoxic Pulmonary Vasoconstriction28" / "Humidifiers366 367":
    footnote-marker digits glued onto the last word. A number set off by
    a space ("Type 2") is part of the title and is left alone."""
    m = _GLUED_FOOTNOTE_RE.search(title)
    if m and len(title[:m.start(1) + 1]) >= 3:
        return title[:m.start(1) + 1].rstrip()
    return title


def outline_entries(doc):
    """Cleaned outline entries [{"level","title","page"(1-based),"y"}], or
    [] if the outline is missing or unusable (blank / numeric titles --
    e.g. the WHO Red Book outline is just numbers)."""
    try:
        raw = doc.get_toc(simple=False)
    except Exception:
        return []
    if not raw:
        return []
    entries = []
    for item in raw:
        level, title, page = item[0], item[1], item[2]
        dest = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
        title = _strip_footnote_digits(clean_title(title))
        if page is None or page < 1:
            continue
        letters = re.sub(r"[^A-Za-z]", "", title)
        if len(letters) < 3:
            continue  # blank, numeric ("12.3"), or symbol titles -- figures/anchors, not sections
        pt = dest.get("to")
        y = float(pt.y) if pt is not None and hasattr(pt, "y") else None
        entries.append({"level": level, "title": title, "page": page, "y": y})
    # Quality gate. Many titles dropped => the outline is mostly anchors
    # for figures, not a structure.
    if len(entries) < 3 or len(entries) < 0.5 * len(raw):
        return []
    return entries


def limit_depth_for_size(entries, num_pages, max_per_page=0.6):
    """Third-party documents only: when an outline is far deeper than the
    document can sensibly be chunked by (Lichtenstein: 690 entries in 394
    pages), keep only the deepest levels whose total stays within
    max_per_page entries per page (never below the top level)."""
    if not entries:
        return entries
    budget = max(10, int(num_pages * max_per_page))
    levels = sorted({e["level"] for e in entries})
    chosen = levels[0]
    for lv in levels:
        if sum(1 for e in entries if e["level"] <= lv) <= budget:
            chosen = lv
        else:
            break
    return [e for e in entries if e["level"] <= chosen]


def anchor_outline_entries(entries, page_lines, body_size):
    """Attach line_idx (index into page_lines[page-1]) to each entry:
    the line whose text is the title near the destination, else the first
    line at/after the destination y, else None (page start)."""
    anchored = []
    for e in entries:
        pi = e["page"] - 1
        if pi < 0 or pi >= len(page_lines):
            continue
        lines = page_lines[pi]
        idx = None
        span = 1
        # a title line close to the destination
        tn = norm(e["title"])
        best = None
        for i, ln in enumerate(lines):
            if ln["list_item"]:
                continue
            kind = _line_match(e["title"], tn, ln)
            if kind:
                dist = abs(ln["y"] - e["y"]) if e["y"] is not None else 0
                if best is None or dist < best[0]:
                    best = (dist, i, 1, kind)
        if best is None:
            hit = find_title_line(e["title"], lines, 0, want_bold=False, body_size=body_size)
            if hit:
                best = (0, hit[0], hit[1], hit[2])
        runin = False
        if best is not None and (e["y"] is None or best[0] <= 60):
            idx, span, runin = best[1], best[2], best[3] == "runin"
            matched = True
        else:
            matched = False
            if e["y"] is not None:
                for i, ln in enumerate(lines):
                    if ln["y"] >= e["y"] - 4:
                        idx = i
                        break
        anchored.append({**e, "line_idx": idx, "span": span, "matched": matched, "runin": runin})
    # keep document order (outline normally is, but guard against odd files)
    anchored.sort(key=lambda a: (a["page"], -1 if a["line_idx"] is None else a["line_idx"]))
    return anchored


# --------------------------------------------------------------------------
# source 2: printed table of contents
# --------------------------------------------------------------------------

def _leader_info(text):
    """(title_text, page_number_or_None, has_leader)"""
    m = _LEADER_RE.search(text)
    if not m:
        return text, None, False
    title = text[:m.start()].strip()
    num = int(m.group(1)) if m.group(1) else None
    return title, num, True


def _toc_page_candidates(page_lines, max_scan=10, min_leaders=5):
    pages = []
    for pi in range(min(max_scan, len(page_lines))):
        n = sum(1 for ln in page_lines[pi] if _LEADER_RE.search(ln["text"]))
        if n >= min_leaders:
            pages.append(pi)
    return pages


def parse_printed_toc(page_lines, page_width=612.0):
    """Returns (entries, toc_page_indexes). entries: [{"level","title",
    "printed_page"}]. Empty if no printed ToC found."""
    toc_pages = _toc_page_candidates(page_lines)
    if not toc_pages:
        return [], []
    # contiguous run starting at the first candidate (a ToC can spill over)
    run = [toc_pages[0]]
    for p in toc_pages[1:]:
        if p == run[-1] + 1:
            run.append(p)
    raw = []  # (title, printed_page, col_relative_x, col_id)
    for pi in run:
        lines = page_lines[pi]
        if not lines:
            continue
        mid = page_width / 2.0
        xs = [ln["x"] for ln in lines]
        two_col = sum(1 for x in xs if x > mid + 10) >= 5 and sum(1 for x in xs if x < mid - 40) >= 5
        cols = {0: [], 1: []}
        for ln in lines:
            cols[1 if (two_col and ln["x"] >= mid) else 0].append(ln)
        for cid in (0, 1):
            col = sorted(cols[cid], key=lambda l: (round(l["y"]), l["x"]))
            if not col:
                continue
            # merge same-row fragments
            rows = []
            for ln in col:
                if rows and abs(rows[-1][0]["y"] - ln["y"]) <= 3.5:
                    rows[-1].append(ln)
                else:
                    rows.append([ln])
            col_min_x = min(r[0]["x"] for r in rows)
            pending = None  # (text, x) a wrapped title awaiting its leader
            for row in rows:
                row = sorted(row, key=lambda l: l["x"])
                text = " ".join(l["text"] for l in row).strip()
                first = row[0]
                title, num, has_leader = _leader_info(text)
                title = clean_title(title)
                letters = re.sub(r"[^A-Za-z]", "", title)
                if has_leader and len(letters) >= 2:
                    if pending and abs(pending[1] - first["x"]) <= 3:
                        title = clean_title(pending[0] + " " + title)
                    elif pending and pending[1] < first["x"] - 3 and len(pending[0]) < 60:
                        # a leader-less parent heading ("Procedures") followed by
                        # indented children -- it is a section of its own
                        raw.append((clean_title(pending[0]), None, pending[1] - col_min_x, cid))
                    pending = None
                    raw.append((title, num, first["x"] - col_min_x, cid))
                elif has_leader:
                    pending = None  # a bare page-number fragment
                elif first["bold"] or text.startswith("("):
                    pending = None  # group header / "(X - see Y)" cross-reference
                elif len(letters) >= 3:
                    pending = (text, first["x"])
                else:
                    pending = None
            if pending and pending[1] - col_min_x <= 3 and len(pending[0]) < 60:
                raw.append((clean_title(pending[0]), None, pending[1] - col_min_x, cid))
    if len(raw) < 4:
        return [], []
    # levels from column-relative indentation clusters
    xs = sorted({round(r[2]) for r in raw})
    clusters = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= 4:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    def level_of(x):
        for i, c in enumerate(clusters):
            if round(x) in c:
                return i + 1
        return 1
    entries = [
        {"level": level_of(x), "title": t, "printed_page": n}
        for t, n, x, _ in raw
    ]
    return entries, run


def _estimate_offset(matches):
    diffs = [m["page"] - m["printed_page"] for m in matches if m.get("printed_page") is not None and m["matched"]]
    if len(diffs) >= 3:
        return int(round(statistics.median(diffs)))
    return 0


def _token_set(s):
    return set(re.findall(r"[a-z0-9]+", s.lower())) - {"the", "a", "an", "of", "and", "in", "for", "to"}


def anchor_printed_entries(entries, page_lines, toc_pages, body_size, min_match_fraction=0.6):
    """Locate each printed-ToC title in the body, in order. Returns the
    anchored list (only entries that were found) or [] if too few were
    found (the 'ToC' was probably something else, e.g. a figure list)."""
    n_pages = len(page_lines)
    skip = set(toc_pages)
    start_page = (max(toc_pages) + 1) if toc_pages else 0
    # Pass 1: strict, ordered, emphasised-first.
    pos = (start_page, 0)
    results = []
    max_gap = max(30, int(n_pages * 0.25))
    for e in entries:
        found = None
        for pi in range(pos[0], min(n_pages, pos[0] + max_gap + 1)):
            if pi in skip:
                continue
            lines = page_lines[pi]
            s = pos[1] if pi == pos[0] else 0
            # emphasised match first on this page, then any
            hit = find_title_line(e["title"], lines, s, want_bold=True, body_size=body_size)
            if hit is None:
                continue
            found = (pi, hit[0], hit[1], hit[2])
            break
        if found is None:
            # second chance: plain (non-emphasised, non-list) exact match, nearest page first
            for pi in range(pos[0], min(n_pages, pos[0] + max_gap + 1)):
                if pi in skip:
                    continue
                s = pos[1] if pi == pos[0] else 0
                hit = find_title_line(e["title"], page_lines[pi], s, want_bold=False, body_size=body_size)
                if hit is not None:
                    found = (pi, hit[0], hit[1], hit[2])
                    break
        if found:
            body_title = e["title"]
            if found[3] == "full" and found[2] == 1:
                cand = _strip_footnote_digits(clean_title(page_lines[found[0]][found[1]]["text"]).rstrip(":"))
                if 2 < len(cand) <= 120:
                    body_title = cand
            results.append({**e, "title": body_title, "page": found[0] + 1, "line_idx": found[1],
                            "span": found[2], "matched": True, "runin": found[3] == "runin"})
            pos = (found[0], found[1] + found[2])
        else:
            results.append({**e, "page": None, "line_idx": None, "span": 1, "matched": False, "runin": False})
    matched = [r for r in results if r["matched"]]
    if not entries or len(matched) < max(3, min_match_fraction * len(entries)):
        return []
    # Pass 2: fuzzy-locate the unmatched, boxed in by their matched neighbours
    offset = _estimate_offset(matched)
    for k, r in enumerate(results):
        if r["matched"]:
            continue
        prev = next((results[j] for j in range(k - 1, -1, -1) if results[j]["matched"]), None)
        nxt = next((results[j] for j in range(k + 1, len(results)) if results[j]["matched"]), None)
        lo = (prev["page"] - 1, prev["line_idx"] + prev["span"]) if prev else (start_page, 0)
        hi = (nxt["page"] - 1, nxt["line_idx"]) if nxt else (n_pages - 1, 10 ** 9)
        want = _token_set(r["title"])
        if not want:
            continue
        best = None
        for pi in range(lo[0], min(hi[0], n_pages - 1) + 1):
            if pi in skip:
                continue
            for i, ln in enumerate(page_lines[pi]):
                if (pi, i) < lo or (pi, i) >= hi or ln["list_item"]:
                    continue
                if not (ln["bold"] or (body_size is not None and ln["size"] >= body_size + 0.4)):
                    continue
                got = _token_set(ln["text"])
                if not got:
                    continue
                inter = len(want & got)
                score = inter / max(len(want | got), 1)
                if score >= 0.6 and (best is None or score > best[0]):
                    best = (score, pi, i)
        if best:
            r.update({"page": best[1] + 1, "line_idx": best[2], "span": 1, "matched": True, "runin": False})
    # A parent that exists only in the printed ToC ("Procedures" groups the
    # procedure pages, but no page is headed "Procedures") is anchored at
    # its first located child, so the children's heading path is right
    # instead of inheriting whatever section came before.
    for k, r in enumerate(results):
        if r["matched"]:
            continue
        child = None
        for j in range(k + 1, len(results)):
            if results[j]["level"] <= r["level"]:
                break
            if results[j]["matched"]:
                child = results[j]
                break
        if child is not None:
            r.update({"page": child["page"], "line_idx": child["line_idx"], "span": 0,
                      "matched": True, "runin": False, "synthetic": True})
    out = [r for r in results if r["matched"]]
    out.sort(key=lambda r: (r["page"], r["line_idx"]))
    return out


# --------------------------------------------------------------------------
# top-level
# --------------------------------------------------------------------------

def build_section_map(doc, page_lines, num_pages, own, page_width=612.0):
    """Returns {"source": "outline"|"printed", "entries": [...anchored...],
    "toc_pages": set(page indexes to drop)} or None.

    own: True for Ryan's own documents (full outline depth kept); False
    for third-party documents (very deep outlines are trimmed to a depth
    that yields sensibly-sized chunks)."""
    body_size = body_font_size(page_lines)

    outline = outline_entries(doc)
    if outline:
        if not own:
            outline = limit_depth_for_size(outline, num_pages)
        anchored = anchor_outline_entries(outline, page_lines, body_size)
        if len(anchored) >= 3:
            return {"source": "outline", "entries": anchored, "toc_pages": set()}

    printed, toc_pages = parse_printed_toc(page_lines, page_width)
    if printed:
        anchored = anchor_printed_entries(printed, page_lines, toc_pages, body_size)
        if anchored:
            return {"source": "printed", "entries": anchored, "toc_pages": set(toc_pages)}
    return None


# --------------------------------------------------------------------------
# applying the map: path stack + intra-page text splitting
# --------------------------------------------------------------------------

def _path_join(stack):
    return "; ".join(t for _, t in stack) or None


def _push(stack, level, title):
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, title))


def split_page_text(text, page_number, page_lines, anchors, stack_in):
    """Split one page's cleaned plain `text` at the section anchors that
    fall on it.

    anchors: this page's entries in document order. stack_in: heading
    stack in effect at the page start (list of (level, title); mutated
    copy returned). Returns (segments, stack_out) with segments =
    [(heading_path, text)], text possibly empty.

    The heading line itself is dropped from the segment (the heading is
    carried separately as the chunk's section, and echoing it would repeat
    the title). The k-th occurrence of the anchor line's text in the
    dict-order lines maps to the k-th occurrence in the plain text, which
    skips look-alike lines earlier on the page (a bullet list that repeats
    the heading titles)."""
    stack = list(stack_in)
    if not anchors:
        return [(_path_join(stack), text)], stack
    text_lines = text.split("\n")
    text_norms = [norm(l) for l in text_lines]
    segments = []
    cut_from = 0       # first text line of the segment currently being built
    search_from = 0
    cur_path = _path_join(stack)
    for ai, a in enumerate(anchors):
        li = a.get("line_idx")
        cut = None
        drop = 0
        if li is not None and li < len(page_lines):
            tn = norm(page_lines[li]["text"])
            # occurrence index among identical-text lines (list items count:
            # the plain text contains them too)
            k = sum(1 for j in range(li) if norm(page_lines[j]["text"]) == tn)
            seen = -1
            for j, tnorm in enumerate(text_norms):
                if tnorm and (tnorm == tn or (tnorm.startswith(tn) and tnorm[len(tn):].isdigit())):
                    seen += 1
                    if seen == k:
                        if j >= search_from:
                            cut = j
                            drop = a.get("span", 1) if a.get("matched") else 1
                        break
        if cut is None:
            if ai == 0 and not segments and cut_from == 0:
                cut, drop = 0, 0   # cannot place the first anchor: whole page belongs to it
            else:
                continue           # drop a mid-page split rather than guess
        segments.append((cur_path, "\n".join(text_lines[cut_from:cut]).strip()))
        _push(stack, a["level"], a["title"])
        cur_path = _path_join(stack)
        if a.get("runin") and cut < len(text_lines):
            rx = _runin_re(a["title"])
            if rx:
                # "Title: body..." -- keep the body, drop only the title
                text_lines[cut] = rx.sub("", text_lines[cut], count=1)
            drop = 0
        cut_from = cut + drop
        search_from = cut_from
    segments.append((cur_path, "\n".join(text_lines[cut_from:]).strip()))
    return segments, stack


def compute_start_stacks(entries, total_pages):
    """({page: [entries on it, document order]}, {page: heading stack in
    effect at the START of that page}). Walks every page, kept or not, so
    a heading on a page the caller later drops (references, scanned) still
    carries forward to the pages after it."""
    anchors_by_page = {}
    for e in entries:
        anchors_by_page.setdefault(e["page"], []).append(e)
    start_stack = {}
    stack = []
    for pn in range(1, total_pages + 1):
        start_stack[pn] = list(stack)
        for e in anchors_by_page.get(pn, []):
            _push(stack, e["level"], e["title"])
    return anchors_by_page, start_stack
