---
name: plan-dim156-nudges-silence
description: Locked implementation spec for nudges module + silence policy + end-of-session quotes (dims 1,5,6)
created: 2026-09-07
base_commit: ab8163d
branch: feat/467-nudges-silence-policy
status: in-progress
---
STATE: spec LOCKED + review verdict consumed — status: READY FOR IMPLEMENTATION — focus: implement Module A+B + tests in feat/467-nudges-silence-policy

## Contract Lock — Dimensions 1, 5, 6 (owner locked 2026-09-07, issue #467)

GATE STATUS: LOCKED (dims 1, 5, 6). Dims 2, 3, 4, 7 stay PENDING.

- Branch: `feat/467-nudges-silence-policy` (worktree `.worktrees/feat-467-nudges-silence`, base ab8163d).
- Seam check at lock: no overlap (claims file holds only factory seams: lexicon-card-pilot, feat/s0-gates).

### Guardrails
1. New domain module `services/nudges.py` (catalog, guard conditions, silence evaluator). Presentation/lore in `config/themes.py` or formatters. Zero DB side effects, zero Telegram imports in `services/nudges.py` (AGENTS.md §3).
2. Zero schema mutations, zero AI cost. In-memory data, `settings` keys, or bounded reads (`due_words_for_user`, `daily_session_budget`). Template substitution only.
3. Persian typography: «،» lists, «؛» clauses, `-`/`.`; never `·`/`—`/`|` in learner strings (except `—` empty, `|` card footers). Persian numerals via `services/utils/formatting.py`.

### Module A: services/nudges.py (pure, no Telegram imports)
- `is_quiet_hours(now_dt)`: True iff Tehran time (`APP_TIMEZONE`) in [23:00, 08:00).
- `evaluate_silence(user_id, session_budget, active_session_exists, due_count)`: Hard Silence True iff active session open OR budget remaining == 0 OR (due == 0 and no new cards).
- Priority (at most ONE per window): 1:M03 streak-at-risk, 2:M06 unfinished, 3:M08 one-to-40%, 4:M05/M09 dues, 5:M04 teaser.
- Template registry M01-M10 verbatim per owner table (M10 fixed for recall < 50%).

### Module B: summary.py integration
- `build_report`: recall < 0.50 injects M10; `target_window == 'today'` on grades 1&2 appends M01 with computed `{hours}`.
- NOTE for reviewer: M10 2-tip already shipped in PR #598 — check overlap/duplication. `build_report` currently takes records only — `target_window` needs a new param or precomputed input.

### Verification matrix
- `tests/test_nudges.py`: quiet boundaries (22:59 allow, 23:00 quiet, 07:59 quiet, 08:00 allow), suppression hierarchy, silence triggers, slot sanitization + Persian numerals.
- `tests/test_integration/test_session_summary_quotes.py`: M10 on recall<50% session; M01 on same-day short-term dues.
- Add `services/nudges.py` keywords to `tests/test_single_source_of_truth.py`; `git diff --check` clean.

## Evidence
- Owner lock text 2026-09-07 (dims 1,5,6 implementation spec, branch named).
- Efficiency review verdict: NEEDS-OWNER-ANSWER on windows/timezone/hours-source + M02 exemption + M04 starvation (2 findings, rest OK or fix-in-implementation).
- Owner answers 2026-09-07 (LOCKED):
  1. Windows on APP_TZ: morning 08-12, noon 12-17, evening 17-23, night-quiet 23-08. Max 1 send per window, cap 2 per calendar day. `target_window` fully APP_TZ-calendar (today; past 00:00 = tomorrow + silence). `{hours}` = now() vs grade `next_review_at` from words.py, rounded, Persian digits.
  2. M02 has NO silence exemption; on midnight rollover it is deferred to first tick after quiet ends (08:00 next day). M04 anti-starvation: if user saw no fresh cards for >=3 consecutive days AND Tier-2 words ready, M04 promotes to priority 2 in noon window.
- Exec fixes approved: build_report frozen (M01 built in handler/summary site), M10 aliases pick_motivation (no duplicate), reads only at nudge tick with cached state.

## Blocked Questions
- None open. Implementation proceeds under this lock.
