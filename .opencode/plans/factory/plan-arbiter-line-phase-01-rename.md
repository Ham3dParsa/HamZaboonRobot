# Phase 01 — P0 rename `arbitrate_link` → `resolve_link` (D2)

Gates: D2. Blocking: none.
Scope: `factory/linking/linker.py:393` + every caller (grep
`arbitrate_link` repo-wide first: tests, viewer vocab?, docs).
Tests: update referencing tests in same commit (test-sync); no behavior
change (pure rename — verify with focused suite before/after).
Acceptance: zero `arbitrate_link` hits outside changelog/history;
`pytest tests/factory -k "linker or arbitrat or resolve"` green.
