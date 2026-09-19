"""
Domain synonym/acronym expansion for search queries.

Why this exists: bi-encoder cosine similarity (and, to a lesser extent,
the cross-encoder reranker) scores on the words actually present in the
query and the chunk. A query for "ARDS" and a chunk that only ever says
"lung injury" can be topically identical and clinically synonymous while
still sharing almost no vocabulary — that's a real gap we hit (the vent
book's Lung Injury/ARDS section wasn't surfacing for an ARDS query at
all). Rather than requiring Ryan to manually find and point at every such
section per query, this bakes the domain knowledge in once, as data: a
glossary of EMS/critical-care acronyms and their expansions, applied
automatically to every query before embedding.

This is deliberately a plain data table, not a model — cheap, fully
inspectable, and trivial to extend. Grow _MEDICAL_SYNONYMS as new gaps
turn up (new acronym, or an existing term that needs another phrasing);
nothing else about the pipeline needs to change.
"""
import re

# canonical acronym -> list of expansions to append when it appears in a query.
# Keys are matched case-insensitively with word boundaries (so "MI" won't
# match inside "minute" but will match "mi" or "MI" as a standalone word).
_MEDICAL_SYNONYMS = {
    "ARDS": ["acute respiratory distress syndrome", "acute lung injury", "lung injury"],
    "COPD": ["chronic obstructive pulmonary disease"],
    "CHF": ["congestive heart failure", "heart failure"],
    "MI": ["myocardial infarction", "heart attack"],
    "STEMI": ["ST elevation myocardial infarction", "heart attack"],
    "NSTEMI": ["non-ST elevation myocardial infarction"],
    "CVA": ["stroke", "cerebrovascular accident"],
    "TIA": ["transient ischemic attack", "mini stroke"],
    "DKA": ["diabetic ketoacidosis"],
    "PE": ["pulmonary embolism"],
    "DVT": ["deep vein thrombosis"],
    "ETT": ["endotracheal tube"],
    "ETI": ["endotracheal intubation"],
    "RSI": ["rapid sequence intubation"],
    "GCS": ["Glasgow Coma Scale"],
    "ROSC": ["return of spontaneous circulation"],
    "TBI": ["traumatic brain injury"],
    "ICP": ["intracranial pressure"],
    "SVT": ["supraventricular tachycardia"],
    "VT": ["ventricular tachycardia"],
    "VF": ["ventricular fibrillation"],
    "PEA": ["pulseless electrical activity"],
    "PEEP": ["positive end-expiratory pressure"],
    "PIP": ["peak inspiratory pressure"],
    "FiO2": ["fraction of inspired oxygen"],
    "SpO2": ["oxygen saturation", "pulse ox"],
    "ETCO2": ["end-tidal carbon dioxide", "capnography"],
    "NIV": ["non-invasive ventilation"],
    "BiPAP": ["bilevel positive airway pressure"],
    "CPAP": ["continuous positive airway pressure"],
    "AMS": ["altered mental status"],
    "SOB": ["shortness of breath"],
    "DIB": ["difficulty in breathing", "shortness of breath"],
    "POCUS": ["point of care ultrasound"],
    "IO": ["intraosseous"],
    "OPA": ["oropharyngeal airway"],
    "NPA": ["nasopharyngeal airway"],
    "LMA": ["laryngeal mask airway"],
    "ACS": ["acute coronary syndrome"],
    # Shorthand for a WORD rather than a diagnosis/procedure name — the
    # gap Ryan flagged directly: "tx for a PE" should still find a
    # pulmonary embolism TREATMENT section even though "tx" isn't a
    # diagnosis acronym like the rest of this glossary. TX is genuinely
    # ambiguous in EMS charting (treatment vs. transport), so both are
    # listed rather than guessing one.
    "TX": ["treatment", "transport"],
    "DX": ["diagnosis"],
    "HX": ["history"],
    "SX": ["symptoms"],
    "RX": ["prescription", "treatment"],
    "FX": ["fracture"],
    "ABX": ["antibiotics"],
}

# built once at import time: {ACRONYM: compiled word-boundary regex}
_PATTERNS = {
    abbr: re.compile(r"\b" + re.escape(abbr) + r"\b", re.IGNORECASE)
    for abbr in _MEDICAL_SYNONYMS
}


def expand_query(query_text):
    """Returns query_text with any matched acronyms' expansions appended
    in parentheses, so the embedding model sees both phrasings at once.
    Returns query_text unchanged if nothing matched (the common case for
    queries that don't use an acronym in this glossary).

    Example:
        expand_query("how do I set PEEP for ARDS transport")
        -> "how do I set PEEP for ARDS transport (positive end-expiratory
            pressure, acute respiratory distress syndrome, acute lung
            injury, lung injury)"
    """
    extras = []
    seen = set()
    for abbr, pattern in _PATTERNS.items():
        if pattern.search(query_text):
            for expansion in _MEDICAL_SYNONYMS[abbr]:
                key = expansion.lower()
                if key not in seen:
                    seen.add(key)
                    extras.append(expansion)
    if not extras:
        return query_text
    return f"{query_text} ({', '.join(extras)})"
