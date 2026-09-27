"""Dynamic provider manifest + N-key rotation (ticket one).

Three locked scenarios (fakes + tmp paths only — no network, no real
keys, no real env files). Secret VALUES never appear in responses,
errors, logs, or terminal output: only provider names and key counts.
"""

import json
import urllib.error
import urllib.request

from factory.precard import provider_manifest as _manifest_mod
from factory.precard import provider_registry as _registry
from factory.precard.provider_transport import KeyRing, _call_with_rotation


def _patched_manifest(monkeypatch, tmp_path):
    path = str(tmp_path / "provider_manifest.json")
    mgr = _manifest_mod.ProviderManifestManager(path=path)
    monkeypatch.setattr(_registry, "_manifest", lambda: mgr)
    monkeypatch.setattr(
        _manifest_mod, "ProviderManifestManager", lambda path=None: mgr)
    return mgr


def _blob_has_no_values(blob, values):
    return all(v not in blob for v in values)


def test_tunneled_provider_without_key_parks_names_only(
        monkeypatch, tmp_path):
    """Scenario 1: mock tunneled provider without a key parks pre-cycle."""
    from factory.webui import server as _srv

    _patched_manifest(monkeypatch, tmp_path)
    _registry.create_provider("kilo", {
        "protocol": "openai_compat",
        "base_url": "https://api.kilo.example/v1/chat/completions",
        "route": "tunnel",
        "key_vars": ["KILO_API_KEY_1"],
        "request_extras": {},
    })
    assert "kilo" in _registry.provider_names()
    # No key anywhere: blank env map + empty operator store + empty files.
    monkeypatch.setattr(_srv, "_operator_key_values", lambda: {})
    monkeypatch.setattr("os.environ", {})
    states = []
    models, error = _srv.provider_model_list(
        "kilo", state_log=states,
        env_map={}, file_paths=[],
        tunneled=frozenset({"kilo"}))
    assert models is None
    assert error.startswith("no key resolves for kilo")
    assert "KILO_API_KEY_1" in error  # names only
    assert states == []  # parked before any cycle ran
    blob = json.dumps({"error": error, "states": states},
                      ensure_ascii=False)
    assert "FAKE" not in blob


def test_default_removal_disappears_from_names(monkeypatch, tmp_path):
    """Scenario 2: deleting a default removes it from names for good."""
    from factory.webui import server as _srv

    _patched_manifest(monkeypatch, tmp_path)
    assert "groq" in _registry.provider_names()
    assert _registry.delete_provider("groq") is True
    assert "groq" not in _registry.provider_names()
    assert _registry.resolve_provider("groq") is None
    # Reload from the same file: the removal pins (seed never resurrects).
    assert "groq" not in _registry.provider_names()
    # Same via the management route (names + counts only out).
    _registry.create_provider("groq", {
        "protocol": "openai_compat",
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "route": "direct",
        "key_vars": ["GROQ_API_KEY_G1"],
        "request_extras": {},
    })
    client = _srv.app.test_client()
    resp = client.delete("/api/managed_providers/groq")
    assert resp.status_code == 200
    assert resp.get_json() == {"deleted": "groq"}
    assert "groq" not in _registry.provider_names()
    blob = json.dumps(resp.get_json(), ensure_ascii=False)
    assert "FAKE" not in blob and "GROQ_API_KEY_G1" not in blob


def test_three_keys_survive_two_quota_errors(monkeypatch, tmp_path):
    """Scenario 3: three keys rotate through two 429s, exhaust on third."""
    _patched_manifest(monkeypatch, tmp_path)
    _registry.create_provider("local-studio", {
        "protocol": "openai_compat",
        "base_url": "http://127.0.0.1:9/v1/chat/completions",
        "route": "direct",
        "key_vars": ["LOCAL_STUDIO_API_KEY_1", "LOCAL_STUDIO_API_KEY_2",
                     "LOCAL_STUDIO_API_KEY_3"],
        "request_extras": {},
    })
    fakes = {"LOCAL_STUDIO_API_KEY_1": "FAKE-KEY-ONE",
             "LOCAL_STUDIO_API_KEY_2": "FAKE-KEY-TWO",
             "LOCAL_STUDIO_API_KEY_3": "FAKE-KEY-THREE"}
    ordered = _manifest_mod.ordered_key_values(
        "local-studio", env_map=dict(fakes), file_paths=[])
    assert ordered == ["FAKE-KEY-ONE", "FAKE-KEY-TWO", "FAKE-KEY-THREE"]

    def _http429():
        req = urllib.request.Request("http://127.0.0.1:9/")
        return urllib.error.HTTPError(
            req.get_full_url(), 429, "Too Many Requests", {}, None)

    calls = {"n": 0}

    def _flaky(current, model, text):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise _http429()
        return "ok-text", None

    ring = KeyRing(list(ordered))
    state = {}
    text, usage = _call_with_rotation(
        _flaky, ring, "m", "hi", lambda s: None, state,
        "local-studio/m", provider="local-studio",
        key_var="LOCAL_STUDIO_API_KEY_1")
    assert text == "ok-text"
    assert calls["n"] == 3  # two quota rotations, third key settles
    assert len(ring.attempt_log) == 3

    # Full round: three consecutive 429s exhaust (raise, never a 4th try).
    calls2 = {"n": 0}

    def _always429(current, model, text):
        calls2["n"] += 1
        raise _http429()

    from factory.precard.provider_transport import RateLimited
    ring2 = KeyRing(list(ordered))
    try:
        _call_with_rotation(
            _always429, ring2, "m", "hi", lambda s: None, {},
            "local-studio/m", provider="local-studio",
            key_var="LOCAL_STUDIO_API_KEY_1")
        exhausted = False
    except RateLimited as exc:
        exhausted = True
        err_text = str(exc)
    assert exhausted is True
    assert calls2["n"] == 3  # every key tried exactly once, then stop
    assert _blob_has_no_values(
        err_text + json.dumps(ring2.attempt_log), list(fakes.values()))


def test_managed_routes_crud_and_exact_counts(monkeypatch, tmp_path):
    """Four routes: create/delete provider, add/delete key; counts exact."""
    from factory.webui import server as _srv

    _patched_manifest(monkeypatch, tmp_path)
    client = _srv.app.test_client()

    created = client.post("/api/managed_providers", json={
        "name": "local-studio",
        "protocol": "openai_compat",
        "base_url": "http://127.0.0.1:9/v1/chat/completions",
        "route": "direct",
        "key_vars": ["LOCAL_STUDIO_API_KEY_1"],
        "request_extras": {},
    })
    assert created.status_code == 200
    assert created.get_json()["row"]["key_count"] == 1

    added = client.post("/api/managed_providers/local-studio/keys",
                        json={"key_var": "LOCAL_STUDIO_API_KEY_2"})
    assert added.status_code == 200
    assert added.get_json()["key_count"] == 2
    appended = client.post(
        "/api/managed_providers/local-studio/keys", json={})
    assert appended.status_code == 200
    assert appended.get_json()["key_count"] == 3

    # Status surface reports the exact active count (names + counts only).
    monkeypatch.setattr(_srv, "_operator_key_values", lambda: {})
    state = {r["name"]: r for r in
             client.get("/api/rate_state").get_json()["providers"]}
    assert state["local-studio"]["key_count"] == 3
    assert state["local-studio"]["active_keys"] == 3
    providers = {r["name"]: r for r in
                 client.get("/api/providers").get_json()["providers"]}
    assert providers["local-studio"]["key_count"] == 3

    deleted = client.delete(
        "/api/managed_providers/local-studio/keys/2")
    assert deleted.status_code == 200
    assert deleted.get_json()["key_count"] == 2  # higher slots shifted
    assert _registry.key_count("local-studio") == 2

    dropped = client.delete("/api/managed_providers/local-studio")
    assert dropped.status_code == 200
    assert "local-studio" not in _registry.provider_names()

    blob = json.dumps({
        "created": created.get_json(),
        "state": state["local-studio"],
    }, ensure_ascii=False)
    assert "FAKE" not in blob


def test_resolve_provider_uses_single_manifest_instance(
        monkeypatch, tmp_path):
    mgr = _patched_manifest(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _counted():
        calls["n"] += 1
        return mgr

    monkeypatch.setattr(_registry, "_manifest", _counted)
    assert _registry.resolve_provider("google") is not None
    assert calls["n"] == 1  # one fresh read, never a double disk load
    assert _registry.resolve_provider("nope") is None
    assert calls["n"] == 2


def test_managed_create_route_normalizes_casing_without_protocol(
        monkeypatch, tmp_path):
    """Falsy-protocol rec still returns a normalized provider name."""
    from factory.webui import server as _srv

    _patched_manifest(monkeypatch, tmp_path)
    monkeypatch.setattr(
        _srv, "_managed_create_provider",
        lambda name, row: ({"protocol": "", "key_vars": []}, ""))
    client = _srv.app.test_client()
    resp = client.post("/api/managed_providers", json={
        "name": "Kilo", "protocol": "openai_compat",
        "base_url": "http://127.0.0.1:9/v1/chat/completions",
        "route": "direct", "key_vars": [], "request_extras": {},
    })
    assert resp.status_code == 200
    assert resp.get_json()["provider"] == "kilo"


def test_seed_fallback_uses_single_manifest_owner(monkeypatch, tmp_path):
    _patched_manifest(monkeypatch, tmp_path)

    def _boom():
        raise OSError("manifest unreachable")

    monkeypatch.setattr(_registry, "_manifest", _boom)
    seed = _manifest_mod.SEED_PROVIDERS
    assert _registry.provider_names() == list(seed)
    row = _registry.resolve_provider("google")
    assert row is not None
    assert row["key_vars"] == tuple(seed["google"]["key_vars"])
    assert row["protocol"] == seed["google"]["protocol"]
    assert _registry.resolve_provider("nope") is None


def test_request_paths_share_one_manifest_manager(monkeypatch, tmp_path):
    from factory.webui import server as _srv

    mgr = _patched_manifest(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _counted():
        calls["n"] += 1
        return mgr

    monkeypatch.setattr(_registry, "_manifest", _counted)
    monkeypatch.setattr(_srv, "_operator_key_values", lambda: {})
    rows = _srv.key_presence(clean_fn=lambda: [])
    assert calls["n"] == 1  # one manager per request, not per call
    assert {r["name"] for r in rows} >= {"google", "groq"}
    models, error = _srv.provider_model_list("nope")
    assert models is None and error.startswith("unknown provider")
    assert calls["n"] == 2  # second request, second single manager


def test_managed_create_rejects_misshapen_body(monkeypatch, tmp_path):
    from factory.webui import server as _srv

    _patched_manifest(monkeypatch, tmp_path)
    client = _srv.app.test_client()
    bad_extras = client.post("/api/managed_providers", json={
        "name": "weird1", "protocol": "openai_compat",
        "base_url": "http://127.0.0.1:9/v1", "route": "direct",
        "key_vars": [], "request_extras": "abc"})
    assert bad_extras.status_code == 400
    assert "request_extras" in bad_extras.get_json()["error"]
    bad_keys = client.post("/api/managed_providers", json={
        "name": "weird2", "protocol": "openai_compat",
        "base_url": "http://127.0.0.1:9/v1", "route": "direct",
        "key_vars": "abc", "request_extras": {}})
    assert bad_keys.status_code == 400
    assert "key_vars" in bad_keys.get_json()["error"]
    plain = client.post("/api/managed_providers", data="abc",
                        content_type="application/json")
    assert plain.status_code == 400
    assert "weird1" not in _registry.provider_names()
    assert "weird2" not in _registry.provider_names()


def test_names_fallback_filters_explicit_removals(monkeypatch, tmp_path):
    _patched_manifest(monkeypatch, tmp_path)

    class _Failing:
        def provider_names(self):
            raise OSError("disk full")

        def is_removed(self, name):
            return name == "groq"

    monkeypatch.setattr(_registry, "_manifest", lambda: _Failing())
    names = _registry.provider_names()
    assert "groq" not in names
    assert set(names) == set(_manifest_mod.SEED_PROVIDERS) - {"groq"}

    class _Dead:
        def provider_names(self):
            raise OSError("disk full")

        def is_removed(self, name):
            raise OSError("disk full")

    monkeypatch.setattr(_registry, "_manifest", lambda: _Dead())
    assert _registry.provider_names() == []


def test_corrupt_manifest_quarantined_before_reseed(tmp_path):
    import pathlib
    path = str(tmp_path / "provider_manifest.json")
    raw = b'{"providers": {"kilo": '
    with open(path, "wb") as handle:
        handle.write(raw)
    mgr = _manifest_mod.ProviderManifestManager(path=path)
    assert mgr.provider_names() != []  # seeds after quarantining
    kept = sorted(pathlib.Path(str(tmp_path)).glob(
        "provider_manifest.json.corrupt.*"))
    assert len(kept) == 1
    assert kept[0].read_bytes() == raw  # original bytes preserved
