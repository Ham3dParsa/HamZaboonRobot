"""Pure session summary report builder — no side effects, no Telegram.

Assembles the post-session report data from per-word review records that the
caller (study handler) has already gathered from ``saved_words`` and
``review_events``. Hides the aggregation logic (counts, average stability
delta, pagination) behind a small interface so it is testable in isolation.

Learner vs admin rendering is a presentation concern handled by the caller;
this module only computes the structured data both variants share.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import fmean

from services.utils.formatting import to_persian_digits


# Learner detail page size (number of words per page). R1: 6 words per page.
PAGE_SIZE = 6

# Weighted recall score per FSRS grade (1=again, 2=hard, 3=good, 4=easy).
# Named constants so the weights are tunable in one place (R4).
RECALL_WEIGHTS = {1: 0.0, 2: 0.7, 3: 1.0, 4: 1.0}


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
    """Aggregated report for a finished study session.

    ``recall_rate`` is the weighted success score in ``[0, 1]`` (R4), or
    ``None`` when no word was graded. ``avg_stability_after`` is the mean final
    stability across graded words (R6b), or ``None`` when unavailable.
    """

    learned_count: int
    reviewed_count: int
    total: int
    rows: tuple[WordReviewRecord, ...]
    avg_stability_delta: float | None
    recall_rate: float | None
    avg_stability_after: float | None
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

    grades = [r.grade for r in rows if r.grade is not None]
    recall_rate = (
        sum(RECALL_WEIGHTS.get(g, 0.0) for g in grades) / len(grades)
        if grades
        else None
    )

    afters = [r.stability_after for r in rows if r.stability_after is not None]
    avg_stability_after = fmean(afters) if afters else None

    return SessionReport(
        learned_count=learned,
        reviewed_count=reviewed,
        total=len(rows),
        rows=rows,
        avg_stability_delta=avg_delta,
        recall_rate=recall_rate,
        avg_stability_after=avg_stability_after,
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


def classify_tier(recall_rate: float | None) -> str | None:
    """Classify a recall rate into a performance tier (R5).

    Thresholds: ≥90% excellent, 75–89% acceptable, <75% needs improvement.
    Returns ``None`` when the rate is unknown (no graded records).
    """
    if recall_rate is None:
        return None
    if recall_rate >= 0.90:
        return "excellent"
    if recall_rate >= 0.75:
        return "acceptable"
    return "needs_improvement"


def _grade_stats(report: SessionReport) -> dict[str, int]:
    """Grade counts plus derived success numbers used by motivation variants.

    Returns only integer stats; the formatter converts to Persian digits.
    """
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for r in report.rows:
        if r.grade in counts:
            counts[r.grade] += 1
    graded = sum(counts.values())
    ok = counts[3] + counts[4]
    return {
        "total": report.total,
        "graded": graded,
        "ok": ok,
        "easy": counts[4],
        "good": counts[3],
        "hard": counts[2],
        "again": counts[1],
        "learned": report.learned_count,
        "reviewed": report.reviewed_count,
    }


# Motivational messages per tier. Each variant references a real session stat
# (no generic filler) per R6. Keys are filled by :func:`pick_motivation`.
_MOTIVATION: dict[str, tuple[str, ...]] = {
    "excellent": (
        "{easy} کلمه رو با «آسان» جواب دادی — حافظه‌ت داره قوی‌تر می‌شه 💪",
        "فوق‌العاده! از {total} کلمه، {ok} تا رو درست یادت اومد — حافظه‌ت داره قوی‌تر می‌شه 💪",
        "روندت عالیه — {easy} تا «آسان» و {ok} یادآوری درست. همین مسیر رو ادامه بده 🚀",
    ),
    "acceptable": (
        "از {graded} کلمه، {ok} تا رو درست یادت اومد. برای بقیه یه کم دقت بیشتر موقع دیدن جواب کمک می‌کنه.",
        "خوب بود — {ok} از {graded} کلمه رو درست زدی. روی بقیه با دقت‌تر دیدن جواب تمرکز کن.",
        "نیمه راه خوبیه — {graded} تا کلمه، {ok} درست. یه قدم دیگه بردار 💪",
    ),
    "needs_improvement": (
        "{again} کلمه رو با «یادم نیومد» ثبت کردی — این طبیعیه؛ همون کلمه‌ها زودتر برمی‌گردن سراغت و تو بهتر می‌شی 🌱",
        "{hard} کلمه رو به‌سختی یادت اومد و {again} تا رو نیومد — صادقانه جواب بده، هر تکرار یه قدمه.",
        "از {graded} کلمه، فقط {ok} تا رو درست یادت اومد. نگران نباش — کلماتی که جا گذاشتی، دقیقاً همون‌هایی‌ان که بیشتر تمرین نیاز دارن.",
    ),
}


def pick_motivation(report: SessionReport, rng: random.Random | None = None) -> str | None:
    """Pick a data-driven motivational line for the report's tier (R6).

    ``rng`` is injectable so callers can make tests deterministic; it defaults
    to a fresh :class:`random.Random`. Returns ``None`` when there is no tier
    (no graded records).
    """
    tier = classify_tier(report.recall_rate)
    if tier is None:
        return None
    if rng is None:
        rng = random.Random()
    stats = _grade_stats(report)
    template = rng.choice(_MOTIVATION[tier])
    return to_persian_digits(template.format(**stats))


__all__ = [
    "PAGE_SIZE",
    "RECALL_WEIGHTS",
    "SessionReport",
    "WordReviewRecord",
    "build_report",
    "classify_tier",
    "paginate",
    "pick_motivation",
]