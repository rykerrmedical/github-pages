"""
Real titles for referenced PDFs.

Why this exists: a citation card ("Cited in Rykerr Medical's Vent Management
Guide...") used to be titled from its reference page's FILENAME, so
Tobin2010.md showed up as "Tobin2010" even though the PDF it points to is
titled "Ventilator-induced respiratory muscle weakness". Ingested PDFs had a
similar gap: when a PDF's embedded /Title is empty or junk ("untitled",
"TA501942 434..439") the card fell back to a file name.

How it works:
  * The title comes from the PDF itself: its embedded title when that looks
    real, otherwise the large title heading printed on page 1.
  * A one-time pass (`python reference_titles.py`) reads each reference page's
    archive.org PDF and writes curation/reference_titles.json. Results are
    cached; later runs only look at PDFs it hasn't seen. Open the JSON to read
    or fix any title -- a hand-edited title (or "manual": true) is never overwritten, and a
    line in curation/title_overrides.txt (URL = Title) beats everything.
  * build_index.py uses the cache for citation cards and to repair junk titles
    on ingested PDFs. Nothing is downloaded during a normal build.

Run it:   python reference_titles.py            (new PDFs only)
          python reference_titles.py --refresh  (redo everything not manual)
          python reference_titles.py --dry-run  (show what it would fetch)
          python reference_titles.py --redo-heading (re-read only titles that look corrupted; hand edits are never touched)
          python reference_titles.py --tidy     (clean cached titles, no download)
          python reference_titles.py --report   (list titles worth a look)
          python reference_titles.py --set NAME "Title"  (fix one by hand, locked)
"""
import html
import json
import re
import sqlite3
import sys
import time
import urllib.parse as urlparse
from pathlib import Path

CACHE_PATH = Path(__file__).resolve().parent / "curation" / "reference_titles.json"
REFERENCES_HOST = "references.rykerrmedical.com"

_JUNK_START_RE = re.compile(
    r"^(untitled|microsoft (word|powerpoint|excel)\b|document\d*\b|presentation\d*\b|slide \d|"
    r"new document|no title|title\b|acrobat|adobe|pdf\b|scan\b|image\d*\b)",
    re.IGNORECASE,
)
_FILE_EXT_RE = re.compile(r"\.(pdf|docx?|dvi|indd|qxd|tex|pptx?|xlsx?|rtf|txt|ps|eps|fm|pm6?)\b", re.IGNORECASE)
_CODE_START_RE = re.compile(r"^[A-Za-z]{1,4}[-_ ]?\d{3,}")

# Lines at the top of a first page that are printed in big type but are not the
# title: public-access banners, journal mastheads, article-type labels.
_BANNER_RE = re.compile(
    r"nih[- ]?pa\b|public access|author manuscript|hhs\b|europe pmc|available in pmc|published in final|"
    r"copyright|©|all rights reserved|downloaded from|https?:|www\.|doi:|^\s*vol\b|volume\s+\d|issn|"
    r"original (article|research|investigation|contribution)s?\b|research (article|paper|letter)s?\b|"
    r"review article|special article|clinical (investigation|review|practice)s?\b|brief (report|communication)s?\b|"
    r"case report|^\s*editorial|^\s*commentary|^\s*perspective|practice guideline|^\s*abstract\s*$|open access|"
    r"^\s*review\s*$|^\s*article\s*$|^\s*articles\s*$|^\s*critical care\s*$|^\s*journal\b|\bjournal of\b|"
    r"\bannals of\b|new england journal|\bthe lancet\b|^\s*chest\s*$|respiratory care\s*$|"
    r"intensive care medicine\s*$|critical care medicine\s*$|bmc\b|plos|frontiers in|^\s*page \d|^\s*\d+\s*$|"
    r"^\s*htt|\S/\S*/|online version|can be found at|^\s*brand:|no slide title|^\s*slide \d",
    re.IGNORECASE,
)


_PRIVATE_RE = re.compile(r"[\ue000-\uf8ff\ufffd\x00-\x08\x0b-\x1f\x7f]")
# a trailing site/publisher name glued on by a web page's <title>
_SITE_SUFFIXES = (
    "Deranged Physiology", "Physiopedia", "VBM Medizintechnik GmbH", "The Airway Jedi", "Airway Jedi",
    "LITFL", "Life in the Fast Lane", "WikEM", "EMCrit", "EMCrit Project", "Medscape", "StatPearls",
    "NCBI Bookshelf", "PubMed", "PMC", "Wikipedia", "UpToDate", "ScienceDirect", "Springer", "Wiley Online Library",
    "Nature", "Cleveland Clinic", "Mayo Clinic", "CDC", "WHO", "NIH",
)
_SITE_SUFFIX_RE = re.compile(
    r"\s+[-\u2013\u2014|:]\s+(?:%s)\s*$" % "|".join(re.escape(x) for x in sorted(_SITE_SUFFIXES, key=len, reverse=True)),
    re.IGNORECASE,
)
_PIPE_SUFFIX_RE = re.compile(r"^(.{15,}?)\s+\|\s+[^|]{2,60}$")
# "g" / "h" left over from glyphs that overlap the title line (not "a", not "I")
_STRAY_LETTER_RE = re.compile(r"(?<![\w'\u2019\-/.])[b-hj-z](?![\w'\u2019\-/])")
# "Kemouna,b, Alexandre Demoulea,b and ..." superscript affiliation letters
_SUPERSCRIPT_LIST_RE = re.compile(r"[a-z],[a-z](?:\b|,)")


def tidy_title(title):
    """Cleans a title taken from PDF metadata or a web page: decodes HTML
    entities, drops private-use/control characters, collapses spaces and strips
    a trailing site name (" | Deranged Physiology", " - Physiopedia")."""
    t = html.unescape(title or "")
    t = _PRIVATE_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" .\u2022*")
    t = re.sub(r"^published (online|in final edited form)\b:?\s*(\d{4}\s+[A-Za-z]+\.?\s+\d{1,2}|[A-Za-z]+\.?\s+\d{1,2},?\s*\d{4})\s*\.?\s*",
               "", t, flags=re.IGNORECASE)
    for _ in range(2):
        t = _SITE_SUFFIX_RE.sub("", t).strip()
        m = _PIPE_SUFFIX_RE.match(t)
        if m:
            t = m.group(1).strip()
    return t


def title_problem(title):
    """Why a title looks corrupted rather than real ('' if it looks fine):
    stray glyph letters, an author line, a masthead fragment."""
    t = title or ""
    if _PRIVATE_RE.search(t) or "&#" in t or re.search(r"&[a-z]{2,6};", t):
        return "bad characters"
    if looks_garbled(t):
        return "garbled"
    if _STRAY_LETTER_RE.search(t):
        return "stray letter"
    if _AUTHORISH_RE.search(t) or _SUPERSCRIPT_LIST_RE.search(t):
        return "author line"
    if re.search(r"published online|supplement from|^\s*supplement\b", t, re.IGNORECASE):
        return "masthead text"
    if _SITE_SUFFIX_RE.search(t):
        return "site suffix"
    return ""


def is_junk_title(title):
    """True for an embedded /Title that is empty, a placeholder, a file name or
    an internal code rather than a real title."""
    t = (title or "").strip()
    if len(t) < 8:
        return True
    if title_problem(t) in ("bad characters", "author line", "masthead text", "garbled"):
        return True
    if _JUNK_START_RE.match(t) or _FILE_EXT_RE.search(t) or _CODE_START_RE.match(t):
        return True
    if " " not in t and re.search(r"[\d_]", t):  # one token with digits/underscores: Tobin2010
        return True
    # an Author-Year file name used as a title: "O'Shea 2017", "Panos, 2018 - Ketamine"
    if len(t) < 45 and re.match(r"^[A-Z][A-Za-z'\-]+,?\s+(et al\.?,?\s*)?\d{4}[a-z]?(\s*[-–]\s*\S.*)?$", t):
        return True
    letters = sum(c.isalpha() for c in t)
    return letters < 0.5 * len(t)


def _clean(text):
    text = _PRIVATE_RE.sub("", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" .•*")


_COMMON_WORDS = {"of", "the", "in", "and", "for", "with", "to", "on", "a", "an", "is", "by", "from", "after", "during"}
_LABEL_RE = re.compile(
    r"^\s*(management\s*&\s*practice|case conferences?|\+?\s*supplemental content|acog practice bulletin|"
    r"practice bulletin|opinion|editorial|commentary|perspective|review|continuing education|"
    r"clinical (focus|scenario|vignette)|current opinion.*|research in .*: an international journal)\s*$",
    re.IGNORECASE,
)
_LEADING_LABEL_RE = re.compile(r"^(opinion|review|editorial|original article|special article|commentary)\s+(?=[A-Za-z])", re.IGNORECASE)
# "Thomas Luecke1and Paolo Pelosi2", "David R Stather1and Thomas E Stewart2": an author line
_AUTHORISH_RE = re.compile(r"[A-Za-z]\d+\s*(and\b|,|$)|\b[A-Z][a-z]+\s+[A-Z]\.?\s*[A-Z][a-z]+\d|[a-z],[a-z](?:\b|,)")
_DANGLING_END_RE = re.compile(r"(\b(to|of|in|the|and|for|with|a|an|on|after|by|from|vs\.?|versus|during|through|"
                              r"construction and|the so-called)|[:\u2014\u2013,-])\s*$", re.IGNORECASE)


def looks_garbled(text):
    """Text from a PDF with a broken font encoding ("@CCQDRRHMF QDROHQ@SNQX")."""
    t = text or ""
    if re.search(r"[A-Za-z][@\[\]\\^_`{|}][A-Za-z]|[@\[\]\\^_`{|}][A-Za-z]{2,}", t):
        return True
    letters = [c for c in t.lower() if c.isalpha()]
    if len(letters) >= 10:
        vowels = sum(c in "aeiouy" for c in letters)
        if vowels / len(letters) < 0.22:
            return True
    return False


def decode_shifted(text):
    """Some PDFs map every character one code point down ("A@RHB" = "BASIC").
    Shift each character back up one; accept only when the result reads as
    English (no stray symbols, normal vowel share, a common small word)."""
    out = "".join(chr(ord(c) + 1) if c != " " else " " for c in (text or ""))
    if looks_garbled(out) or re.search(r"[^A-Za-z0-9 ,.:;()&'\-]", out):
        return None
    words = set(re.findall(r"[a-z]+", out.lower()))
    if not (words & _COMMON_WORDS):
        return None
    return out.capitalize() if out.isupper() else out


def _gap(a_bottom, b_top):
    return b_top - a_bottom


def heading_title(doc):
    """The title printed at the top of page 1: the largest-type text that is not
    a banner/masthead/label/author line, joined across its wrapped lines. None
    if nothing plausible turns up."""
    try:
        page = doc[0]
        data = page.get_text("dict")
        page_h = float(page.rect.height) or 800.0
    except Exception:
        return None

    lines = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for ln in block.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            txt = _clean("".join(s["text"] for s in spans))
            if not txt:
                continue
            size = max(float(s.get("size", 0)) for s in spans)
            top, bottom = float(ln["bbox"][1]), float(ln["bbox"][3])
            if top > page_h * 0.65:
                continue
            lines.append({"text": txt, "size": size, "top": top, "bottom": bottom,
                          "bbox": ln["bbox"]})
    lines.sort(key=lambda l: (round(l["top"]), l["top"]))
    if not lines:
        return None

    def _banner(txt):
        return bool(_BANNER_RE.search(txt) or _LABEL_RE.match(txt))

    def _line_text(l):
        """Re-read one line with the PDF's own word spacing (joining spans
        loses spaces in some PDFs). The re-read is used only when it holds
        exactly the same letters as the line's own spans: a clip box also picks
        up glyphs from neighbouring lines, which corrupted titles."""
        try:
            import pymupdf
            r = pymupdf.Rect(l["bbox"])
            r = pymupdf.Rect(r.x0 - 1, r.y0 - 0.5, r.x1 + 1, r.y1 + 0.5)
            t = _clean(page.get_text("text", clip=r).replace("\n", " "))
            if t and _squash(t) == _squash(l["text"]):
                return t
        except Exception:
            pass
        return l["text"]

    tried = set()
    for _ in range(6):
        candidates = [l for l in lines
                      if id(l) not in tried and len(l["text"]) >= 12 and not _banner(l["text"])
                      and not _AUTHORISH_RE.search(l["text"])]
        if not candidates:
            return None
        anchor = max(candidates, key=lambda l: (round(l["size"], 1), -l["top"]))
        tried.add(id(anchor))

        idx = lines.index(anchor)
        parts = [anchor]
        j = idx - 1
        while j >= 0:
            l = lines[j]
            if abs(l["size"] - anchor["size"]) <= 1.0 and _gap(l["bottom"], parts[0]["top"]) < 1.4 * anchor["size"] \
                    and not _banner(l["text"]) and not _AUTHORISH_RE.search(l["text"]):
                parts.insert(0, l)
                j -= 1
            else:
                break
        j = idx + 1
        while j < len(lines):
            l = lines[j]
            if abs(l["size"] - anchor["size"]) <= 1.0 and _gap(parts[-1]["bottom"], l["top"]) < 1.4 * anchor["size"] \
                    and not _banner(l["text"]) and not _AUTHORISH_RE.search(l["text"]):
                parts.append(l)
                j += 1
            else:
                break

        def _join(ps):
            out = _line_text(ps[0])
            for p in ps[1:]:
                nxt = _line_text(p)
                if out.endswith("-") and nxt[:1].islower():
                    out += nxt
                else:
                    out += " " + nxt
            return _clean(out)

        out = _join(parts)
        # a title that stops on "of"/"and"/":" is cut off: take up to two more
        # lines below it that are nearly as large
        extra = 0
        while _DANGLING_END_RE.search(out) and extra < 2:
            k = lines.index(parts[-1]) + 1
            if k >= len(lines):
                break
            l = lines[k]
            if l["size"] >= 0.75 * anchor["size"] and _gap(parts[-1]["bottom"], l["top"]) < 1.8 * anchor["size"] \
                    and not _banner(l["text"]) and not _AUTHORISH_RE.search(l["text"]):
                parts.append(l)
                out = _join(parts)
                extra += 1
            else:
                break

        out = _LEADING_LABEL_RE.sub("", out).strip()
        if looks_garbled(out):
            fixed = decode_shifted(out)
            if fixed:
                out = fixed
            else:
                continue
        out = tidy_title(out)
        if len(out) < 12 or len(out) > 300 or is_junk_title(out) or _banner(out) or title_problem(out):
            continue
        return out
    return None


def archive_filename_title(url):
    """A readable title from an archive.org file name, when the name is real
    words (Principles_and_Practice_of_Mechanical_Ventilation_3rd_Tobin.pdf) and
    not just Author+Year (Tobin2010.pdf)."""
    name = urlparse.unquote(urlparse.urlsplit(url or "").path.rsplit("/", 1)[-1])
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    name = re.sub(r"[_]+", " ", name).strip()
    # Author+Year names (Tobin2010, Bishop2022_Vent_Book) are Ryan's own
    # reference-style names, not a book's real title: no filename title.
    if re.match(r"^[A-Za-z'\-]+[ ,]*\d{4}[a-z]?\b", name) or is_junk_title(name):
        return None
    return name


def pdf_title_candidates(pdf_bytes):
    """(embedded_title_or_None, heading_title_or_None) for a PDF's bytes."""
    import pymupdf
    meta_title, heading = None, None
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return None, None
    try:
        meta_title = ((doc.metadata or {}).get("title") or "").strip() or None
        heading = heading_title(doc)
    finally:
        doc.close()
    return meta_title, heading


_TRAILING_TAG_RE = re.compile(
    r"\s*[\(\[](review|original article|original research|research article|systematic review|"
    r"update|full text|article)[\)\]]\s*$",
    re.IGNORECASE,
)


def _squash(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _agree(meta, heading):
    """Do the embedded title and the printed heading name the same paper? True
    when one contains the other once spaces/punctuation are ignored (PDF text
    often loses its spaces) or they share most of their words."""
    a, b = _squash(meta), _squash(heading)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    wa = set(re.findall(r"[a-z]{4,}", meta.lower()))
    wb = set(re.findall(r"[a-z]{4,}", heading.lower()))
    return bool(wa and wb) and len(wa & wb) >= 0.5 * min(len(wa), len(wb))


def _sane_heading(heading):
    if not heading:
        return None
    heading = _TRAILING_TAG_RE.sub("", heading).strip()
    words = heading.split()
    if len(heading) > 220 or (heading.endswith(".") and len(words) >= 15):
        return None  # a sentence or citation, not a title
    return heading or None


def best_title(pdf_bytes, url):
    """Title for a freshly downloaded PDF: the real embedded title, else the
    page-1 heading, else a readable archive file name, else None (caller falls
    back). When the embedded title is a short generic label that disagrees with
    a longer printed heading ("Austere Medicine" on a WHO manual titled "Medical
    evacuation in emergencies"), the heading wins; the cache keeps the embedded
    one for review."""
    meta, heading = pdf_title_candidates(pdf_bytes)
    heading = _sane_heading(heading)
    meta = tidy_title(meta) if meta else meta
    if meta and (title_problem(meta) and title_problem(meta) != "site suffix"):
        meta = None
    if meta and not is_junk_title(meta):
        meta = _TRAILING_TAG_RE.sub("", meta).strip()
        if heading and not _agree(meta, heading) and len(meta.split()) <= 3 and len(heading.split()) >= 4:
            return heading, "heading"
        return meta, "metadata"
    if heading:
        return heading, "heading"
    fn = archive_filename_title(url)
    if fn:
        return fn, "filename"
    return None, "none"


# ---------------------------------------------------------------- cache

_cache = None


def load_cache(path=None):
    global _cache
    p = Path(path) if path else CACHE_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _cached():
    global _cache
    if _cache is None:
        _cache = load_cache()
    return _cache


def save_cache(cache, path=None):
    stamp_auto(cache)
    p = Path(path) if path else CACHE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def title_for(key):
    """Cached title for a citation target URL or a PDF URL, or None."""
    e = _cached().get(key)
    return (e or {}).get("title") or None


def retitle_junk_pdfs(conn):
    """Repairs ingested PDFs whose stored title is junk, from the cache (no
    download). Returns how many sources changed."""
    changed = 0
    rows = conn.execute(
        "SELECT DISTINCT source_id, source_title FROM chunks WHERE source_type='pdf'"
    ).fetchall()
    for source_id, title in rows:
        if not (is_junk_title(title) or title_problem(title)):
            continue
        new = title_for(source_id)
        if new and new != title:
            conn.execute("UPDATE chunks SET source_title=? WHERE source_id=?", (new, source_id))
            changed += 1
    if changed:
        conn.commit()
    return changed


# ---------------------------------------------------------------- the pass

def _fetch(url):
    import pdf_ingest
    # archive.org/details/<item>/<file> is the viewer page, not the PDF.
    return pdf_ingest.download_pdf(url.replace("archive.org/details/", "archive.org/download/"))


def run_pass(refresh=False, dry_run=False, db_path=None, fetch=None, refs_root=None, sleep=0.4, redo_heading=False):
    import config
    import curation
    import reference_citations

    fetch = fetch or _fetch
    cache = load_cache()
    try:  # never lose hand edits: keep the file as it was before this run
        if CACHE_PATH.exists():
            (CACHE_PATH.parent / (CACHE_PATH.name + ".bak")).write_bytes(CACHE_PATH.read_bytes())
    except OSError:
        pass
    print("tidied %d cached title(s)" % tidy_cache(cache))
    overrides = {}
    try:
        overrides = curation.load_title_overrides()
    except Exception:
        pass

    work = []  # (cache_key, pdf_url, label)
    by_permalink, _, stats = reference_citations.build_reference_index(refs_root or config.REFERENCES_REPO_ROOT)
    for permalink, entry in sorted(by_permalink.items()):
        if entry.get("pdf_link"):
            work.append(("https://%s%s" % (REFERENCES_HOST, permalink), entry["pdf_link"], entry["title_guess"]))
    db = Path(db_path or config.OUTPUT_DB_PATH)
    if db.exists():
        conn = sqlite3.connect(str(db))
        try:
            for source_id, title in conn.execute(
                "SELECT DISTINCT source_id, source_title FROM chunks WHERE source_type='pdf'"
            ).fetchall():
                if is_junk_title(title):
                    work.append((source_id, source_id, title))
        finally:
            conn.close()

    todo = []
    for key, url, label in work:
        cur = cache.get(key) or {}
        if is_hand_edited(cur):
            continue
        if key in overrides or url in overrides:
            cache[key] = {"title": overrides.get(key) or overrides.get(url), "source": "override", "pdf": url}
            continue
        if cur.get("title") and cur.get("pdf") == url and not refresh \
                and not (redo_heading and title_problem(cur.get("title"))):
            continue
        todo.append((key, url, label))

    print("%d reference/PDF item(s) with a PDF; %d need a title lookup" % (len(work), len(todo)))
    if dry_run:
        for key, url, label in todo[:40]:
            print("  would read", url)
        return cache

    got = {"metadata": 0, "heading": 0, "filename": 0, "none": 0, "failed": 0}
    for n, (key, url, label) in enumerate(todo, 1):
        data = fetch(url)
        if data is None:
            # too big for the PDF size cap, or unreachable: a readable archive
            # file name is the only thing left.
            fn = archive_filename_title(url)
            if fn:
                cache[key] = {"title": fn, "source": "filename", "pdf": url}
                got["filename"] += 1
            else:
                got["failed"] += 1
            continue
        title, source = best_title(data, url)
        got[source] = got.get(source, 0) + 1
        if title:
            cache[key] = {"title": title, "source": source, "pdf": url}
        elif cache.get(key) and title_problem(cache[key].get("title")):
            cache.pop(key)  # corrupted and nothing better found: fix it by hand
            print("  NEEDS A MANUAL TITLE: %s" % url)
        if n % 20 == 0:
            save_cache(cache)
            print("  ...%d/%d" % (n, len(todo)))
        time.sleep(sleep)
    save_cache(cache)
    report_suspicious(cache)

    print("Done. metadata=%d heading=%d filename=%d none=%d failed/skipped=%d" % (
        got["metadata"], got["heading"], got["filename"], got["none"], got["failed"]))
    print("Review curation/reference_titles.json (lines with source heading/filename are guesses);")
    print("Edit any title there by hand: the script remembers what it wrote (\"auto\") and never")
    print("overwrites a title that differs from it. A .bak copy is kept on every run.")
    return cache


def is_hand_edited(entry):
    """True when a person set this title: it is flagged "manual", or its title no
    longer equals the "auto" title this script last wrote there. Such entries
    are never touched by any run, flagged or not."""
    e = entry or {}
    if e.get("manual"):
        return True
    return "auto" in e and (e.get("title") or "") != e["auto"]


def stamp_auto(cache):
    """Records, for every entry the script wrote, the title it wrote, so a later
    hand edit can be told apart from the script's own output."""
    for v in cache.values():
        if not is_hand_edited(v) and v.get("title"):
            v["auto"] = v["title"]


def tidy_cache(cache):
    """Re-cleans every non-manual cached title (entities, site suffixes,
    control characters). Returns how many changed."""
    n = 0
    for k, v in cache.items():
        if is_hand_edited(v) or not v.get("title"):
            continue
        t = tidy_title(v["title"])
        if t and t != v["title"]:
            v["title"] = t
            n += 1
    return n


def set_manual(name, title):
    """python reference_titles.py --set Woodruff2007 "The real title": sets the
    title for the one reference whose key contains NAME and locks it
    ("manual": true), so no later run overwrites it."""
    cache = load_cache()
    needle = name.lower().replace(".html", "")
    keys = [k for k in cache if k.rsplit("/", 1)[-1].lower().replace(".html", "") == needle] \
        or [k for k in cache if needle in k.lower()]
    if len(keys) != 1:
        print("%d reference(s) match %r%s" % (len(keys), name, (": " + ", ".join(k.rsplit("/", 1)[-1] for k in keys[:8])) if keys else ""))
        return False
    k = keys[0]
    cache[k] = dict(cache[k], title=title.strip(), source="manual", manual=True)
    save_cache(cache)
    print("set %s -> %s" % (k.rsplit("/", 1)[-1], title.strip()))
    return True


def report_suspicious(cache):
    """Prints titles worth a human look: the same title on two different
    references (one reference page probably links the wrong PDF), and titles
    that look cut off or too short."""
    by_title = {}
    for k, v in cache.items():
        by_title.setdefault((v.get("title") or "").strip().lower(), []).append(k)
    dups = {t: ks for t, ks in by_title.items() if t and len(ks) > 1}
    odd = [(k, v["title"]) for k, v in cache.items()
           if not is_hand_edited(v) and v.get("title")
           and (len(v["title"]) < 18 or _DANGLING_END_RE.search(v["title"]))]
    bad = [(k, v["title"], title_problem(v["title"])) for k, v in cache.items()
           if not is_hand_edited(v) and v.get("title") and title_problem(v["title"])]
    if bad:
        print("\nLOOK CORRUPTED (fix with --set):")
        for k, t, why in sorted(bad):
            print("  %s | %s   [%s]" % (k.rsplit("/", 1)[-1], t, why))
    if dups:
        print("\nSAME TITLE ON SEVERAL REFERENCES (check their PDF links):")
        for t, ks in sorted(dups.items()):
            print("  %r  <-  %s" % (t[:70], ", ".join(k.rsplit("/", 1)[-1] for k in ks)))
    if odd:
        print("\nLOOK SHORT OR CUT OFF:")
        for k, t in sorted(odd):
            print("  %s | %s" % (k.rsplit("/", 1)[-1], t))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if "--set" in sys.argv:
        i = sys.argv.index("--set")
        if len(sys.argv) < i + 3:
            print('usage: python reference_titles.py --set NAME "The real title"')
        else:
            set_manual(sys.argv[i + 1], sys.argv[i + 2])
    elif "--tidy" in sys.argv:
        c = load_cache()
        print("tidied %d title(s)" % tidy_cache(c))
        save_cache(c)
        report_suspicious(c)
    elif "--report" in sys.argv:
        report_suspicious(load_cache())
    else:
        run_pass(refresh="--refresh" in sys.argv, dry_run="--dry-run" in sys.argv,
                 redo_heading="--redo-heading" in sys.argv)
