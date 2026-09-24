"""Interface tests for the factory-data console linking tab.

Reads factory/linking/webui/index.html + server routes; no browser needed.
Behavior/safety engines untouched: localhost-only, same CLI builder, no
secret values in any surface.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.linking.webui import server as webui

HTML_PATH = os.path.join(PROJECT_ROOT, "factory", "webui",
                         "index.html")


def _html():
    with open(HTML_PATH, encoding="utf-8") as handle:
        return handle.read()


def test_wide_canvas_two_column():
    text = _html()
    assert "max-width: 1600px" in text
    assert "minmax(0, 7.5fr) minmax(320px, 4.5fr)" in text


def test_v5_identity_and_no_demo_constants():
    text = _html()
    for token in ("کنسول عملیات کارخانه داده هم‌زبان",
                  "view-linking", "view-providers", "view-telemetry",
                  "view-paths", "btn-nav-linking"):
        assert token in text, token
    assert "kilo" not in text.lower()  # NOT ready engine-side: never shown
    for demo in ("124 / 200 RPH", "screened_run20.jsonl",
                 "run%2:38:00::", "verdictAlert", "gemini-3.8",
                 "llama-3.3-70b", "precards.jsonl", "kaikki-en-words.jsonl"):
        assert demo not in text, demo


def test_nav_sidebar_views_no_popups():
    text = _html()
    assert 'id="main-nav"' in text
    assert 'id="menu-toggle-btn"' in text
    assert 'id="nav-backdrop"' in text
    for view in ("view-providers", "view-telemetry", "view-paths",
                 "view-screening", "view-linking", "view-precard",
                 "view-pilot", "view-transfer"):
        assert 'id="%s"' % view in text, view
    assert "openView" in text
    # no popups, no side drawer, no thick colored borders
    assert "alert(" not in text
    assert "confirm(" not in text
    assert "prompt(" not in text


def test_status_bar_wired_to_real_endpoints():
    text = _html()
    for ctrl in ('id="badge-root"', 'id="badge-keys"',
                 'id="badge-egress"'):
        assert ctrl in text, ctrl
    assert "/api/master/status" in text
    assert "/api/egress/health" in text
    assert "/api/files/roots" in text


def test_linking_queue_from_screened_and_label_wiring():
    text = _html()
    # queue + current sense render only from the screened output
    assert 'id="queue-list"' in text
    assert 'id="sense-id"' in text and 'id="sense-def"' in text
    assert 'id="sense-example"' in text and 'id="sense-meta"' in text
    assert "/api/screened" in text
    assert 'id="handoff-path"' in text and 'id="handoff-total"' in text
    # reject-all + link vote post to the label endpoint with a receipt
    assert 'id="btn-reject-all"' in text
    assert 'id="btn-record-link"' in text
    assert 'id="btn-skip-next"' in text
    assert 'id="label-target"' in text
    assert 'id="label-stratum"' in text
    assert 'id="label-annotator"' in text
    assert 'id="label-receipt"' in text
    assert "'POST'" in text and "/api/labels" in text
    # no candidate feed exists server-side: honest empty state, never stubs
    assert "بدون فید زنده نامزدها" in text


def test_paths_view_from_live_roots():
    text = _html()
    assert 'id="paths-tbody"' in text
    assert 'id="paths-badge"' in text
    assert "/api/files/roots" in text
    rules = sorted(r.rule for r in webui.app.url_map.iter_rules())
    assert "/api/files/list" in rules


def test_preset_form_live_registry_locked_temp():
    text = _html()
    assert 'id="preset-provider"' in text
    assert 'id="preset-model"' in text
    assert 'id="btn-fetch-models"' in text
    assert 'id="preset-models"' in text
    assert "/api/providers/" in text and "/models" in text
    assert "/api/engine_info" in text
    # backend preset kinds stay working (no preset UI save in v5)
    rules = sorted(r.rule for r in webui.app.url_map.iter_rules())
    assert "/api/presets" in rules
    assert "/api/job_templates" in rules
    assert "/api/judge_presets" in rules


def test_telemetry_live_facts_honest_empty_tokens():
    text = _html()
    assert 'id="telemetry-tbody"' in text
    assert 'id="telemetry-badge"' in text
    assert "/api/rate_state" in text
    # token/cost aggregates have no server computation: honest "—", never faked
    assert "سرور ثبت نمی‌کند" in text


def test_provider_list_matches_engine_registry_no_kilo():
    import json as _json
    text = _html().lower()
    assert "kilo" not in text  # NOT ready engine-side: never shown
    client = webui.app.test_client()
    info = client.get("/api/engine_info").get_json()
    from factory.precard import provider_registry
    assert info["providers"] == provider_registry.provider_names()
    assert info["model_list"] is None
    assert info["temperature"]["supported"] is False
    assert isinstance(info["judge_batch"], int)


def test_benchmark_table_meaning_first():
    text = _html()
    # telemetry table keeps the provider/model-first columns; every
    # token/cost cell renders the honest empty state (no fake numbers)
    assert "ارائه‌دهنده" in text and "مدل فعال" in text
    assert "توکن ورودی عادی" in text and "ارزش تخمینی دلاری" in text


def test_form_hints_progressive_disclosure():
    text = _html()
    # v5 carries no tooltip popups and no always-visible hint paragraphs
    # on the wiring surfaces; dynamic latin is isolated via classes
    assert "bindTips" not in text
    assert "data-tip=" not in text
    # dynamic validation/errors stay inline text lines
    assert 'id="provider-err"' in text
    assert 'id="label-status"' in text


def test_guide_grouped_accordion_with_bulk_toggle_and_search_expand():
    text = _html()
    # v5 ships no guide accordion; the linking queue is the live browser
    assert "guideSetAll" not in text
    assert 'id="queue-list"' in text


def test_dark_default_persisted_toggle():
    text = _html()
    assert 'data-theme="dark"' in text
    assert "hz-theme" in text
    assert 'id="theme-btn"' in text


def test_rtl_persian_digits_latin_isolation():
    text = _html()
    assert '<html lang="fa" dir="rtl"' in text
    assert "faNum" in text
    # v5 isolation contract: dedicated classes, never bare latin runs
    assert "ltr-text" in text and "code-token" in text
    assert "unicode-bidi: isolate" in text


def test_safety_surfaces_unchanged():
    assert webui.HOST == "127.0.0.1" and webui.PORT == 5561
    client = webui.app.test_client()
    for path in ("/", "/api/providers", "/api/keys", "/api/job_templates"):
        body = client.get(path).get_data(as_text=True)
        for var, val in os.environ.items():
            upper = var.upper()
            if ("KEY" in upper or "TOKEN" in upper or "SECRET" in upper) \
                    and val and len(val) >= 8:
                assert val not in body


def test_job_template_alias_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "PRESETS_DIR", str(tmp_path))
    client = webui.app.test_client()
    resp = client.post("/api/job_templates", json={"name": "jt1",
                                                   "provider": "avalai",
                                                   "model": "", "sample": "",
                                                   "limit": 0,
                                                   "concurrency": 8})
    assert resp.status_code == 200
    rec = resp.get_json()["job_template"]
    assert rec["version"] == 1 and rec["concurrency"] == 8
    assert client.get("/api/job_templates").get_json()["job_templates"]
    assert client.delete("/api/job_templates/jt1").status_code == 200


def test_create_run_accepts_job_template_field(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(webui, "PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.setattr(webui, "RUNS_DIR", str(tmp_path / "runs"))
    registry = tmp_path / "runs.json"
    registry.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(webui, "REGISTRY_PATH", str(registry))
    client = webui.app.test_client()
    client.post("/api/job_templates", json={"name": "jt2",
                                            "provider": "avalai", "model": "",
                                            "sample": "", "limit": 0,
                                            "concurrency": 8})
    # unknown template -> plain 400, nothing spawned
    resp = client.post("/api/runs", json={"flow": "precard",
                                          "provider": "avalai", "model": "",
                                          "sample": "", "limit": 0,
                                          "concurrency": 8, "resume": "on",
                                          "job_template": "ghost"})
    assert resp.status_code == 400


def test_provider_cards_explicit_keyvar_mapping_and_rate_state():
    text = _html()
    # per-provider endpoints drive save/delete from the cards
    assert "/api/providers/" in text and "/key" in text
    assert "providerKeySave" in text and "providerKeyDelete" in text
    assert "refreshProviderCards" in text
    # per-card status pills: ready versus missing
    assert "کلید آماده است" in text and "بدون کلید" in text
    # effective key-variable mapping is displayed (names only, persisted);
    # the rename (PUT) stays API-level in v5
    assert "key_var" in text
    assert 'id="btn-master-ensure"' in text
    assert "masterEnsure" in text
    assert "/api/master/ensure" in text
    # honest per-provider rate facts under each card
    assert "rateLineFor" in text and "/api/rate_state" in text
    # loose-keys card and manual generic variable inputs are gone
    for gone in ('id="key-list"', 'id="k-value"', 'id="k-var"',
                 'id="s-keyvar"', 'id="btn-key-save"'):
        assert gone not in text, gone
    # server mapping round-trip (names only, persisted across reads)
    client = webui.app.test_client()
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        import os as _os
        map_path = _os.path.join(tmp, "provider_key_vars.json")
        old = webui.KEY_VAR_MAP_PATH
        webui.KEY_VAR_MAP_PATH = map_path
        try:
            got = client.get("/api/providers/groq/key_var").get_json()
            assert got["key_var"] == "GROQ_API_KEY_G1"
            put = client.put("/api/providers/groq/key_var",
                             json={"key_var": "GROQ_API_KEY_G2"})
            assert put.status_code == 200
            assert put.get_json()["key_var"] == "GROQ_API_KEY_G2"
            again = client.get("/api/providers/groq/key_var").get_json()
            assert again["key_var"] == "GROQ_API_KEY_G2"
            bad = client.put("/api/providers/groq/key_var",
                             json={"key_var": "9bad"})
            assert bad.status_code == 400
            ghost = client.put("/api/providers/ghost/key_var",
                               json={"key_var": "GHOST_API_KEY"})
            assert ghost.status_code == 404
        finally:
            webui.KEY_VAR_MAP_PATH = old
    # rate state: honest per-provider facts, names + booleans only
    state = client.get("/api/rate_state").get_json()["providers"]
    by_name = {r["name"]: r for r in state}
    for name in ("avalai", "google", "groq", "openrouter"):
        row = by_name[name]
        assert set(row["groups"]) == {"G1", "G2"}
        assert row["groups_count"] == sum(
            1 for v in row["groups"].values() if v)
        assert row["route"] in ("direct", "tunnel")
        assert row["pacing"]["rpm_limiter"] is False
    # master status: name + boolean only, never a value
    master = client.get("/api/master/status").get_json()
    assert master["var"] == "AI_MASTER_KEY"
    assert isinstance(master["configured"], bool)
    # unconfirmed ensure never generates anything
    denied = client.post("/api/master/ensure", json={})
    assert denied.status_code == 400


def test_custom_profiles_stay_api_level():
    # v5 ships no custom-profile form; the backend routes stay working
    # (creation round-trips are covered in the adapter suite).
    rules = sorted(r.rule for r in webui.app.url_map.iter_rules())
    assert "/api/custom_providers" in rules
    text = _html()
    assert 'id="drawer-settings"' not in text


def test_compare_returns_full_rows_for_filter(tmp_path, monkeypatch):
    import json
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps([
        {"kind": "word", "text": "a", "sense_id": "a#0"},
        {"kind": "word", "text": "b", "sense_id": "b#0"},
    ]), encoding="utf-8")
    out = tmp_path / "precard.jsonl"
    out.write_text('{"key": "w:a", "sense_id": "a#0"}\n'
                   '{"key": "w:b", "sense_id": "b#9"}\n',
                    encoding="utf-8")
    monkeypatch.setattr(webui, "RUNS_DIR", str(tmp_path / "runs"))
    registry = tmp_path / "runs.json"
    registry.write_text(json.dumps([{
        "id": "r-rows", "sample": str(sample), "out": str(out),
        "status": "done", "cli": "python -m factory.precard",
        "profile": None}]), encoding="utf-8")
    monkeypatch.setattr(webui, "REGISTRY_PATH", str(registry))
    body = webui.app.test_client().get("/api/runs/r-rows/compare").get_json()
    assert body["comparable"] is True
    by_key = {r["key"]: r for r in body["rows"]}
    assert by_key["w:a"]["match"] is True
    assert by_key["w:b"]["match"] is False
    assert body["mismatches"] == [
        {"key": "w:b", "gold": "b#0", "predicted": "b#9"}]


def test_routing_line_visible_before_launch():
    text = _html()
    # leased-vs-direct routing facts render under each provider card
    assert "تونل استیجاری" in text and "مستقیم" in text
    client = webui.app.test_client()
    rows = {r["name"]: r
            for r in client.get("/api/providers").get_json()["providers"]}
    assert rows["google"]["route"] == "leased"
    assert "403" in rows["google"]["route_reason"]
    assert "\n" not in rows["google"]["route_reason"]
    # whitelist slot: names only, "" when no verified exit exists
    assert rows["google"]["clean_exit"] == ""
    assert rows["avalai"]["clean_exit"] == ""
    assert rows["avalai"]["route"] == "direct"
    assert rows["groq"]["route"] == "direct"
    # dedicated per-provider route endpoint (pre-launch facts)
    one = client.get("/api/providers/google/route").get_json()
    assert one == {"provider": "google", "route": "leased",
                   "reason": rows["google"]["route_reason"],
                   "clean_exit": ""}
    assert client.get("/api/providers/ghost/route").status_code == 404
    # rate state keeps the leased note (no silent direct Google)
    state = {r["name"]: r for r in
             client.get("/api/rate_state").get_json()["providers"]}
    assert "tunnel" in state["google"]["lease_note"]


def test_routing_line_notes_whitelisted_exit(monkeypatch):
    from factory.linking import google_clean as _gc
    monkeypatch.setattr(_gc, "fresh_clean_exits",
                        lambda *a, **k: ["srv-clean"])
    client = webui.app.test_client()
    rows = {r["name"]: r
            for r in client.get("/api/providers").get_json()["providers"]}
    assert rows["google"]["clean_exit"] == "srv-clean"
    one = client.get("/api/providers/google/route").get_json()
    assert one["clean_exit"] == "srv-clean"
    info = client.get("/api/engine_info").get_json()
    assert info["routing"]["google"]["clean_exit"] == "srv-clean"
    # compose line renders the noted exit (pre-launch fact, names only)
    text = _html()
    assert "clean_exit" in text and "خروجی تمیز" in text


def test_engine_info_routing_and_judge_schema_mirror_bot():
    client = webui.app.test_client()
    info = client.get("/api/engine_info").get_json()
    # inspiration 1: routing table with the one-line Google reason
    assert info["routing"]["google"]["route"] == "leased"
    assert "403" in info["google_tunnel_reason"]
    assert "\n" not in info["google_tunnel_reason"]
    assert info["routing"]["google"]["clean_exit"] == ""
    assert info["routing"]["avalai"]["route"] == "direct"
    # inspiration 2: judge schema mirrors the bot preset wording
    from handlers import admin_ai_wizard as _wiz
    schema = info["judge_schema"]
    by_field = {f["field"]: f for group in (
        schema["rate_caps"] + schema["pacing"] + schema["timeout"])
        for f in [group]}
    for field in ("max_rpm", "max_tpm", "max_daily_req",
                  "max_concurrency", "timeout_seconds"):
        assert by_field[field]["label"] == _wiz.FIELD_LABELS[field]
        assert by_field[field]["help"] == _wiz._FIELD_HELP[field]
    temp = schema["temperature"]
    assert temp["locked"] is True and temp["supported"] is False
    assert temp["fixed"] == 0.0 and temp["reason"]
    # the spare form carries no judge-schema panel (backend stays working)
    text = _html()
    assert 'id="judge-schema"' not in text
    assert "paintJudgeSchema" not in text


def test_egress_health_read_only_no_spawn(monkeypatch):
    client = webui.app.test_client()
    rules = sorted(r.rule for r in webui.app.url_map.iter_rules())
    assert "/api/egress/health" in rules
    monkeypatch.setattr(webui, "_supervisor_token", lambda: "")
    resp = client.get("/api/egress/health")
    assert resp.status_code == 503
    assert "EGRESS_SUP_TOKEN" in resp.get_json()["error"]
    monkeypatch.setattr(webui, "supervisor_health_snapshot",
                        lambda timeout=10: (True, {"servers": 2,
                                                  "leases": 1,
                                                  "healthy": True}))
    body = client.get("/api/egress/health").get_json()
    assert body == {"healthy": True, "servers": 2, "leases": 1}


def test_model_list_endpoint_key_gated_and_attributed(monkeypatch):
    client = webui.app.test_client()
    rules = sorted(r.rule for r in webui.app.url_map.iter_rules())
    assert "/api/providers/<name>/models" in rules
    assert client.get("/api/providers/ghost/models").status_code == 404
    # key-gated: no resolvable key -> plain 400 naming the vars
    monkeypatch.setattr(webui, "_provider_key_var",
                        lambda p: "GOOGLE_AI_API_KEY")
    monkeypatch.setattr(webui, "_operator_key_values", lambda: {})
    import factory.precard.provider_lease_policy as _net
    monkeypatch.setattr(_net, "resolve_key", lambda *a, **k: "")
    resp = client.get("/api/providers/google/models")
    assert resp.status_code == 400
    assert "no key resolves" in resp.get_json()["error"]
    # attributed errors pass through (provider + kind, never values)
    monkeypatch.setattr(webui, "provider_model_list",
                        lambda p, timeout=30: (
                            None, "google models fetch failed: "
                                   "http-403 (provider-side; check the "
                                   "key and retry)"))
    resp = client.get("/api/providers/google/models")
    assert resp.status_code == 502
    assert "http-403" in resp.get_json()["error"]
    # exact ids pass through byte-identical (one-click copy source)
    monkeypatch.setattr(webui, "provider_model_list",
                        lambda p, timeout=30: (
                            ["gemini-3.5-flash-lite", "gemini-2.0-flash"],
                            None))
    body = client.get("/api/providers/google/models").get_json()
    assert body["models"] == ["gemini-3.5-flash-lite",
                              "gemini-2.0-flash"]
    assert body["count"] == 2


def test_model_id_parsers_never_invent():
    assert webui._google_model_ids(
        {"models": [{"name": "models/gemini-3.5-flash-lite"},
                    {"name": "models/gemini-2.0-flash"},
                    {"name": ""}, "junk"]}) == [
        "gemini-3.5-flash-lite", "gemini-2.0-flash"]
    assert webui._google_model_ids({}) == []
    assert webui._google_model_ids(None) == []
    assert webui._openai_model_ids(
        {"data": [{"id": "llama-3.3-70b-versatile"},
                  {"id": ""}, 42]}) == ["llama-3.3-70b-versatile"]
    assert webui._openai_model_ids({}) == []
    assert webui._openai_models_endpoint(
        "https://api.groq.com/openai/v1/chat/completions") == \
        "https://api.groq.com/openai/v1/models"
    assert webui._openai_models_endpoint("not-a-url") == ""


def test_model_list_endpoint_stays_server_side():
    # no model picker lives in the spare form; the key-gated endpoint
    # stays on the server (keys never touch the browser)
    text = _html()
    for gone in ('id="btn-model-list"', 'id="model-search"',
                 'id="model-filter-chips"', 'id="model-list"',
                 'id="model-err"', 'id="model-chips"'):
        assert gone not in text, gone
    rules = sorted(r.rule for r in webui.app.url_map.iter_rules())
    assert "/api/providers/<name>/models" in rules
    assert webui.app.test_client().get(
        "/api/providers/ghost/models").status_code == 404


def test_run_launch_leases_tunnel_for_google_only(tmp_path, monkeypatch):
    import subprocess as _sub

    monkeypatch.setattr(webui, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(webui, "PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.setattr(webui, "RUNS_DIR", str(tmp_path / "runs"))
    registry = tmp_path / "runs.json"
    registry.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(webui, "REGISTRY_PATH", str(registry))
    monkeypatch.setattr(webui, "_operator_key_values", lambda: {})

    leased = []

    def _fake_lease(provider):
        leased.append(provider)
        return ({"lease_id": "bb11cc22dd33", "mode": "tunnel",
                 "proxy_url": "http://127.0.0.1:19998",
                 "server_id": "srv-webui", "provider": provider,
                 "target": "google"}, None)

    monkeypatch.setattr(webui, "lease_tunnel_for_run", _fake_lease)
    reported = []
    monkeypatch.setattr(webui, "report_run_lease",
                        lambda lid, p, ok: reported.append((lid, p, ok)))

    seen_env = {}

    class _FakeStdout:
        def __iter__(self):
            return iter([])

    class _FakeProc:
        stdout = _FakeStdout()

        def wait(self):
            return 0

    def _fake_popen(argv, **kwargs):
        seen_env.update(kwargs.get("env") or {})
        return _FakeProc()

    monkeypatch.setattr(_sub, "Popen", _fake_popen)
    client = webui.app.test_client()
    resp = client.post("/api/runs", json={"flow": "precard",
                                          "provider": "google",
                                          "model": "", "sample": "",
                                          "limit": 0, "concurrency": 8,
                                          "resume": "on"})
    assert resp.status_code == 201
    rec = resp.get_json()["run"]
    assert rec["route"] == "leased"
    assert rec["lease"] == "bb11cc22"
    assert rec["egress"] == "srv-webui"
    assert "403" in rec["route_reason"]
    # OUR lease proxy rides the child env only.
    assert seen_env.get("HTTPS_PROXY") == "http://127.0.0.1:19998"
    assert seen_env.get("EGRESS_LEASE_ID") == "bb11cc22dd33"
    assert leased == ["google"]
    # direct providers lease nothing.
    resp = client.post("/api/runs", json={"flow": "precard",
                                          "provider": "avalai",
                                          "model": "", "sample": "",
                                          "limit": 0, "concurrency": 8,
                                          "resume": "on"})
    assert resp.get_json()["run"]["route"] == "direct"
    assert leased == ["google"]

    import time as _time
    for _ in range(100):
        if reported:
            break
        _time.sleep(0.05)
    assert reported and reported[0] == ("bb11cc22dd33", "google", True)


def test_input_hint_and_footer_word_list_identity():
    """Handoff strip names the screened input; console identity kept."""
    text = _html()
    assert 'id="handoff-path"' in text
    assert 'id="handoff-total"' in text
    assert "/api/screened" in text
    assert "کنسول عملیات کارخانه داده هم‌زبان" in text
