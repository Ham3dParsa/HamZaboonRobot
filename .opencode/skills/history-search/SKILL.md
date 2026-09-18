---
name: history-search
description: Search local OpenCode conversation history (zero tokens) when past discussions, decisions, or context are needed. Use when the owner asks about earlier talks, an agent hits unknown context, or before work that may repeat settled decisions.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  gate: pre-work
  author: Ham3dParsa
  author_url: https://github.com/Ham3dParsa
---
# History Search

The local opencode SQLite store holds hundreds of past sessions. Query it with the repo script before claiming anything about earlier discussions — recall accuracy matters (a prior incident involved an agent claiming unread talks).

## Scope

Fire on these branches only:

- the owner asks about past discussions, decisions, or what was said when
- an agent hits context it does not have (unknown names, numbers, prior verdicts)
- a pre-work recall sweep before repeating or contradicting earlier work

Out of scope: never a substitute for reading repo docs, `ROADMAP.md`, or GitHub issues first; never queries the live bot DB (script is read-only on the opencode store); never a source of code truth — verify against the repo.

## Steps

### 1. Normalize keywords

Persian normalize before running: each positional arg is one term, a quoted multi-word arg is an exact phrase. Default is AND (part must contain all terms); `--any` for OR. Prefer 2+ distinctive terms over one short one (short substrings over-match).

### 2. Run the script

```powershell
python scripts/search_opencode_history.py "کشینگ معنایی" --limit 8
python scripts/search_opencode_history.py --any کش ویس --limit 5
python scripts/search_opencode_history.py "عبارت دقیق" --since 2026-09-01
python scripts/search_opencode_history.py "عبارت" --exclude-session ses_XXXX
```

Project auto-detects from cwd (`--project <sub>` to override, `--all-projects` to skip). Text parts only by default (`--include-tools` to also match tool/reasoning blobs). Score = hits × 30/(30+age_days); title match adds +3. `--out <file>` writes utf-8-sig.

### 3. Read snippets, escalate only if needed

Snippets decide relevance. Escalate to a full part read (sqlite query on that `session_id`) only when snippets prove the session is the right one but lack the detail. Quote the session id prefix (`ses_XXXX`) when citing.

## Completion

All of these hold: repo docs/issues were checked first; the script ran with stated terms and mode; cited claims name the session id; no statement about past talks rests on memory alone.
