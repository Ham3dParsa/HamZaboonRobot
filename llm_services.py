import logging
import threading
import time
from collections import deque

import ai
from config import AI_MAX_CONCURRENCY, AI_MAX_REQUESTS_PER_MINUTE
from formatting import CardPreparationError

logger = logging.getLogger(__name__)

_ai_slots = threading.BoundedSemaphore(AI_MAX_CONCURRENCY)
_ai_request_times: deque[float] = deque()
_ai_request_lock = threading.Lock()


def _call_ai_limited(function, *args, **kwargs):
    _ai_slots.acquire()
    try:
        while True:
            now = time.monotonic()
            with _ai_request_lock:
                while _ai_request_times and now - _ai_request_times[0] >= 60:
                    _ai_request_times.popleft()
                if len(_ai_request_times) < AI_MAX_REQUESTS_PER_MINUTE:
                    _ai_request_times.append(now)
                    break
            time.sleep(0.25)
        return function(*args, **kwargs)
    finally:
        _ai_slots.release()


def _ask_batch_limited(*args, **kwargs):
    return _call_ai_limited(ai.ask_batch, *args, **kwargs)


def _prepare_cached_card(card, *, lang, user_id, plan, source, persist_patch):
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
