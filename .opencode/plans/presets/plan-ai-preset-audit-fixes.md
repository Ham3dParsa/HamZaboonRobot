---
name: ai-preset-audit-fixes
description: Locked fix spec for the Admin AI Preset audit findings (R1–R15, F1/F2) + thinking-control (R16→#241) + activation/preferred fix (R17)
created: 2026-08-12
base_commit: 8166c9c
branch: fix/ai-preset-audit-findings
status: in-progress
---
STATE: phase 5/7 — status: complete (PR #339 merged 0d9a491; R11/F2 encrypted-at-rest keys, v1: marker + MasterKeyRequiredError added in Kilo loop) — next: Phase 6 (R17 activation/preferred)

# Contract Lock — Admin AI Preset Panel fixes

Baseline: `main` @ `8166c9c`. Audit: `docs/audits/audit_admin_ai_preset_panel_2026-08-10.md`.
UI authority: the owner-provided "Telegram Bot UI/UX Design System" doc (emoji dictionary + templates A–D) is the canonical spec for all preset-panel text/emoji/keyboard rendering (overrides earlier R8 proposals).
Seam claim: acquired 2026-08-12 for seams Persistence / Telegram UI→Admin / AI Config / Plans / Cost / AI-LLM Provider; rule_ids extended with R16,R17.

## Locked rules (R1–R15, F1, F2, R16, R17)

| # | Decision (final) |
|---|---|
| 1 | Two-tier chain: normal by `priority` asc, then emergency by `priority` asc; swap within tier only; one db-owned order source; `set_emergency` flips target only. Rendered as 📂 عادی / 🛡️ اضطراری sections (Template C). |
| 2 | Add `priority` to `set_preset`; wire wizard to send it. |
| 3 | Two-step delete confirm (reached from preset **detail** page per §4). |
| 4 | Duplicate Preset = `<old> (copy)` + rename option; Duplicate Group = prompt new name/key/URL (reuse-or-type) then clone presets. Buttons on detail/manage page. |
| 5 | Edit-flow nav = Plan Definition pattern (Back/Skip/Cancel/Save, one callback set); list/detail pages use doc §4 bottom-row 🔙/🏠. |
| 6 | Shared render fix (both list sites) → clean `🟢 name [tags]` format (Templates A/B/C). |
| 7 | Paginate usage (`per_page=5`) + stop re-send; render per Template D (only show exceptions, no emoji walls). |
| 8 | Lock to the UI/UX doc emoji dictionary (below). Authoritative for all preset-panel text/emoji/keyboard. |
| 9 | Relabel usage to **«مصرف ۲۴ ساعته»** (rolling) — overrides doc's «روزانه». |
| 10 | Hard error + owner alert when no active preset (no silent empty). |
| 11 | Group-level API key, entered via admin panel, **encrypted at rest (Fernet, master key in app env var)**; no `$ENV` refs; never log literal; consistent masking. Replaces AGENTS.md §3 pattern (F2). |
| 12 | Guard all four: rename collision, emergency-flip-one, no disable-last, repair `ai_fallback_preset` on delete. |
| 13 | Atomic quota reserve + prune >24h + count failure only if provider emitted usage/partial. |
| 14 | End-of-create: status/priority prompt + inline connection test (✅/❌) before save; default disabled/lowest. |
| 15 | Fix all: idx checks, int-parse guard, stale-token reject, N+1 batch, no bare except, re-enable path, plan-text escape. |
| F1 | Builtin removal = own PR (code-only deletion of seed/builtin refs; no migration; existing DB rows become ordinary presets). |
| F2 | R11 replaces `$ENV-only`; update AGENTS.md §3, `.env.example`, audit accordingly. |
| 16 | **Reasoning-effort per preset** (GitHub #241): add per-preset `reasoning_effort` (none/low/medium/high) column + migration; pass as `extra_body` for thinking models; UI field in create/edit (R14). Not a secret → no R11 encryption. |
| 17 | **Activation / "preferred" fix**: "active" = enabled; "preferred" = first-in-chain target; chain fails over by priority (R1) to a working preset. `activate_preset` sets *preferred* (`ai_primary_preset`); fix `get_active_preset_name` duality; drop legacy flat-key copy; remove builtin default; reject disabled preset. |

## Emoji dictionary (R8 — authoritative)

| Emoji | Meaning | Rule |
|---|---|---|
| 🟢 / ⚫ | ON / OFF (toggle) | never ✅/❌ for on/off |
| ✅ / ❌ / ⚠️ | connection-test result & system warnings | health only |
| 🎯 | active preset (live routing) | replaces ★ |
| 🛡️ | emergency tier | 🚨 reserved for system-down only |
| 🔋 / 🪫 | quota sufficient / exhausted | separate from health |
| 💰 or `[موفق]` | last AI call success (billed) | replaces 💸; failure = ❌ |

Connection test in Template A `⚡` → **✅**. Quota already 🔋. Last AI call uses 💰/[موفق] success, ❌ failure.

## Dependency & Wiring Map

| Dependent feature | Seam | Disposition |
|---|---|---|
| `set_preset` signature (+priority) | Persistence / AI Config | update |
| `get_active_preset` empty/disabled handling | Persistence / AI/LLM Provider | update |
| order source (swap/reindex/set_emergency) | Persistence / AI Config | update |
| delete confirm callback + route | AI Config / callback prefixes | add |
| Duplicate Preset/Group handlers + buttons | AI Config / callback prefixes | add |
| edit-flow Back/Skip semantics | Admin / AI Config | update |
| `_show_fallback_usage_details` pagination | AI Config | update |
| emoji legend (admin_ai + admin_cost + templates) | AI Config / Cost | update |
| `ai_fallback_preset` repair on delete | Persistence / settings | update |
| `preset_hourly_usage` pruning | Persistence | add |
| quota atomic reserve + token-aware failure count | AI/LLM Provider (llm_services) | update |
| `admin_plans.py` escaping | Plans | update |
| `resolve_api_key` logging + encryption-at-rest | AI/LLM Provider | update (F2) |
| F1 builtin seed/ref removal | Persistence / AI Config | remove (own PR) |
| R17 activate→preferred + drop flat-key copy | Persistence / AI Config / AI-LLM Provider | update |
| R16 `reasoning_effort` column + passthrough | Persistence / AI-LLM Provider / AI Config | add |

Wiring-integrity (`tests/test_wiring.py`) + dead-code-guard (`tests/test_dead_code_guard.py`) required for every callback/schema change.

## Phases (per-phase plan files in this folder)

| Phase | Plan file | Rules | Depends on |
|-------|-----------|-------|------------|
| 1 | `plan-ai-preset-audit-fixes-phase-01-cosmetic.md` | R6,R8,R9,R15 | — |
| 2 | `plan-ai-preset-audit-fixes-phase-02-db-correctness.md` | R1,R2,R10,R12,R13,R14 | R2 before R14 |
| 3 | `plan-ai-preset-audit-fixes-phase-03-handlers-ux.md` | R3,R4,R5,R7 | Phase 2 (R14), Phase 1 (R8) |
| 4 | `plan-ai-preset-audit-fixes-phase-04-builtin-removal.md` | F1 | Phase 2 |
| 5 | `plan-ai-preset-audit-fixes-phase-05-secure-keys.md` | R11,F2 | Phase 2, Phase 4 |
| 6 | `plan-ai-preset-audit-fixes-phase-06-activation-preferred.md` | R17 | Phase 2,4,5 |
| 7 | `plan-ai-preset-audit-fixes-phase-07-reasoning-effort.md` | R16 (#241) | Phase 5, Phase 2 (R14) |

## Independent review
Each behavioral phase requires `hamzaboon-reviewer` sign-off before commit (AGENTS.md §5).

## Blocked Questions
- None. All rules locked 2026-08-12; owner confirmed "locked". R16 added per GitHub #241; R17 added per owner's active/preferred semantics.
