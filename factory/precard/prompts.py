"""Prompt texts owned by the precard line (single owner).

T-RUN-B (2026-09-18): thin re-export shim — the canonical wordings live
in factory.precard.prompt_registry (versioned, variant-pickable). Kept so
existing ``from factory.precard.prompts import ...`` sites keep working
with byte-identical values; wording changes happen in the registry, never
here. The pilot line (factory/pipeline/card_pilot.py) keeps its own copies
and evolves separately.
"""

from __future__ import annotations

from factory.precard.prompt_registry import (
    INFLECTION_REVIEW_SYS, TOPIC_TIEBREAK)

__all__ = ["TOPIC_TIEBREAK", "INFLECTION_REVIEW_SYS"]
