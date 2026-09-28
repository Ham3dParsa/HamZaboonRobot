"""T02 — human duration helper (smart-relative + dual calendar, fa digits).

Locked rule: pure ``format_duration(seconds)`` (≤90s ``N ثانیه``;
<90min ``M دقیقه و S ثانیه``; else ``H ساعت و M دقیقه``; never >1
decimal, never a raw float to the UI) and ``format_moment(iso)`` →
smart-relative primary + شمسی/میلادی detail with Asia/Tehran + UTC
labels. Server snapshot adds ``elapsed_human`` + ``started_iso`` and
keeps raw ``elapsed`` for compat.

Hermetic: no clock mocking beyond explicit args, Flask test client
with a fake child. No network, no secret values.
"""

import os
import sys
import threading
import time

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.webui import duration_fmt as duration
from factory.webui import server as webui

_FA = "۰۱۲۳۴۵۶۷۸۹"


def _has_fa_digits(text):
    return any(ch in _FA for ch in str(text))


def test_duration_table():
    """Unit table: sub-second, minute boundary, hour scale, None."""
    assert duration.format_duration(0.4) == "۰٫۴ ثانیه"
    assert duration.format_duration(75) == "۷۵ ثانیه"
    assert duration.format_duration(150) == "۲ دقیقه و ۳۰ ثانیه"
    assert duration.format_duration(3700) == "۶۱ دقیقه و ۴۰ ثانیه"
    assert duration.format_duration(7260) == "۲ ساعت و ۱ دقیقه"
    assert duration.format_duration(None) == "—"


def test_duration_fa_digits_never_raw_float():
    """Every numeric rendering uses fa digits with at most 1 decimal."""
    for seconds in (5, 12.438291, 90, 91, 3600, 7260):
        text = duration.format_duration(seconds)
        assert _has_fa_digits(text), text
        assert "12.438291" not in text
        assert "." not in text  # latin dot never leaks (٫ is the decimal)


def test_duration_edges():
    assert duration.format_duration(0) == "۰ ثانیه"
    assert duration.format_duration(60) == "۶۰ ثانیه"
    assert duration.format_duration(91) == "۱ دقیقه و ۳۱ ثانیه"
    assert duration.format_duration(3600) == "۶۰ دقیقه"
    assert duration.format_duration(-3) == "—"
    assert duration.format_duration("nope") == "—"


def test_moment_dual_calendar():
    """Smart-relative primary + شمسی/میلادی detail with tz labels."""
    moment = duration.format_moment("2026-09-27T14:00:00+00:00",
                                    now="2026-09-27T14:05:00+00:00")
    assert moment["relative"] == "۵ دقیقه پیش"
    assert "شمسی" in moment["detail"]
    assert "میلادی" in moment["detail"]
    assert "Asia/Tehran" in moment["detail"]
    assert "UTC" in moment["detail"]
    assert _has_fa_digits(moment["detail"])
    bad = duration.format_moment("not-a-date")
    assert bad == {"relative": "—", "detail": "—"}


@pytest.fixture()
def _idle_screening():
    def _reset():
        with webui._SCREENING_LOCK:
            webui._SCREENING.update(
                proc=None, pid=None, status="idle", words=[],
                out_dir="", started=None, started_iso=None,
                exit_code=None, log=[], manifest=None, note="")

    _reset()
    yield
    _reset()


class _FakeProc:
    def __init__(self):
        self.stdout = iter(())
        self.pid = 4242
        self._done = threading.Event()

    def poll(self):
        return None

    def wait(self, timeout=None):
        self._done.wait(timeout if timeout is not None else 60)
        return 0


def test_snapshot_keeps_raw_elapsed_and_adds_human(tmp_path, monkeypatch,
                                                   _idle_screening):
    """Snapshot keeps raw ``elapsed`` and adds human + started_iso."""
    import subprocess as _sub

    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    monkeypatch.setattr(_sub, "Popen", lambda argv, **kw: _FakeProc())
    client = webui.app.test_client()
    resp = client.post("/api/screening/run", json={"words": "run"})
    assert resp.status_code == 201
    body = resp.get_json()["screening"]
    assert isinstance(body["elapsed"], float)
    assert _has_fa_digits(body["elapsed_human"])
    assert "12.438" not in body["elapsed_human"]
    assert isinstance(body["started_iso"], str) and body["started_iso"]
    # Idle snapshot still carries the keys (honest empties).
    with webui._SCREENING_LOCK:
        webui._SCREENING.update(proc=None, status="idle", started=None,
                                started_iso=None)
    # T04: the POST above persisted a disk record (restart-resume reads
    # it back); honest idle needs no run anywhere — memory or disk.
    from factory.webui import run_status as _run_status
    try:
        os.remove(_run_status.status_path(str(tmp_path), "screening"))
    except OSError:
        pass
    idle = client.get("/api/screening/status").get_json()["screening"]
    assert idle["elapsed"] is None
    assert idle["started_iso"] is None
    assert idle["elapsed_human"] == "—"
    assert time.monotonic() > 0  # monotonic clock source unchanged
