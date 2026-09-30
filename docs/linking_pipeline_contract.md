# Linking Pipeline Contract (R1–R7) + Audit State

Frozen 2026-09-28/29 pre-compaction. No code was written for R1–R7;
GATE STATUS is PENDING owner rule-choices. This file is the single
source for resuming.

## 1. Locked context both sides already agreed

- Arbiter = LLM-based only; `judge` banned factory-wide (legacy word).
- Mechanical step = `mechanical_review` (renamed from `arbitrate_link`).
- AI preset (WHO + HOW MUCH, shared) vs step prompt (WHAT, cabin-owned);
  bot and factory preset stores unrelated.
- Owner (not builder) runs live models; builder tests with stubs only.
- A2 = design language; R2 = rebuild package (rebuilt on working tabs).

## 2. The seven rules (as proposed, awaiting per-rule lock)

- **R1 — best_key selection:** first candidate in table index order
  (matches lookup + shortlist order-kept; zero invention). Alt:
  score-based picking (rejected: invents scoring).
- **R2 — fires extraction:** split row evidence on `+` into fire
  tokens, unioned across the sense's rows for the best key (shipped
  data only). Alt: raw string as one fire (rejected: starves vetoes).
- **R3 — twin/ultra-short/exact inputs:** all default off in v1;
  twin-suspect and ultra-short senses route to DEFERRED (never
  approved/rejected; arbiter + operator still see them). Alt:
  threshold-guessing (rejected: invents unreported rules).
- **R4 — method→verdict map:** `LINK:*` → approved;
  `MANUAL-NONE`/`quarantined-known-false` → rejected;
  `JUDGE-PENDING`/`UNMAPPED`/`twin-pending` → deferred. Nearly forced
  by `mechanical_review` doctests.
- **R5 — RunLog class** (`factory/webui/run_log.py`, one owner for all
  cabins/steps): append-only JSONL `{ts, level, event, detail}` +
  `tail(n)` + `<pre>` log-box UI idiom (screening-log pattern).
  Wired into arbiter + mechanical workers now, screening later.
  Per-sense `current` sense also surfaced in run status. Alt:
  per-module log code (rejected: duplication).
- **R6 — tab-1 rename:** «گزینش نامزدها» (candidate selection). Tests
  asserting the old label get updated, not reverted.
- **R7 — mechanical→arbiter handoff:** mechanical run record stores
  `deferred_ids` server-side; arbiter create accepts `{from_run: id}`.
  Alt: client-passed raw ids (rejected: unauditable).

## 3. Two live-observed blocking bugs (owner-reported, unfixed)

**(a) Empty verdict cards (tab 3/arbiter panel):** cards show no gloss,
no proposed candidate, no model reasoning — three bare words repeated
in a large grey box. Root hypothesis (unverified): verdict rows render
without joining sense definitions/candidates, and the model-evidence
fields are never displayed. Fix belongs to the R2/tab-panel pass with
a content contract per card (sense_id + gloss + winner + evidence).

**(b) Tab-4 dead end on active batch:** issuing a new batch fails while
an older batch is still active, but the UI neither disables the issue
button nor surfaces the active batch state in the workflow. Fix: live
active-batch state drives the button (disabled + reason) and a visible
"active batch" strip; the error path stays as backstop, never the
primary signal.

## 4. Branch state (`feat/arbiter-line`, base `origin/main` @ `0ee3141`)

Commits (oldest→newest): `ecea030` spec/DDD/plans → `6087e67` naming
lock → `e68b538` P0-P2 (rename, runner, feed, CLI) → `8e978ab` STATE
→ `3129c14` P1-P3 (jobs, endpoint) → `2019d58` STATE → `81feaac`
P4/P5 tickets → `3998967` P4 tab-2 panel → `e2a76db` STATE →
`cbaf6db` P5 five panels + unified history → `006ffb2` P6 migration
→ `3c1c732` cost guards → `9e84650` test isolation fix (HEAD).

Validation: focused suites green (242+ unit incl. migration/cost-guard
suites; live P4/P5/P6 browser tests green with inspected desktop
shots). Full local suite is environment-flaky on the shared box (see
`.opencode/plans/factory/env-pytest-reliability.md`); CI arbitrates.

Data paths (W: drive, shared root): screened inputs under
`W:\hamzaban_data_factory\proof-linker\screened\`;
`W:\hamzaban_data_factory\webui\` holds `presets/`, `batches/`,
`arbiter_runs/<run-id>/{status.json,verdicts.jsonl}`,
`arbiter_usage.jsonl`, `labels.jsonl`. No live model was ever run by
the builder (stubs/mocks only).

## 5. Resume checklist (post-compact)

1. Read this file + `CONTEXT.md` + plan STATE
   (`.opencode/plans/factory/plan-arbiter-line.md`).
2. Owner gives per-rule R1–R7 choices (or "locked as recommended").
3. Implement in order: RunLog → mechanical runner + CLI + endpoint →
   tab-1 panel + rename → arbiter live-log/progress → R7 handoff →
   fix bugs (a)+(b) with content/button contracts → TDD + reviewer +
   live-browser proof per tab → commit → push → PR + merge loop.
