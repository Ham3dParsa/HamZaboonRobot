"""Shared webui data-root tickets: T1 migration, T3 file facts, T2 init race.

Hermetic: tmp_path + monkeypatch only (never touches the real shared
root or the multi-GB kaikki dump — the cap test uses a small file with
a monkeypatched cap). Secrets: names only, values never.
"""

import json
import os

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

TELEMETRY_JS = os.path.join(
    PROJECT_ROOT, "factory", "webui", "static", "js",
    "telemetry", "telemetry_dashboard_controller.js")


def _webui():
    from factory.webui import server as webui
    return webui


# ─── T1: first-boot auto-migration ───────────────────────────────

def _seed_legacy(legacy_dir, presets=("witness-benchmark.json",)):
    os.makedirs(os.path.join(legacy_dir, "presets"), exist_ok=True)
    for name in presets:
        with open(os.path.join(legacy_dir, "presets", name), "w",
                  encoding="utf-8") as handle:
            json.dump({"name": "witness-benchmark", "kind": "run",
                       "provider": "avalai"}, handle)
    with open(os.path.join(legacy_dir, "operator_keys.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"SOME_API_KEY": "ciphertext-names-only"}, handle)
    with open(os.path.join(legacy_dir, "labels.jsonl"), "w",
              encoding="utf-8") as handle:
        handle.write('{"kid": "k1"}\n')


def _point_store_at(monkeypatch, webui, legacy_dir, shared_dir):
    monkeypatch.setattr(webui, "SCRIPT_DIR", legacy_dir)
    monkeypatch.setattr(webui, "PRESETS_DIR",
                        os.path.join(shared_dir, "presets"))
    monkeypatch.setattr(webui, "OPERATOR_KEYS_PATH",
                        os.path.join(shared_dir, "operator_keys.json"))
    monkeypatch.setattr(webui, "LABELS_PATH",
                        os.path.join(shared_dir, "labels.jsonl"))


def test_migration_copies_only_into_empty_slots(tmp_path, monkeypatch):
    webui = _webui()
    legacy, shared = str(tmp_path / "legacy"), str(tmp_path / "shared")
    _seed_legacy(legacy)
    _point_store_at(monkeypatch, webui, legacy, shared)
    webui._ensure_shared_store_migrated()
    assert json.load(open(os.path.join(
        shared, "presets", "witness-benchmark.json"),
        encoding="utf-8"))["provider"] == "avalai"
    assert "SOME_API_KEY" in json.load(open(
        os.path.join(shared, "operator_keys.json"), encoding="utf-8"))
    assert open(os.path.join(shared, "labels.jsonl"),
                encoding="utf-8").read() == '{"kid": "k1"}\n'


def test_migration_never_overwrites(tmp_path, monkeypatch):
    webui = _webui()
    legacy, shared = str(tmp_path / "legacy"), str(tmp_path / "shared")
    _seed_legacy(legacy)
    _point_store_at(monkeypatch, webui, legacy, shared)
    os.makedirs(os.path.join(shared, "presets"), exist_ok=True)
    with open(os.path.join(shared, "presets", "witness-benchmark.json"),
              "w", encoding="utf-8") as handle:
        json.dump({"name": "witness-benchmark",
                   "operator": "edited"}, handle)
    with open(os.path.join(shared, "operator_keys.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"MINE": "mine-ciphertext"}, handle)
    webui._ensure_shared_store_migrated()
    assert json.load(open(os.path.join(
        shared, "presets", "witness-benchmark.json"),
        encoding="utf-8"))["operator"] == "edited"
    assert json.load(open(os.path.join(shared, "operator_keys.json"),
                          encoding="utf-8")) == {"MINE": "mine-ciphertext"}
    # restart-safe: a second boot changes nothing either
    webui._ensure_shared_store_migrated()
    assert json.load(open(os.path.join(
        shared, "presets", "witness-benchmark.json"),
        encoding="utf-8"))["operator"] == "edited"


def test_preset_ops_work_against_pointed_store(tmp_path, monkeypatch):
    """save-upsert + rename-edit + delete + save-as clone, all on the store
    the globals point at (shared in production)."""
    webui = _webui()
    monkeypatch.setattr(webui, "PRESETS_DIR", str(tmp_path / "presets"))
    rec = webui.save_preset({"name": "orig", "provider": "avalai",
                             "model": "", "limit": 5, "concurrency": 8})
    assert rec["version"] == 1
    assert os.path.isfile(os.path.join(
        str(tmp_path / "presets"), "orig.json"))
    renamed = webui.save_preset({"name": "renamed",
                                 "previous_name": "orig",
                                 "provider": "avalai", "model": "",
                                 "limit": 5, "concurrency": 8})
    assert renamed["version"] == 2
    assert webui.get_preset("orig") is None
    clone = webui.save_preset({"name": "clone", "provider": "avalai",
                               "model": "", "limit": 5, "concurrency": 8})
    assert clone["version"] == 1  # save-as: fresh record, no previous_name
    assert webui.delete_preset("renamed") is True
    assert webui.delete_preset("renamed") is False
    assert webui.get_preset("clone")["name"] == "clone"


# ─── T3: bounded file facts ──────────────────────────────────────

def test_file_facts_small_file_exact(tmp_path):
    webui = _webui()
    target = str(tmp_path / "s.jsonl")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write('{"a": 1}\n{"a": 2}\n{"a": 3}\n')
    facts = webui._file_facts(target)
    assert facts["exists"] is True
    assert facts["size"] == os.path.getsize(target)
    assert (facts["lines"], facts["lines_label"],
            facts["truncated"]) == (3, "3", False)


def test_file_facts_missing_file(tmp_path):
    webui = _webui()
    facts = webui._file_facts(str(tmp_path / "nope.jsonl"))
    assert facts["exists"] is False
    assert facts["size"] == 0
    assert (facts["lines"], facts["lines_label"],
            facts["truncated"]) == (0, "0", False)


def test_file_facts_truncates_with_honest_label(tmp_path, monkeypatch):
    webui = _webui()
    monkeypatch.setattr(webui, "_FILE_LINES_CAP", 50)
    target = str(tmp_path / "big.jsonl")
    with open(target, "w", encoding="utf-8") as handle:
        for num in range(60):
            handle.write('{"n": %d}\n' % num)
    facts = webui._file_facts(target)
    assert facts["exists"] is True
    assert facts["size"] == os.path.getsize(target)
    assert (facts["lines"], facts["lines_label"],
            facts["truncated"]) == (50, "50+", True)


def test_files_roots_reports_both_datasets():
    webui = _webui()
    body = webui.app.test_client().get("/api/files/roots").get_json()
    assert body["roots"] and all(
        "path" in r and "label" in r for r in body["roots"])
    files = body["files"]
    assert sorted(files.keys()) == ["kaikki_raw", "screened"]
    for facts in files.values():
        assert "exists" in facts and "size" in facts
        assert "lines" in facts and "lines_label" in facts
        assert "truncated" in facts
        if facts["truncated"]:
            assert facts["lines_label"].endswith("+")
        else:
            assert facts["lines_label"] == str(facts["lines"])


# ─── T2: telemetry init race (controller-only) ───────────────────

def _telemetry_text():
    with open(TELEMETRY_JS, encoding="utf-8") as handle:
        return handle.read()


def _main_text():
    with open(os.path.join(PROJECT_ROOT, "factory", "webui", "static",
                           "js", "main.js"), encoding="utf-8") as handle:
        return handle.read()


def test_telemetry_controller_fetches_on_init_besides_listeners():
    text = _telemetry_text()
    assert "export async function fetchAndRenderTelemetry" in text
    assert "export async function fetchAndRenderPaths" in text
    assert "hz:providers-refreshed" in text
    assert "hz:paths-refreshed" in text
    # init calls live at module bottom (after the listeners), so tables
    # populate on page load even when the refresh events fired first
    tail = text.split("hz:paths-refreshed")[-1]
    assert "fetchAndRenderTelemetry();" in tail
    assert "fetchAndRenderPaths();" in tail
    assert "/api/providers" in text and "/api/files/roots" in text
    # wiring: main.js must actually load the controller, else neither the
    # listeners nor the init fetches ever run (proven frozen "…" live)
    assert "telemetry/telemetry_dashboard_controller.js" in _main_text()
