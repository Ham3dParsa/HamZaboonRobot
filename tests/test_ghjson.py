#!/usr/bin/env python3
"""Unit tests for scripts/ghjson.py path navigation and input guards."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ghjson import _split_path, _navigate  # noqa: E402

SAMPLE = {
    "comments": [{"body": "hi"}, {"body": "yo"}],
    "a": [[1, 2], [3, 4]],
    "title": "t",
}


def test_split_path_simple():
    assert _split_path("a.b.c") == ["a", "b", "c"]


def test_split_path_array_suffix():
    assert _split_path("comments[0].body") == ["comments[0]", "body"]


def test_split_path_top_level_array():
    assert _split_path("[1].a") == ["[1]", "a"]


def test_navigate_dict_key():
    assert _navigate(SAMPLE, "title") == "t"


def test_navigate_array_index():
    assert _navigate(SAMPLE, "comments[1].body") == "yo"


def test_navigate_nested_array():
    assert _navigate(SAMPLE, "a[1][0]") == 3


def test_navigate_top_level_array():
    assert _navigate([{"a": 1}, {"a": 2}], "[1].a") == 2


def test_navigate_missing_raises():
    with pytest.raises((KeyError, IndexError, TypeError, ValueError)):
        _navigate(SAMPLE, "missing.key")


def test_navigate_bad_index_diagnostic():
    with pytest.raises(ValueError) as exc:
        _navigate(SAMPLE, "a[0][x]")
    assert "invalid array index" in str(exc.value)


def test_navigate_unclosed_bracket_rejected():
    with pytest.raises(ValueError) as exc:
        _navigate(SAMPLE, "a[0")
    assert "unclosed" in str(exc.value) or "unbalanced" in str(exc.value)


def test_navigate_unbalanced_nested_bracket_rejected():
    with pytest.raises(ValueError) as exc:
        _navigate(SAMPLE, "a[0][1")
    assert "unclosed" in str(exc.value) or "unbalanced" in str(exc.value)


def _run(args, stdin):
    proc = subprocess.run(
        [sys.executable, "scripts/ghjson.py", *args],
        input=stdin,
        capture_output=True,
        text=True,
    )
    return proc


def test_cli_empty_stdin_friendly():
    proc = _run([], "")
    assert proc.returncode == 1
    assert "ghjson:" in proc.stderr


def test_cli_non_json_friendly():
    proc = _run([], "not json")
    assert proc.returncode == 1
    assert "not valid JSON" in proc.stderr


def test_cli_invalid_utf8_friendly():
    proc = subprocess.run(
        [sys.executable, "scripts/ghjson.py"],
        input=b"\xff\xfe bad",
        capture_output=True,
    )
    assert proc.returncode == 1
    assert b"ghjson:" in proc.stderr


def test_cli_extract_path():
    proc = _run(["comments[0].body"], json.dumps(SAMPLE))
    assert proc.returncode == 0
    assert proc.stdout.strip() == "hi"
