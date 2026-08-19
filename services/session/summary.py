"""Pure session summary report builder — no side effects, no Telegram.

Assembles the post-session report data from per-word review records that the
caller (study handler) has already gathered from ``saved_words`` and
``review_events``. Hides the aggregation logic (counts, average stability
delta, pagination) behind a small interface so it is testable in isolation.

Learner vs admin rendering is a presentation concern handled by the caller;
this module only computes the structured data both variants share.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean


# Learner detail page size (number of words per page).
PAGE_SIZE = 8


@dataclass(frozen=True)
class WordReviewRecord:
    """One graded word in a finished session.

    ``stability_before`` is the pre-grade stability captured when the card was
    first rendered; ``stability_after`` is the post-grade value. All FSRS
    fields are optional so the builder is robust to missing data.
    """

    word_id: int
    word: str
    activity_type: str
    stability_before: float | None = None
    stability_after: float | None = None
    prior_review_date: str | None = None
    grade: int | None = None
    interval_days: float | None = None
    next_review_date: str | None = None
    difficulty: float | None = None


@dataclass(frozen=True)
class SessionReport:
    """Aggregated report for a finished study session."""

    learned_count: int
    reviewed_count: int
    total: int
    rows: tuple[WordReviewRecord, ...]
    avg_stability_delta: float | None
    pages: tuple[tuple[WordReviewRecord, ...], ...]


def build_report(records: list[WordReviewRecord]) -> SessionReport:
    """Aggregate the per-word records into a :class:`SessionReport`.

    Counts: ``first_exposure`` activity counts as "learned"; ``srs_review``
    counts as "reviewed". Other activity types appear in the rows and total
    but are not counted in either bucket.
    """
    rows = tuple(records)
    learned = sum(1 for r in rows if r.activity_type == "first_exposure")
    reviewed = sum(1 for r in rows if r.activity_type == "srs_review")

    deltas = [
        r.stability_after - r.stability_before
        for r in rows
        if r.stability_before is not None and r.stability_after is not None
    ]
    avg_delta = fmean(deltas) if deltas else None

    return SessionReport(
        learned_count=learned,
        reviewed_count=reviewed,
        total=len(rows),
        rows=rows,
        avg_stability_delta=avg_delta,
        pages=paginate(records),
    )


def paginate(
    records: list[WordReviewRecord],
    page_size: int = PAGE_SIZE,
) -> tuple[tuple[WordReviewRecord, ...], ...]:
    """Slice the records into ordered pages of at most ``page_size`` each."""
    if not records:
        return ()
    return tuple(
        tuple(records[i : i + page_size])
        for i in range(0, len(records), page_size)
    )


__all__ = [
    "PAGE_SIZE",
    "SessionReport",
    "WordReviewRecord",
    "build_report",
    "paginate",
]