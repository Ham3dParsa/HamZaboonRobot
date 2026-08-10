---
name: phase-2b-drop-daily-tables
description: Superseded 2026-08-05 Phase 2b plan retained for decision history.
created: 2026-08-05
archived: 2026-08-09
status: archived
---

# Archived — Original Phase 2b Daily-Table Drop Plan

This plan originally covered only:

- dropping `daily_cards`, `daily_progress`, and `daily_card_sessions`;
- removing their DB functions and re-exports;
- deleting `migrate_saved_words_to_fsrs` and its startup call;
- rewriting schema/migration guards that depended on daily tables.

It was persisted after Phase 3a and before approximately 35 later commits. The
2026-08-09 plan-validity audit found that its line references and scope were no
longer sufficient.

## Why It Was Superseded

The current code and locked contract also require:

- removal of the dead TTS daily source branch;
- removal of the `daily_card_sessions` column-migration block;
- safe abort when an old DB has daily tables without `fsrs_migration_done=1`;
- dropping the dead `saved_words.interval_idx` column;
- explicit preservation of pending/retry fields through Phase 3b;
- fresh and prior-schema migration coverage;
- integration into the larger FSRS timestamp/grading dependency chain.

The canonical replacement is:

`.opencode/plans/fsrs/plan-fsrs-session-completion-phase-01-daily-schema-purge.md`

The locked main spec is:

`.opencode/plans/fsrs/plan-fsrs-session-completion.md`

## Original Locked Decisions Preserved

| Original rule | Decision retained in replacement |
|---|---|
| Rule 2 (partial) | Remove dead migration and startup call |
| Rule 3 | Drop all three daily tables |
| Rule 4 | Rewrite migration tests without daily-table dependencies |

## Final Verdict

- Done: The original Phase 2b scope and decision history are preserved here.
- Deliberately Not Done: No production implementation was performed from this obsolete plan.
- Deferred: Implementation is governed by the replacement Phase 1 ticket.
- Uncertain: None; the 2026-08-09 audit and owner contract resolved the identified gaps.
