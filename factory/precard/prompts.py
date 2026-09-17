"""Prompt texts owned by the precard line (single owner).

Forked verbatim from factory/pipeline/card_pilot (provenance: precard
line R1-R6, 2026-09-14) so this package imports nothing project-owned.
The pilot line keeps its own copies and evolves separately. Label names
track the live 16-head registry.
"""

from __future__ import annotations

TOPIC_TIEBREAK = (
    "V14.1 TIE-BREAK ADDENDUM (apply strictly): "
    "biological sex and sociological gender (gender, male/female roles) "
    "are NEVER Animals & Living Beings — map biological/anatomical senses "
    "to Health & Body and social-role senses to Society. "
    "Functional and social concepts (phone calls, employment, public "
    "performances, money accumulation, lifting) are NEVER Other / "
    "Abstract — assign the concrete domain (technology, work, society, "
    "business, daily life). Other / Abstract stays a last resort for "
    "genuinely abstract, grammatical, or unclassifiable senses.")


# Frozen from factory/pipeline/card_pilot (provenance: inflection-review R36, strict-English R4, 2026-09-14).
INFLECTION_REVIEW_SYS = (
    "You are an English learner-dictionary editor for Persian learners. "
    "Given an inflected word form and its dictionary gloss, reply "
    '{"keep": bool, "reason": "string"}. '
    "KEEP criteria (ONLY IF any applies): "
    "1. The inflected form has established, independent usage as an "
    "Adjective with a distinct meaning beyond the action of the verb "
    "(e.g., 'charming', 'striking', 'demanding'). "
    "2. The form carries a unique, non-transparent nominal or idiomatic "
    "sense that a learner cannot deduce from the base lemma (e.g., "
    "'building', 'drawing', 'do one's best'). "
    "3. Established legal terms, crimes, physical objects, or field "
    "concepts ending in -ing (e.g., 'kidnapping', 'building', "
    "'lightning') are independent headwords -> KEEP. "
    "DROP criteria (ONLY IF any applies): "
    "1. Regular plurals (-s, -es) with transparent compositional meaning "
    "-> Drop in favor of the singular base lemma. "
    "2. Regular past tense and participles (-ed) acting merely as the "
    "verbal completion of the action -> Drop in favor of the base lemma. "
    "3. Plain gerunds/participles (-ing) that simply describe the active "
    "progress of the verb (e.g., 'forcing' = act of forcing; 'wondering' "
    "= act of wondering) -> Drop in favor of the base lemma. "
    "4. Plain grammatical comparatives/superlatives (-er, -est, more, "
    "most) -> Drop in favor of the base lemma. "
    "Return ONLY raw JSON, no markdown fences, no commentary. "
    "Reason MUST be strictly in concise English (max 12 words).")
