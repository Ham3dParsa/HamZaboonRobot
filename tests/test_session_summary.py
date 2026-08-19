"""Tests for the pure session summary report builder (services/session/summary.py)."""

from __future__ import annotations

import pytest

from services.session.summary import (
    PAGE_SIZE,
    SessionReport,
    WordReviewRecord,
    build_report,
    paginate,
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