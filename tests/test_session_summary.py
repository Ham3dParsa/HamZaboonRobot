"""Tests for the pure session summary report builder (services/session/summary.py)."""

from __future__ import annotations

import random

import pytest

from services.session.summary import (
    PAGE_SIZE,
    RECALL_WEIGHTS,
    SessionReport,
    WordReviewRecord,
    build_report,
    classify_tier,
    paginate,
    pick_motivation,
)


def _rec(
    activity: str,
    before: float | None = 1.0,
    after: float | None = 2.0,
    **kw,
) -> WordReviewRecord:
    defaults = {
        "word_id": 1,
        "word": "word",
        "stability_before": before,
        "stability_after": after,
        "grade": 3,
    }
    defaults.update(kw)
    return WordReviewRecord(activity_type=activity, **defaults)


class TestCounts:
    def test_splits_learned_vs_reviewed(self):
        records = [
            _rec("first_exposure"),
            _rec("first_exposure"),
            _rec("srs_review"),
            _rec("srs_review"),
            _rec("srs_review"),
        ]
        report = build_report(records)
        assert report.learned_count == 2
        assert report.reviewed_count == 3
        assert report.total == 5

    def test_empty(self):
        report = build_report([])
        assert report.learned_count == 0
        assert report.reviewed_count == 0
        assert report.total == 0
        assert report.avg_stability_delta is None
        assert report.pages == ()

    def test_unknown_activity_not_counted_in_either(self):
        report = build_report([_rec("sentence_write")])
        assert report.learned_count == 0
        assert report.reviewed_count == 0
        assert report.total == 1


class TestAverageDelta:
    def test_mean_of_after_minus_before(self):
        records = [
            _rec("srs_review", before=1.0, after=3.0),
            _rec("srs_review", before=2.0, after=2.0),
        ]
        report = build_report(records)
        assert report.avg_stability_delta == pytest.approx(1.0)

    def test_ignores_rows_missing_before_or_after(self):
        records = [
            _rec("srs_review", before=1.0, after=3.0),
            _rec("first_exposure", before=None, after=2.0),
        ]
        report = build_report(records)
        assert report.avg_stability_delta == pytest.approx(2.0)

    def test_none_when_no_comparable_rows(self):
        report = build_report([_rec("first_exposure", before=None, after=None)])
        assert report.avg_stability_delta is None


class TestRows:
    def test_preserves_word_metadata(self):
        rec = _rec(
            "srs_review",
            before=1.0,
            after=4.0,
            prior_review_date="2026-08-01",
            grade=3,
            interval_days=6,
            next_review_date="2026-08-25",
            difficulty=3.2,
        )
        report = build_report([rec])
        row = report.rows[0]
        assert row.word_id == 1
        assert row.stability_before == 1.0
        assert row.stability_after == 4.0
        assert row.prior_review_date == "2026-08-01"
        assert row.grade == 3
        assert row.interval_days == 6
        assert row.next_review_date == "2026-08-25"
        assert row.difficulty == 3.2

    def test_missing_fields_are_none_not_errors(self):
        rec = WordReviewRecord(word_id=7, word="x", activity_type="srs_review")
        report = build_report([rec])
        assert report.rows[0].stability_before is None
        assert report.rows[0].grade is None


class TestPagination:
    def test_single_page_under_limit(self):
        records = [_rec("srs_review") for _ in range(3)]
        assert paginate(records) == (tuple(records),)

    def test_splits_across_pages_at_page_size(self):
        records = [_rec("srs_review") for _ in range(PAGE_SIZE + 2)]
        pages = paginate(records)
        assert len(pages) == 2
        assert len(pages[0]) == PAGE_SIZE
        assert len(pages[1]) == 2

    def test_build_report_exposes_pages(self):
        records = [_rec("srs_review") for _ in range(PAGE_SIZE + 1)]
        report = build_report(records)
        assert len(report.pages) == 2

    def test_empty_pages(self):
        assert paginate([]) == ()


class TestReportShape:
    def test_report_is_frozen_dataclass(self):
        report = build_report([_rec("srs_review")])
        assert isinstance(report, SessionReport)
        with pytest.raises(AttributeError):
            report.learned_count = 9

    def test_page_size_is_six(self):
        # R1 — 6 words per page (was 8).
        assert PAGE_SIZE == 6


class TestRecallRate:
    def test_weighted_success_score(self):
        # grades 1,2,3,4 → (0 + 0.7 + 1.0 + 1.0) / 4 = 0.675 (R4)
        records = [_rec("first_exposure", grade=g) for g in (1, 2, 3, 4)]
        report = build_report(records)
        assert report.recall_rate == pytest.approx(0.675)

    def test_all_again_is_zero(self):
        report = build_report([_rec("srs_review", grade=1) for _ in range(2)])
        assert report.recall_rate == pytest.approx(0.0)

    def test_all_good_or_easy_is_one(self):
        report = build_report([_rec("srs_review", grade=3), _rec("srs_review", grade=4)])
        assert report.recall_rate == pytest.approx(1.0)

    def test_weights_are_named_constants(self):
        assert RECALL_WEIGHTS[1] == 0.0
        assert RECALL_WEIGHTS[2] == 0.7
        assert RECALL_WEIGHTS[3] == 1.0
        assert RECALL_WEIGHTS[4] == 1.0

    def test_none_when_no_grades(self):
        report = build_report([_rec("first_exposure", grade=None)])
        assert report.recall_rate is None

    def test_empty_report_has_none_rate(self):
        report = build_report([])
        assert report.recall_rate is None


class TestAvgStabilityAfter:
    def test_mean_of_after_values(self):
        records = [
            _rec("first_exposure", after=4.0),
            _rec("srs_review", after=6.0),
        ]
        report = build_report(records)
        assert report.avg_stability_after == pytest.approx(5.0)

    def test_ignores_rows_missing_after(self):
        report = build_report([_rec("srs_review", after=None), _rec("srs_review", after=2.0)])
        assert report.avg_stability_after == pytest.approx(2.0)

    def test_none_when_no_values(self):
        report = build_report([_rec("srs_review", after=None)])
        assert report.avg_stability_after is None

    def test_empty_report_has_none(self):
        assert build_report([]).avg_stability_after is None


class TestTier:
    def test_excellent_at_90(self):
        assert classify_tier(0.90) == "excellent"

    def test_acceptable_band_75_to_89(self):
        assert classify_tier(0.89) == "acceptable"
        assert classify_tier(0.75) == "acceptable"

    def test_needs_improvement_below_75(self):
        assert classify_tier(0.74) == "needs_improvement"

    def test_none_rate_is_none(self):
        assert classify_tier(None) is None


class TestMotivation:
    def test_deterministic_with_seed(self):
        report = build_report([_rec("first_exposure", grade=g) for g in (1, 2, 3, 4)])
        assert pick_motivation(report, rng=random.Random(0)) == pick_motivation(
            report, rng=random.Random(0)
        )

    def test_excellent_references_easy_count(self):
        report = build_report([_rec("first_exposure", grade=4) for _ in range(3)])
        msg = pick_motivation(report, rng=random.Random(1))
        assert msg is not None
        assert "آسان" in msg

    def test_acceptable_references_graded_ratio(self):
        # grades 3,3,3,1 → (3×1.0)/4 = 0.75 → acceptable; graded=4, ok=3
        report = build_report(
            [_rec("srs_review", grade=3), _rec("srs_review", grade=3),
             _rec("srs_review", grade=3), _rec("srs_review", grade=1)]
        )
        msg = pick_motivation(report, rng=random.Random(2))
        assert msg is not None
        assert "۴" in msg and "۳" in msg

    def test_needs_improvement_reframes_again(self):
        report = build_report(
            [_rec("srs_review", grade=1) for _ in range(3)] + [_rec("srs_review", grade=2)]
        )
        # R6: EVERY motivation variant must reference a real stat (Persian digit),
        # never generic filler. Sweep seeds so every variant is exercised.
        for seed in range(20):
            msg = pick_motivation(report, rng=random.Random(seed))
            assert msg is not None
            assert any(c in msg for c in "۰۱۲۳۴۵۶۷۸۹"), f"filler variant picked for seed {seed}: {msg}"

    def test_none_when_no_rate(self):
        report = build_report([_rec("srs_review", grade=None)])
        assert pick_motivation(report) is None