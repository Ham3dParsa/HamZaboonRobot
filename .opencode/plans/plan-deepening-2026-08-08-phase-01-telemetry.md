# Phase 01 — AI telemetry wrapper (Finding #1)

Blocking edges: none (first).
Contract rule: #1. Gate: fast-track (mechanical, no behavior).
Wiring rows: `services/ai/ai.py` outcome ternary ×5 (143, 517, 602, 646, 756) → single `_call_tracked(...)`.

## Scope
- `services/ai/ai.py`: add `_call_tracked(request_kind, preset, log_target=...)` owning telemetry + try/except/finally + outcome classification + `_log_llm_request`.
- Convert `repair_card` (485-522), `ask_json` (568-607), `ask_card` (610-651), `ask_batch` (708-761) to call the wrapper.
- `custom_test_card` writes to `config_tests` — wrapper accepts a log target so that path stays separate.

## Tests
- Unit: wrapper classifies success vs failure_billed vs failure_zero_cost correctly.
- Unit: wrapper honors custom log target (config_tests) for test-only path.
- Existing AI tests must pass unchanged (no behavior change).

## Acceptance
- `failure_billed`/`failure_zero_cost` outcome logic exists exactly once.
- No AI contract/quota/behavior change. No new AI calls (zero token impact).
- `pytest tests/` AI-related green; `test_wiring.py` unchanged green.

## Verify
`python -m pytest tests/ -n 14` (AI subset first), `ruff F821/F811`.
