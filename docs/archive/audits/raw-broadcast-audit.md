# REF1-T3 — Raw / raw_rich broadcast audit (REPORT-ONLY, no .py diff)

- Ticket: REF1-T3. Scope is read-only analysis. No production `.py` was changed.
- Base: `origin/main` at `7d8d2dd` (`ref(ai): extract json_codec leaf with ai alias (#652)`).
- Date (UTC): 2026-09-12.
- Fast-track note: docs-only audit report; no behavioral change, so the full
  Contract Lock Gate is skipped per the AGENTS.md fast-track exception.

## 1. Method

- Read `services/send_pretty.py` (`Raw` class, `raw_rich`, `_render_plain`,
  `_render_rich`, `_render_mdv2`, `_render_html`, `send()`/`say()` RICH fallback,
  `RawFormat` vs `Raw` distinction).
- Read `handlers/admin.py` broadcast chain (`_handle_admin_broadcast`,
  `broadcast_confirm`) and `handlers/admin_users.py` DM confirm as a comparator.
- Searched all prod `.py` (`services/`, `handlers/`, `bot.py`, `config/`) for
  `Raw\(`, `raw_rich`, and `\bRaw\b`. Test/tool hits are listed separately and
  are NOT counted as prod call sites.

## 2. (a) Prod Raw / raw_rich inventory

| # | Location | What it is | Is it a call site? |
|---|----------|------------|--------------------|
| P1 | `services/send_pretty.py:468-473` | `class Raw(Span)` definition + docstring ("Rich-only: renders the text as-is; other backends degrade it to plain text") | No — definition |
| P2 | `services/send_pretty.py:538-540` | `def raw_rich(text: str) -> Span: return Raw(text)` factory | No — definition |
| P3 | `services/send_pretty.py:842-843` | `_render_rich` `Raw` branch: `parts.append(span.text)` (verbatim, no escaping) | No — renderer branch |
| P4 | `services/send_pretty.py:777-778` | `_render_plain` `Raw` branch: `parts.append(span.text)` (verbatim = plain-text degradation) | No — renderer branch |
| P5 | `services/send_pretty.py:637-672` (`_render_mdv2`), `:675-716` (`_render_html`) | No `Raw` branch; a `Raw` span raises `TypeError("Unsupported span type …")` | No — intentional loud failure |
| P6 | `services/send_pretty.py:761` / `:809-810` | `_render_plain` `Plain` branch (verbatim append) / `_render_rich` `Plain` branch (`_escape_rich(span.text)`) | No — leaf-escape points, not `Raw` |
| P7 | `services/send_pretty.py:988-995` (`send`), `:1039-1044` (`say`), `:1126-1130` (second send path) | RICH path: try `render(MDV2)`, on `TypeError` degrade to `escape_mdv2(render(PLAIN))` | No — degradation path for all Rich-only spans (`Heading`, `Table`, `Details`, `Math`, `Raw`) |
| P8 | `services/send_pretty.py:99,115` | `__all__` exports `"Raw"`, `"raw_rich"` | No — export |
| P9 | `services/send_pretty.py:304-313` (`RawFormat`), `:931-954` (`_resolve_content`), `:957-1010` (`send`), `:1013+` (`say`) | `RawFormat.HTML/PLAIN/MDV2` string path (`raw=` param). Distinct from the `Raw` span | No — separate mechanism; broadcast uses this one, not `Raw` spans |

**Prod instantiation count: zero.** No `Raw(...)` or `raw_rich(...)` call exists
in `services/`, `handlers/`, `bot.py`, or `config/` outside the definitions and
renderer branches above.

Non-prod hits (documented for completeness, NOT prod):

| # | Location | Nature |
|---|----------|--------|
| N1 | `tests/test_send_pretty.py:151-158` | `test_raw_rich_span_verbatim`: static literal markup (`<details open>…<table>…`) asserted verbatim on RICH and PLAIN |
| N2 | `tools/send_pretty_research/test_bot_send_pretty.py:893` (import at `:100`) | `raw_rich(_collapsible_html_table(card))` in the `session_card_mockup` experiment only |
| N3 | `tools/send_pretty_research/send_pretty.py:66` | Re-export inside the research sandbox copy, not the prod module |

Broadcast chain (context, not `Raw` spans):

| # | Location | What it is |
|---|----------|------------|
| B1 | `handlers/admin.py:665-718` (`_handle_admin_broadcast`) | Captures `text_html` (`:694-702`), stores `pending_broadcast = {"text": msg, "html": html, "count": count}` (`:707`), renders preview (`:710-718`) |
| B2 | `handlers/admin.py:391-397` (`broadcast_confirm`) | `html = pending.get("html") or pending.get("text", "")`; `use_html = bool(html and html != text_val)`; `send_kwargs["parse_mode"] = ParseMode.HTML` when `use_html` |
| B3 | `handlers/admin.py:123-130` (context only) | `_broadcast_send_one`: per-user `_send_with_retry`, exception → log + `False` |
| B4 | `handlers/admin.py:398-405` (context only; ticket-cited `:398` cap line has drifted — `:398` is now the `Semaphore` line) | Bounded fan-out (`BROADCAST_MAX_CONCURRENCY`, 100-user chunks). Length cap lives at `:688` (`len(msg) > 4000` on the plain-text `msg`) |
| B5 | `handlers/admin_users.py:294-301` (comparator) | Same `html or text` / `parse_mode=HTML` pattern for 1:1 owner→user DM |

## 3. (b) Static-trusted vs dynamic-untrusted per site

- P1–P9 (all prod `Raw`/`raw_rich` sites): **not applicable — no caller.**
  Definitions and renderer branches are trust-neutral; a `Raw` span inherits
  whatever trust its (currently nonexistent) caller passes. The verbatim
  passthrough at P3/P4 is by design (Rich-only injection hatch).
- N1 (test): **static-trusted** — hardcoded literal, no interpolation.
- N2 (research prototype): **dynamic-untrusted pattern, sandboxed in `tools/`.**
  `_collapsible_html_table` (`test_bot_send_pretty.py:853-879`) interpolates
  `card["word"]`, `card["fa_meaning"]`, `card["examples"]`,
  `card["example_translations"]` (AI-generated dynamics) into raw HTML via
  `_b()` (`:866-869`) with no escaping. Never shipped; must not be copied into
  prod without an escaping/allowlist step.
- B1/B2 (broadcast): classified in §4, not via `Raw` spans.

## 4. (c) Can `admin.py:391-397` html carry unescaped dynamics?

**Yes — owner-supplied HTML only; no learner/AI/DB dynamics.**

- Provenance: `html` is `update.effective_message.text_html` (Telegram's
  HTML rendering of the owner's own typed message) with fallback `html = msg`
  (`admin.py:694-702`). `msg` is the owner's plain text (`text.strip()`).
- At the send site (`:391-397`) `send_text = html` is passed **verbatim** with
  `parse_mode=HTML` whenever `html != text_val` — i.e. whenever the owner used
  any formatting (bold/italic/link/etc.). Any tag the owner's client produced
  (or pasted) is forwarded as-is to every recipient.
- Preview (`:711`): `preview_text = f"…{html}…"` with static wrappers escaped
  via `html_escape` but `{html}` interpolated verbatim, sent with
  `raw=RawFormat.HTML` when `use_html` — same trust shape as the fan-out.
- What it does NOT carry: no third-party, learner, AI-output, or DB dynamics
  are concatenated at B1/B2. Trust boundary is the owner gate (`is_owner`),
  the `admin_broadcast` awaiting flow, and the `_BROADCAST_RUNNING` re-entry
  guard.
- Failure mode (factual, no change): malformed/overlong owner HTML is not
  validated or sanitized. Each per-user send fails independently as
  `BadRequest` inside `_broadcast_send_one` (`:123-130`) → logged, counted as
  unsent, remaining recipients still attempted. The `:688` length cap measures
  plain-text `msg`, not the expanded `html` (tag overhead uncounted).

## 5. (d) Recommended disposition per site

| Site | Recommendation | Justification |
|------|---------------|---------------|
| P1 `class Raw`, P2 `raw_rich` | **Keep as-is (reserved Rich-only hatch).** | Zero prod callers = zero current risk. Docstring already scopes it to Rich-only verbatim injection for shapes the span tree cannot express (HTML `<table>` inside `<details>`). Removing it would close the documented research path for no safety gain. |
| P3 `_render_rich Raw`, P4 `_render_plain Raw` | **Keep verbatim.** | Matches the class contract: RICH injects as-is; PLAIN degrades to plain text by appending as-is. Any escaping here would corrupt the intended Rich markup. |
| P5 MDV2/HTML `TypeError`, P7 RICH→MDV2→PLAIN fallback | **Keep loud-failure + escape-on-degrade.** | Correct fail-closed shape: Rich-only spans cannot silently emit broken MDV2; the fallback escapes degraded plain text so the MDV2 path cannot raise a parse error. No change. |
| P6 `:761`/`:809` leaf paths | **No change.** | `:761` (PLAIN `Plain`) is correctly verbatim; `:809` (RICH `Plain`) correctly routes through `_escape_rich`. They are the safe counterparts to the verbatim `Raw` branch, not a defect. |
| N1 test | **Keep.** | Pins the verbatim contract. |
| N2 research `raw_rich(_collapsible_html_table(card))` | **Keep in `tools/`; do NOT promote to prod without a new contract.** | Demonstrates exactly why `Raw` exists (table-in-details), but its unescaped AI-dynamic interpolation is unsafe as a prod pattern. Any future prod use needs its own LOCKED contract with escaping/allowlist rules. |
| B2 broadcast `html` + `parse_mode=HTML` | **Keep `RawFormat` string path; do NOT convert to `Raw` spans or generic span tree.** | Broadcast correctly bypasses the span tree (owner HTML preserved verbatim). Converting to spans would either strip owner formatting or require a new HTML→span parser — out of scope and higher risk. Optional hardening (HTML tag allowlist, expanded-length check) is **deferred**: needs its own contract lock if ever pursued; not recommended in this ticket. |

## 6. Line-number note

Ticket cites `send_pretty.py:761/:809` and `admin.py:123-130/:398`. At base
`7d8d2dd`, `:761` is the `_render_plain` `Plain` branch, `:809-810` the
`_render_rich` `Plain` branch (both leaf-escape points, neither a `Raw`
branch); `admin.py:123-130` is `_broadcast_send_one`; `:398` is the broadcast
`Semaphore` line (the 4000-char cap is at `:688`). Content matches; only line
offsets drifted.

## 7. What was deliberately NOT changed

- No `.py` file touched (verified: `git status --porcelain` in the worktree
  shows only this report as untracked).
- No `Raw`/`raw_rich`/broadcast/preview logic altered, added, or removed.
- Open follow-ups (not actioned): none required by this ticket. A future
  broadcast-hardening proposal (tag allowlist / expanded-length accounting)
  would need a separate contract lock.
