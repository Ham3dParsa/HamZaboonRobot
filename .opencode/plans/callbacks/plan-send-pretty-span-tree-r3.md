---
name: plan-send-pretty-span-tree-r3
description: Deep outbound-message module send_pretty (R3) — recursive span tree, single parse-standard owner, fixes *bold*/<b> parsing bugs
created: 2026-08-17
base_commit: 1583a0a
branch: refactor/send-pretty
status: in-progress
---

STATE: LOCKED + owner scope decision — status: in-progress — execution model: per-ticket
commits on the branch (spec-to-tickets), each independently reviewed via the Kilo PR loop;
`_edit_or_send` kept as a thin adapter routing through `say()` (owner Option A); its deletion
deferred to a dedicated cleanup PR. T8 (admin_ai screens, seam 12) HELD for j-B2 merge.

## Progress
- T1 DONE (c787742) — services/send_pretty.py span tree + renderers + 20 unit tests.
- T2 DONE (b21d77e) — _telegram_slots guard test in tests/test_wiring.py.
- T3 DONE (2d4ebab) — _edit_or_send → thin adapter routing through say().
- T4 DONE (ede4d20) — user.py onboarding span fixes + test_integration/test_onboarding_span.py.
- T5 DONE (a435189) — help_command span tokenizer (_render_help_template/_help_spans/_help_guillemets).
- T6 PENDING — learner renderer Message factories. **DEFERRED by owner (2026-08-17): follow-up PR.**
- T7 PENDING — 13 direct bypass sites. **DEFERRED by owner (2026-08-17): follow-up PR.**
- **THIS PR = T1–T5 only** (owner confirmed 2026-08-17: "Defer T6+T7").
- T8 NOT IN THIS PR — admin_ai screens (seam 12), held for j-B2.

## Scope (locked contract — R3) — ticket-based execution
- **Execution model (owner 2026-08-17):** decompose the full deep-module leap into small
  per-task tickets (T1–T8), each a single commit on `refactor/send-pretty`. Create the PR
  after a group of tickets; after each meaningful commit wait for the Kilo comment delta
  (sleep loop: 90s timer, 15m timeout) and address before the next commit; rebase onto
  `origin/main` after each push so a changed j-B2/unblock state is always visible. Loop until
  Kilo says merge.
- **Ticket map (each = one commit, small + independently reviewable):**
  - T1 — `services/send_pretty.py` span tree + renderers (MDV2/HTML/PLAIN) + pure unit tests. (new file; no seam conflict)
  - T2 — Guard test: only `send_pretty` imports `_telegram_slots` outside itself. (tests/test_wiring.py)
  - T3 — `_edit_or_send` → thin adapter routing through `say()` (83 call sites untouched). (services/utils/helpers.py)
  - T4 — user.py `*bold*`/`@@@` fixes → span `Message`. (handlers/user.py, seam 7)
  - T5 — help_command `@@BOT@@`/`@@START@@` + `_apply_bold` → span `Message`. (handlers/help_command.py, seam 16)
  - T6 — format_card/format_srs_* → `Message` factories (return Message, keep signatures). (services/utils/formatting.py)
  - T7 — 13 direct bypass sites → `send(...)`/`say(...)` (study_handler/srs_handler/admin.py/admin_plans.py, seams 5/6/8/10).
  - T8 — **admin_ai.py screens → spans (seam 12). HELD: conflicts with j-B2; run as a separate follow-up PR after j-B2 merges. NOT in this PR.**
- **PR grouping (owner):** create the PR after a group of tickets (at my discretion); do not
  wait for all of T1–T7 to be done before opening it.
- **Anti-divergence with j-B2:** j-B2 (`refactor/preset-field-registry`) owns seams 12
  (`handlers/admin_ai.py`) + 2 (`services/ai/ai.py`). R3 (T1–T7) stays within seams
  5/6/7/8/10/15/16 + helpers/formatting — no file overlap with j-B2. T8 (seam 12) is
  excluded here and sequenced after j-B2.
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
- **OWNER DECISION (2026-08-17, Option A):** `_edit_or_send` is NOT deleted in this PR.
  It has 83 call sites across 7 files — far beyond this PR's migration list. Instead it
  becomes a thin adapter that internally routes through `say(...)`, so the deep module owns
  parse-standard/retry/slots while callers are untouched. Full deletion is deferred to a
  dedicated cleanup PR (recorded out-of-scope here).

## Migration plan (ticket-aligned — each item = one commit)
- **T1** — Add `services/send_pretty.py` (span tree + `send`/`say`/`raw` + MDV2/HTML/PLAIN
  render) + pure unit tests (render both backends + nesting + escape correctness).
- **T2** — Guard test: only `send_pretty` imports `_telegram_slots` outside itself
  (tests/test_wiring.py or new tests/test_send_pretty.py).
- **T3** — Convert `_edit_or_send` into a thin adapter routing through `say(...)`; keep
  signature so the 83 call sites are untouched (services/utils/helpers.py). Deletion deferred.
- **T4** — Onboarding `*bold*` fixes: `user.py:143-144` (cmd_start welcome), `user.py:159-160`
  (on_lang_selected), `user.py:196-198` (`@@@` dance deleted) → span `Message` with `bold(...)`.
- **T5** — help_command.py: `@@BOT@@`/`@@START@@` + `_apply_bold` deleted → span `Message`
  with `bold(...)`/`plain(...)`/`code("/start")` (handlers/help_command.py).
- **T6** — Rebuild learner renderers `format_card` / `format_srs_front_stage` /
  `format_srs_back_stage` (services/utils/formatting.py) as `Message` factories (return
  `Message`, keep signatures); migrate bot.py / study_handler.py / srs_handler.py callers.
- **T7** — Direct bypass sites (13) in study_handler / srs_handler / admin.py / admin_plans.py →
  `send(...)`/`say(...)`, routing them back onto the retry/slot seam.
- **T8 — NOT IN THIS PR.** admin_ai.py (~30 HTML screens, seam 12) → spans. HELD for j-B2
  merge; separate follow-up PR. Admin screens keep working unchanged via the `_edit_or_send`
  adapter (raw="html") until then.

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