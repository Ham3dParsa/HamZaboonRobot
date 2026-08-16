---
name: plan-send-pretty-span-tree-r3
description: Deep outbound-message module send_pretty (R3) — recursive span tree, single parse-standard owner, fixes *bold*/<b> parsing bugs
created: 2026-08-17
base_commit: 9c822ce
branch: (pending — R3 runs after R2)
status: locked-design
---

STATE: design-it-twice LOCKED — status: locked-design — focus: recursive span tree chosen; implementation deferred until R2 merges

## Scope (locked contract — R3)
- **R3**: new deep module `services/send_pretty.py` — the single owner of outbound-message
  parse-standard, escaping, retry, concurrency slots, and edit/send decision. It replaces
  the current dispersion: 3 parse standards (MarkdownV2 / HTML / none), ~50 call sites that
  each hand-pick `ParseMode`, the `@@@` / `@@BOT@@` / `@@START@@` sentinels, and 13 direct
  `context.bot.*` bypass sites that skip `_telegram_slots`.
- Owner directive (2026-08-17): set all rules per `/codebase-design` + audits — deeper
  modules, no code divergence, no dispersion in public modules, no god modules.
- **Design chosen (design-it-twice, owner): "Recursive span tree"** — every span can nest
  other spans (bold can hold spoiler, quote holds bold), so nested formatting is supported
  and a future native-Markdown/"richmessages" standard is a one-module swap.

## The bugs being fixed (root causes, confirmed)
1. **`*bold*` shown as plain in /start** — `handlers/user.py:143-144` authors `*هم‌زبان*`
   (intending bold) then `escape_mdv2(welcome_text)` escapes the `*` (it's a MarkdownV2
   special char), so Telegram renders literal asterisks, not bold. Same at `user.py:159-160`.
   Root cause: markup authored in a string, then a whole-string escape destroys it.
2. **`<b></b>` shown as plain** — HTML parse mode used in admin (`admin_ai.py`, `admin.py`)
   while learner code uses MarkdownV2; dozens of `reply_text`/`send_message` pass no parse
   mode at all (e.g. `admin.py:322`, `admin_ai.py:2168`). No single standard.
3. Ad-hoc escape hacks: `@@@` (user.py:196-198), `@@BOT@@`/`@@START@@` sentinels +
   `_apply_bold` guillemets (help_command.py).

## Locked design (recursive span tree)
Module: `services/send_pretty.py` (a peer of `services/utils/helpers.py` — a domain-owning
module, consistent with semantic-centralization; NOT inside services/utils/).

Content vocabulary (pure value types, no Telegram, no side effects) — spans are recursive
so any span can contain other spans or a plain string leaf:
- Span types: `Plain`, `Bold`, `Italic`, `Code`, `Spoiler`, `Link`, `Quote`, `Newline`.
- Builder helpers: `plain(x)`, `bold(*children)`, `italic(*children)`, `code(x)`,
  `spoiler(*children)`, `link(url, *children)`, `quote(*children)`, `nl()`.
- Value type: `Message` — a list of lines; `line(*spans)`, `keyboard(kb)`, `render(backend)`.
- Nesting example: `bold("واژه", code("/start"), spoiler("پنهان"))`; `quote(bold("نکته"), ...)`.

Delivery verbs (the only Telegram-touching seam):
- `send(chat_id, content, *, bot, keyboard=None, raw=None) -> Message | None` — new message.
- `say(update, context, content, *, mode="auto"|"edit"|"send", keyboard=None, raw=None)` —
  edit-vs-send decision; `mode="auto"` edits when a callback is present, else sends.
- `raw=` escape hatch for legacy strings — MUST declare its format ("html"/"mdv2"/"plain")
  or raise; no "AUTO guess" (caller can never ask the module to guess).

Render/backend:
- Module holds a `Backend` enum internally (MDV2 / HTML / PLAIN / future RICH), selected by
  config/availability. `Message.render(backend)` walks the span tree.
- Escaping is scoped to the *content of each leaf*; markup is emitted by the renderer around
  the structure — never by the caller. So `*`-loss, sentinels, and unescaped dynamic values
  become structurally impossible. A malformed tree fails at construction, not runtime.
- Future native-Markdown/"richmessages": render the same tree to native Markdown or Telegram
  entities by adding `Backend.RICH` + a renderer clause; zero caller changes.

Internal wiring (composes existing helpers, preserves the retry/slots seam):
- Composes `services/utils/helpers.py` `_send_with_retry` / `_edit_with_retry` /
  `_telegram_slots` and `services/utils/formatting.py` `escape_mdv2` / `escape_mdv2_code` /
  `html_escape`. Does NOT reuse `_edit_or_send` (it bypasses retry/slots).
- BadRequest fallback ("message is not modified" / "not found") reuses the existing
  edit-then-fall-back-to-send semantics.
- `_edit_or_send` becomes provably dead after migration → deleted (bounded cleanup).

## Migration plan
1. Add `services/send_pretty.py` + tests (pure `render` unit tests for both backends +
   nesting; mock tests asserting retry/slots/fallback; guard test that only `send_pretty`
   imports `_telegram_slots`).
2. Rebuild learner renderers `format_card` / `format_srs_front_stage` / `format_srs_back_stage`
   (services/utils/formatting.py) as `Message` factories (return `Message`, keep signatures) —
   instantly migrates bot.py, study_handler.py, srs_handler.py.
3. Admin HTML cluster: rewrite ~30 static screens as `Message` (`html_escape(x)` → `plain(x)`/
   `bold(x)`/`code(x)`); one-off templates use the `raw="html"` on-ramp.
4. Onboarding `*bold*` fixes: `user.py:143-144`, `user.py:159-160`, `user.py:196-198`
   (`@@@` dance deleted) → `bold(lang_name)` etc.
5. help_command.py: `@@BOT@@`/`@@START@@` + `_apply_bold` deleted → `Message` with
   `bold(...)`/`plain(...)`/`code("/start")`.
6. Direct bypass sites (13) in study_handler / srs_handler / admin.py / admin_plans.py →
   `send(...)`/`say(...)`, routing them back onto the retry/slot seam.
7. Delete `_edit_or_send` after zero references (grep-verified).
8. Add guard test: `tests/test_wiring.py` (or new `tests/test_send_pretty.py`) asserting
   only `send_pretty` imports `_telegram_slots` outside itself.

## Dependencies / module-change guard
- New module `services/send_pretty.py` → update AGENTS.md §3 responsibilities table +
  `tests/test_wiring.py` scan targets + `.opencode/skills/parallel-work-guard/SEAMS.md`.
- Seams touched: 5 (study), 6 (srs), 8 (admin), 10 (plans), 15 (callback_notifications),
  16 (help), plus the helpers.py/formatting.py seam.

## Sequencing (owner: two separate serial PRs)
- **R2 first** (`handlers/flows.py` awaiting registry — `refactor/awaiting-flows`, in progress).
- **R3 second** (this plan) — new worktree after R2 merges; fresh contract-lock not needed
  (already LOCKED here), but acquire the R3 parallel-work claim at start.

## Blocked Questions
- [2026-08-17] Module location: owner chose a dedicated deep module; final file path
  `services/send_pretty.py` (peer of helpers.py) — confirmed in the lock. If any doubt,
  revisit at R3 start.