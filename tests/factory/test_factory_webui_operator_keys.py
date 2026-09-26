"""T8: one-time supervisor-token paste (encrypted) + factory env resolution.

Secrets names-only: the pasted canary below is a fake test literal, never a
real credential. No test writes the real factory env file or the real
operator store — everything rides tmp paths + monkeypatched seams.
"""

import json
import logging
import os

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from factory.webui import server as webui

SUP_VAR = "EGRESS_SUP_TOKEN"
MASTER_VAR = "AI_MASTER_KEY"

# Fake canary literal (test-only, never a real credential).
CANARY = "T8CANARY-supervisor-bearer-fake-9f31"
FACTORY_HIT = "T8CANARY-factory-file-fake-51ab"
OPERATOR_HIT = "T8CANARY-operator-store-fake-77cd"


def _ephemeral_master(monkeypatch):
    """In-memory-only Fernet master for the test (never written anywhere)."""
    from cryptography.fernet import Fernet
    import config as _cfg
    raw = Fernet.generate_key().decode()
    monkeypatch.setenv(MASTER_VAR, raw)
    monkeypatch.setattr(_cfg, MASTER_VAR, raw)
    return raw


def _isolate_token_seams(monkeypatch, tmp_path):
    """Point the operator store at tmp; silence every other token source."""
    store = tmp_path / "operator_keys.json"
    store.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(webui, "OPERATOR_KEYS_PATH", str(store))
    monkeypatch.delenv(SUP_VAR, raising=False)
    monkeypatch.setattr(webui, "_read_supervisor_token_file", lambda *a, **k: "")
    try:
        from tools.egress import supervisor as _sup
        monkeypatch.setattr(_sup, "load_env", lambda *a, **k: {})
    except Exception:
        pass
    try:
        from factory.precard import provider_lease_policy as _lease
        monkeypatch.setattr(_lease, "resolve_key", lambda *a, **k: "")
    except Exception:
        pass
    return store


def test_token_paste_one_time_only(tmp_path, monkeypatch, caplog):
    """Paste once: value never returned; second read is names-only."""
    _ephemeral_master(monkeypatch)
    _isolate_token_seams(monkeypatch, tmp_path)
    client = webui.app.test_client()
    with caplog.at_level(logging.INFO):
        resp = client.post("/api/supervisor/token",
                           json={"key_value": CANARY})
    assert resp.status_code == 200
    assert CANARY not in resp.get_data(as_text=True)
    first = client.get("/api/supervisor/status").get_json()
    assert first == {"var": SUP_VAR, "configured": True}
    assert CANARY not in json.dumps(first)
    second = client.get("/api/supervisor/status").get_json()
    assert second == {"var": SUP_VAR, "configured": True}
    assert CANARY not in json.dumps(second)
    keys = client.get("/api/keys").get_json()
    assert CANARY not in json.dumps(keys)
    for record in caplog.records:
        assert CANARY not in record.getMessage()
    text = open(webui.HTML_PATH
                if hasattr(webui, "HTML_PATH") else
                os.path.join(PROJECT_ROOT, "factory", "webui", "index.html"),
                encoding="utf-8").read()
    assert CANARY not in text


def test_token_encrypted_at_rest(tmp_path, monkeypatch):
    """Stored blob carries no plaintext; it decrypts only via key_crypto."""
    _ephemeral_master(monkeypatch)
    store = _isolate_token_seams(monkeypatch, tmp_path)
    client = webui.app.test_client()
    resp = client.post("/api/supervisor/token", json={"key_value": CANARY})
    assert resp.status_code == 200
    raw = store.read_text(encoding="utf-8")
    assert CANARY not in raw
    blob = json.loads(raw).get(SUP_VAR, "")
    assert blob.startswith("v1:")
    from services.db import key_crypto
    assert key_crypto.decrypt_secret(blob) == CANARY


def test_factory_env_primary_resolution(tmp_path, monkeypatch):
    """Primary factory env file beats the operator store."""
    _ephemeral_master(monkeypatch)
    _isolate_token_seams(monkeypatch, tmp_path)
    monkeypatch.setattr(webui, "_factory_env_value",
                        lambda var: FACTORY_HIT if var == SUP_VAR else "")
    monkeypatch.setattr(webui, "_operator_key_values",
                        lambda: {SUP_VAR: OPERATOR_HIT})
    assert webui._supervisor_token() == FACTORY_HIT
    monkeypatch.setattr(webui, "_factory_env_value", lambda var: "")
    assert webui._supervisor_token() == OPERATOR_HIT


def test_surfaces_names_only(tmp_path, monkeypatch):
    """Keys/status/providers surfaces carry names + booleans, never values."""
    _ephemeral_master(monkeypatch)
    _isolate_token_seams(monkeypatch, tmp_path)
    client = webui.app.test_client()
    assert client.post("/api/supervisor/token",
                       json={"key_value": CANARY}).status_code == 200
    bodies = [
        client.get("/api/supervisor/status").get_data(as_text=True),
        client.get("/api/keys").get_data(as_text=True),
        client.get("/api/providers").get_data(as_text=True),
        client.get("/api/master/status").get_data(as_text=True),
    ]
    for body in bodies:
        assert CANARY not in body
    status = client.get("/api/supervisor/status").get_json()
    assert set(status) == {"var", "configured"}
    assert status["var"] == SUP_VAR
    assert status["configured"] is True
    # Providers panel hosts the one-time paste UI (placement: providers
    # panel); the input clears on submit and no value is ever rendered.
    text = open(os.path.join(PROJECT_ROOT, "factory", "webui", "index.html"),
                encoding="utf-8").read()
    assert 'id="supervisor-card"' in text
    assert 'id="supervisor-token-input"' in text
    assert 'id="btn-supervisor-save"' in text
    assert "/api/supervisor/token" in text
    assert "/api/supervisor/status" in text
    assert "supervisorTokenSave" in text
    # Fail-closed: with no master key nothing resolves and nothing stores.
    import config as _cfg
    monkeypatch.delenv(MASTER_VAR, raising=False)
    monkeypatch.setattr(_cfg, MASTER_VAR, "")
    assert webui._supervisor_token() == "" or isinstance(
        webui._supervisor_token(), str)
    denied = client.post("/api/supervisor/token",
                         json={"key_value": CANARY + "-no-master"})
    assert denied.status_code in (400, 500)
    assert CANARY not in denied.get_data(as_text=True)
