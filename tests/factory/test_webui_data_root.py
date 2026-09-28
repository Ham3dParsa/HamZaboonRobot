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
    monkeypatch.setattr(webui, "presets_dir",
                        lambda: os.path.join(shared_dir, "presets"))
    monkeypatch.setattr(webui, "operator_keys_path",
                        lambda: os.path.join(shared_dir,
                                             "operator_keys.json"))
    monkeypatch.setattr(webui, "labels_path",
                        lambda: os.path.join(shared_dir, "labels.jsonl"))


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
    the helpers point at (shared in production)."""
    webui = _webui()
    monkeypatch.setattr(webui, "presets_dir", lambda: str(tmp_path / "presets"))
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


def test_files_roots_reports_both_datasets(monkeypatch):
    webui = _webui()
    # Hermetic: never run the real boot migration off a bare GET here
    # (dedicated test below covers the hook with a pointed store).
    monkeypatch.setitem(webui._MIGRATED_ONCE, "done", True)
    webui._reset_file_facts_cache()
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


# ─── Lazy helpers + boot migration + facts TTL ────────────────

def test_store_helpers_follow_data_root_between_calls(tmp_path, monkeypatch):
    """presets_dir()/operator_keys_path()/labels_path() are lazy: a later
    data_root() change moves every helper (no import-time split)."""
    webui = _webui()
    first, second = str(tmp_path / "one"), str(tmp_path / "two")
    monkeypatch.setattr(webui, "data_root", lambda: first)
    assert webui.presets_dir() == os.path.join(first, "webui", "presets")
    assert webui.operator_keys_path() == os.path.join(
        first, "webui", "operator_keys.json")
    assert webui.labels_path() == os.path.join(
        first, "webui", "labels.jsonl")
    monkeypatch.setattr(webui, "data_root", lambda: second)
    assert webui.presets_dir() == os.path.join(second, "webui", "presets")
    assert webui.operator_keys_path() == os.path.join(
        second, "webui", "operator_keys.json")
    assert webui.labels_path() == os.path.join(
        second, "webui", "labels.jsonl")


def test_boot_migration_runs_on_first_request(tmp_path, monkeypatch):
    """Any serve path (not only __main__) migrates once before serving."""
    webui = _webui()
    legacy, shared = str(tmp_path / "legacy"), str(tmp_path / "shared")
    _seed_legacy(legacy)
    _point_store_at(monkeypatch, webui, legacy, shared)
    monkeypatch.setitem(webui._MIGRATED_ONCE, "done", False)
    webui._reset_file_facts_cache()
    resp = webui.app.test_client().get("/api/files/roots")
    assert resp.status_code == 200
    assert webui._MIGRATED_ONCE["done"] is True
    assert json.load(open(os.path.join(
        shared, "presets", "witness-benchmark.json"),
        encoding="utf-8"))["provider"] == "avalai"
    assert "SOME_API_KEY" in json.load(open(
        os.path.join(shared, "operator_keys.json"), encoding="utf-8"))


def test_data_file_facts_cached_with_short_ttl(tmp_path, monkeypatch):
    """Second /api/files/roots payload within TTL performs zero rescans."""
    webui = _webui()
    calls = {"n": 0}
    real = webui._file_facts

    def _counting(path):
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(webui, "_file_facts", _counting)
    webui._reset_file_facts_cache()
    first = webui._data_file_facts()
    assert calls["n"] == 2  # kaikki_raw + screened, exactly once each
    second = webui._data_file_facts()
    assert calls["n"] == 2  # served from cache — no rescan
    assert second == first
    webui._reset_file_facts_cache()
    webui._data_file_facts()
    assert calls["n"] == 4  # reset re-arms the scan


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


# ─── T10: paths T3 wiring + formatting sweep ────────────────────
# Locked: renderPaths consumes files.{kaikki_raw,screened} (exists/size/
# lines/mtime or titled —); every — titled; dead roots drop with count;
# elapsed via elapsed_human; log idle/live/final with cause. Route-delete:
# no splitDropReasons symbol exists (grep proof) — nothing to remove.

def _screening_text():
    with open(os.path.join(PROJECT_ROOT, "factory", "webui", "static",
                           "js", "screening",
                           "screening_cabin_controller.js"),
              encoding="utf-8") as handle:
        return handle.read()


def test_file_facts_include_mtime_for_existing_file(tmp_path):
    webui = _webui()
    target = str(tmp_path / "m.jsonl")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write('{"a": 1}\n')
    facts = webui._file_facts(target)
    assert facts["exists"] is True
    assert facts["mtime_iso"], facts
    assert facts["mtime_relative"] != "—", facts
    assert "Asia/Tehran" in facts["mtime_detail"] or \
        "میلادی" in facts["mtime_detail"], facts


def test_file_facts_missing_file_keeps_honest_mtime(tmp_path):
    webui = _webui()
    facts = webui._file_facts(str(tmp_path / "nope.jsonl"))
    assert facts["exists"] is False
    assert facts["mtime_iso"] is None
    assert facts["mtime_relative"] == "—"
    assert facts["mtime_detail"] == "—"


def test_files_roots_files_carry_four_values(monkeypatch):
    """roots response with facts → 4 values per dataset (exists/size/
    lines/mtime); over-cap lines keep the honest 50000+ label."""
    webui = _webui()
    monkeypatch.setitem(webui._MIGRATED_ONCE, "done", True)
    webui._reset_file_facts_cache()
    body = webui.app.test_client().get("/api/files/roots").get_json()
    assert sorted(body["files"].keys()) == ["kaikki_raw", "screened"]
    for facts in body["files"].values():
        for key in ("exists", "size", "lines", "lines_label",
                    "truncated", "mtime_iso", "mtime_relative",
                    "mtime_detail"):
            assert key in facts, (key, facts)
        if facts["truncated"]:
            assert facts["lines"] == 50000
            assert facts["lines_label"] == "50000+"


def test_telemetry_paths_consumes_files_facts():
    """Static wiring proof: renderPaths(roots, files) reads screened/
    kaikki_raw exists/size/lines/mtime; every — built with a title."""
    text = _telemetry_text()
    assert "export function renderPaths(roots, files)" in text
    assert "files.screened" in text and "files.kaikki_raw" in text
    assert "mtime_relative" in text and "lines_label" in text
    assert "titledEmpty(" in text
    # no bare dash construction remains in the paths renderer:
    # every "—" literal in this module rides a titled cell
    assert text.count("title") >= text.count("—"), text.count("—")
    # event + init fetch both carry files through
    assert "detail.files" in text
    assert "f && f.files" in text or "(f && f.files)" in text


def test_screening_metrics_prefer_drop_reasons_and_titled():
    """Static proof: drop_reasons preferred, elapsed_human primary,
    metric empties titled, log 3-state titled, no splitDropReasons."""
    text = _screening_text()
    assert "manifest.drop_reasons" in text or \
        "manifest && manifest.drop_reasons" in text
    # route-delete proof: no fallback reader function exists (the word
    # only appears in the T10 proof comment, never as a def/call)
    assert "function splitDropReasons" not in text
    assert "splitDropReasons(" not in text.replace(
        "splitDropReasons reader exists", "")
    assert "elapsed_human" in text
    # metricVal builds titled empties (no removeAttribute on the — path)
    assert "emptyCause" in text
    assert "سرور تفکیک علت ثبت نکرد" in text
    assert "هنوز اجرایی شروع نشده است" in text
    # log box three states each with a titled cause
    assert "وضعیت: بیکار" in text
    assert "وضعیت: در حال اجرا" in text
    assert "سرور گزارشی برنگرداند" in text
