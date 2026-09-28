"""T06 — pinned_paths.json shared pins (UX-15, OQ-4).

Locked rule: shared factory file at
``<DATA_ROOT>/webui/pinned_paths.json`` (all consoles/worktrees see
the same pins). Entries ``{name, path, kind: dir|file}``; paths
validated under the data root OR existing browse roots; atomic
tmp+replace writes; DELETE needs the exact name (no cascade).

Hermetic: tmp data root, Flask test client. No network, no secrets.
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.webui import pinned_paths as pins
from factory.webui import server as webui


def test_add_persists_across_instances(tmp_path):
    """Add → a second store instance (simulated restart) still sees it."""
    target = tmp_path / "proof-linker"
    target.mkdir()
    entry = pins.add_pin(str(tmp_path), "screened", str(target), "dir",
                         extra_roots=[])
    assert entry == {"name": "screened", "path": os.path.abspath(target),
                     "kind": "dir"}
    assert pins.load_pins(str(tmp_path)) == [entry]
    # Corrupt file reads as honest empty, never raises.
    (tmp_path / "webui" / "pinned_paths.json").write_text(
        "{broken", encoding="utf-8")
    assert pins.load_pins(str(tmp_path)) == []


def test_invalid_path_rejected_and_remove_exact(tmp_path):
    """Outside-root paths fail; remove matches the exact name only."""
    target = tmp_path / "proof-linker"
    target.mkdir()
    with pytest.raises(ValueError):
        pins.add_pin(str(tmp_path), "evil", "C:\\Windows", "dir",
                     extra_roots=[])
    with pytest.raises(ValueError):
        pins.add_pin(str(tmp_path), "bad-kind", str(target), "socket",
                     extra_roots=[])
    with pytest.raises(ValueError):
        pins.add_pin(str(tmp_path), "", str(target), "dir",
                     extra_roots=[])
    pins.add_pin(str(tmp_path), "a", str(target), "dir", extra_roots=[])
    pins.add_pin(str(tmp_path), "b", str(target), "dir", extra_roots=[])
    assert pins.remove_pin(str(tmp_path), "a") is True
    assert [p["name"] for p in pins.load_pins(str(tmp_path))] == ["b"]
    assert pins.remove_pin(str(tmp_path), "missing") is False


def test_pins_endpoints_roundtrip(tmp_path, monkeypatch):
    """GET/POST/DELETE /api/files/pins over the live Flask app."""
    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    target = tmp_path / "proof-linker"
    target.mkdir()
    client = webui.app.test_client()
    assert client.get("/api/files/pins").get_json() == {"pins": []}
    resp = client.post("/api/files/pins",
                       json={"name": "screened", "path": str(target),
                             "kind": "dir"})
    assert resp.status_code == 200
    assert resp.get_json()["pin"]["name"] == "screened"
    assert [p["name"] for p in
            client.get("/api/files/pins").get_json()["pins"]] == ["screened"]
    # Invalid path → 400, never a partial write (Q: is on no browse root).
    bad = client.post("/api/files/pins",
                      json={"name": "evil", "path": "Q:\\no-such-root\\x",
                            "kind": "dir"})
    assert bad.status_code == 400
    assert [p["name"] for p in
            client.get("/api/files/pins").get_json()["pins"]] == ["screened"]
    # Restart persistence: file on disk holds the pin.
    stored = json.loads((tmp_path / "webui" / "pinned_paths.json")
                        .read_text(encoding="utf-8"))
    assert [p["name"] for p in stored["pins"]] == ["screened"]
    assert client.delete("/api/files/pins/screened").status_code == 200
    assert client.get("/api/files/pins").get_json() == {"pins": []}
    assert client.delete("/api/files/pins/screened").status_code == 404
