"""Card generation for the AI hot path (REF5-T7, terminal).

Owns the generation unit ONLY (verbatim move from ``llm_services.py``):
- ``_get_active_preset``: active-preset read via ``db`` (fallback-aware).
- ``_ask_batch_limited``: batch entry through the router seam.
- ``_prepare_cached_card``: validate -> repair -> merge -> revalidate ->
  persist order with exactly 3 ``CardPreparationError`` paths
  (no-repair / persist-failed / repair-failed); merge copies via
  ``dict(card)`` so the caller is never mutated.

Consumes (never moves): the ``fallback_router`` seam (``_call_ai_limited``),
pure validation (``ai.*``), ``CardPreparationError``. ``_retry_primary_preset``
stays owned by ``fallback_router.py`` (T6 unit); ``llm_services.py`` keeps
thin re-export aliases so existing callers (``bot.py``, tests) keep working.
"""

import logging

from services import db
from services.ai import ai
from services.ai.fallback_router import _call_ai_limited
from services.utils.formatting_cards import CardPreparationError

logger = logging.getLogger(__name__)


def _get_active_preset() -> dict:
    """Get the currently active AI preset (considers fallback)."""
    return db.get_active_preset()


def _ask_batch_limited(*args, **kwargs):
    return _call_ai_limited(ai.ask_batch, *args, **kwargs)


def _prepare_cached_card(card, *, lang, user_id, plan, source, persist_patch, deadline=None):
    try:
        return ai.validate_card(card)
    except ai.CardValidationError as validation_error:
        fields = ai.card_repair_fields(card)
        if not fields:
            raise CardPreparationError(
                f"{source} card has no repairable fields"
            ) from validation_error
        try:
            patch = _call_ai_limited(
                ai.repair_card,
                card,
                fields,
                lang,
                user_id=user_id,
                plan=plan,
                deadline=deadline,
            )
            merged = dict(card) if isinstance(card, dict) else {}
            merged.update(patch)
            repaired = ai.validate_card(merged)
            if not persist_patch(patch):
                raise CardPreparationError(
                    f"{source} card repair could not be persisted"
                )
            logger.info(
                "cached card repaired source=%s user_id=%s fields=%s",
                source,
                user_id,
                fields,
            )
            return repaired
        except CardPreparationError:
            # OP-005: an already-meaningful preparation error (e.g. the
            # persist failure above) keeps its own message instead of being
            # re-wrapped as a generic repair failure — still logged so the
            # path never goes silent.
            logger.warning(
                "cached card persist failed source=%s user_id=%s",
                source,
                user_id,
            )
            raise
        except Exception as repair_error:
            logger.exception(
                "cached card repair failed source=%s user_id=%s fields=%s",
                source,
                user_id,
                fields,
            )
            raise CardPreparationError(
                f"{source} card could not be repaired safely"
            ) from repair_error
