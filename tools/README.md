# HamZaban Utility Tools

This directory contains utility scripts for managing, inspecting, and generating data for the HamZaban bot.

## Available Tools

### 1. `generate_cards.py`
A CLI tool to generate new vocabulary cards using the bot's production LLM logic and insert them directly into the database.

**Features:**
- Uses the same `prompts.py` and `ai.py` validation logic as the live Telegram bot.
- Supports language, goal, and level customization based on `catalog.py`.
- **Safety First:** Defaults to `dry-run` mode (does not insert into DB).
- Built-in validation ensures generated cards match the required schema.

**Usage:**
```bash
# Preview a new card (Dry run - default)
python tools/generate_cards.py --lang en --goal general --level beginner

# Generate and insert into the database
python tools/generate_cards.py --lang en --goal general --level beginner --no-dry-run
```

### 2. `inspect_outputs.py`
A diagnostic tool to inspect and validate existing vocabulary cards stored in the `daily_cards` database table.

**Features:**
- Configurable output limits.
- Supports randomization of results.
- Keyword filtering within the raw card JSON (searches across all content).

**Usage:**
```bash
# View the 5 most recent cards
python tools/inspect_outputs.py --limit 5

# View 3 random cards
python tools/inspect_outputs.py --limit 3 --random

# Search for cards containing a specific keyword
python tools/inspect_outputs.py --filter "Beautiful"
```
*Note: Currently, it is not possible to filter by language, goal, or level, as this metadata is not stored in the database alongside the card content.*

---
*Note: Always ensure you have a backup of `hamzaban.db` before performing operations that modify the database.*
