"""Stable precard ids (sole owner inside factory/precard).

Vendored from factory/pipeline/precard_pipeline (provenance: precard
line R1-R6/C3, 2026-09-14): sha1-hex16 over normalized EN content only,
so Persian phase-2 edits can never move an id.
"""

from __future__ import annotations

import hashlib
import re


def normalize_id_part(text):
    """One id component: stripped, lowered, whitespace-collapsed."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def compute_pre_card_id(lemma, pos, en_def):
    """Stable precard id: sha1-hex16("lemma|pos|en_def") over normalized
    EN content only (Persian phase-2 edits can never move it). The 64-bit
    truncation is fine at precard volume; if this id ever becomes a
    cross-run dedup key, revisit the birthday bound first."""
    key = "%s|%s|%s" % (
        normalize_id_part(lemma),
        normalize_id_part(pos),
        normalize_id_part(en_def))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
