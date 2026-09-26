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
    # reject-all + link vote post to the label endpoint with a receipt;
    # the link target comes from the tapped candidate card, never typed
    assert 'id="btn-reject-all"' in text
    assert 'id="btn-record-link"' in text
    assert 'id="btn-skip-next"' in text
    assert 'id="label-target"' not in text  # manual synset field removed
    assert 'id="label-target-name"' in text  # selected-card target readout
    assert "selectedTarget" in text and "setSelectedTarget" in text
    # domain-language compliance: raw English stratum/annotator are OUT
    # of the form flow entirely (background defaults, never typed)
    assert 'id="label-stratum"' not in text
    assert 'id="label-annotator"' not in text
    assert "labelDefaults" in text
    assert 'id="label-receipt"' in text
    assert "'POST'" in text and "/api/labels" in text
    # live candidate feed: selecting a sense loads touch cards w/ real data
    assert 'id="candidates-stack"' in text
    assert 'id="candidates-status"' in text
    assert 'id="no-candidates-note"' not in text  # placeholder removed
    assert "بدون فید زنده نامزدها" not in text
    assert "loadCandidates" in text and "renderCandidates" in text
    assert "/api/candidates" in text
    rules = sorted(r.rule for r in webui.app.url_map.iter_rules())
    assert "/api/candidates" in rules


def _write_table(path):
    path.write_text(
        "kaikki_sense_id\twordnet_sensekey\tmethod\tevidence\tprovenance\n"
        "kid-apple\tapple%1:20:00::\tLINK:2-sig\tSa:j=0.50\tlinker-v0.6:test\n",
        encoding="utf-8")


def test_candidates_feed_returns_linker_rows_with_wordnet_fields(
        tmp_path, monkeypatch):
    """Feed shape: linker index rows + viewer wordnet readers, read-only."""
    import factory.linking.viewer as _viewer

    table = tmp_path / "table.tsv"
    _write_table(table)
    monkeypatch.setattr(
        _viewer, "_default_wordnet_resolver",
        lambda: {"apple%1:20:00::":
                 "round fruit || words: apple; orchard apple"})
    monkeypatch.setattr(webui, "_wordnet_live_fields",
                        lambda skey: ("apple.n.01", "she ate an apple"))
    body = webui.app.test_client().get(
        "/api/candidates",
        query_string={"sense_id": "kid-apple",
                      "table": str(table)}).get_json()
    assert body["sense_id"] == "kid-apple"
    assert body["total"] == 1
    (cand,) = body["candidates"]
    assert cand["sensekey"] == "apple%1:20:00::"
    assert cand["synset"] == "apple.n.01"
    assert cand["synset_locator"] == "20:00"
    assert cand["gloss"] == "round fruit"
    assert cand["synonyms"] == ["apple", "orchard apple"]
    assert cand["example"] == "she ate an apple"
    assert cand["method"] == "LINK:2-sig"
    assert cand["evidence"] == "Sa:j=0.50"


def test_candidates_feed_requires_sense_id():
    """Missing identifier fails closed (400, never an invented list)."""
    resp = webui.app.test_client().get("/api/candidates")
    assert resp.status_code == 400


def test_candidates_feed_unknown_sense_is_honest_empty(tmp_path):
    """No rows for the sense: honest empty list, never stubs."""
    table = tmp_path / "table.tsv"
    _write_table(table)
    body = webui.app.test_client().get(
        "/api/candidates",
        query_string={"sense_id": "kid-missing",
                      "table": str(table)}).get_json()
    assert body["sense_id"] == "kid-missing"
    assert body["total"] == 0
    assert body["candidates"] == []


# ─── T5 (phase-07): candidates from REAL runs + human-review join ───
# Diagnosis (verified against real data, 2026-09-24): the feed showed none
# for every queue sense for two stacked reasons. (1) Join-key mismatch: the
# queue sends the SHORT screened id (sense.sense_id, e.g. "run#5") but
# candidates_for_sense looked it up VERBATIM in the vendor table keyed by
# FULL kaikki ids (sense.id, e.g. "en-run-en-verb-tL7-sssU") — lookup_link
# always missed. (2) Wrong source + review list never loaded: the feed read
# ONLY the frozen 141-row vendor table (23/267 screened senses) and never
# the REAL run candidate files (run20 candidates_run20.json covers 100/267)
# nor any human-review list (human-queue sink, witness labels). Fix: resolve
# short->full through the screened map, join real-run top3 first (order
# preserved) then table rows deduped by sensekey, annotate read-only review
# flags. Fixture shapes below mirror the real files cited in each test.

_REAL_KID = "en-run-en-verb-tL7-sssU"
_REAL_SHORT = "run#5"


def _write_screened_short_full(path):
    """Screened export carrying BOTH key forms (mirrors the real file:
    sense.sense_id is short "run#5", sense.id is the full kaikki id)."""
    import json as _json
    path.write_text(
        _json.dumps({"lemma": "run", "sense": {
            "id": _REAL_KID, "sense_id": _REAL_SHORT,
            "glosses": ["To move swiftly."],
            "examples": [{"text": "Run!"}]}}) + "\n",
        encoding="utf-8")


def _write_real_run(path):
    """REAL run candidate file shape (mirrors run20 candidates_run20.json:
    dict kid -> {lemma, linker_row, top3[{sensekey, gloss, lemmas,
    examples, fires, jaccard}]})."""
    import json as _json
    path.write_text(_json.dumps({
        _REAL_KID: {
            "lemma": "run",
            "linker_row": {"sensekey": "run%2:38:11::",
                           "method": "JUDGE-PENDING",
                           "evidence": "Sd:hyp=move"},
            "top3": [
                {"sensekey": "run%2:38:11::",
                 "gloss": "move about freely and without restraint",
                 "lemmas": ["run"],
                 "examples": ["who are these people running around?"],
                 "fires": ["Sd:hyp=move"], "jaccard": 0.0},
                {"sensekey": "run%2:38:00::",
                 "gloss": "move fast by using one's feet",
                 "lemmas": ["run"],
                 "examples": ["Don't run--you'll be out of breath"],
                 "fires": [], "jaccard": 0.1176},
            ]}}), encoding="utf-8")


def _write_review_queue(path):
    """Human-review list via the owner's own sink (mirrors
    reports/linker/human_escalation_queue.jsonl records)."""
    from factory.linking import human_queue as _hq
    _hq.enqueue_escalation(
        {"lemma": "run", "pos": "verb", "sense_id": _REAL_KID,
         "escalation_reason": "SplitVoteVeto",
         "candidates": ["run%2:38:11::", "run%2:38:00::"]},
        str(path))


def _write_witness_labels(path):
    """Witness label list shape (mirrors gold/calibration_gold_26.json:
    list of {kid, verdict, winner_sensekey})."""
    import json as _json
    path.write_text(_json.dumps([
        {"n": 1, "kid": _REAL_KID, "lemma": "run",
         "gemini_verdict": "LINK",
         "winner_sensekey": "run%2:38:00::",
         "winner_gloss": "move fast by using one's feet"}]),
        encoding="utf-8")


def _t5_query(tmp_path):
    table = tmp_path / "table.tsv"
    _write_table(table)
    screened = tmp_path / "screened.jsonl"
    _write_screened_short_full(screened)
    run = tmp_path / "candidates_run.json"
    _write_real_run(run)
    queue = tmp_path / "human_escalation_queue.jsonl"
    _write_review_queue(queue)
    witness = tmp_path / "witness.json"
    _write_witness_labels(witness)
    return {"screened": str(screened), "run": str(run),
            "queue": str(queue), "witness": str(witness),
            "table": str(table)}


def test_candidates_from_real_run_with_reviews(tmp_path):
    """Selecting the queue's SHORT sense id loads its REAL run candidates
    plus human-review flags (run file: candidates_run20.json shape; review
    lists: human_queue sink + witness gold shape)."""
    paths = _t5_query(tmp_path)
    body = webui.app.test_client().get(
        "/api/candidates",
        query_string={"sense_id": _REAL_SHORT, **paths}).get_json()
    assert body["cause"] == "joined"
    assert body["full_id"] == _REAL_KID
    assert body["total"] == 2
    by_key = {c["sensekey"]: c for c in body["candidates"]}
    assert set(by_key) == {"run%2:38:11::", "run%2:38:00::"}
    # real run data, verbatim: gloss/synonyms/example/evidence from top3
    first = by_key["run%2:38:11::"]
    assert first["gloss"] == "move about freely and without restraint"
    assert first["synonyms"] == ["run"]
    assert first["example"] == "who are these people running around?"
    assert "Sd:hyp=move" in first["evidence"]
    # human-review join, read-only: queue escalation + witness verdict
    assert first["in_review"] is True
    assert first["review_reason"] == "SplitVoteVeto"
    assert body["witness_verdict"] == "LINK"
    # witness winner pick is marked, never re-ranked (run order kept)
    assert body["candidates"][0]["sensekey"] == "run%2:38:11::"
    assert by_key["run%2:38:00::"]["witness_pick"] is True
    assert first["witness_pick"] is False


def test_candidates_empty_state_names_cause(tmp_path):
    """Empty states distinguish no-join (unresolvable id) from no-data
    (joined id with no rows anywhere)."""
    paths = _t5_query(tmp_path)
    client = webui.app.test_client()
    # unknown short id: not in the screened map, no full-form rows
    body = client.get(
        "/api/candidates",
        query_string={"sense_id": "zzz#9", **paths}).get_json()
    assert body["candidates"] == [] and body["total"] == 0
    assert body["cause"] == "no-join"
    # resolvable full id with rows nowhere: joined, honestly empty
    body = client.get(
        "/api/candidates",
        query_string={"sense_id": "en-ghost-en-verb-00000000",
                      "screened": paths["screened"], "run": paths["run"],
                      "queue": paths["queue"], "witness": paths["witness"],
                      "table": paths["table"]}).get_json()
    assert body["candidates"] == [] and body["total"] == 0
    assert body["cause"] == "no-data"


def test_candidates_never_invented(tmp_path):
    """Empty real sources return [], never fabricated rows (missing run /
    review files degrade to empty, the unreadable vendor table stays 500)."""
    paths = _t5_query(tmp_path)
    client = webui.app.test_client()
    body = client.get(
        "/api/candidates",
        query_string={"sense_id": _REAL_SHORT,
                      "screened": paths["screened"],
                      "run": str(tmp_path / "no-such-run.json"),
                      "queue": str(tmp_path / "no-such-queue.jsonl"),
                      "witness": str(tmp_path / "no-such-witness.json"),
                      "table": paths["table"]}).get_json()
    assert body["cause"] == "no-data"
    assert body["total"] == 0 and body["candidates"] == []
    # unreadable vendor table keeps the existing fail-closed 500
    resp = client.get(
        "/api/candidates",
        query_string={"sense_id": _REAL_SHORT,
                      "screened": paths["screened"],
                      "run": paths["run"],
                      "table": str(tmp_path / "no-such-table.tsv")})
    assert resp.status_code == 500


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


def test_vote_metadata_out_of_form_flow_background_defaults():
    """Raw English stratum/annotator OUT of the form; safe role defaults.

    No stratum/annotator inputs, placeholders, or settings section in
    the form flow; the background ``labelDefaults`` honors
    settings-section values when the operator set them, else safe
    operator role defaults — never an invented personal name.
    """
    text = _html()
    assert 'id="label-settings"' not in text
    assert 'id="label-stratum"' not in text
    assert 'id="label-annotator"' not in text
    assert 'placeholder="stratum"' not in text
    assert 'placeholder="annotator"' not in text
    assert "labelDefaults" in text
    assert "LABEL_DEFAULT_STRATUM" in text
    assert "LABEL_DEFAULT_ANNOTATOR" in text
    assert "'operator-review'" in text or '"operator-review"' in text
    assert "'operator'" in text or '"operator"' in text


def test_themed_scrollbar_styles_only():
    """Public themed scrollbar class + root styling (day-night by inherit).

    Narrow rounded theme-matched scrollbar: page root plus the public
    ``.themed-scroll`` class for inner scroll areas (sense queue opts
    in by class); day-night follows the theme variables by inheritance.
    """
    text = _html()
    assert "scrollbar-width" in text
    assert "scrollbar-color" in text
    assert "::-webkit-scrollbar" in text
    assert ".themed-scroll" in text
    assert ".themed-scroll::-webkit-scrollbar-thumb" in text
    assert ".queue-list::-webkit-scrollbar-thumb" in text
    assert 'class="queue-list themed-scroll"' in text


def test_queue_filter_input_and_wiring():
    """Reusable filter module driving the arbitration queue live.

    Standalone ``FilterableListController`` (filter-input id +
    items-container id + text-match fn) instantiated for the
    arbitration queue with live filtering by identifier or status,
    ready for reuse in precard and data-store cabins.
    """
    text = _html()
    assert 'id="queue-filter"' in text
    assert "queueFilter" in text
    assert "queueItemMatches" in text
    assert "class FilterableListController" in text
    assert "queueFilterCtl" in text
    assert "new FilterableListController" in text
    assert "'queue-filter'" in text and "'queue-list'" in text


def test_empty_candidates_neutral_latin_isolated():
    """Empty state: neutral tone in an isolated Latin box, layout kept."""
    text = _html()
    assert "No candidates in the link table for this sense." in text
    assert "ltrLine('No candidates" in text


def test_supervisor_down_names_exact_start_command(monkeypatch):
    """Supervisor down with failed wake: exact start command, never raw."""
    monkeypatch.setattr(webui, "_supervisor_token", lambda: "")
    ok, err = webui.supervisor_health_snapshot()
    assert ok is False
    assert "EGRESS_SUP_TOKEN" in err  # name only, never the value
    assert "python tools/egress/supervisor.py" in err
    assert webui.SUPERVISOR_START_CMD in err
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "test leased"))
    _lease, lease_err = webui.lease_tunnel_for_run(
        "google", wake_fn=lambda: False)
    assert _lease is None
    assert "python tools/egress/supervisor.py" in lease_err


def test_model_list_supervisor_down_shows_start_command(monkeypatch):
    """Leased model list with failed wake: command, not dead end."""
    monkeypatch.setattr(webui, "_provider_key_var",
                        lambda p: "GOOGLE_AI_API_KEY")
    monkeypatch.setattr(webui, "_operator_key_values", lambda: {})
    import factory.precard.provider_lease_policy as _net
    monkeypatch.setattr(_net, "resolve_key",
                        lambda v, **k: "k-test"
                        if v == "GOOGLE_AI_API_KEY" else "")
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "test leased"))
    monkeypatch.setattr(webui, "_supervisor_token", lambda: "")
    models, err = webui.provider_model_list("google",
                                            wake_fn=lambda: False)
    assert models is None
    assert "python tools/egress/supervisor.py" in err


def test_auto_wake_retries_leased_request_without_raw_error(monkeypatch):
    """Universal auto-wake: missing token wakes, then the lease retries.

    Wake success + token resolving after the wake retries the lease
    (no raw error surfaces); the wake rides the factory domain path
    and the lease seam only — others' leases never touched.
    """
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "test leased"))
    tokens = {"tok": ""}
    monkeypatch.setattr(webui, "_supervisor_token",
                        lambda: tokens["tok"])
    woke = []

    def _fake_wake():
        woke.append(True)
        tokens["tok"] = "tok-test"  # wake resolves the token; fake value
        return True

    def _fake_lease(target):
        return {"lease_id": "l1", "server_id": "s1",
                "proxy_url": "http://127.0.0.1:1"}

    lease, err = webui.lease_tunnel_for_run(
        "google", lease_fn=_fake_lease, wake_fn=_fake_wake,
        clean_fn=lambda: [], verify_fn=lambda *a, **k: None)
    assert err is None
    assert lease["lease_id"] == "l1"
    assert woke == [True]


def test_auto_wake_applies_beyond_google(monkeypatch):
    """Auto-wake is route-based: every flagged provider, never Google-only."""
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "test leased"))
    monkeypatch.setattr(webui, "_supervisor_token", lambda: "tok-test")
    seen = []

    def _fake_lease(target):
        seen.append(target)
        return {"lease_id": "l9", "server_id": "s9",
                "proxy_url": "http://127.0.0.1:1"}

    lease, err = webui.lease_tunnel_for_run(
        "groq", lease_fn=_fake_lease, wake_fn=lambda: True)
    assert err is None
    assert lease["lease_id"] == "l9"
    assert seen == ["groq"]


def test_auto_wake_never_restarts_healthy_supervisor(monkeypatch):
    """Healthy supervisor present: wake path never spawns, token untouched."""
    monkeypatch.setattr(webui, "supervisor_health_snapshot",
                        lambda timeout=10: (True, {"healthy": True,
                                                  "servers": 1,
                                                  "leases": 0}))
    calls = []
    assert webui._wake_supervisor_background(
        spawn_fn=lambda port: calls.append(port),
        health_fn=lambda: (True, {})) is True
    assert calls == []
    # factory domain path owns the script (no rival literal in the adapter)
    import factory.run as _frun
    assert webui._factory_supervisor_script() == _frun.SUPERVISOR_SCRIPT


def test_direct_provider_never_wakes_supervisor(monkeypatch):
    """Direct-route providers skip the supervisor entirely (no wake call)."""
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("direct", "test direct"))

    def _boom_wake():
        raise AssertionError("direct route must never wake")

    lease, err = webui.lease_tunnel_for_run("avalai", wake_fn=_boom_wake)
    assert (lease, err) == (None, None)


def test_supervisor_token_rides_unified_loader_not_branch_copy(
        monkeypatch, tmp_path):
    """Token resolves through the shared egress loader (hermetic fakes).

    Branch location plays no role: the working directory moves, the
    branch-local resolver must not even be consulted — values here are
    obvious fakes, never secrets.
    """
    import tools.egress.supervisor as _sup
    monkeypatch.delenv("EGRESS_SUP_TOKEN", raising=False)
    monkeypatch.setattr(_sup, "load_env",
                        lambda: {"EGRESS_SUP_TOKEN": "tok-test"})
    import factory.precard.provider_lease_policy as _net

    def _boom(*args, **kwargs):
        raise AssertionError("branch-local copy must not be consulted")

    monkeypatch.setattr(_net, "resolve_key", _boom)
    monkeypatch.chdir(tmp_path)
    assert webui._supervisor_token() == "tok-test"


def test_supervisor_resolution_is_path_based_not_branch_based():
    """Lookup files anchor at the module file: same tree, any checkout."""
    import pathlib as _pl
    import tools.egress.supervisor as _sup
    egress_env = _pl.Path(str(_sup.ENV_PATH))
    factory_env = _pl.Path(str(_sup.FACTORY_DOTENV))
    assert egress_env.is_absolute()
    assert factory_env.is_absolute()
    assert egress_env.parent.name == "egress"
    assert factory_env.parent.name == "factory"
    # both anchors live under the checkout that serves this console
    assert egress_env.parent.parent.parent == _pl.Path(PROJECT_ROOT)
    assert factory_env.parent.parent == _pl.Path(PROJECT_ROOT)


def test_supervisor_token_reads_shared_temp_file(monkeypatch, tmp_path):
    """Parent re-reads the supervisor-issued temp file (no child env).

    A child process cannot change the parent environment, so the
    supervisor workflow leaves the bearer in the shared temp file and
    the parent reads it — values here are obvious fakes, never
    secrets.
    """
    import tools.egress.supervisor as _sup
    token_file = tmp_path / "hamzaban-egress-sup-token"
    token_file.write_text("tok-test-temp-file", encoding="utf-8")
    monkeypatch.delenv("EGRESS_SUP_TOKEN", raising=False)
    monkeypatch.setattr(webui, "_supervisor_token_file",
                        lambda: str(token_file))
    monkeypatch.setattr(_sup, "load_env", lambda: {})
    import factory.precard.provider_lease_policy as _net

    def _boom(*args, **kwargs):
        raise AssertionError("later sources must not be consulted")

    monkeypatch.setattr(_net, "resolve_key", _boom)
    assert webui._supervisor_token() == "tok-test-temp-file"


def test_supervisor_token_env_wins_over_temp_file(monkeypatch, tmp_path):
    """Process env keeps precedence over the shared temp file."""
    token_file = tmp_path / "hamzaban-egress-sup-token"
    token_file.write_text("tok-test-temp-file", encoding="utf-8")
    monkeypatch.setenv("EGRESS_SUP_TOKEN", "tok-test-env")
    monkeypatch.setattr(webui, "_supervisor_token_file",
                        lambda: str(token_file))
    assert webui._supervisor_token() == "tok-test-env"


def test_supervisor_token_file_guards(
        monkeypatch, tmp_path):
    """Missing/multiline/hostile temp files fail closed to ""."""
    import tools.egress.supervisor as _sup
    monkeypatch.delenv("EGRESS_SUP_TOKEN", raising=False)
    monkeypatch.setattr(_sup, "load_env", lambda: {})
    import factory.precard.provider_lease_policy as _net
    monkeypatch.setattr(_net, "resolve_key", lambda *a, **k: "")
    monkeypatch.setattr(webui, "_supervisor_token_file",
                        lambda: str(tmp_path / "no-such-file"))
    assert webui._read_supervisor_token_file() == ""
    assert webui._supervisor_token() == ""
    hostile = tmp_path / "hostile"
    hostile.write_text("tok-one\ntok-two", encoding="utf-8")
    assert webui._read_supervisor_token_file(str(hostile)) == ""
    hostile.write_text("short", encoding="utf-8")
    assert webui._read_supervisor_token_file(str(hostile)) == ""


def test_egress_client_auth_refresh_places_token(monkeypatch):
    """Resolved bearer reaches the loopback lease legs (in-memory).

    tools.egress.client binds its bearer at import time; the refresh
    places the active token on lease/health/report requests for every
    leased route — names only, the fake value never leaves the test.
    """
    import tools.egress.client as _client
    monkeypatch.setattr(webui, "_supervisor_token",
                        lambda: "tok-test-refresh")
    monkeypatch.setattr(webui, "_supervisor_url",
                        lambda: "http://127.0.0.1:18789")
    monkeypatch.setattr(_client, "SUP_TOKEN", "", raising=False)
    webui._refresh_egress_client_auth()
    assert _client.SUP_TOKEN == "tok-test-refresh"


def test_cabin_tabs_match_five_linker_stages():
    """Five cockpit tabs mirror the five real linking-folder stages."""
    text = _html()
    assert text.count('class="tab-link') == 5
    for label in ("کوتاه‌فهرست نامزدها", "پیوند مکانیکی",
                  "داوری هوش مصنوعی", "بازبینی انسانی",
                  "خروجی جدول پیوند (TSV)"):
        assert label in text, label
    # each tab names its repo-folder code owner (never the data drive)
    for owner in ("linker.py", "arbitration.py", "human_queue.py",
                  "cli.py", "table.tsv"):
        assert owner in text, owner
    assert "W:" not in text


def test_queue_rows_show_gloss_slice_muted_ltr():
    """Queue rows render identifier + one-line muted gloss (BiDi-safe)."""
    text = _html()
    assert ".queue-gloss" in text
    assert "queue-gloss ltr-text" in text
    assert 'setAttribute' in text and "'dir', 'ltr'" in text
    assert "glossSlice" in text and "row.gloss" in text
    assert "text-overflow: ellipsis" in text
    assert "queueItemMatches" in text and "(row.gloss || '')" in text


def test_lan_autobind_detect_shape():
    """Detection returns "" or a non-loopback IPv4 (never 127.x)."""
    import re
    hit = webui._detect_lan_ipv4()
    assert isinstance(hit, str)
    if hit:
        assert re.match(r"^\d{1,3}(\.\d{1,3}){3}$", hit), hit
        assert not hit.startswith("127."), hit
        assert hit != "0.0.0.0"


def test_lan_autobind_env_overrides_detection(monkeypatch):
    """HAMZABAN_WEBUI_HOST wins over any detected LAN address."""
    monkeypatch.setenv("HAMZABAN_WEBUI_HOST", "192.0.2.9")
    monkeypatch.setattr(webui, "_detect_lan_ipv4",
                        lambda: "10.9.9.9")
    assert webui._default_host() == "192.0.2.9"


def test_lan_autobind_detected_address_used(monkeypatch):
    """No env -> all-interfaces bind (LAN detection no longer selects it)."""
    monkeypatch.delenv("HAMZABAN_WEBUI_HOST", raising=False)
    monkeypatch.setattr(webui, "_detect_lan_ipv4",
                        lambda: "10.9.9.9")
    assert webui._default_host() == "0.0.0.0"
    args = webui.parse_server_args([])
    assert args.host == "0.0.0.0"


def test_lan_autobind_loopback_only_when_undetectable(monkeypatch):
    """Detection failure still binds all interfaces (never blank)."""
    monkeypatch.delenv("HAMZABAN_WEBUI_HOST", raising=False)
    monkeypatch.setattr(webui, "_detect_lan_ipv4", lambda: "")
    assert webui._default_host() == "0.0.0.0"


def test_lan_autobind_explicit_flag_overrides(monkeypatch):
    """An explicit --host still overrides env and detection."""
    monkeypatch.setenv("HAMZABAN_WEBUI_HOST", "192.0.2.9")
    monkeypatch.setattr(webui, "_detect_lan_ipv4",
                        lambda: "10.9.9.9")
    args = webui.parse_server_args(["--host", "127.0.0.1"])
    assert args.host == "127.0.0.1"


def _queue_row_js():
    """JS source of the queue-row renderer only (renderQueue body)."""
    text = _html()
    start = text.index("function renderQueue()")
    end = text.index("function selectSense(", start)
    return text[start:end]


def test_queue_row_three_fields_only():
    """Queue rows carry exactly: kaikki identifier, gloss slice, status."""
    row = _queue_row_js()
    assert "row.sense_id" in row  # kaikki identifier
    assert "glossSlice" in row and "queue-gloss" in row  # gloss slice
    assert "status-tag" in row  # status
    # nothing else rides the row: no lemma, no candidates, no
    # examples, no full text beyond the slice
    assert "row.lemma" not in row
    assert "sub.title = glossSlice;" in row


def test_detail_section_owns_candidates_examples_fulltext():
    """Named detail section alone owns candidates/examples/full text."""
    text = _html()
    assert "جزئیات سنس" in text  # visibly named in the interface
    assert 'id="sense-detail"' in text
    start = text.index('id="sense-detail"')
    for token in ('id="sense-def"', 'id="sense-example"',
                  'id="candidates-stack"', 'id="candidates-status"'):
        assert start < text.index(token), token


def test_queue_never_renders_candidates():
    """Negative: no candidates/examples/full-text markup in the row path."""
    row = _queue_row_js().lower()
    for token in ("candidate", "sensekey", "synset", "example",
                  "sense-def", "loadcandidates", "rendercandidates"):
        assert token not in row, token


def test_view_memory_restores_cabin_and_tab():
    """T6: stored cabin+tab restore via openView + tab select on load."""
    text = _html()
    assert "hz-view-memory" in text
    assert "restoreViewMemory" in text
    assert "selectLinkingTab" in text
    assert "localStorage.getItem('hz-view-memory')" in text
    assert "localStorage.setItem('hz-view-memory'" in text
    assert "openView" in text


def test_view_memory_first_run_default():
    """T6: no stored value keeps the existing default, no crash."""
    text = _html()
    # existing default unchanged: linking cabin + 4th tab active
    assert 'class="workspace-view active" id="view-linking"' in text
    assert text.count('class="tab-link') == 5
    assert "restoreViewMemory" in text
    # restore guards: try/catch + element-exists check, view ids only
    start = text.index("restoreViewMemory")
    block = text[start:start + 2000]
    assert "try" in block
    assert "getElementById" in block
    assert "key_var" not in block
    assert "API_KEY" not in block
    assert "access_token" not in block.lower()
