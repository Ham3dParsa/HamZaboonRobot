STATE: S-COMPLETE — Q-merged, S-merged (#460), P-merged (#462); F complete

# Scalability/Security Bottleneck Audit — Plan Index (2026-08-23)

**Source decisions:** `decisions-20260823.json` (22 findings, all `keep`) extracted from `docs/audit/scalability-security-bottleneck-audit-2026-08-23-simple-decisions-202608230122.html`.
**Global note:** «یک گروه بندی از سمت خودت نیاز دارم تا بررسی دقیقی بکنیم که کدام موارد به شکل موازی میتوانند الان پیش بروند از طریق مهارت "گارد کارهای موازی".»
**Older sources triaged:** `orphaned-features-audit-2026-08-22` + `Deepening/2026-08-16-*` — see `remaining-from-older-audits.md` (now archived, consolidated in `docs/audit/consolidated-remaining-2026-08-23.md`).

## Phases

| Phase | Seam | Status |
|-------|------|--------|
| F — Fast-track | `docs/`, `services/utils/` | complete |
| Q — Quota/DB | `services/db/*`, `services/scheduling.py` | complete (#458) |
| S — Security/AI | `services/ai/*`, `services/db/preset_registry.py`, `cost_tracking.py`, `key_crypto.py`, `tts.py` | complete (#460) — tickets #4,9,13,14,33,37 |
| P — Perf/Handlers | `handlers/*`, `config/keyboards.py` | complete (#462) |
| A — Architecture | `config/catalog.py`, `plan_identity`, `preset_fields` | pending |

Claims in `$(git rev-parse --git-common-dir)/parallel-work-claims.json` — S disjoint from Q at file level (owner approved `proceed`).
