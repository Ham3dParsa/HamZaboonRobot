# send_pretty_research

A **self-contained research sandbox** for the `send_pretty` deep outbound-message
module (R3) — the single owner of the outbound parse standard, escaping, retry,
concurrency slots, and the edit-vs-send decision.

This folder is an isolated, standalone copy used for experimentation. It does
**not** link to or modify the real root `bot.py`, `config/`, `services/`, or
`handlers/` files. It bundles minimal stubs (`bot.py`, `db.py`, `config/`,
`helpers.py`, `formatting.py`, `callback_notifications.py`) plus the research
`send_pretty.py` so the span-rendering engine can be explored in isolation.

## Contents

- `send_pretty.py` — the span-tree engine (`Backend`, `RawFormat`, spans, renderers).
- `test_bot_send_pretty.py` — an interactive demo / preview bot that renders each
  span/backend combination and a set of render assertions.
- `bot.py`, `db.py`, `config/`, `helpers.py`, `formatting.py`,
  `callback_notifications.py` — minimal local stubs so the sandbox is runnable
  on its own, decoupled from the real application modules.

## Run the demo

```bash
python test_bot_send_pretty.py preview
```

## Relationship to the merged work

The real `services/send_pretty.py` is the production deep module, already merged
on `main`. This folder persists a research copy of that work so the exploration
is not lost. It is related to (but separate from) the production module and
should remain under `tools/`.