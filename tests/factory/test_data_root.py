"""HAMZABAN_DATA_ROOT data-root resolution (locked R1-R4).

Hermetic: tmp_path + monkeypatch only, no network, no W: drive.
Covers data_root() itself plus every resolved data default in the four
locked modules (kaikki index/raw x2, CEFR TSV x2, tatoeba pools x2,
topic vectors; EVP stays repo-local by design).
"""

import os

import pytest

from factory.core import env_loader
from factory.core.env_loader import data_root
from factory.lexicon import cefr_bridge
from factory.pipeline import card_pilot
from factory.precard import cefr as precard_cefr
from factory.precard import pipeline as precard_pipeline

ROUTED = [
    (card_pilot, "DEFAULT_KAIKKI_INDEX", ("raw", "kaikki-en-index.jsonl")),
    (card_pilot, "DEFAULT_KAIKKI_RAW", ("raw", "kaikki-en-words.jsonl")),
    (card_pilot, "DEFAULT_TATOEBA_POOL",
     ("fixtures", "tatoeba_pool_v13a.json")),
    (card_pilot, "DEFAULT_TOPIC_VECTORS",
     ("fixtures", "topic_vectors-v16b.json")),
    (precard_pipeline, "DEFAULT_KAIKKI_INDEX",
     ("raw", "kaikki-en-index.jsonl")),
    (precard_pipeline, "DEFAULT_KAIKKI_RAW",
     ("raw", "kaikki-en-words.jsonl")),
    (precard_pipeline, "DEFAULT_TATOEBA_POOL",
     ("fixtures", "tatoeba_pool_v13a.json")),
    (cefr_bridge, "DEFAULT_TSV",
     ("fixtures", "cefr-wordnet", "wordnet_sensekey_cefr.tsv")),
    (precard_cefr, "DEFAULT_TSV",
     ("fixtures", "cefr-wordnet", "wordnet_sensekey_cefr.tsv")),
]

MODULES = [card_pilot, precard_pipeline, cefr_bridge, precard_cefr]


@pytest.fixture
def clean_attrs():
    """Drop leftover module-global overrides so env resolution is tested.

    A monkeypatch.setattr round-trip in another test restores a resolved
    string into the module dict; without cleanup that stale entry would
    shadow the lazy env lookup here. monkeypatch.delattr cannot be used:
    getattr succeeds via the module __getattr__ while the real delete
    finds no dict entry. Leftovers are restored on teardown (no trace).

    Teardown additionally drops every ROUTED name that was NOT present at
    setup: a setattr round-trip during a test (e.g. the override-wins
    test) restores the resolved string into the module dict on undo,
    which would otherwise shadow lazy env resolution for every later
    test in the same xdist worker (opencode review on PR #812).
    """
    saved = []
    for module, name, _parts in ROUTED:
        if name in module.__dict__:
            saved.append((module, name, module.__dict__.pop(name)))
    saved_keys = {(id(module), name) for module, name, _value in saved}
    yield
    for module, name, _parts in ROUTED:
        if (id(module), name) not in saved_keys:
            module.__dict__.pop(name, None)
    for module, name, value in saved:
        module.__dict__[name] = value


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv(env_loader.DATA_ROOT_ENV_VAR, raising=False)
    return monkeypatch


def _norm(path):
    return str(path).replace("\\", "/")


def test_data_root_unset_falls_back_to_repo_data(clean_attrs, clean_env):
    root = data_root()
    assert _norm(root).endswith("/data")
    assert "W:" not in root


@pytest.mark.parametrize("blank", ["", "   "])
def test_data_root_blank_falls_back_to_repo_data(clean_attrs, clean_env,
                                                     monkeypatch,
                                                 blank):
    monkeypatch.setenv(env_loader.DATA_ROOT_ENV_VAR, blank)
    root = data_root()
    assert _norm(root).endswith("/data")
    assert "W:" not in root


def test_data_root_set_returns_env_root(clean_attrs, monkeypatch, tmp_path):
    monkeypatch.setenv(env_loader.DATA_ROOT_ENV_VAR, str(tmp_path))
    assert data_root() == str(tmp_path)


def test_data_root_reflects_env_changes_between_calls(clean_attrs,
                                                      monkeypatch, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv(env_loader.DATA_ROOT_ENV_VAR, str(first))
    assert data_root() == str(first)
    monkeypatch.setenv(env_loader.DATA_ROOT_ENV_VAR, str(second))
    assert data_root() == str(second)
    monkeypatch.delenv(env_loader.DATA_ROOT_ENV_VAR)
    assert _norm(data_root()).endswith("/data")


def test_set_root_prefixes_every_resolved_default(clean_attrs, monkeypatch,
                                                  tmp_path):
    """Env root set -> every routed default lives under it.

    (No zero-"W:" check here: on Windows tmp_path itself may sit on a
    W: drive. The zero-"W:" criterion belongs to the unset/blank
    fallback cases below.)
    """
    monkeypatch.setenv(env_loader.DATA_ROOT_ENV_VAR, str(tmp_path))
    for module, name, parts in ROUTED:
        resolved = getattr(module, name)
        assert _norm(resolved) == _norm(os.path.join(str(tmp_path), *parts))


def test_unset_root_resolves_under_repo_data_without_w(clean_attrs,
                                                          clean_env):
    """Env root unset -> every routed default under repo data/, zero W:."""
    for module, name, parts in ROUTED:
        resolved = getattr(module, name)
        assert "W:" not in resolved
        tail = _norm(os.path.join("data", *parts))
        assert _norm(resolved).endswith(tail)


def test_blank_root_resolves_under_repo_data_without_w(clean_attrs,
                                                       monkeypatch):
    monkeypatch.setenv(env_loader.DATA_ROOT_ENV_VAR, "  ")
    for module, name, _parts in ROUTED:
        assert "W:" not in getattr(module, name)


def test_module_global_override_wins_over_env(clean_attrs, monkeypatch,
                                              tmp_path):
    """A monkeypatched DEFAULT_* (existing suite style) wins everywhere,
    including the internal resolver path."""
    override = str(tmp_path / "custom-index.jsonl")
    monkeypatch.setenv(env_loader.DATA_ROOT_ENV_VAR, str(tmp_path / "root"))
    monkeypatch.setattr(card_pilot, "DEFAULT_KAIKKI_INDEX", override)
    assert card_pilot.DEFAULT_KAIKKI_INDEX == override
    assert card_pilot._data_default("DEFAULT_KAIKKI_INDEX") == override


def test_evp_stays_repo_local_pack_in_all_env_states(clean_attrs, clean_env,
                                                         monkeypatch,
                                                     tmp_path):
    """DEFAULT_EVP is git-tracked factory data (not data-root content):
    repo-local pack path with zero W:, independent of the env root."""
    expected_tail = _norm(os.path.join(
        "factory", "packs", "en", "evp_sense.json"))
    for module in (cefr_bridge, precard_cefr):
        assert _norm(module.DEFAULT_EVP).endswith(expected_tail)
        assert "W:" not in module.DEFAULT_EVP
    monkeypatch.setenv(env_loader.DATA_ROOT_ENV_VAR, str(tmp_path))
    for module in (cefr_bridge, precard_cefr):
        assert _norm(module.DEFAULT_EVP).endswith(expected_tail)
        assert "W:" not in module.DEFAULT_EVP


def test_unknown_attr_still_raises_attribute_error():
    for module in MODULES:
        with pytest.raises(AttributeError):
            getattr(module, "DEFAULT_NO_SUCH_THING_XYZ")
