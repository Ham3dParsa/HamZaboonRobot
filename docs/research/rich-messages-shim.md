# Rich Messages — shim vs native (now / later / works / not)

**Official:** `core.telegram.org/bots/api#inputrichmessage` · `Rich Message Formatting Options`
**PTB native (upcoming):** PR #5263 — `InputRichMessage(html|markdown|blocks, is_rtl, skip_entity_detection, media)` + `Bot.send_rich_message` / `send_rich_message_draft`

**Shim owner:** `services/telegram_rich.py` — the ONLY place calling `sendRichMessage` / `editMessageText(rich_message=)`. All callers go through `services/send_pretty.py:send`/`say` with `Backend.RICH`.

## What the shim sends (now)

`rich_message: { markdown, is_rtl, skip_entity_detection }` via `bot.do_api_request`. `RICH_ENABLED=False` by default; 404 latch (`_rich_disabled`) disables after first probe.

## NOT sent — tracked as Later

`html`, `blocks` (Bot API 10.2 `InputRichBlock*`), `media` array, `sendRichMessageDraft` (streaming). Not needed for HamZaban.

## Limits (official)

32768 UTF-8 chars, 500 blocks, 16 nesting levels, 50 media attachments, 20 table columns.

## Matrix

| Area | Official | Our status | Use for HamZaban |
|---|---|---|---|
| Bold, Italic, Code inline, Link, Spoiler `||`, Quote `>`, Heading `#`, Table `| |`, List/TaskList, Details `<details>`, Math `$`/`$$`, CustomEmoji | RichText* / RichBlock* | **Works** | core cards/sessions |
| Underline `__`, Strikethrough `~~`, Marked `==` | RichTextUnderline/Strikethrough/Marked | **Works** (Phase 01) | grammar emphasis, highlight alt |
| Spoiler in table cell | `<tg-spoiler>` in HTML | **Works** via `TgSpoiler` span (no `Raw` needed) | hidden translations in table |
| Pre block (`<pre>`) | RichBlockPreformatted | **Later** — inline `Code` suffices | code examples only |
| `is_rtl` per-message, `skip_entity_detection` | InputRichMessage fields | **Works** (per-cell via BiDi workaround `\u202A`/`\u202B`) | Persian/English mixing |
| `html` / `blocks` / `media` / `sendRichMessageDraft` | InputRichMessage.html/blocks/media | **Later** | maps/collage/slideshow not needed |

Notes:
- Table cells can contain only inline formatting; `|` inside a cell breaks the table.
- Markdown is not parsed inside block HTML tags except `<details>`, `<tg-collage>`, `<tg-slideshow>`.
- `Table` header alignment and `is_bordered`/`is_striped` not yet exposed.

## Migration to native PTB (3 steps)

1. Upgrade to PTB ≥ version that includes PR #5263 (`InputRichMessage`).
2. Replace `services/telegram_rich.py:send_rich_message` body: `bot.do_api_request("sendRichMessage", {rich_message:{markdown,...}})` → `bot.send_rich_message(InputRichMessage(markdown=..., is_rtl=..., skip_entity_detection=...))`; same for `edit_rich_message` → `bot.edit_message_text(rich_message=...)`; drop `_rich_disabled` latch if PTB handles it.
3. If `html`/`blocks`/`media` needed, add `Backend.BLOCKS` and a blocks renderer; keep `Raw` as escape hatch.
