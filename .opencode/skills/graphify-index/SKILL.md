---
name: graphify-index
description: Build and query the HamZaban code knowledge graph with the graphify CLI — local AST extraction (tree-sitter, no API key), then query/path/explain against graphify-out/graph.json instead of grepping raw files. Load when searching for symbol relationships, tracing callers/callees across modules, or reducing context reads.
license: MIT
compatibility: opencode
metadata:
  category: indexing
  tool: graphifyy
author: Ham3dParsa
author_url: https://github.com/Ham3dParsa
---
# Graphify Index Skill

## When to load
- Tracing callers/callees across `bot.py`, `services/`, `handlers/`, `config/`
- Answering structural questions ("what connects X to Y?") without reading full modules
- Reducing context-read overhead in large refactors (e.g., SRS, delivery, callbacks)
- Updating the graph after code changes

## Install (one-time)
```bash
uv tool install graphifyy
# (uv is required; graphifyy[ sql ] adds SQL grammar)
```

## Build / Update
```bash
# Full AST index (code-only, no API key, fully local)
graphify . --code-only

# Incremental re-extract after code changes (offline, no LLM)
graphify update .

# Cluster + name communities (requires LLM backend for labels; optional)
graphify cluster-only .
```

## Query (no LLM cost — pure graph traversal)
```bash
graphify query "how does the review callback route to the SRS handler?"   # BFS, default 2000-token budget
graphify query "..." --budget 1000
graphify path "SymbolA" "SymbolB"      # shortest path between two nodes
graphify explain "Symbol"              # plain-language node + neighbors
graphify affected "function"           # reverse traversal (needs clustered build)
```

## Repo-specific usage
- Graph output: `graphify-out/graph.json` (gitignored)
- `.graphify_analysis.json` written alongside
- **After meaningful code changes**, run `graphify update .` before structural queries
- SQL grammar (`graphifyy[sql]`) optional — repo SQL is migration files only

## Token-savings guidance
Prefer `graphify query "..."` over reading entire modules (e.g., `bot.py` is 1,362 lines) when the question is structural. Reserve `read`/`grep` for symbol-level details the graph can't answer (exact logic, escaping, literals).

## Revert
- Uninstall: `uv tool uninstall graphifyy`
- Graph artifacts are gitignored; remove `graphify-out/` to clean disk
