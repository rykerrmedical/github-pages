"""Dry-run the ToC section map on local PDFs: python3 toc_probe2.py file.pdf [own|ext] [-v]"""
import sys, re, pymupdf
import toc_sections as T

def run(path, own, verbose):
    doc = pymupdf.open(path)
    n = len(doc)
    page_lines, texts = [], []
    width = doc[0].rect.width
    for p in doc:
        page_lines.append(T.lines_from_page_dict(p.get_text("dict")))
        texts.append(p.get_text())
    m = T.build_section_map(doc, page_lines, n, own, width)
    print(f"== {path.split('/')[-1][:60]} pages={n} own={own}")
    if not m:
        print("  no section map (fallback to font heuristic)"); return
    ents = m["entries"]
    print(f"  source={m['source']} entries={len(ents)} toc_pages={sorted(p+1 for p in m['toc_pages'])}")
    if verbose:
        for e in ents[:400]:
            print(f"   L{e['level']} p{e['page']:>3} li={e['line_idx']} {'ok ' if e.get('matched') else '?? '}{e['title'][:60]}")
    by_page = {}
    for e in ents:
        by_page.setdefault(e["page"], []).append(e)
    stack, secs = [], []
    for pi in range(n):
        if pi in m["toc_pages"]:
            continue
        segs, stack = T.split_page_text(texts[pi], pi + 1, page_lines[pi], by_page.get(pi + 1, []), stack)
        for path_, t in segs:
            if not t.strip(): continue
            if secs and secs[-1][0] == path_:
                secs[-1][1] += len(t.split()); secs[-1][3] = pi + 1
            else:
                secs.append([path_, len(t.split()), pi + 1, pi + 1])
    words = [s[1] for s in secs]
    print(f"  sections={len(secs)} median words={sorted(words)[len(words)//2]} min={min(words)} max={max(words)} tiny(<30)={sum(1 for w in words if w<30)}")
    if verbose:
        for s in secs[:300]:
            print(f"   p{s[2]}-{s[3]} {s[1]:>5}w  {s[0]}")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    run(args[0], (args[1] if len(args) > 1 else "ext") == "own", "-v" in sys.argv)
