# SRS v2.8 Simulation Tool

A pure-Python offline simulator for the SRS session-based review engine,
allowing product owners to test different plan caps, backlog limits, and
user-behavior scenarios **before** locking product numbers.

## Quick Start

```bash
# Interactive mode — walks you through all parameters
python -m tools.srs_simulation

# Direct mode — all flags at once
python -m tools.srs_simulation --plan free --days 30 --seed 42 --csv results.csv
```

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--plan` | free | `free`, `silver`, or `gold` |
| `--days` | 30 | Number of simulation days |
| `--daily-cards` | *plan default* | New cards per day (free=3, silver=8, gold=12) |
| `--word-query-cap` | *plan default* | Word queries per day (free=3, silver=10, gold=14) |
| `--word-query-save-prob` | 0.5 | Probability a query becomes saved word |
| `--session-cap` | *plan default* | Review sessions per day (free=1, silver=4, gold=10) |
| `--session-size` | 5 | Cards per session |
| `--backlog-ceiling` | 50 | Max pre-graduation backlog cards |
| `--fail-review-prob` | 0.15 | Probability a review is "Again" (vs "Remembered") |
| `--overflow-session-threshold` | None | If backlog exceeds this, trigger overflow session |
| `--seed` | None | Random seed for repeatable runs |
| `--report-every` | 5 | Print table every N days (0 = final only) |
| `--csv` | None | Export results to CSV |

## Examples

### Compare all three plans with the same seed

```bash
python -m tools.srs_simulation --plan free   --days 30 --seed 42
python -m tools.srs_simulation --plan silver --days 30 --seed 42
python -m tools.srs_simulation --plan gold   --days 30 --seed 42
```

### Test what happens if users save words more aggressively

```bash
python -m tools.srs_simulation --plan free --word-query-save-prob 0.8 --days 60
```

### Test overflow relief mechanism

```bash
python -m tools.srs_simulation --plan free --days 60 --overflow-session-threshold 30
```

### Full 90-day simulation with CSV export

```bash
python -m tools.srs_simulation --plan gold --days 90 --seed 7 --csv gold_90d.csv
```

## Understanding the Output

| Column | Meaning |
|--------|---------|
| **Day** | Simulation day (0-indexed) |
| **Backlog** | Pre-graduation queue size (idx=-1) |
| **DueProc** | Due cards processed today |
| **DueCarry** | Due cards NOT processed (carried over) |
| **Grad** | Total graduated cards (idx >= 0) |
| **Rej** | New cards rejected due to full backlog |
| **Ovrflw** | Overflow session triggered? |

### Summary metrics

- **Average backlog (last 7 days)** — how full the queue stays in steady state
- **Max carry streak** — longest consecutive days with carry-over
- **Days with rejection (%)** — how often backlog ceiling blocks new cards
- **Overflow sessions triggered** — how often the relief valve activated

## How the Simulation Works

Each day:

1. **New cards** are added to the pre-graduation backlog (up to ceiling)
2. **Word queries** may add more cards to backlog (based on save probability)
3. **Review sessions** process up to `session_cap × session_size` cards:
   - Priority 1: overdue graduated cards (most overdue first)
   - Priority 2: fill remaining slots from backlog (FIFO)
4. **Overflow session** (optional): if backlog exceeds threshold, one extra session from backlog only

### Review outcomes per card

- **Backlog first interaction** → graduates to `idx=0, next_review=today+1`
- **Graduated + Remembered** → advance interval index: `[1, 3, 7, 16, 30]` day gaps
- **Graduated + Again** → reset to `idx=0, next_review=today+1`
