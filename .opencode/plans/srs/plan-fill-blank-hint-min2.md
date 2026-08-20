---
name: fill-blank-hint-min2
description: Fill-blank pre-reveal hints show >=2 sense-consistent syn/ant items (issue #408 rendering mitigation)
created: 2026-08-20
base_commit: 96dc0f6
branch: fix/fill-blank-hint-min-2
status: in-progress
---

STATE: phase 1/1 — status: in-progress (implemented, pending commit/PR) — focus: commit + push + PR

## Locked Rules (contract 2026-08-20, GATE STATUS LOCKED)

- **Scope:** rendering-only band-aid for issue #408 part 2. Defer generation sense-fix (part 1) and report-loop (part 3).
- **Rule 1 (adaptive hints):** fill_blank shows 3 hints (2 from dominant category + 1 from other; dominant = whichever visible category has more items, synonyms on tie) when one visible category has >=2 AND the other has >=1; else 2 hints from the combined visible syn+ant pool; else meaning fallback (defensive for direct calls).
- **Rule 2:** no fa_explanation hint.
- **Rule 3 (gate):** a card is eligible for `fill_blank` only if combined visible syn+ant >= 2; below that falls back to standard/meaning/synonym.
- No callback / keyboard / router / DB / AI-call change. No wiring test required.

## Files
- `services/utils/formatting.py`: `_fill_blank_hint` -> `_fill_blank_hints`, eligibility gate in `eligible_srs_prompt_types`, render block.
- `tests/test_srs_prompt_engine.py`: update 2 obsolete tests, add gate + adaptive-mode tests.

## Blocked Questions
(none)

## Evidence
- RED: 8 failures before implementation (new/updated tests).
- GREEN: `tests/test_srs_prompt_engine.py` 38 passed after implementation.
- Full suite: 1303 passed (pytest -n 14), compile_all clean, ruff F821/F811 clean, git diff --check clean.
- hamzaboon-reviewer: no confirmed findings.