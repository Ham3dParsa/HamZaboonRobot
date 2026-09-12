# factory/core — shared kernel (registry/transport/telemetry/env/glossary)

Package `factory.core` — the only shared imports the line and lexicon builders may use:

- `registry.py` — single source for lemma/POS normalization + `registry.db` ledger access.
- `llm_json.py` — JSON extraction + error classification (`AuthError`, `raise_for_auth`).
- `telemetry.py` — call counts/usage records + summary tables.
- `env_loader.py` — `factory/.env` key loading (allowlist `KEYS`; values via env, never logged).
- `probe_keys.py` — egress + key health check (`python -m factory.core.probe_keys`, no secrets printed).
- `stage_glossary.py` — sole owner of the stage/gate/rule/reason naming map
  (old ids ↔ domain names: preprocess/inflection/anchor/judge/vectors/label/enrich).

No heavy imports here (torch-less); `factory/__init__.py` stays empty so
`services/` + fast tests never pay import cost.
