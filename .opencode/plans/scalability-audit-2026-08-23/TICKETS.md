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
| 18 | plan-limits-dup | plan limits single-source (`_PLAN_LIMITS` vs `valid_plans`) | in-progress | #475 `refactor/plan-limits-allowlist` `5788c15` |
| 20 | allowlist-dup | allowlist derived from `ROUTES` | in-progress | #475 `refactor/plan-limits-allowlist` `5788c15` |

Full 37-ticket table was in previous TICKETS.md (now consolidated in `docs/audit/consolidated-remaining-2026-08-23.md`). This file restores S completion after untracked clean deleted it.
Session F (4 tickets) merged as `ab7160a` — lightweight `git diff --check` only, no behavior beyond docs/help/prune.
Session A #18+#20 locked ALL A 2026-08-23 → worktree `.worktrees/a-02` branch `refactor/plan-limits-allowlist`; plan `plan-18-20-plan-limits-allowlist.md` STATE LOCKED → implemented 5788c15 awaiting CI/Kilo.
