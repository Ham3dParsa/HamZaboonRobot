"""Unit tests for Phase 01 per-user sliding-window rate guard.

TDD — failing first, then implemented in services/scheduling.py.
Covers: window expiry, limit hit, isolation by action and user.
"""

import time

import pytest

import services.scheduling as sched


@pytest.fixture(autouse=True)
def _clear_buckets():
    # Reset in-memory buckets before each test to ensure isolation.
    # The implementation exposes _clear_rate_buckets or similar; try both.
    clear = getattr(sched, "_clear_rate_buckets", None)
    if clear is None:
        clear = getattr(sched, "_reset_rate_buckets", None)
    if clear is None:
        # fallback: manually clear internal dicts if present
        for attr in ("_buckets", "_rate_buckets", "_per_user_buckets"):
            d = getattr(sched, attr, None)
            if isinstance(d, dict):
                d.clear()
        for attr in ("_bucket_locks", "_rate_locks", "_locks"):
            d = getattr(sched, attr, None)
            if isinstance(d, dict):
                d.clear()
        yield
        for attr in ("_buckets", "_rate_buckets", "_per_user_buckets"):
            d = getattr(sched, attr, None)
            if isinstance(d, dict):
                d.clear()
        for attr in ("_bucket_locks", "_rate_locks", "_locks"):
            d = getattr(sched, attr, None)
            if isinstance(d, dict):
                d.clear()
        return
    clear()
    yield
    clear()


def _record(user_id, action, now):
    # Try record_per_user_action first, then record
    fn = getattr(sched, "record_per_user_action", None)
    if fn is None:
        fn = getattr(sched, "record", None)
    assert fn is not None, "record_per_user_action not found"
    fn(user_id, action, now=now)


def _check(user_id, action, now=None):
    fn = getattr(sched, "check_per_user_rate", None)
    assert fn is not None, "check_per_user_rate not found"
    return fn(user_id, action, now=now)


def _is_limited(user_id, action, now=None):
    fn = getattr(sched, "is_rate_limited", None)
    assert fn is not None, "is_rate_limited not found"
    # helper may or may not accept now
    try:
        return fn(user_id, action, now=now) if now is not None else fn(user_id, action)
    except TypeError:
        return fn(user_id, action)


def test_limit_hit_blocks_sixth_request():
    uid = 1001
    action = "study_start"
    base = 1_000_000.0
    # 5 within window should be allowed
    for i in range(5):
        assert not _is_limited(uid, action, now=base + i * 0.5), f"should not be limited at i={i}"
        _record(uid, action, now=base + i * 0.5)
        # check_per_user_rate should reflect limited state after 5
    # 6th within same window should be limited
    assert _is_limited(uid, action, now=base + 2.0)
    assert _check(uid, action, now=base + 2.0) is False  # check returns False when limited (not allowed)


def test_window_expiry_allows_again():
    uid = 2002
    action = "srs_grade"
    base = 2_000_000.0
    for i in range(5):
        _record(uid, action, now=base + i)
    # still limited at base+5 (within 10s window)
    assert _is_limited(uid, action, now=base + 5)
    # after window slides past first entries: base+11 should have expired 0,1
    # only 3 entries remain (at 2,3,4 are within (1,11] window of 10s)
    # Actually window is (now-10, now], so at 11, entry at 0 is expired (11-10=1, 0 <=1), 1 is at boundary?
    # Implementation uses <= cutoff, so at 11 cutoff=1, entry at 1 is expired too.
    # Expect not limited after enough time.
    assert not _is_limited(uid, action, now=base + 11)
    # After expiry, we can record again and not be limited until 5 again
    _record(uid, action, now=base + 11)
    assert not _is_limited(uid, action, now=base + 11)


def test_isolation_by_action():
    uid = 3003
    base = 3_000_000.0
    for i in range(5):
        _record(uid, "query_ask", now=base + i * 0.1)
    assert _is_limited(uid, "query_ask", now=base + 1)
    # different action should not be limited
    assert not _is_limited(uid, "grammar_tip", now=base + 1)
    assert not _is_limited(uid, "study_start", now=base + 1)
    assert not _is_limited(uid, "srs_grade", now=base + 1)
    # check returns True for isolated action (allowed)
    assert _check(uid, "grammar_tip", now=base + 1) is True


def test_isolation_by_user():
    base = 4_000_000.0
    for i in range(5):
        _record(4004, "study_start", now=base + i * 0.1)
    assert _is_limited(4004, "study_start", now=base + 1)
    # different user should not be limited
    assert not _is_limited(4005, "study_start", now=base + 1)
    assert _check(4005, "study_start", now=base + 1) is True


def test_check_and_is_limited_consistency():
    uid = 5005
    action = "query_ask"
    base = 5_000_000.0
    # initially not limited, check allowed True
    assert _check(uid, action, now=base) is True
    assert not _is_limited(uid, action, now=base)
    for i in range(5):
        _record(uid, action, now=base + i * 0.2)
    assert _is_limited(uid, action, now=base + 1)
    assert _check(uid, action, now=base + 1) is False
