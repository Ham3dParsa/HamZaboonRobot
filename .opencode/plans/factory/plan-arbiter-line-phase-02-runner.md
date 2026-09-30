# Phase 02 — P1 arbiter-runner engine

Gates: D1/D4 + spec stages 3–4. Blocking: P0 (clean names first).
Scope (new module, e.g. `factory/linking/arbiter_runner.py`):
per-sense prompt build (`arbitration_prompt.py` — read-only),
transport via provider row (local endpoint configurable per preset, or
registry provider incl. Google; timeout + concurrency caps explicit),
verdict parse (strict, fail-closed → routed-to-supervised, never
invented), gate assembly (`ArbitrationVerdict`), verdicts file output.
TUI and WUI share this module (D3 order note).
Tests: stub transports only (D4 — zero live calls); happy + malformed
payload + timeout + gate-routing cases.
Acceptance: runner over fixture senses → verdicts file; no network in tests.
