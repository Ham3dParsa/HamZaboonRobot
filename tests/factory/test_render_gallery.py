"""Unit tests for factory.pipeline.render_gallery (offline gallery helper)."""

from factory.pipeline.render_gallery import END_MARKER, START_MARKER
from factory.pipeline.render_gallery import normalize_rows, render_text

TEMPLATE = (
    "<html><script>"
    "const CARDS = /*GALLERY_DATA_START*/[]/*GALLERY_DATA_END*/;"
    "</script></html>"
)


def test_normalize_requires_word():
    try:
        normalize_rows([{"cefr": "A1"}])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for missing word")


def test_normalize_rejects_non_list():
    try:
        normalize_rows({"word": "kiss"})
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-list data")


def test_normalize_defaults_ids_and_isolation():
    rows = normalize_rows([{"word": "kiss"}, {"word": "note", "status_ok": False}])
    assert [r["id"] for r in rows] == [0, 1]
    assert rows[0]["examples"] == [] and rows[0]["gates"] == []
    assert rows[0]["status_ok"] is True
    rows[0]["examples"].append("x")
    assert rows[1]["examples"] == []


def test_render_replaces_single_block():
    html = render_text(TEMPLATE, normalize_rows([{"word": "kiss"}]))
    assert html.count(START_MARKER) == 1
    assert html.count(END_MARKER) == 1
    assert '"word": "kiss"' in html


def test_render_rejects_missing_block():
    try:
        render_text("<html></html>", [])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for missing markers")


def test_render_neutralizes_script_breakout():
    html = render_text(
        TEMPLATE,
        normalize_rows([{"word": "</script><script>alert(1)</script>"}]),
    )
    body = html.split(START_MARKER, 1)[1].split(END_MARKER, 1)[0]
    assert "</script" not in body.lower()
    assert "\\u003c/script\\u003e" in body
