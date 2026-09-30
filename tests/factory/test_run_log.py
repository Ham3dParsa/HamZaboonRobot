"""R5 RunLog unit tests (append-only JSONL + tail)."""

from __future__ import annotations

import json
import os

from factory.webui.run_log import RunLog


def test_append_and_tail_roundtrip(tmp_path):
    log = RunLog(str(tmp_path / "run_log.jsonl"))
    log.append("info", "started", "senses=3")
    log.append("info", "sense", "run#1")
    rows = log.tail(10)
    assert len(rows) == 2
    assert rows[0]["event"] == "started"
    assert rows[1]["detail"] == "run#1"
    for rec in rows:
        assert set(("ts", "level", "event", "detail")) <= set(rec)


def test_tail_bounds_and_skips_bad_lines(tmp_path):
    path = str(tmp_path / "run_log.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("not-json\n")
        for i in range(5):
            handle.write(json.dumps({"ts": "t", "level": "info",
                                     "event": "e%d" % i,
                                     "detail": ""}) + "\n")
    assert len(RunLog(path).tail(3)) == 3
    assert RunLog(path).tail(3)[-1]["event"] == "e4"
    assert RunLog(path).tail(0) != []


def test_missing_file_tails_empty(tmp_path):
    assert RunLog(str(tmp_path / "nope.jsonl")).tail(5) == []


def test_append_never_raises_on_bad_path():
    RunLog("").append("info", "x")
    RunLog(os.path.join("Z:", "definitely", "missing",
                        "run_log.jsonl") if os.name == "nt"
           else "/proc/definitely-missing/run_log.jsonl").append(
        "info", "x")
