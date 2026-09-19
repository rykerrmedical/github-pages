"""
One-off diagnostic — NOT part of the pipeline. Runs the full new
citation pipeline (extract_citation_blurbs -> resolve_entry_links ->
reference_citations.resolve_link / fuzzy_match_label) against real page
64 and real page 211 text pulled straight from the live index, using the
real hyperlink data citation_link_probe.py already confirmed for those
same two pages — so this checks the whole chain end-to-end against real
data without needing to re-download or re-open the PDF.

Usage (from search-indexer/, in your normal venv):
    python citation_pipeline_test.py
"""
import pdf_ingest
import reference_citations as rc

# Real page 64 text (from dump_page_text.py against the live index).
PAGE_64_TEXT = (
    "consequences.127 To expand on this idea just a bit before we move on, "
    "one specific argument against a high FiO2 is the idea of absorption "
    "atelectasis – the closing of alveoli related to nitrogen washout and "
    "the fact that oxygen quickly diffuses into the bloodstream leaving "
    "less gas in the alveoli.128 While the clinical impact of this "
    "sequence of events is up for debate and may not actually make a "
    "difference, it is something that comes up in the discussion of "
    "ventilated patients.129 129 Yartsev, 2023h - This article both sheds "
    "some doubt on the idea of absorption atelectasis and describes many "
    "of the other mechanisms by which oxygen can adversely affect our "
    "patients 128 Dunphy, 2012 - Short video that explains both the "
    "mechanism of absorption atelectasis and how patient effort can "
    "mitigate the effect 127 Kallet & Branson, 2016 - This article looks "
    "at both why it may make sense to limit oxygenation and how the "
    "negative consequences of oxygen may be exaggerated; we also have a "
    "video on this concept - Oxygen Haterz 126 Murphy, 2017b; Macintyre, "
    "2014 - And to review the different types of hypoxia, take a look at "
    "this video"
)

# Real link list for page 64 (from citation_link_probe.py's actual output
# against the real PDF — trimmed to just uri+label, dropping the youtu.be
# one since it's not a citation label match target here).
PAGE_64_LINKS = [
    ("Yartsev, 2023h", "https://references.rykerrmedical.com/Yartsev2019Oxygen.html"),
    ("Dunphy, 2012", "https://references.rykerrmedical.com/Dunphy2012.html"),
    ("Kallet & Branson, 2016", "https://references.rykerrmedical.com/Kallet2016.html"),
    ("Murphy, 2017b;", "http://references.rykerrmedical.com/Murphy2017.html"),
    ("Macintyre, 2014", "http://references.rykerrmedical.com/Macintyre2014.html"),
    ("Desai, 2012", "https://references.rykerrmedical.com/Desai2012.html"),
]

# Real page 211 text + links.
PAGE_211_TEXT = (
    "There is also some concern about the effect benzos can have on "
    "weaning and their contribution to ICU delirium.487 487 Skrobik, "
    "2012 - This opinion piece is in favor of benzodiazepines for "
    "sedation of mechanically ventilated patients, but it does review "
    "and address many of the concerns that folks have with this "
    "strategy 486 Adams & friends, 1985 - Older paper that first "
    "investigated this idea using mega-doses of midazolam on dogs 485 "
    "Fuller & friends, 2019 - This review attempted to collate data on "
    "ketamine use with intubated patients, it found"
)
PAGE_211_LINKS = [
    ("Skrobik, 2012", "http://references.rykerrmedical.com/Skrobik2012_Benzos_Vented_Pts.html"),
    ("Adams & friends, 1985", "http://references.rykerrmedical.com/Adams1985_Midazolam_Hypovolemia.html"),
    ("Fuller & friends, 2019", "http://references.rykerrmedical.com/Fuller2020_Ketamine_Mechanical_Ventilation.html"),
]


def run_page(label, text, links):
    print(f"=== {label} ===")
    clean_text, entries = pdf_ingest.extract_citation_blurbs(text)
    print(f"  {len(entries)} entries found, clean text {len(clean_text)} chars "
          f"(was {len(text)})")
    for entry in entries:
        entry["links"] = pdf_ingest.resolve_entry_links(entry, links)
        print(f"  #{entry['number']} {entry['label']!r} -> links: {entry['links']}")
        print(f"      blurb: {entry['blurb'][:80]!r}...")
    print()
    return entries


def main():
    by_permalink, by_author_year, stats = rc.build_reference_index("../../rykerr-references")
    print(f"Reference index: {len(by_permalink)} permalinks, from {stats['pages_scanned']} files\n")

    all_entries = []
    all_entries += run_page("Page 64", PAGE_64_TEXT, PAGE_64_LINKS)
    all_entries += run_page("Page 211", PAGE_211_TEXT, PAGE_211_LINKS)

    print("=== Resolution ===")
    for entry in all_entries:
        if entry["links"]:
            for uri in entry["links"]:
                citation_id, ref_entry = rc.resolve_link(uri, by_permalink)
                if citation_id and ref_entry:
                    print(f"  {entry['label']!r} -> EXACT LINK -> {citation_id} "
                          f"(category={ref_entry['category']}, title_guess={ref_entry['title_guess']!r})")
                elif citation_id:
                    print(f"  {entry['label']!r} -> EXTERNAL LINK -> {citation_id}")
                else:
                    print(f"  {entry['label']!r} -> link {uri} didn't resolve, falling back to fuzzy match")
                    match = rc.fuzzy_match_label(entry["label"], by_author_year, entry["blurb"])
                    print(f"      fuzzy match -> {match}")
        else:
            print(f"  {entry['label']!r} -> NO LINK, fuzzy matching")
            match = rc.fuzzy_match_label(entry["label"], by_author_year, entry["blurb"])
            print(f"      fuzzy match -> {match}")


if __name__ == "__main__":
    main()
