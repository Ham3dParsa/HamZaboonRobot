# Console tickets (locked scope, docs only)

Worktree: `.worktrees/webui-v5` (branch `feat/webui-v5`). No production code
changes in this task — ticket files are the deliverable. Implementers work
inside the worktree only; primary stays on `main`.

| Ticket | Priority | Title | Blocks / blocked by |
|--------|----------|-------|---------------------|
| T1 | P0 | All-interfaces default bind + explicit override + LAN-visibility note | Blocks T7; blocks T2 (same `server_ctl.ps1` seam) |
| T2 | P1 | Tidy `server_ctl.ps1` output, pid-only safety untouched | Blocked by T1 |
| T3 | P0 | Queue rows: exactly 3 fields; `جزئیات سنس` alone owns candidates/examples/full text | Blocks T4, T5 |
| T4 | P1 | Row no-shrink rule + browser regression test (real-shaped rows) | Blocked by T3; blocks T5 |
| T5 | P0 | Candidates from REAL runs + human-review lists (diagnose empty feed, fix join) | Blocked by T3, T4; blocks T7 |
| T6 | P2 | View memory: restore last cabin + tab on load (local, first-run default unchanged) | — |
| T7 | P1 | Wake-on-demand gate + idle sleep (minutes pending) + wake/sleep buttons + state surface | Blocked by T1, T5 |
| T8 | P1 | One-time token paste (encrypted) + primary factory env resolution | — |
| T9 | final | Local commit + push + open PR (no merge) + review loop to APPROVED | Blocked by T1–T8 |

Forbidden zone (all tickets): bot handlers/`services/` domain logic (read-only
`key_crypto` seam already in use), cloud provider registry (read-only),
`factory/webui/operator_keys.json` values, any secret VALUES (names only:
`AI_MASTER_KEY`, `EGRESS_SUP_TOKEN`, `HAMZABAN_WEBUI_HOST`, `HAMZABAN_WEBUI_PORT`).
