"""Pure scheduling policy used by the durable delivery queue."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DeliverySession:
    """Immutable delivery session configuration.

    session_index: 0-based session number in the daily sequence.
    card_count: Number of cards to deliver in this session.
    preferred_minute: User's preferred time slot (0-1439 minutes from midnight).
    planned_minute: Actual scheduled time after load-balancing.
    """

    session_index: int
    card_count: int
    preferred_minute: int
    planned_minute: int


def session_sizes(
    allowance: int,
    *,
    min_sessions: int = 3,
    max_sessions: int = 6,
    target_cards_per_session: int = 3,
    feasible_slots: int | None = None,
) -> list[int]:
    """Compute session card counts for even distribution across a day.

    Distributes allowance cards across sessions while respecting min/max bounds
    and target density per session. Returns list of card counts per session.
    """
    if allowance <= 0:
        return []
    if target_cards_per_session <= 0 or min_sessions <= 0 or max_sessions < min_sessions:
        raise ValueError("invalid session policy")
    desired = min(
        allowance,
        max_sessions,
        max(min_sessions, math.ceil(allowance / target_cards_per_session)),
    )
    if feasible_slots is not None:
        desired = min(desired, max(1, feasible_slots))
    desired = max(1, desired)
    base, remainder = divmod(allowance, desired)
    return [base + (1 if index < remainder else 0) for index in range(desired)]


def feasible_minutes(start: int, end: int, step: int) -> list[int]:
    """Generate available minute slots within an active time window.

    Returns sorted list of minutes from start to end (inclusive) with given step.
    Handles midnight wraparound when end < start.
    """
    if step <= 0:
        raise ValueError("slot step must be positive")
    start = max(0, min(1439, start))
    end = max(0, min(1439, end))
    if end < start:
        end += 1440
    return [((start + offset) % 1440) for offset in range(0, end - start + 1, step)]


def choose_load_aware_minute(
    preferred_minute: int,
    candidates: list[int],
    bucket_loads: dict[int, int],
    capacity: int,
) -> int:
    """Select best minute slot near preferred time under load constraints.

    Prefers under-capacity slots; when all candidates are at capacity,
    chooses the one with smallest circular distance to preferred time.
    """
    if not candidates:
        return preferred_minute % 1440
    preferred = preferred_minute % 1440

    def distance(minute: int) -> tuple[int, int, int]:
        circular = min(abs(minute - preferred), 1440 - abs(minute - preferred))
        return (bucket_loads.get(minute, 0) >= capacity, circular, bucket_loads.get(minute, 0))

    return min(candidates, key=distance)


def plan_sessions(
    allowance: int,
    preferred_minute: int,
    active_start: int,
    active_end: int,
    *,
    slot_minutes: int = 30,
    bucket_capacity: int = 4,
    min_sessions: int = 3,
    max_sessions: int = 6,
    target_cards_per_session: int = 3,
    bucket_loads: dict[int, int] | None = None,
) -> list[DeliverySession]:
    """Plan delivery sessions with load-aware slot placement.

    Returns list of DeliverySession objects with computed planned times
    that balance user preference and system capacity.
    """
    candidates = feasible_minutes(active_start, active_end, slot_minutes)
    sizes = session_sizes(
        allowance,
        min_sessions=min_sessions,
        max_sessions=max_sessions,
        target_cards_per_session=target_cards_per_session,
        feasible_slots=len(candidates),
    )
    loads = dict(bucket_loads or {})
    sessions: list[DeliverySession] = []
    for index, card_count in enumerate(sizes):
        ideal = candidates[index * len(candidates) // len(sizes)]
        planned = choose_load_aware_minute(ideal, candidates, loads, bucket_capacity)
        loads[planned] = loads.get(planned, 0) + 1
        sessions.append(DeliverySession(index, card_count, preferred_minute % 1440, planned))
    return sessions


def planned_datetime(day: dt.date, minute: int, timezone_name: str | None = None) -> str:
    """Convert planned minute to ISO datetime string for given day.

    Uses zoneinfo timezone if timezone_name provided.
    """
    timezone = ZoneInfo(timezone_name) if timezone_name else None
    return dt.datetime.combine(
        day,
        dt.time(minute // 60, minute % 60, tzinfo=timezone),
    ).isoformat()
