"""Steps 2-6 tests: screened export, probe harness, browser, labels.

- Export: schema of kept lines + drops sidecar; sense_ids byte-identical
  to the screening output (fake screen_fn — never the real chain here).
- Probes: hermetic (injected transports/keys — no network, no real keys);
  skipped-with-reason when keys/models are missing; secrets never leak.
- Browser: read path lists identifier + gloss + example; read-only (no
  POST/PUT/DELETE route under /api/screened); never imports screening
  or ranking internals.
- Labels: endpoint stores exactly the 7 fields, enum-validated,
  append-only; receipt carries replay reference + store path.
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.linking import export_screened as export_mod
from factory.linking import probe_providers as probe_mod
from factory.linking.webui import server as webui


# ─── Step 2: screened export schema ───

def _fake_screen(senses, lemma=""):
    kept, drops = [], []
    for idx, sense in enumerate(senses):
        sid = sense.get("sense_id") or "%s#%d" % (lemma, idx)
        if ";;DROP;;" in (sense.get("glosses") or [""])[0]:
            drops.append({"sense_id": sid, "reason": "obsolete"})
        else:
            row = dict(sense)
            row.setdefault("sense_id", sid)
            kept.append(row)
    return kept, drops, {}


def _senses():
    return [
        {"sense_id": "run#0", "glosses": ["move fast"],
         "examples": [{"text": "run fast!"}]},
        {"glosses": [";;DROP;; old word"], "examples": []},
        {"glosses": ["manage"], "examples": [{"text": "run a shop"}]},
    ]


def test_export_schema_and_byte_identical_ids(tmp_path):
    index = {"run": [{"offset": 0, "length": 1}]}
    import factory.precard.pipeline as pipe
    real_read = pipe.read_kaikki_entry
    pipe.read_kaikki_entry = lambda *a: {"senses": _senses()}
    try:
        manifest = export_mod.export_words(
            ["run"], str(tmp_path), index=index,
            raw_path="dummy", screen_fn=_fake_screen)
    finally:
        pipe.read_kaikki_entry = real_read
    assert manifest["kept_total"] == 2
    assert manifest["dropped_total"] == 1
    kept = [json.loads(l) for l in
            open(tmp_path / "screened.jsonl", encoding="utf-8")]
    assert [r["sense"]["sense_id"] for r in kept] == ["run#0", "run#2"]
    assert all(r["lemma"] == "run" for r in kept)
    assert kept[0]["sense"]["glosses"] == ["move fast"]
    drops = [json.loads(l) for l in
             open(tmp_path / "screened.drops.jsonl", encoding="utf-8")]
    assert drops == [{"lemma": "run", "sense_id": "run#1",
                      "reason": "obsolete"}]
    saved_manifest = json.load(
        open(tmp_path / "screened.manifest.json", encoding="utf-8"))
    assert saved_manifest["kept_total"] == 2
    assert "export_screened" in saved_manifest["replay"]


# ─── Step 3: probe harness (hermetic, no network) ───

def _resolve_with(mapping):
    def _resolve(var):
        return mapping.get(var, "")
    return _resolve


def test_probe_skipped_when_key_missing():
    results = probe_mod.probe_all(
        prompt_text="PROMPT",
        resolve_fn=_resolve_with({}),
        chain_fn=lambda p, leg: ["m"])
    assert [r["status"] for r in results] == ["skipped"] * 3
    assert all("no key resolves" in r["reason"] for r in results)
    blob = json.dumps(results)
    assert "SECRET" not in blob


def test_probe_skipped_when_no_default_model(monkeypatch):
    # No engine chain AND no probe free default => skipped-with-reason
    # (operator --model is the only way through).
    monkeypatch.setattr(probe_mod, "PROBE_FREE_MODELS", {})
    mapping = {"GROQ_API_KEY": "x" * 16}
    results = probe_mod.probe_all(
        providers=["groq"], prompt_text="PROMPT",
        resolve_fn=_resolve_with(mapping),
        chain_fn=lambda p, leg: [])
    (rec,) = results
    assert rec["status"] == "skipped"
    assert "--model groq=" in rec["reason"]


def test_probe_free_defaults_per_provider():
    assert probe_mod.default_model(
        "google", chain_fn=lambda p, leg: ["gemini-3.5-flash-lite"]) == \
        "gemini-3.5-flash-lite"
    assert probe_mod.default_model(
        "groq", chain_fn=lambda p, leg: []) == \
        probe_mod.PROBE_FREE_MODELS["groq"]
    assert probe_mod.default_model(
        "openrouter", chain_fn=lambda p, leg: []) == \
        probe_mod.PROBE_FREE_MODELS["openrouter"]
    assert probe_mod.default_model(
        "kilo", chain_fn=lambda p, leg: []) == ""
    assert probe_mod.model_source(
        "google", {}, chain_fn=lambda p, leg: ["m"]) == "engine-default"
    assert probe_mod.model_source(
        "groq", {}, chain_fn=lambda p, leg: []) == "probe-free-default"
    assert probe_mod.model_source(
        "groq", {"groq": "op-m"},
        chain_fn=lambda p, leg: []) == "operator-provided"
    assert probe_mod.model_source(
        "kilo", {}, chain_fn=lambda p, leg: []) == ""


def test_probe_all_marks_model_source_hermetic():
    mapping = {"GROQ_API_KEY": "k" * 16}

    def _ok(api_key, model, text):
        assert api_key == "k" * 16
        assert model == probe_mod.PROBE_FREE_MODELS["groq"]
        return ("PICK run#0", None)

    results = probe_mod.probe_all(
        providers=["groq"], prompt_text="PROMPT",
        resolve_fn=_resolve_with(mapping),
        transport_fn_for=lambda p: _ok,
        chain_fn=lambda p, leg: [],
        clock=lambda: 1.0)
    (rec,) = results
    assert rec["status"] == "ok"
    assert rec["model_source"] == "probe-free-default"
    assert "k" * 16 not in json.dumps(results)


def test_load_factory_env_names_only_no_values(tmp_path, monkeypatch):
    # Single allowlisted loader: only canonical + legacy names load;
    # unknown vars (QUOTED) are ignored. Names only out, never values.
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# comment\nEMPTY=\nGROQ_API_KEY=file-secret-value\n"
        'QUOTED="quoted-secret"\n', encoding="utf-8")
    old_groq = os.environ.get("GROQ_API_KEY")
    old_quoted = os.environ.get("QUOTED")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    try:
        info = probe_mod.load_factory_env(str(dotenv))
        assert info["loaded"] is True
        assert info["vars"] == ["GROQ_API_KEY"]
        assert "QUOTED" not in info["vars"]
        assert "file-secret-value" not in json.dumps(info)
        assert "quoted-secret" not in json.dumps(info)
        assert os.environ["GROQ_API_KEY"] == "file-secret-value"
        assert os.environ.get("QUOTED") is None
        # ambient wins without override; override replaces
        info2 = probe_mod.load_factory_env(str(dotenv))
        assert info2["vars"] == []
        info3 = probe_mod.load_factory_env(str(dotenv), override=True)
        assert info3["vars"] == ["GROQ_API_KEY"]
        assert probe_mod.load_factory_env(
            str(tmp_path / "missing.env")) == {
                "path": os.path.abspath(str(tmp_path / "missing.env")),
                "loaded": False, "vars": []}
    finally:
        if old_groq is None:
            os.environ.pop("GROQ_API_KEY", None)
        else:
            os.environ["GROQ_API_KEY"] = old_groq
        if old_quoted is None:
            os.environ.pop("QUOTED", None)
        else:
            os.environ["QUOTED"] = old_quoted
    # default path helper points at factory/.env
    assert probe_mod.default_factory_env_path().endswith(
        os.path.join("factory", ".env"))


def test_probe_ok_and_http_error_hermetic():
    mapping = {"GROQ_API_KEY": "k" * 16, "GOOGLE_AI_API_KEY": "g" * 16}

    def _transports(provider):
        import urllib.error

        if provider == "groq":
            def _ok(api_key, model, text):
                assert api_key == "k" * 16
                return ("PICK run#0", None)
            return _ok

        def _fail(api_key, model, text):
            raise urllib.error.HTTPError(
                "url", 429, "too many", {}, None)
        return _fail

    # Google rides the leased tunnel: inject the lease seam (fake clean
    # tunnel) + the report seam — no network, no real supervisor.
    reports = []

    def _fake_lease(provider):
        return {"lease_id": "ab12cd34ef56", "mode": "tunnel",
                "proxy_url": "http://127.0.0.1:19099",
                "server_id": "srv-fake", "provider": provider,
                "target": "google"}

    results = probe_mod.probe_all(
        providers=["groq", "google"], prompt_text="PROMPT",
        operator_models={"groq": "op-model", "google": "gemini-x"},
        resolve_fn=_resolve_with(mapping),
        transport_fn_for=_transports,
        chain_fn=lambda p, leg: [],
        clock=lambda: 1.0,
        lease_fn_for=lambda p: _fake_lease
        if p == "google" else None,
        report_fn=lambda *a: reports.append(a) or {},
        clean_fn_for=lambda p: (lambda: []),
        remember_fn=lambda *a: None)
    by_name = {r["provider"]: r for r in results}
    assert by_name["groq"]["status"] == "ok"
    assert by_name["groq"]["latency_s"] == 0.0
    assert by_name["groq"]["route"] == "direct"
    assert by_name["google"]["status"] == "http-error"
    assert by_name["google"]["http_status"] == 429
    assert by_name["google"]["error_kind"] == "http-429"
    assert by_name["google"]["route"] == "leased"
    assert by_name["google"]["lease"] == "ab12cd34"
    assert by_name["google"]["egress"] == "srv-fake"
    # 429 on OUR lease cools OUR server (per-(server,provider) cooldown).
    assert reports and reports[0][1] == "http429"
    blob = json.dumps(results)
    assert "k" * 16 not in blob and "g" * 16 not in blob
    assert "probe provider=google status=http-error route=leased" in \
        probe_mod.probe_line(by_name["google"])


def test_probe_prompt_uses_standard_wording():
    from factory.linking.arbitration_prompt import (
        ArbitrationPromptTemplate,
        SenseLinkingArbitrationPromptBuilder,
    )
    prompt = probe_mod.build_probe_prompt()
    text = probe_mod.PROBE_ITEM["text"]
    kaikki = {"lemma": text, "gloss": text, "synonyms": [],
              "examples": []}
    candidates = [{"sensekey": str(c.get("sense_id") or ""),
                   "gloss": str(c.get("gloss") or ""),
                   "lemmas": [text], "examples": []}
                  for c in probe_mod.PROBE_CANDIDATES]
    want, _index_map = SenseLinkingArbitrationPromptBuilder().build(
        kaikki, candidates, ArbitrationPromptTemplate.BASE)
    assert prompt == want
    assert "move fast on foot" in prompt
    assert "manage or be in charge of" in prompt


def test_probe_line_never_carries_values():
    line = probe_mod.probe_line({
        "provider": "groq", "status": "skipped",
        "reason": "no key resolves (GROQ_API_KEY)", "model": None,
        "latency_s": None, "http_status": None, "error_kind": None})
    assert "GROQ_API_KEY" in line
    assert line.startswith("probe provider=groq status=skipped")


# ─── Step 3b: leased-tunnel routing (precard TARGETS mirror) ───

def _leased_providers():
    return {"google", "openrouter"}


def test_probe_route_defaults_leased_for_tunnel_providers():
    assert probe_mod.route_for("google") == "leased"
    assert probe_mod.route_for("openrouter") == "leased"
    assert probe_mod.route_for("avalai") == "direct"
    assert probe_mod.route_for("groq") == "direct"
    assert probe_mod.route_for("ghost-unknown") == "direct"


def test_probe_google_reason_states_geo_block_one_line():
    reason = probe_mod.route_reason("google", "leased")
    assert "403" in reason
    assert "\n" not in reason
    assert reason == probe_mod.GOOGLE_TUNNEL_REASON


def test_probe_leased_success_reports_ok_and_restores_env(monkeypatch):
    import os as _os

    reports = []
    seen_env = {}

    def _ok(api_key, model, text):
        seen_env["https_proxy"] = _os.environ.get("HTTPS_PROXY")
        seen_env["http_proxy"] = _os.environ.get("HTTP_PROXY")
        return ("PICK run#0", None)

    _os.environ.pop("HTTPS_PROXY", None)
    _os.environ.pop("HTTP_PROXY", None)
    rec = probe_mod.probe_one(
        "google", "PROMPT", model="gemini-x", key_value="g" * 16,
        transport_fn=_ok, clock=lambda: 1.0, route="auto",
        lease_fn=lambda target: {"lease_id": "aa11bb22cc33",
                                 "mode": "tunnel",
                                 "proxy_url": "http://127.0.0.1:19999",
                                 "server_id": "srv-1",
                                 "provider": "google", "target": target},
        report_fn=lambda *a: reports.append(a) or {},
        target_fn=lambda p: "google",
        clean_fn=lambda: [],
        remember_fn=lambda *a: None)
    assert rec["status"] == "ok"
    assert rec["route"] == "leased"
    assert rec["lease"] == "aa11bb22"
    assert rec["egress"] == "srv-1"
    # Guest-vs-leased: the transport saw the leased proxy ...
    assert seen_env["https_proxy"] == "http://127.0.0.1:19999"
    # ... but the parent env is untouched afterwards.
    assert _os.environ.get("HTTPS_PROXY") is None
    assert _os.environ.get("HTTP_PROXY") is None
    assert reports and reports[0][1] == "ok"


def test_probe_leased_refusal_is_loud_and_calls_no_transport():
    calls = []

    def _never(api_key, model, text):
        calls.append(1)
        return ("X", None)

    rec = probe_mod.probe_one(
        "google", "PROMPT", model="gemini-x", key_value="g" * 16,
        transport_fn=_never, clock=lambda: 1.0, route="auto",
        lease_fn=lambda target: {"error": "park",
                                 "message": "no server available"},
        target_fn=lambda p: "google",
        clean_fn=lambda: [],
        remember_fn=lambda *a: None)
    assert rec["status"] == "lease-error"
    assert rec["error_kind"] == "lease-error"
    assert rec["route"] == "leased"
    assert calls == []


def test_probe_explicit_direct_skips_lease_for_google():
    calls = []

    def _ok(api_key, model, text):
        return ("PICK run#0", None)

    rec = probe_mod.probe_one(
        "google", "PROMPT", model="gemini-x", key_value="g" * 16,
        transport_fn=_ok, clock=lambda: 1.0, route="direct",
        lease_fn=lambda target: calls.append(target) or {},
        target_fn=lambda p: "google")
    assert rec["status"] == "ok"
    assert rec["route"] == "direct"
    assert rec["lease"] is None
    assert calls == []


def test_probe_auth_error_retires_own_lease_only():
    import urllib.error

    reports = []

    def _auth(api_key, model, text):
        raise urllib.error.HTTPError("url", 403, "forbidden", {}, None)

    rec = probe_mod.probe_one(
        "google", "PROMPT", model="gemini-x", key_value="g" * 16,
        transport_fn=_auth, clock=lambda: 1.0, route="leased",
        lease_fn=lambda target: {"lease_id": "zz11yy22xx33",
                                 "mode": "tunnel", "proxy_url": "",
                                 "server_id": "srv-9",
                                 "provider": "google", "target": target},
        report_fn=lambda *a: reports.append(a) or {},
        target_fn=lambda p: "google",
        clean_fn=lambda: [],
        remember_fn=lambda *a: None)
    assert rec["status"] == "http-error"
    assert rec["http_status"] == 403
    assert rec["lease"] == "zz11yy22"
    # Only OUR lease id is ever reported — others' leases untouched.
    assert len(reports) == 1 and reports[0][0] == "zz11yy22xx33"
    assert reports[0][1] == "auth_err"


# ─── Step 4: browser read path ───

def _write_screened(path):
    path.write_text(
        '{"lemma": "run", "sense": {"sense_id": "run#0", '
        '"glosses": ["move fast"], "examples": [{"text": "run!"}]}}\n'
        'broken line\n'
        '{"lemma": "run", "sense": {"glosses": ["no id here"]}}\n',
        encoding="utf-8")


def test_screened_reader_lists_id_gloss_example(tmp_path):
    target = tmp_path / "screened.jsonl"
    _write_screened(target)
    rows = webui.screened_rows(str(target))
    assert rows == [{"lemma": "run", "sense_id": "run#0",
                     "gloss": "move fast", "example": "run!"}]
    assert webui.screened_rows(str(tmp_path / "missing.jsonl")) == []


def test_screened_never_imports_core_internals():
    import ast

    import factory.linking.webui.server as srv
    import inspect

    tree = ast.parse(inspect.getsource(srv))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not {m for m in imported
                if m in ("factory.precard.prune", "factory.linking.linker")}


def test_api_screened_read_only_and_joined(tmp_path):
    target = tmp_path / "screened.jsonl"
    _write_screened(target)
    client = webui.app.test_client()
    body = client.get("/api/screened",
                      query_string={"path": str(target)}).get_json()
    assert body["total"] == 1
    (row,) = body["rows"]
    assert row["sense_id"] == "run#0" and row["gloss"] == "move fast"
    assert row["example"] == "run!"
    assert body["truncated"] is False
    assert client.get("/api/screened",
                      query_string={"path": str(target),
                                    "q": "zzz"}).get_json()["total"] == 0
    # read-only: no write route exists under /api/screened
    rules = [r.rule for r in webui.app.url_map.iter_rules()
             if r.rule.startswith("/api/screened")]
    assert rules == ["/api/screened"]
    assert client.post("/api/screened").status_code == 405


# ─── Step 5/6: label endpoint + receipt ───

def _label(sense="run#0", verdict="link", target="run%2:38:00::",
           stratum="custom", annotator="op-1"):
    return {"sense_id": sense, "lemma": "run", "target_synset": target,
            "verdict": verdict, "stratum": stratum,
            "annotator": annotator}


def test_label_endpoint_stores_exact_fields_and_receipt(tmp_path):
    store = str(tmp_path / "labels.jsonl")
    client = webui.app.test_client()
    resp = client.post("/api/labels",
                       json=dict(_label(), store=store))
    assert resp.status_code == 201
    body = resp.get_json()
    assert set(body["label"]) == {"sense_id", "lemma", "target_synset",
                                  "verdict", "stratum", "annotator",
                                  "created_at"}
    assert body["store"] == store
    assert "run#0" in body["replay"] and "link" in body["replay"]
    assert body["watermark"]  # custom stratum watermarked
    lines = open(store, encoding="utf-8").read().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["sense_id"] == "run#0"
    # gold stratum: no watermark
    resp = client.post("/api/labels",
                       json=dict(_label(stratum="gold"), store=store))
    assert resp.get_json()["watermark"] is None
    assert len(open(store, encoding="utf-8").read().splitlines()) == 2


def test_label_endpoint_rejects_bad_verdicts(tmp_path):
    store = str(tmp_path / "labels.jsonl")
    client = webui.app.test_client()
    assert client.post("/api/labels",
                       json=dict(_label(verdict="maybe"),
                                 store=store)).status_code == 400
    assert client.post("/api/labels",
                       json=dict(_label(verdict="link", target=None),
                                 store=store)).status_code == 400
    assert client.post("/api/labels",
                       json=dict(_label(verdict="none",
                                        target="run%2:38:00::"),
                                 store=store)).status_code == 400
    assert client.post("/api/labels",
                       json=dict(_label(sense=""),
                                 store=store)).status_code == 400
    assert not os.path.exists(store)


def test_label_nonce_is_append_only_null_target(tmp_path):
    store = str(tmp_path / "labels.jsonl")
    client = webui.app.test_client()
    resp = client.post("/api/labels",
                       json=dict(_label(verdict="none", target=None),
                                 store=store))
    assert resp.status_code == 201
    assert resp.get_json()["label"]["target_synset"] is None
    got = client.get("/api/labels",
                     query_string={"store": store}).get_json()
    assert [r["verdict"] for r in got["labels"]] == ["none"]
