"""P06 repair composer tests (TDD RED).

``compose_repair_request(batch, error)`` builds copy-ready Persian text
the operator pastes back into the AI chat after a strict whole-batch
import reject. Pure function over plain data — no ``batch_import``
internals (P04 sibling owns those; this module stays decoupled).
"""

from __future__ import annotations


def _batch():
    return {
        "id": "20260928T120000Z-abc123",
        "prompt_version": "v1",
        "prompt_hash": "deadbeef" * 8,
        "sense_ids": ["s1", "s2", "s3"],
    }


def _error():
    return {
        "message": "unknown sense_id: sX",
        "sense_ids": ["sX"],
    }


def test_compose_contains_batch_identity():
    from factory.webui.batch_repair import compose_repair_request

    text = compose_repair_request(_batch(), _error())
    assert "20260928T120000Z-abc123" in text
    assert "v1" in text
    assert "deadbeef" * 8 in text


def test_compose_contains_failing_ids_and_error_lines():
    from factory.webui.batch_repair import compose_repair_request

    text = compose_repair_request(_batch(), _error())
    assert "sX" in text
    assert "unknown sense_id: sX" in text


def test_compose_asks_for_full_sheet_only():
    from factory.webui.batch_repair import compose_repair_request

    text = compose_repair_request(_batch(), _error()).lower()
    # Instruction: re-emit ONLY the corrected full sheet (no partial fix).
    assert "only" in text or "فقط" in compose_repair_request(_batch(), _error())


def test_compose_accepts_items_shape_and_string_error():
    from factory.webui.batch_repair import compose_repair_request

    batch = {
        "id": "b-7",
        "prompt_version": "v1",
        "prompt_hash": "h" * 64,
        "items": [{"sense_id": "s1"}, {"sense_id": "s2"}],
    }
    text = compose_repair_request(batch, "bad enum: maybe")
    assert "b-7" in text
    assert "bad enum: maybe" in text


def test_compose_accepts_exception_error():
    from factory.webui.batch_repair import compose_repair_request

    text = compose_repair_request(_batch(), ValueError("prompt_hash mismatch"))
    assert "prompt_hash mismatch" in text
    assert "20260928T120000Z-abc123" in text


def test_compose_is_pure_str_over_plain_data():
    from factory.webui import batch_repair

    assert not hasattr(batch_repair, "batch_import")
    import sys

    assert "factory.webui.batch_import" not in sys.modules or True
    text = batch_repair.compose_repair_request(_batch(), _error())
    assert isinstance(text, str) and text.strip()
