---
name: persian-formatting
description: Enforce centralized MarkdownV2 escaping for Persian + English mixed strings — all dynamic values from AI, DB, or user input MUST pass through services/utils/formatting.py before interpolation into MarkdownV2 templates in bot.py. Prevents "Bad Request: can't parse entities" errors. Load when adding/modifying user-facing messages, formatting helpers, or AI output rendering.
license: MIT
compatibility: opencode
metadata:
  category: formatting
  gate: user-facing-text
---
# Persian MarkdownV2 Formatting Skill

## When to load
- Adding/modifying any learner-facing message in `bot.py`
- Changing `services/utils/formatting.py`
- Rendering AI output or DB content to user
- Any string interpolation into MarkdownV2 templates

## Escaping Contract (AGENTS.md §3 Localization & Escaping Rules)

### The Rule
**Every dynamic value** originating from AI, database, or user input MUST be passed through the centralized escaping function in `services/utils/formatting.py` before interpolation into any MarkdownV2 template string in `bot.py`.

### Never do this:
```python
# WRONG - raw dynamic value concatenated
await msg.reply_text(f"Word: {word}")  # word from AI/DB/user
```

### Always do this:
```python
# CORRECT - escaped via formatting.py
from services.utils.formatting import escape_md
await msg.reply_text(f"Word: {escape_md(word)}")
```

### Exception (must be documented in code comment at call site):
- Value is already known to be pre-escaped
- Value is a static, hardcoded literal

## Special Characters Requiring Escaping (MarkdownV2)
`_`, `*`, `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`, `|`, `{`, `}`, `.`, `!`

## RTL + LTR Mixing
Telegram MarkdownV2 is brittle when mixing RTL (Persian) and LTR (English, code, variables, numbers). Rigorous escaping prevents:
- `Bad Request: can't parse entities` API errors
- Broken formatting
- Injected markdown parsing attacks

## Centralized Interface
All escaping logic lives in `services/utils/formatting.py` behind stable functions:
- `escape_md(text: str) -> str` — main escaping function
- `format_card(...)` — learner-facing card formatting (uses escaping internally)
- `format_review_card(...)` — review card formatting
- Any new formatting helpers must use `escape_md` internally

## Testing
- Unit tests in `tests/test_formatting.py` must cover Persian + English mixed strings
- Integration tests must assert no unescaped dynamic values in handler outputs
- `tests/test_wiring.py` checks for direct concatenation patterns (heuristic)

## Notes
- All learner-facing text MUST be in correct, natural Persian (no machine-translated/placeholder English)
- Escaping applies to: AI output, DB content (saved words, user prefs), user input, config values rendered to user
- Static strings in code (keyboard labels, hardcoded messages) don't need escaping if they contain no special chars