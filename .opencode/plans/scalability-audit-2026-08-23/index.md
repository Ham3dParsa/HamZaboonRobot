STATE: A-22 COMPLETE (#481) — F/Q/S/P/A-18-20/A-24/A-22 done; A-remaining #21,27 pending

# Scalability/Security Bottleneck Audit — Plan Index (2026-08-23)

**Source decisions:** `decisions-20260823.json` (22 findings, all `keep`) extracted from `docs/audit/scalability-security-bottleneck-audit-2026-08-23-simple-decisions-202608230122.html`.
**Global note:** «یک گروه بندی از سمت خودت نیاز دارم تا بررسی دقیقی بکنیم که کدام موارد به شکل موازی میتوانند الان پیش بروند از طریق مهارت "گارد کارهای موازی".»
**Older sources triaged:** `orphaned-features-audit-2026-08-22` + `Deepening/2026-08-16-*` — see `remaining-from-older-audits.md` (now archived, consolidated in `docs/audit/consolidated-remaining-2026-08-23.md`).

## Phases

| Phase | Seam | Status |
|-------|------|--------|
| F — Fast-track | `docs/`, `services/utils/`, `handlers/help_command.py`, `config/keyboards.py`, `handlers/admin_ai.py`, `services/db/__init__.py:prune` | complete (#455) — tickets O-config-tests, O-reports-help, O-help-button, O-view-mode |
| Q — Quota/DB | `services/db/*`, `services/scheduling.py` | complete (#458) |
| S — Security/AI | `services/ai/*`, `services/db/preset_registry.py`, `cost_tracking.py`, `key_crypto.py`, `tts.py` | complete (#460) — tickets #4,9,13,14,33,37 |
| P — Perf/Handlers | `handlers/*`, `config/keyboards.py`, `services/db/schema.py` | complete (#462 P-UNBLOCKED + #477 P-DB a17e23e) |
| A — Architecture | `config/catalog.py`, `plan_identity`, `preset_fields` | in-progress — plan-21 (#21) `refactor/split-keyboards` LOCKED keyboards first; plan-22 (#22) complete 834076f (#481); plan-24 (#24) complete 99471e0 (#478); remaining #27 pending |

Claims in `$(git rev-parse --git-common-dir)/parallel-work-claims.json` — S disjoint from Q at file level (owner approved `proceed`).
