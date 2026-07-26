# SRS Session Engine v3 — Pull-Based Simulation

A pure-Python offline simulator for the **pull-based** SRS review engine.
Unlike v1 (push-based), v3 only generates AI cards when review sessions
have room AFTER due cards and query backlog are handled. This eliminates
backlog choking and reduces AI costs.

## Philosophy

| v1 (Push) | v3 (Pull) |
|-----------|-----------|
| Forces new cards into backlog daily | Only generates AI cards when slots are empty |
| Backlog ceiling (50) blocks entries | No ceiling — backlog grows but doesn't block |
| Overflow session as relief valve | No overflow needed — pull design prevents choking |
| AI budget is fully consumed | AI budget used only on demand (cost savings) |

## Quick Start

```bash
# Interactive mode
python -m tools.srs_simulation_v2

# Direct mode
python -m tools.srs_simulation_v2 --plan free --days 30 --seed 42
python -m tools.srs_simulation_v2 --plan gold --days 90 --seed 7 --csv gold_v2.csv
```

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--plan` | free | `free`, `silver`, or `gold` |
| `--days` | 30 | Simulation duration |
| `--ai-daily-cap` | *plan default* | Max AI-generated cards/day (free=3, silver=8, gold=12) |
| `--query-daily-cap` | *plan default* | Word queries/day (free=3, silver=10, gold=14) |
| `--query-save-prob` | 0.5 | Chance a query saves to backlog |
| `--sessions` | *plan default* | Review sessions/day (free=1, silver=3, gold=5) |
| `--session-size` | *plan default* | Cards/session (free=4, silver=6, gold=6) |
| `--fail-prob` | 0.15 | Chance user clicks "Again" |
| `--seed` | None | Random seed for repeatability |
| `--report-every` | 5 | Print table every N days |
| `--csv` | None | Export to CSV |

## Plan Defaults

| Plan | Sessions | Slot/ session | Total slots | AI cap | Query cap |
|------|----------|--------------|-------------|--------|-----------|
| Free | 1 | 4 | 4 | 3 | 3 |
| Silver | 3 | 6 | 18 | 8 | 10 |
| Gold | 5 | 6 | 30 | 12 | 14 |

## How It Works

Each day:
1. **Queries**: User makes `query-daily-cap` queries. Saved ones enter `query_backlog`.
2. **Slot filling** (bulk, `sessions × session_size` total):
   - **Priority 1 (Due cards)**: Overdue graduated cards first
   - **Priority 2 (Query backlog)**: FIFO from saved queries
   - **Priority 3 (AI generation)**: New AI cards, up to daily cap
   - Remaining slots (if all sources empty) = session runs smaller

## Metrics

- **DueRem**: Due cards that couldn't fit (should be near zero)
- **QBacklog**: Pending saved queries waiting for a session slot
- **AIGen**: AI cards actually generated today (vs AICap)
- **Active**: Total active cards in the SRS loop

## Examples

```bash
# Compare all three
python -m tools.srs_simulation_v2 --plan free   --days 30 --seed 42
python -m tools.srs_simulation_v2 --plan silver --days 30 --seed 42
python -m tools.srs_simulation_v2 --plan gold   --days 30 --seed 42

# What if user does more sessions?
python -m tools.srs_simulation_v2 --plan free --sessions 2 --days 60

# Higher fail rate impact
python -m tools.srs_simulation_v2 --plan silver --fail-prob 0.3 --days 30 --seed 42
```
