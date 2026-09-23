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

HTML_PATH = os.path.join(PROJECT_ROOT, "factory", "linking", "webui",
                         "index.html")


def _html():
    with open(HTML_PATH, encoding="utf-8") as handle:
        return handle.read()


def test_wide_canvas_two_column():
    text = _html()
    assert "max-inline-size:1400px" in text
    assert "grid-template-columns:minmax(0,7fr) minmax(0,5fr)" in text


def test_separation_drawer_and_templates():
    text = _html()
    # run form alone on compose; provider configuration only in drawer
    assert 'id="drawer-settings"' in text
    assert 'id="btn-settings"' in text
    drawer = text.split('id="drawer-settings"')[1].split("</aside>")[0]
    assert 'id="provider-cards"' in drawer and 'id="s-name"' in drawer
    assert 'id="s-key"' in drawer  # unified custom form includes key field
    # no loose-keys card, no manual variable typing in the drawer
    assert 'id="key-list"' not in drawer
    assert 'id="k-value"' not in drawer and 'id="k-var"' not in drawer
    assert 'id="s-keyvar"' not in drawer
    compose = text.split('id="panel-compose"')[1].split("</section>")[0]
    assert 'id="provider-cards"' not in compose
    assert 'id="s-name"' not in compose


def test_engineering_renames_consistent():
    text = _html()
    # new names present across page + guide + receipts
    for token in ("کنسول کارخانه داده", "غربال‌سازی و داوری",
                  "پیش‌تنظیم‌های اجرا", "پیش‌تنظیم", "رسید فرمان",
                  "رسید فرمان پیوند", "محک",
                  "کارت‌های رویداد", "اتصال‌های سفارشی"):
        assert token in text, token
    # old names gone from visible headings/labels
    for old in ("پریست‌ها", "پریست", "قبض فرمان", "سنجش با طلا",
                "داور پیوند", "ساخت اجرا", "قالب‌های داور",
                "قالب‌های کاری", "نشاندن در فرم", "قالب داور",
                "قالب کاری"):
        assert old not in text, old
    # linking-tab receipt builds the linking line's own command (never precard)
    compose = text.split('id="panel-compose"')[1].split("</section>")[0]
    assert "رسید فرمان پیوند" in compose
    assert "factory.linking.cli" in text  # receipt builder script
    assert "factory.precard" not in compose
    assert "precard" not in compose
    # job-template alias routes exist alongside canonical presets
    rules = sorted(r.rule for r in webui.app.url_map.iter_rules())
    assert "/api/job_templates" in rules
    assert "/api/presets" in rules


def test_ergonomics_controls():
    text = _html()
    assert 'id="btn-skey-toggle"' in text  # client-side only toggle
    assert 'id="provider-cards"' in text  # per-provider cards
    assert 'pill done' in text and 'pill fail' in text  # status pills
    assert 'id="file-picker"' in text  # input/output path picker
    # spare run form: no steppers, spinners, or extra knobs
    for gone in ('id="btn-conc-minus"', 'id="btn-conc-plus"',
                 'id="paths-spinner"', 'id="f-limit"',
                 'id="f-concurrency"', 'id="f-resume"',
                 'id="f-progress"'):
        assert gone not in text, gone


def test_watch_cards_progress_no_raw_dump():
    text = _html()
    assert 'id="watch-cards"' in text
    assert 'id="watch-progress"' in text
    assert 'role="progressbar"' in text
    assert 'evcard lv-' in text
    assert 'id="watch-events"' not in text  # raw dump removed


def test_benchmark_filters_sort_search_pagination():
    text = _html()
    assert 'id="b-mismatch-only"' in text
    # meaning-first sorts: source word, gold, prediction (no key sort:
    # internal w:key ids are secondary small text only)
    assert 'data-sort="text"' in text and 'data-sort="gold"' in text
    assert 'data-sort="predicted"' in text
    assert 'data-sort="key"' not in text
    assert 'id="b-search"' in text
    assert 'id="b-prev"' in text and 'id="b-next"' in text
    assert 'BENCH_PAGE_SIZE' in text


def test_compose_path_pickers_plus_manual_entry():
    text = _html()
    # spare form: picker dialog buttons next to input + output only
    for btn, field in (("btn-browse-sample", "f-sample"),
                       ("btn-browse-out", "f-out")):
        assert 'id="%s"' % btn in text, btn
        assert 'id="%s"' % field in text, field
    assert 'id="btn-browse-progress"' not in text
    assert 'id="f-progress"' not in text
    assert 'id="file-picker"' in text
    assert 'id="picker-list"' in text and 'id="picker-pick"' in text


def test_spare_run_form_provider_model_input_output():
    text = _html()
    compose = text.split('id="panel-compose"')[1].split("</section>")[0]
    # spare and modern: provider, model, input file, output path, run button
    for ctrl in ('id="f-provider"', 'id="f-model"', 'id="f-sample"',
                 'id="f-out"', 'id="btn-launch"'):
        assert ctrl in compose, ctrl
    assert "فایل ورودی" in compose
    assert "مسیر خروجی" in compose
    # removed knobs stay out of the linking tab
    for gone in ('id="f-limit"', 'id="f-concurrency"', 'id="f-resume"',
                 'id="f-progress"', 'id="sample-about"',
                 'id="schema-example"', 'id="paths-echo"'):
        assert gone not in compose, gone


def test_single_run_preset_section():
    text = _html()
    compose = text.split('id="panel-compose"')[1].split("</section>")[0]
    # one straightforward section for run presets: a single save/load
    assert "پیش‌تنظیم‌های اجرا" in compose
    assert 'id="t-name"' in compose and 'id="t-list"' in compose
    assert 'id="btn-template-save"' in compose
    assert 'id="btn-template-load"' in compose
    assert 'id="btn-template-del"' in compose
    # the two side-column boxes are gone (no judge presets, no job presets)
    for gone in ('id="j-name"', 'id="j-list"',
                 'id="btn-judge-save"', 'id="btn-judge-apply"',
                 'id="btn-judge-del"', 'judge-kind'):
        assert gone not in text, gone
    # backend endpoints stay working; old stored records keep loading
    rules = sorted(r.rule for r in webui.app.url_map.iter_rules())
    assert "/api/presets" in rules
    assert "/api/job_templates" in rules
    assert "/api/judge_presets" in rules


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
    assert "منبع" in text and "شاهد مرجع" in text
    assert "پیش‌بینی موتور" in text
    assert "هم‌خوان با شاهد" in text and "مغایر با شاهد" in text
    assert "badge-ok" in text and "badge-mis" in text
    assert "sub-id" in text  # technical ids kept as secondary small text
    assert "شناسه‌های فنی" in text


def test_form_hints_progressive_disclosure():
    text = _html()
    # every kept field help is a tooltip popup toggled by a small button,
    # never an always-visible paragraph
    for tip in ("tip-provider", "tip-model", "tip-sample",
                "tip-out", "tip-tname", "tip-tlist",
                "tip-brun", "tip-gsearch",
                "tip-sname", "tip-sbase", "tip-skey", "tip-smodel"):
        assert 'id="%s"' % tip in text, tip
        assert '<p class="hint" id="%s"' % tip not in text, tip
        assert 'data-tip="%s"' % tip in text, tip
    # removed knobs leave no tooltip behind
    for gone in ("tip-limit", "tip-concurrency", "tip-resume",
                 "tip-progress", "tip-jname", "tip-jlist"):
        assert 'id="%s"' % gone not in text, gone
    assert "bindTips" in text
    # dynamic validation line stays a live paragraph
    assert 'id="sample-check"' in text


def test_guide_grouped_accordion_with_bulk_toggle_and_search_expand():
    text = _html()
    assert 'id="guide-expand-all"' in text
    assert 'id="guide-collapse-all"' in text
    assert "<details" in text and "<summary>" in text
    assert 'class="qgroup"' in text
    assert "guideSetAll" in text
    assert "card.open = true" in text  # search auto-expands hits


def test_dark_default_persisted_toggle():
    text = _html()
    assert 'data-theme="dark"' in text
    assert "hb-theme" in text
    assert 'id="btn-theme"' in text


def test_rtl_persian_digits_latin_isolation():
    text = _html()
    assert '<html lang="fa" dir="rtl"' in text
    assert "faNum" in text
    assert 'lang="en" dir="ltr"' in text


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
    resp = client.post("/api/runs", json={"provider": "avalai", "model": "",
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
    # explicit per-provider key-variable mapping (names only, persisted)
    assert "providerKeyVarSave" in text
    assert "/key_var" in text
    assert 'id="btn-master-ensure"' in text
    assert "masterEnsure" in text
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


def test_custom_unified_creation_form():
    text = _html()
    drawer = text.split('id="drawer-settings"')[1].split("</aside>")[0]
    for ctrl in ('id="s-name"', 'id="s-base"', 'id="s-model"',
                 'id="s-key"', 'id="btn-profile-save"',
                 'id="profile-list"'):
        assert ctrl in drawer, ctrl


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
    # leased-vs-direct routing line under the provider select
    assert 'id="route-line"' in text
    assert "updateRouteLine" in text
    assert "تونل اجاره‌ای" in text and "مستقیم" in text
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
    resp = client.post("/api/runs", json={"provider": "google",
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
    resp = client.post("/api/runs", json={"provider": "avalai",
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
    """Hint names the linking word list; footer matches console identity."""
    text = _html()
    tip = text.split('id="tip-sample"')[1].split("</span>")[0]
    assert "فهرست واژه" in tip
    assert "sample.json" not in tip
    compose = text.split('id="panel-compose"')[1].split("</section>")[0]
    assert "sample.json" not in compose
    assert "factory.precard" not in compose
    footer = text.split("<footer>")[1].split("</footer>")[0]
    assert "factory.precard" not in footer
    assert "کنسول" in footer and "کارخانه داده" in footer
    assert "موتور خط فرمان" not in footer
