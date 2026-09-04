---
name: plan-preset-panel-ux
description: Preset panel UX polish — 2-col keyboard, name icon, view stats, feedback wording, impact notes, wizard alignment
created: 2026-09-04
base_commit: 1b4bb00fe5b34fec728a18b59ec5a886a89fdd4f
branch: feat/preset-panel-ux
status: in-progress
---
STATE: phase 0/4 — status: in-progress — focus: T7 keyboard layout

## CONTRACT LOCK TEMPLATE (self-locked — owner delegated 2026-09-04: "هرچی خودت میدونی ... قفل کن")

Rule #U1 — Edit keyboard 2-col pairing (owner: buttons stacked ugly, pair related).
Option Chosen: pair related fields 2-per-row; API Key solo full-width (security prominence);
detach solo (conditional); full-edit solo; [save|discard], [cancel|close] pairs.
Pairs: [Base URL|Model], [API Key], [Batch|Concurrency], [RPM|Timeout],
[Temperature|Max Tokens], [TPM|Daily Req], [Input Cost|Output Cost],
[Priority|In Fallback], [Emergency|Reasoning], [Name|Group Label].
Alternatives Rejected: all-solo (current ugly); auto-chunk pairs (splits related fields across rows when list changes).
Trade-offs: ~half the scroll; paired buttons narrower (labels already short; 64-byte callback limit untouched — only TEXT changes, callback_data byte-identical → no wiring change).
Owner Confirmation: delegated self-lock ("قفل کن").
GATE STATUS: LOCKED

Rule #U2 — Name button icon 🆔 (owner: "نام پریست" mid-list without icon; 🤖 belongs to Model).
Option Chosen: IBTN_FIELD_NAME = "🆔 نام پریست". Dirty guard (startswith "✏️") keeps working: dirty → "✏️ 🆔 نام پریست".
Alternatives Rejected: ✏️ static (indistinguishable, just fixed); 🤖 reuse (collides with Model).
Owner Confirmation: delegated self-lock.
GATE STATUS: LOCKED

Rule #U3 — Preset view usage stats (owner: view has empty button slot).
Option Chosen: append usage-stats lines to _show_ai_preset_view message from existing registry getters (preset_hourly_usage / llm_requests counters — implementer greps cheapest source; no new tables/queries-per-render beyond one cheap read).
Alternatives Rejected: new stats button (adds navigation for read-only info); new table (overkill).
Owner Confirmation: delegated self-lock.
GATE STATUS: LOCKED

Rule #U4 — Feedback + notes package (synthesis of Teams A/B/C; owner: decide yourself).
Option Chosen: (a) delete dead notify_callback toast (Team A); (b) reword just_staged to «پیش‌نویس "label" نگه داشته شد — هنوز ذخیره نشده» + pending count line (Team C; "ثبت شد" lies); (c) notes: keep 🎯/⛓️, add separate 🚨 for is_emergency + 🔑 for api_key dirty (Team C risk argument; fixed order 🎯→🔑→⛓️→🚨, confirm dialog only); (d) emoji stem docs note (all teams).
Alternatives Rejected: uniform toast composer (Team B — over-engineering for a dead path); is_emergency inside ⛓️ (hides bigger blast radius); "registered, no save needed" wording (false).
Owner Confirmation: delegated self-lock.
GATE STATUS: LOCKED

Rule #U5 — Wizard summary alignment (Teams B+C agree; A dissents on cost).
Option Chosen: route _show_wizard_summary through FieldDiff + render_diffs/build_confirm_message with numbered=False (preserves unnumbered look, same shape family); presets wizard only, plans later. Old bullet loop route-deleted same PR.
Alternatives Rejected: leave divergent (third dialect forever); numbered=True (changes wizard look unnecessarily).
Owner Confirmation: delegated self-lock.
GATE STATUS: LOCKED

<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE> — satisfied via delegated self-lock.

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | none new (TEXT/layout only) | keep |
| Router branches | none | keep |
| Keyboard builders | ai_preset_edit_keyboard (rows pair up) | update |
| Keyboard constants | IBTN_FIELD_NAME 🆔; stems | update |
| DB | read-only usage getters | keep |
| Handler functions | _edit_ai_preset, _show_ai_preset_view, _handle_ai_preset_field_input, _confirm_save_preset notes, _show_wizard_summary | update |
| Tests | keyboard layout tests, view tests, notes tests, wizard tests | add/update |
| Docs | emoji note in phase-03 file | update |

Seams: #12 Telegram UI → AI Config. No overlap (prior claim released post-merge).
Callback impact: TEXT-only → no new wiring test; test_wiring must stay green.

## Tickets

- T7: `plan-preset-panel-ux-phase-07-keyboard.md` — U1+U2.
- T8: `plan-preset-panel-ux-phase-08-view-stats.md` — U3.
- T9: `plan-preset-panel-ux-phase-09-feedback-notes.md` — U4.
- T10: `plan-preset-panel-ux-phase-10-wizard.md` — U5.
