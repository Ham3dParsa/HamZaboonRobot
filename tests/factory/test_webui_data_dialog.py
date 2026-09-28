"""T09 — slide-over data dialog server surface (UX-12/13/14/16, OQ-1/3).

Locked rules:
- ``_list_dir`` files gain ``mtime_iso`` + T02 ``format_moment``
  (``mtime_relative``/``mtime_detail``) + ``lines``/``lines_label`` via
  the existing ``_file_facts`` (cap ``50000+``); scan-gated at
  ``_LIST_LINES_SCAN_CAP`` (oversized → honest "—"); folders carry NO
  size claim.
- Ops: ``POST /api/files/mkdir`` + ``POST /api/files/rename``
  (same-parent only, constrained under the data root / browse roots).
  Delete is HARD-BLOCKED (no route) and upload has no route either
  (upload endpoint is T11-owned, allowlisted dirs only).
- ``GET /api/files/words`` fills A1 through the existing readers
  (JSON word-list arrays, else the linker's ``read_wordlist`` line
  rule), bounded + truncated honestly.
- ``_browse_roots`` starts at the data root when it exists.

Hermetic: tmp data root, Flask test client. No network, no secrets.
T08 files untouched (history tab is the parallel worker's).
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.webui import server as webui


@pytest.fixture()
def _roots(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", str(tmp_path))
    # Containment tests must not leak through the real home/drive roots.
    monkeypatch.setattr(webui, "_browse_roots",
                        lambda: [{"path": str(tmp_path),
                                  "label": "data root"}])
    return tmp_path


def _client():
    return webui.app.test_client()


def test_list_dir_files_carry_facts_and_dirs_carry_no_size(_roots):
    """Small file → exact lines + mtime triple; dir → name+flag only."""
    target = _roots / "words.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    sub = _roots / "sub"
    sub.mkdir()
    ok, error, payload = webui._list_dir(str(_roots))
    assert ok, error
    by_name = {e["name"]: e for e in payload["entries"]}
    row = by_name["words.txt"]
    assert row["is_dir"] is False
    assert row["size"] == os.path.getsize(target)
    assert row["lines"] == 3
    assert row["lines_label"] == "3"
    assert row["mtime_iso"], row
    assert row["mtime_relative"] != "—", row
    assert "میلادی" in row["mtime_detail"], row
    drow = by_name["sub"]
    assert drow == {"name": "sub", "is_dir": True}


def test_list_dir_lines_cap_uses_file_facts(_roots, monkeypatch):
    """Lowered file-facts cap surfaces the honest ``N+`` label."""
    monkeypatch.setattr(webui, "_FILE_LINES_CAP", 5)
    target = _roots / "ten.txt"
    target.write_text("\n".join("w%d" % i for i in range(10)) + "\n",
                      encoding="utf-8")
    ok, _, payload = webui._list_dir(str(_roots))
    assert ok
    row = {e["name"]: e for e in payload["entries"]}["ten.txt"]
    assert row["lines"] == 5
    assert row["lines_label"] == "5+"


def test_list_dir_oversized_file_honest_empty_lines(_roots):
    """Files over the scan cap keep size+mtime with ``—`` lines."""
    big = _roots / "big.txt"
    with open(big, "w", encoding="utf-8") as handle:
        for i in range(20000):
            handle.write("word-%06d padding-padding-padding\n" % i)
    assert os.path.getsize(big) > webui._LIST_LINES_SCAN_CAP
    ok, _, payload = webui._list_dir(str(_roots))
    assert ok
    row = {e["name"]: e for e in payload["entries"]}["big.txt"]
    assert row["size"] == os.path.getsize(big)
    assert row["lines"] is None
    assert row["lines_label"] == "—"
    assert row["lines_note"], row
    assert row["mtime_iso"], row


def test_mkdir_and_rename_roundtrip(_roots):
    """mkdir creates one level; rename stays in the same parent."""
    client = _client()
    resp = client.post("/api/files/mkdir",
                       json={"dir": str(_roots), "name": "t09-new"})
    assert resp.status_code == 200, resp.get_json()
    assert (_roots / "t09-new").is_dir()
    assert client.post("/api/files/mkdir",
                       json={"dir": str(_roots),
                             "name": "t09-new"}).status_code == 409
    target = _roots / "t09-new" / "a.txt"
    target.write_text("x\n", encoding="utf-8")
    resp = client.post("/api/files/rename",
                       json={"path": str(target), "name": "b.txt"})
    assert resp.status_code == 200, resp.get_json()
    assert (_roots / "t09-new" / "b.txt").is_file()
    assert not (_roots / "t09-new" / "a.txt").exists()


def test_mkdir_rename_fail_closed(_roots):
    """Traversal, bad names, missing targets, outside roots → 400."""
    client = _client()
    for body in ({"dir": str(_roots), "name": "../evil"},
                 {"dir": str(_roots), "name": "a/b"},
                 {"dir": str(_roots), "name": ""},
                 {"dir": "Q:\\no-such-root-t09\\x", "name": "ok"}):
        assert client.post("/api/files/mkdir",
                           json=body).status_code == 400, body
    outside = _roots.parent / "t09-outside-check"
    outside.mkdir(exist_ok=True)
    try:
        resp = client.post("/api/files/mkdir",
                           json={"dir": str(outside), "name": "nope"})
        assert resp.status_code == 400, resp.get_json()
        victim = outside / "v.txt"
        victim.write_text("v\n", encoding="utf-8")
        resp = client.post("/api/files/rename",
                           json={"path": str(victim), "name": "w.txt"})
        assert resp.status_code == 400, resp.get_json()
    finally:
        for child in sorted(outside.glob("*")):
            child.unlink()
        outside.rmdir()
    missing = _roots / "missing.txt"
    assert client.post(
        "/api/files/rename",
        json={"path": str(missing), "name": "b.txt"}).status_code == 400
    real = _roots / "real.txt"
    real.write_text("r\n", encoding="utf-8")
    assert client.post(
        "/api/files/rename",
        json={"path": str(real), "name": ".."}).status_code == 400


def test_words_endpoint_readers_and_bounds(_roots):
    """TXT line rule + JSON array shape; outside/missing → 400."""
    plain = _roots / "plain.txt"
    plain.write_text("alpha\n# comment\n\nbeta\n", encoding="utf-8")
    body = _client().get(
        "/api/files/words?path=" + str(plain)).get_json()
    assert body["words"] == ["alpha", "beta"]
    assert body["truncated"] is False
    arr = _roots / "sample.json"
    arr.write_text(json.dumps([{"kind": "word", "text": "one"},
                               {"kind": "phrase", "text": "two words"},
                               {"kind": "word", "text": "  "}]),
                   encoding="utf-8")
    body = _client().get(
        "/api/files/words?path=" + str(arr)).get_json()
    assert body["words"] == ["one", "two words"]
    client = _client()
    assert client.get("/api/files/words").status_code == 400
    assert client.get(
        "/api/files/words?path=" + str(_roots / "nope.txt")
    ).status_code == 400
    assert client.get(
        "/api/files/words?path=C:\\Windows\\win.ini").status_code == 400


def test_delete_and_upload_routes_absent():
    """OQ-1/OQ-3: no file-delete route; upload is T11-owned (present).

    T11 landed ``POST /api/files/upload`` (allowlisted dirs only, no
    silent overwrite — covered in ``test_screening_intake.py``); delete
    stays hard-blocked (no DELETE anywhere under /api/files/).
    """
    rules = [(str(r.rule), sorted(set(r.methods or ()) - {"HEAD", "OPTIONS"}))
             for r in webui.app.url_map.iter_rules()
             if str(r.rule).startswith("/api/files/")]
    by_rule = {rule: methods for rule, methods in rules}
    assert by_rule.get("/api/files/upload") == ["POST"], by_rule
    for rule, methods in rules:
        if rule.startswith("/api/files/pins"):
            continue  # T06 unpin (exact-name, no cascade) — not file delete
        assert "DELETE" not in methods, (rule, methods)
