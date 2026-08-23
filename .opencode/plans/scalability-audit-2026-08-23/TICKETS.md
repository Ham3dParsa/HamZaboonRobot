# Tickets — Scalability/Security Audit (2026-08-23) — restored after clean

| # | ID | Title | Status | PR |
|---|----|-------|--------|----|
| 29 | O-config-tests | config_tests prune (`prune_config_tests`) | complete | #455 |
| 30 | O-reports-help | /reports help entry (HELP_SECTIONS `reports`) | complete | #455 |
| 32 | O-help-button | راهنما button (`BTN_HELP` main_menu) | complete | #455 |
| 34 | O-view-mode | view_mode payload honored | complete | #455 |
| 4 | tts-race | 🔊 race per-key lock | complete | #460 |
| 9 | cost-5000 | GROUP BY + USD rate | complete | #460 |
| 13 | pragma-inject | quoted ident | complete | #460 |
| 14 | restore-size | 100M guard | complete | #460 |
| 33 | llm-gate | owner_only | complete | #460 |
| 37 | preset-drift | re alias | complete | #460 |
| 18 | plan-limits-dup | plan limits single-source (`_PLAN_LIMITS` vs `valid_plans`) | complete | #475 `c9886bc` `c75459f` Kilo fix |
| 20 | allowlist-dup | allowlist derived from `ROUTES` | complete | #475 `c9886bc` `c75459f` Kilo fix |
| 24 | O-grammar-standalone | send_grammar_tip retire (export, disable) | locked | chore/retire-grammar-tip `a-03` |

Full 37-ticket table was in previous TICKETS.md (now consolidated in `docs/audit/consolidated-remaining-2026-08-23.md`). This file restores S completion after untracked clean deleted it.
Session F (4 tickets) merged as `ab7160a` — lightweight `git diff --check` only, no behavior beyond docs/help/prune.

Session A #18+#20 complete 2026-08-23 c9886bc (#475) — Kilo 1 suggestion minor merged; worktree removed.


| Q-2 | grammar-quota | quota never burns | complete | #458 |
| Q-3 | session-slot | slot never burns | complete | #459 |
| Q-7 | report-purge | purge atomic | complete | #463 |
| Q-8 | due-scan | due index | complete | #464 |
| Q-25 | auto-delivery | legacy_batch unwired | complete | #465 |
| Q-26 | optional-limit | drop dead columns | complete | #466 |
| Q-agent | agent-allowlist | safe guards | complete | #474 |
Session Q 6+1 merged to main 7b50746 (services/db released).

