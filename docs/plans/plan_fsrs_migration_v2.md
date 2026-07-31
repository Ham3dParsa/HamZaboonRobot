# FSRS-6 Migration Plan v2 — Architecture-Locked, Modular Implementation

**Status:** ✅ Architecture locked — ready for Phase 0 implementation
**Cutover strategy:** Atomic (bot is OFF; all changes land in one deployment)
**References:**
- `docs/FSRS_v6.md` — Complete FSRS-6 algorithm reference
- `services/fsrs_core.py` — Existing pure FSRS-6 engine (needs Phase 0.0 completion)
- `gap_analysis.md` — Pre-plan code audit (generated 2026-07-31)
- Consultant: Claude (architecture review, July 2026)

---

## Table of Contents

- [0. Locked Architecture Decisions](#0-locked-architecture-decisions)
- [1. Gap Analysis Summary](#1-gap-analysis-summary)
- [2. Execution Phases](#2-execution-phases)
  - [Phase 0: Pre-Flight (Independent)](#phase-0-pre-flight)
  - [Phase 1a: Database Layer](#phase-1a-database-layer)
  - [Phase 1b: Keyboards](#phase-1b-keyboards)
  - [Phase 1c: Core Engine + Grade Policy](#phase-1c-core-engine--grade-policy)
  - [Phase 1d: SRS Handler](#phase-1d-srs-handler)
  - [Phase 1e: Session Scheduling + Study Handler](#phase-1e-session-scheduling--study-handler)
  - [Phase 1f: bot.py Integration](#phase-1f-botpy-integration)
  - [Phase 1g: Tests](#phase-1g-tests)
  - [Phase 2: Cleanup](#phase-2-cleanup)
- [3. Collision Points (Atomic Cutover)](#3-collision-points-atomic-cutover)
- [4. Final File Structure](#4-final-file-structure)
- [5. Owner Decision Log](#5-owner-decision-log)
- [6. Rollback Appendix](#6-rollback-appendix)

---

## 0. Locked Architecture Decisions

These decisions were confirmed via external architecture consultant (Claude) and approved by the project owner. Each is locked — no implementation should deviate from them.

### 0.1 Module Structure

```
services/
├── fsrs_core.py           # Pure DSR math functions (unchanged structure + Phase 0.0 additions)
├── session/
│   ├── __init__.py        # Public API: build_session(), SessionNode
│   ├── assembly.py        # 3-tier priority session generator (internal)
│   └── grade_policy.py    # GradePolicy, GRADE_POLICIES, ACTIVITY_REGISTRY, get_interaction_ui()
├── scheduling.py          # Standalone: daily budget, session quotas (separate from session engine)
├── db/
│   ├── __init__.py        # Connection/re-export (thin)
│   ├── schema.py          # CREATE TABLE, migrations
│   ├── users.py           # User CRUD
│   ├── reviews.py         # review_events CRUD
│   └── words.py           # saved_words CRUD + SRS-specific functions
```

**Rationale (consultant):** "Keep responsibilities aligned with module boundaries — a bug in scheduling should never require touching the algorithm." Session engine becomes a package because Phase 4 (interactive flows) adds real complexity; grade_policy is a distinct concern from session assembly.

### 0.2 Algorithm Interface — Functions, Not Class

`fsrs_core.py` exports pure module-level functions. No stateful class.

```python
@dataclass(frozen=True)
class FSRSConfig:
    w: MappingProxyType                       # w0-w20 dict (immutable via MappingProxyType)
    first_exposure_stability: MappingProxyType  # {1: 0.212, 2: 1.5, 3: 3.0, 4: 12.0}
    desired_retention: float = 0.9
    maximum_interval: int = 365               # Cap against absurd multi-year intervals
    enable_short_term: bool = False
    name: str = "default"                     # Self-identifying for Phase 6 config comparison

DEFAULT_FSRS_CONFIG = FSRSConfig(...)

def compute_retrievability(elapsed_days, stability, config=DEFAULT_FSRS_CONFIG) -> float
def compute_interval(stability, retention=0.9, config=DEFAULT_FSRS_CONFIG) -> float
def initial_stability(grade, config=DEFAULT_FSRS_CONFIG) -> float
def initial_stability_first_exposure(grade, config=DEFAULT_FSRS_CONFIG) -> float  # NEW wrapper
def initial_difficulty(grade, config=DEFAULT_FSRS_CONFIG) -> float
def update_difficulty(d, grade, config=DEFAULT_FSRS_CONFIG) -> float
def update_stability(d, s, r, grade, config=DEFAULT_FSRS_CONFIG) -> float
def short_term_stability(s, grade, config=DEFAULT_FSRS_CONFIG) -> float
```

**Rationale (consultant):** "A class buys you nothing since there's no meaningful internal state — it's just namespacing, which a module already gives you for free. Pass a config object into the functions rather than wrapping them in a class."

### 0.3 First Exposure — Separate Wrapper Function

`initial_stability_first_exposure(grade)` is a standalone function, **not** a `first_exposure=True` boolean flag on `initial_stability()`.

**Rationale (consultant):** "A bare `first_exposure=True` flag threaded through multiple functions tends to metastasize into `if first_exposure` branches scattered across the algorithm layer. A thin wrapper function keeps the branch in one spot."

### 0.4 Session Assembly — Generator Internally, List Externally

`build_session()` is implemented as a generator internally (for testability of tier logic), but the Telegram handler materialises Tiers 1+2 into a plain list stored in `context.user_data['session_nodes']`. Tier 3 (AI generation) is a separate `generate_tier3_node()` function called only when Tiers 1+2 are exhausted.

**Rationale (consultant):** "Materialize Tier 1+2 eagerly — they're cheap DB queries. Tier 3 becomes a refill function, not a live generator. This gets you the laziness you wanted (never call AI unless user is still engaged) without persisting a generator object across handler invocations."

### 0.5 Keyboard in ActivityHandler, Not Handler Layer

```python
ACTIVITY_REGISTRY = {
    "srs_review": ActivityHandler(
        grade_policy=..., 
        get_interaction_ui=get_srs_review_ui,  # (node: SessionNode) → (text, keyboard)
    ),
    "first_exposure": ActivityHandler(
        grade_policy=..., 
        get_interaction_ui=get_first_exposure_ui,
    ),
}
```

`get_interaction_ui(node)` returns a complete `(str, InlineKeyboardMarkup | None)` tuple with fully-formed callback data strings. The Telegram handler's job: get node → dispatch to registry → send `(text, keyboard)` → done. No callback-data inspection in the generic handler.

**Rationale (consultant):** "If keyboard selection lives in the Telegram handler, you'll end up with an `if activity_type == ...` chain that duplicates the dispatch you already built in the registry."

### 0.6 Data Layer Split

`services/db/` is split into `__init__.py` (connection), `schema.py`, `users.py`, `reviews.py`, `words.py` **before** any FSRS behavioral changes are made. This is a pure file-splitting refactor with zero behavior change.

**Rationale (consultant):** "The highest-value, lowest-risk refactor on your list — pure file-splitting with no behavior change, and it'll make the FSRS migration diffs much easier to review."

### 0.7 Data Migration — Keep Words, Reset SRS State

Saved word records (word text, translation, card_data) are preserved. Only SRS scheduling fields are reset:
- `stability = 0.0`
- `difficulty = 5.0`
- `first_exposure_done = 0`
- `next_review = <today>` (so words appear as "due immediately")
- `interval_idx = DROPPED` (not kept as a rollback column)

**Rationale (owner + consultant):** With 10 test users and the bot off, writing a lossy `interval_idx → stability` migration function is effort that preserves nothing meaningful (difficulty was never tracked). A clean reset is safer, simpler, and the correct approach pre-production.

### 0.8 review_events — Store Raw Signal

```sql
grade_source TEXT     -- 'direct_button' | 'right_wrong' | 'ai_judgment'
raw_signal TEXT       -- JSON: {"button_value": 3} or {"ai_raw_score": 0.85}
```

**Rationale (consultant):** "Phase 6 (parameter optimization) will want to re-derive grades under different policies without re-running AI judging, so store the raw signal, not just the final grade."

### 0.9 Import Compatibility

No backward-compat shim. All import sites are updated directly. `services/srs_engine.py` is deleted outright when `services/session/` is created.

**Rationale (consultant):** "A backward-compat shim earns its keep when you have external consumers or a slow rollout. You have neither. Grep-and-replace the import sites."

### 0.10 Session Engine is Frontend-Agnostic

`SessionNode`, `GradePolicy`, `ACTIVITY_REGISTRY` — all deal only in plain data (dataclasses/dicts). No `telegram.Update`, no `InlineKeyboardMarkup` in the engine layer. Future Mini App/WebApp just wraps the same session engine calls.

**Rationale (consultant):** "Building actual REST endpoints or auth now, before you have a concrete Mini App requirement, is speculative work against a future that may look different."

### 0.11 Interactive Flow State is Handler-Land

Multi-step flow state (quiz progression, sentence-writing partial results) lives in `context.user_data['current_flow']`, entirely in the Telegram handler layer. The session engine never owns or inspects it.

**Rationale (consultant):** "Interactive flow state is presentation/interaction state, not scheduling state — it doesn't need to survive a session engine restart."

---

## 1. Gap Analysis Summary

Per the comprehensive gap analysis (`gap_analysis.md`), the following files are affected. Section references link to the gap analysis for line-level detail.

### 1.1 services/fsrs_core.py (106 lines, existing)

| Component | Status | Action |
|---|---|---|
| `DSR_W` constants | ✅ Complete | No change |
| `FIRST_EXPOSURE_STABILITY` constant | ❌ Missing | Add in Phase 0.0 |
| `FSRSConfig` dataclass | ❌ Missing | Add in Phase 0.0 |
| `initial_stability()` | ⚠️ Exists | Add `config` parameter; no breaking change |
| `initial_stability_first_exposure()` | ❌ Missing | Add wrapper in Phase 0.0 |
| All other DSR functions | ✅ Complete | Add optional `config` parameter only |
| Short-term formula | ⚠️ Gated | Keep `enable_short_term=False` default |
| 31 unit tests | ✅ Passing | Add tests for new functions in Phase 1g |

### 1.2 services/db/ (1985 lines, monolithic → split)

| Function | Line (current) | Status | Action |
|---|---|---|---|
| `add_saved_word()` | 1248 | **REWRITE** | FSRS initial state, no `interval_idx` |
| `update_saved_word_fields()` | 1291 | Stays | No change |
| `due_words_for_user()` | 1326 | **REWRITE** | FSRS ordering + exclude `first_exposure_done=0` |
| `get_saved_word()` | 1349 | Stays | No change |
| `advance_word_review()` | 1359 | **DELETE** | Replaced by `grade_word_review(grade=3)` |
| `defer_word_review()` | 1377 | **DELETE** | Replaced by `grade_word_review(grade=1)` |
| `record_review_event()` | 1393 | **MODIFY** | Add `grade`, `activity_type`, `grade_source`, `raw_signal` params |
| `touch_streak()` | 553 | Stays | No change |
| `migrate_saved_words_to_fsrs()` | — | **ADD** | Reset SRS fields, drop `interval_idx` |
| `grade_word_review()` | — | **ADD** | Replaces advance/defer |
| `grade_first_exposure()` | — | **ADD** | First-exposure wrapper |
| `get_pre_first_exposure_words()` | — | **ADD** | Tier 2 for session engine |
| `INTERVALS_DAYS` constant | 25 | **DELETE** | Replaced by FSRS |
| `REVIEW_OUTCOMES` | 1390 | **MODIFY** | Expand for first-exposure |

Schema changes:
- `saved_words`: Add `stability REAL DEFAULT 0.0`, `difficulty REAL DEFAULT 5.0`, `first_exposure_done INTEGER DEFAULT 0`; **drop** `interval_idx` (in migration, not as rollback)
- `review_events`: Add `grade INTEGER`, `activity_type TEXT DEFAULT 'srs_review'`, `grade_source TEXT DEFAULT 'direct_button'`, `raw_signal TEXT`, `response_time_ms INTEGER`

### 1.3 config/keyboards.py (883 lines)

| Component | Line | Status | Action |
|---|---|---|---|
| `IBTN_REMEMBERED` | 48 | **DELETE** | Replaced by 4-grade buttons |
| `IBTN_REVEAL` | 49 | Stays | No change |
| `IBTN_CONFIRM_CORRECT` | 50 | **DELETE** | Replaced by grade buttons |
| `IBTN_REMIND_AGAIN` | 51 | **DELETE** | Replaced by grade buttons |
| `IBTN_SRS_AGAIN/HARD/GOOD/EASY` | — | **ADD** | Review 4-grade labels |
| `IBTN_FE_AGAIN/HARD/GOOD/EASY` | — | **ADD** | First-exposure familiarity labels |
| `srs_hidden_keyboard()` | 401 | **REWRITE** | 4-grade + reveal |
| `srs_revealed_keyboard()` | 429 | **REWRITE** | 4-grade + translations |
| `srs_review_keyboard()` | 464 | **REWRITE** | 4-grade |
| `srs_first_exposure_keyboard()` | — | **ADD** | First-exposure 4-grade |

### 1.4 handlers/srs_handler.py (286 lines)

| Function | Line | Status | Action |
|---|---|---|---|
| `_handle_srs_review()` | 86 | **REWRITE** | Accept `grade: int` (1-4), call `db.grade_word_review()` |
| `_handle_srs_reveal()` | 138 | **MODIFY** | Show 4-button keyboard after reveal |
| `_handle_srs_prepare()` | 205 | **MODIFY** | Show 4-button keyboard |
| `_handle_first_exposure_grade()` | — | **ADD** | Grade first encounter |

Callback patterns (old → new):

| Old | New | Status |
|---|---|---|
| `srs:remember:{uid}:{wid}` | `srs:3:{uid}:{wid}` | Replace |
| `srs:confirm:{uid}:{wid}` | `srs:3:{uid}:{wid}` | Replace |
| `srs:again:{uid}:{wid}` | `srs:1:{uid}:{wid}` | Replace |
| — (new) | `srs:2:{uid}:{wid}` | Add |
| — (new) | `srs:4:{uid}:{wid}` | Add |
| — (new) | `srs:fe:{grade}:{uid}:{wid}` | Add |
| `srs:reveal:{uid}:{wid}` | Keep | No change |
| `srs:prepare:{uid}:{wid}` | Keep | No change |

### 1.5 services/srs_engine.py → services/session/ (91 lines → new package)

| Current | Status | Target |
|---|---|---|
| `ACTIVITY_REGISTRY` (empty) | **EXPAND** | `session/grade_policy.py` |
| `register_activity()` | **KEEP** | `session/grade_policy.py` |
| `SessionNode` | **MODIFY** | `session/__init__.py` — add `grade_policy_ref`, `interaction_schema` |
| `generate_v3_session()` | **REWRITE** | `session/assembly.py` — 3-tier generator + Tier-3 refill |
| GradePolicy framework | **ADD** | `session/grade_policy.py` — dataclass, registry, `resolve_grade()` |
| File itself | **DELETE** | Replaced by `services/session/` package |

### 1.6 services/scheduling.py — CREATE (new file)

Does not exist. Must be created with:
- `daily_session_budget(user_id, plan) → dict` — timezone-aware slot budget
- `consume_session_slot(user_id) → bool` — atomic slot consumption
- `release_session_slot(user_id)` — rollback on error
- `PLAN_SESSION_CONFIG` constants

### 1.7 handlers/study_handler.py (44 lines, stub → rewrite)

| Function | Status | Action |
|---|---|---|
| `handle_study_start()` | **REWRITE** | Call `generate_v3_session()`, check quota, present first card, manage in-place editing | 

### 1.8 handlers/user.py (789 lines)

| Function | Line | Status | Action |
|---|---|---|---|
| `show_status()` | 464 | **MODIFY** | Internal `due_words_for_user()` changes |
| `start_srs_review()` | 499 | **MODIFY** | Uses new 4-button `srs_hidden_keyboard` |

### 1.9 bot.py (1314 lines)

| Route | Line | Status | Action |
|---|---|---|---|
| `srs:prepare:` | 1086-1091 | **MODIFY** | Handler changes internally; routing stays |
| `srs:reveal:` | 1092-1097 | **MODIFY** | Handler changes internally; routing stays |
| `srs:fe:` | — | **ADD** | New route before catch-all |
| `srs:` (catch-all) | 1098-1103 | **REWRITE** | Parse grade from `parts[1]`, route to `_handle_srs_review(grade=int(...))` |
| Old patterns | N/A | **None** | Bot is off; no legacy patterns exist in flight |

Import changes:
- Add `from handlers.srs_handler import _handle_first_exposure_grade`
- No backward-compat shim imports

### 1.10 services/utils/formatting.py (119 lines)

| Symbol | Status | Action |
|---|---|---|
| `SRS_HIDDEN_INSTRUCTION` | **MODIFY** | Update text to mention 4-grade buttons |
| `format_srs_prompt()` | Stays | No change |
| `format_card()` | Stays | No change |

### 1.11 services/utils/helpers.py (229 lines)

**No changes.** Zero SRS-specific logic.

### 1.12 config/catalog.py

**No changes.** Zero SRS-specific content.

### 1.13 Test Files

| File | Status | Action |
|---|---|---|
| `tests/test_fsrs_core.py` (31 tests, existing) | **MODIFY** | Add `initial_stability_first_exposure()` tests + `FSRSConfig` injection tests |
| `tests/test_keyboards.py` | **REWRITE** | Assert 4-grade callback patterns |
| `tests/test_srs_staged_reveal.py` | **REWRITE** | Test integer grade values, remove old string patterns |
| `tests/test_custom_word_query.py` | **MODIFY** | Update callback pattern assertions |
| `tests/test_reliability.py` | **MODIFY** | Replace `advance_word_review()`/`defer_word_review()` tests with `grade_word_review()` tests |
| `tests/test_wiring.py` | **VERIFY** | Auto-scan will detect new patterns; update `ALLOWLIST` if needed |
| **NEW:** `tests/test_integration/test_srs_callback_routing.py` | **ADD** | End-to-end callback dispatch test |

---

## 2. Execution Phases

All changes are grouped into ordered phases. Within each phase, items can be done in any order unless a dependency is noted.

**Progress tracking format:** Each item is a checklist entry. During implementation, the commit hash or PR number is added next to each item.

---

### Phase 0: Pre-Flight (Independent)

**Dependency:** None — these can be done first and independently of all other changes.

| # | File | Change | Verifiable Acceptance |
|---|---|---|---|
| 0.1 | `services/fsrs_core.py` | Add `FSRSConfig` dataclass with `frozen=True`, `MappingProxyType` for dict fields, `maximum_interval`, `name` | `FSRSConfig(w={**DSR_W, 'w3': 20.0})` produces different interval output than default; `cfg.w['w3'] = X` raises `TypeError` |
| 0.2 | `services/fsrs_core.py` | Add `FIRST_EXPOSURE_STABILITY` as `MappingProxyType({1: 0.212, 2: 1.5, 3: 3.0, 4: 12.0})` | `FIRST_EXPOSURE_STABILITY[1] == 0.212` by unit test |
| 0.3 | `services/fsrs_core.py` | Add `initial_stability_first_exposure(grade, config=DEFAULT_FSRS_CONFIG)` wrapper | Returns `config.first_exposure_stability[grade]` for all 4 grades |
| 0.4 | `services/fsrs_core.py` | All 7 existing functions accept optional `config: FSRSConfig = DEFAULT_FSRS_CONFIG` | Existing 31 tests pass with no code change; new test verifies config injection produces expected variation |
| 0.5 | `services/utils/formatting.py` | Update `SRS_HIDDEN_INSTRUCTION` text to reference 4-grade buttons | Persian text reads naturally; no MarkdownV2 escaping errors |
| 0.6 | `services/scheduling.py` | **CREATE** with `PLAN_SESSION_CONFIG`, `daily_session_budget()`, `consume_session_slot()`, `release_session_slot()` | `daily_session_budget(test_user, "silver")` returns correct slot counts for today |
| 0.7 | `docs/FSRS_v6.md` | **VERIFY** — cross-check `compute_retrievability()` and `compute_interval()` against corrected §2.1 and §2.8 formulas (commit 304b2a8). Both functions confirmed matching: no `/9` in code, correct `factor = 0.9^(-1/w20) - 1`, correct `I = S · (r^(-1/w20) - 1) / factor`. | Running `compute_retrievability(S=30, t=30)` returns ≈0.9; `compute_interval(S=30, r=0.9)` returns ≈30 |

**Phase 0 commit:** `[` ☑ `]`

---

### Phase 1a: Database Layer (Split + Schema)

**Dependency:** Phase 0.1–0.4 (FSRSConfig exists).

**Before any behavioral change:** Split monolithic `services/db/__init__.py` into submodules.

| # | File | Change | Verifiable Acceptance |
|---|---|---|---|
| 1a.1 | `services/db/__init__.py` | Thin to connection + re-export from submodules | All existing imports (`from services.db import ...`) continue to work unchanged |
| 1a.2 | `services/db/schema.py` | **CREATE** — move `init_db()`, `CREATE TABLE` statements, migration logic here | Fresh `init_db()` creates all tables; `review_events` has `grade`, `activity_type`, `grade_source`, `raw_signal`, `response_time_ms` columns |
| 1a.3 | `services/db/words.py` | **CREATE** — move `add_saved_word()`, `get_saved_word()`, `get_pre_first_exposure_words()`, `due_words_for_user()`, `update_saved_word_fields()`, `grade_word_review()`, `grade_first_exposure()`, `migrate_saved_words_to_fsrs()` | All functions importable from `services.db.words` |
| 1a.4 | `services/db/reviews.py` | **CREATE** — move `record_review_event()` | Accepts `grade`, `activity_type`, `grade_source`, `raw_signal`, `response_time_ms` params |
| 1a.5 | `services/db/users.py` | **CREATE** — move user CRUD functions | No functional change |
| 1a.6 | `services/db/__init__.py` | Implement `migrate_saved_words_to_fsrs()` — reset SRS fields, drop `interval_idx` | Run against snapshot of all 10 test users' data; output diffed against expected reset state (`stability=0.0, difficulty=5.0, first_exposure_done=0, next_review=<today>`) |
| 1a.7 | `services/db/words.py` | Rewrite `add_saved_word()` — write FSRS initial state (no `interval_idx`) | `INSERT` produces row with `stability=0.0, difficulty=5.0, first_exposure_done=0, next_review=NULL` |
| 1a.8 | `services/db/words.py` | Rewrite `due_words_for_user()` — FSRS ordering, exclude `first_exposure_done=0` | Due list sorted by `compute_retrievability()` ascending; pre-first-exposure words excluded |
| 1a.9 | `services/db/words.py` | Add `grade_word_review()` — apply FSRS grade, update stability/difficulty/next_review | Existing word with `first_exposure_done=1` after `grade_word_review(id, uid, 3)` has `stability > 0.0` and `next_review > today` |
| 1a.10 | `services/db/words.py` | Add `grade_first_exposure()` — set initial S0/D0 from familiarity weights | First-exposure grade=4 produces `stability=12.0`; grade=1 forces `next_review = today + 1` |
| 1a.11 | `services/db/words.py` | Add `get_pre_first_exposure_words()` | Returns words with `first_exposure_done=0` ordered by `added_at ASC` |
| 1a.12 | `services/db/reviews.py` | Modify `record_review_event()` — accept `grade`, `activity_type`, `grade_source`, `raw_signal`, `response_time_ms` | Event with all new fields stores correctly; calling without new fields fills defaults |
| 1a.13 | `services/db/words.py` | Delete `advance_word_review()` and `defer_word_review()` | All callers updated to use `grade_word_review()`; grep confirms zero references remain |
| 1a.14 | `services/db/reviews.py` + docs | Document constraint: any future gamified activity type MUST use a distinct `activity_type` value (never reuse `srs_review`). This costs nothing now (no new column, no handler change) but prevents contaminated training data later. | Constraint stated in docstring at `record_review_event()` and in this plan's schema section; active grep verification not required until gamification is implemented |

**Phase 1a commit:** `[` ☑ `]`

---

### Phase 1b: Keyboards

**Dependency:** None — can happen concurrently with Phase 1a.

| # | File | Change | Verifiable Acceptance |
|---|---|---|---|
| 1b.1 | `config/keyboards.py` | Delete `IBTN_REMEMBERED`, `IBTN_CONFIRM_CORRECT`, `IBTN_REMIND_AGAIN` | Grep shows zero references to these symbols elsewhere |
| 1b.2 | `config/keyboards.py` | Add `IBTN_SRS_AGAIN/HARD/GOOD/EASY`, `IBTN_FE_AGAIN/HARD/GOOD/EASY` | All 8 constants present with correct Persian text and grade comments |
| 1b.3 | `config/keyboards.py` | Rewrite `srs_hidden_keyboard()` — 4-grade + reveal | `srs_hidden_keyboard(123, 456)` returns 4 callbacks matching `srs:1:123:456` through `srs:4:123:456` + `srs:reveal:123:456` |
| 1b.4 | `config/keyboards.py` | Rewrite `srs_revealed_keyboard()` — 4-grade + translations | `srs_revealed_keyboard(123, 456)` returns same 4-grade pattern + `srs:prepare:123:456` |
| 1b.5 | `config/keyboards.py` | Rewrite `srs_review_keyboard()` — 4-grade | Same 4-grade pattern as hidden |
| 1b.6 | `config/keyboards.py` | Add `srs_first_exposure_keyboard()` — IBTN_FE_* labels, `srs:fe:{grade}:{uid}:{wid}` callbacks | `srs_first_exposure_keyboard(123, 456)` returns 4 callbacks matching `srs:fe:1:123:456` through `srs:fe:4:123:456` |

**Phase 1b commit:** `[` ☑ `]`

---

### Phase 1c: Core Engine + Grade Policy

**Dependency:** Phase 0 (FSRSConfig exists), Phase 1a (DB functions exist).

| # | File | Change | Verifiable Acceptance |
|---|---|---|---|
| 1c.1 | `services/session/grade_policy.py` | Add `GradePolicy` dataclass (`activity_type`, `grade_source`, `grade_mapping`, `description`) | `GradePolicy("srs_review", "direct_button", {1:1, 2:2, 3:3, 4:4}, "...")` instantiates |
| 1c.2 | `services/session/grade_policy.py` | Add `GRADE_POLICIES` registry dict with entries for `srs_review`, `first_exposure`, `new_ai_card`, `ai_quiz`, `sentence_write` | All 5 policies present; each has a valid `grade_mapping` |
| 1c.3 | `services/session/grade_policy.py` | Add `ACTIVITY_REGISTRY` with `ActivityHandler` (pairs `GradePolicy` with `render`/`get_interaction_ui` callable) | `ACTIVITY_REGISTRY["srs_review"].grade_policy.activity_type == "srs_review"` |
| 1c.4 | `services/session/grade_policy.py` | Add `resolve_grade(activity_type, source_value) → int` | `resolve_grade("ai_quiz", "correct") == 3`; `resolve_grade("srs_review", 2) == 2` |
| 1c.5 | `services/session/__init__.py` | Add `SessionNode` dataclass with `activity_type`, `source_tier`, `card_data`, `source_id`, `activity_meta`, `grade_policy_ref`, `interaction_schema` | All fields present, typed |
| 1c.6 | `services/session/assembly.py` | Implement `build_session()` as internal generator — 3-tier priority | Generator yields nodes in order: due SRS → first-exposure → new AI |
| 1c.7 | `services/session/assembly.py` | Implement `generate_tier3_node()` — lazy AI card generation | Called only after Tiers 1+2 exhausted; respects AI daily cap |
| 1c.8 | `services/session/assembly.py` | Materialize function: `build_session_list()` → materialises Tiers 1+2 into list, stores Tier-3 params for refill | Returns `(session_nodes: list, tier3_params: dict | None)` |
| 1c.9 | Delete `services/srs_engine.py` | Remove old scaffold | Grep confirms zero imports of `services.srs_engine` remain |

**Phase 1c commit:** `[` ☑ `]`

---

### Phase 1d: SRS Handler

**Dependency:** Phase 1b (keyboards), Phase 1c (grade_policy, session engine).

| # | File | Change | Verifiable Acceptance |
|---|---|---|---|
| 1d.1 | `handlers/srs_handler.py` | Rewrite `_handle_srs_review()` to accept `grade: int` (1-4), call `db.grade_word_review()`, call `db.record_review_event()` | Handler dispatches correctly for all 4 grades; review event recorded with matching `grade` and `activity_type='srs_review'` |
| 1d.2 | `handlers/srs_handler.py` | Add `_handle_first_exposure_grade()` — calls `db.grade_first_exposure()` + `db.record_review_event()` with `activity_type='first_exposure'` | First-exposure grading sets initial stability from `FIRST_EXPOSURE_STABILITY` weights |
| 1d.3 | `handlers/srs_handler.py` | Modify `_handle_srs_reveal()` — show `srs_revealed_keyboard` with 4-grade buttons | After reveal, keyboard shows 4 grade buttons + translations |
| 1d.4 | `handlers/srs_handler.py` | Modify `_handle_srs_prepare()` — show `srs_review_keyboard` with 4-grade buttons | Prepare action shows 4-grade keyboard |

**Phase 1d commit:** `[` ☑ `]`

---

### Phase 1e: Session Scheduling + Study Handler

**Dependency:** Phase 1c (session engine), Phase 0.6 (scheduling.py exists).

| # | File | Change | Verifiable Acceptance |
|---|---|---|---|
| 1e.1 | `handlers/study_handler.py` | Rewrite `handle_study_start()` — call `build_session_list()`, check session quota, present first card via `ACTIVITY_REGISTRY` dispatch | User with 0 sessions today gets a valid session; user at daily cap gets "همه کارت‌های امروز تموم شده!" |
| 1e.2 | `handlers/user.py` | Modify `start_srs_review()` — use new `srs_hidden_keyboard` with 4-grade buttons | Existing SRS review menu shows 4-grade keyboard |

**Phase 1e commit:** `[` ☑ `]`

---

### Phase 1f: bot.py Integration

**Dependency:** All of Phase 1a–1e (handlers, keyboards, engine, DB must all be ready).

| # | File | Change | Verifiable Acceptance |
|---|---|---|---|
| 1f.1 | `bot.py` | Add `srs:fe:` route before catch-all — dispatch to `_handle_first_exposure_grade()` | Callback `srs:fe:3:123:456` reaches first-exposure handler with grade=3 |
| 1f.2 | `bot.py` | Rewrite `srs:` catch-all route — parse `parts[1]` as integer grade, dispatch to `_handle_srs_review(grade=int(...))` | Callbacks `srs:1:123:456` through `srs:4:123:456` each reach review handler with correct grade |
| 1f.3 | `bot.py` | Update imports — add `_handle_first_exposure_grade` | Import succeeds; no unused import warnings |
| 1f.4 | `bot.py` | No legacy pattern handling (bot was off; no old keyboards exist) | Router rejects unknown patterns gracefully (no crash) |

**Phase 1f commit:** `[` ☑ `]`

---

### Phase 1g: Tests

**Dependency:** All of Phase 0–1f (test correctness depends on implementation being complete).

**Ordering:** These can be written concurrently with the phases they test, but must all pass before deployment.

| # | File | Change | Verifiable Acceptance |
|---|---|---|---|
| 1g.1 | `tests/test_fsrs_core.py` | Add tests for `FSRSConfig` injection, `initial_stability_first_exposure()`, `MappingProxyType` immutability guard | 4+ new tests passing |
| 1g.2 | `tests/test_keyboards.py` | Rewrite all SRS keyboard tests — assert 4-grade callback patterns (`srs:1:`–`srs:4:`, `srs:fe:1:`–`srs:fe:4:`) | All old patterns removed from test assertions |
| 1g.3 | `tests/test_srs_staged_reveal.py` | Rewrite handler flow tests — test integer grade values | All string-action tests replaced |
| 1g.4 | `tests/test_custom_word_query.py` | Update callback assertions to new patterns | Tests pass with new keyboard functions |
| 1g.5 | `tests/test_reliability.py` | Replace `advance_word_review()`/`defer_word_review()` tests with `grade_word_review()` tests | `grade_word_review()` with grade=1 produces same effect as old `defer_word_review()` |
| 1g.6 | `tests/test_wiring.py` | Verify ALLOWLIST includes new patterns; auto-scan detects all `srs:`-prefixed and `srs:fe:`-prefixed callbacks | Scan finds all 8 new callback patterns plus 2 staying patterns |
| 1g.7 | `tests/test_integration/test_srs_callback_routing.py` | **NEW** — construct mock `Update` with old-style callback (`srs:remember:123:456`) and new-style (`srs:3:123:456`); route through `callback_router`; assert correct handler / graceful rejection | Old pattern is silently handled (logged, no crash); new pattern dispatches to `_handle_srs_review` with `grade=3` |
| 1g.8 | `tests/test_integration/test_srs_callback_routing.py` | Schema migration test: run `migrate_saved_words_to_fsrs()` against temp DB with 10-user snapshot; assert all rows have `stability=0.0, difficulty=5.0, first_exposure_done=0, next_review=<today>` | No row has `interval_idx` column; no row has `NULL` next_review |
| 1g.9 | Full validation suite | Run `python -m unittest discover -s tests -v` + `ruff check --select F821,F811` + `python scripts/compile_all.py` + `git diff --check` | All new tests pass; no regressions; no whitespace errors |

**Phase 1g commit:** `[` ☑ `]`

---

### Phase 2: Cleanup

**Dependency:** Phase 1g tests pass; migration complete.

| # | File | Change | Verifiable Acceptance |
|---|---|---|---|
| 2.1 | `services/db/schema.py` | Remove one-time `migrate_saved_words_to_fsrs()` call from `init_db()` | `init_db()` no longer calls migration function (function itself may be kept or deleted) |
| 2.2 | (entire repo) | Final grep sweep: verify zero references to `INTERVALS_DAYS`, `interval_idx`, `IBTN_REMEMBERED`, `IBTN_CONFIRM_CORRECT`, `IBTN_REMIND_AGAIN`, `advance_word_review`, `defer_word_review` in production code | Only hits are in git history, archived docs, and `gap_analysis.md` |
| 2.3 | `docs/plans/plan_fsrs_migration.md` | Archive or replace with reference to v2 | Old plan marked as superseded |

**Phase 2 commit:** `[` ☑ `]`

---

## 3. Collision Points (Atomic Cutover)

**Context:** The bot is OFF for the entire migration. All changes land in one atomic deployment. There is no concurrent old/new system running, no partial rollout, no transitional window. No Telegram cached keyboards exist from a live deployment.

| # | Location | Theoretical Risk | Verdict | Plan Action |
|---|---|---|---|---|
| CP1 | `bot.py:1098` callback_router | Old patterns (`srs:remember:`) arrive after cutover | **No risk** — bot was off; no old patterns are in flight. If a test user taps a stale message from before the bot went dark, the pattern will not match any route and is silently ignored (logged, no crash). Acceptable for 10 test users. | Clean rewrite — no legacy branching. Add `logger.warning` for unrecognized patterns as a debugging aid. |
| CP2 | `saved_words` schema | `interval_idx` column still referenced by old code | **No risk** — `interval_idx` is dropped in the same migration that adds FSRS columns. Old code never runs after cutover. | Drop in migration; no rollback column. |
| CP3 | Telegram cached keyboards | Old inline keyboard buttons in user chat history | **No risk** — bot was off. Zero existing keyboards are in flight. If a user taps a 2-week-old message, it arrives as an unrecognized callback pattern (handled by CP1's graceful rejection). | No action needed. Documented here for reader clarity. |
| CP4 | `handlers/srs_handler.py:_handle_srs_review()` signature | Old callers pass `action: str` | **No risk** — all callers are updated atomically. | Clean rewrite to `grade: int`; no `Union` type, no `isinstance` branching. |
| CP5 | `review_events` schema | Old rows lack `grade` column | **No risk** — all old review events are reset (no data preserved). New columns added as part of initial schema. | Add columns normally; no NULL-handling needed in application code. |
| CP6 | `add_saved_word()` INSERT | Mixed old/new callers write different columns | **No risk** — all callers use the new function atomically. | Write FSRS columns only; no dual-write. |

**Stale-keyboard acceptance statement (CP3):** A test user may still have a message with old inline buttons in their Telegram history from before the bot was taken offline. If they tap such a button post-cutover, the callback arrives at the bot with an unrecognized pattern (e.g., `srs:remember:123:456`). The router's catch-all will log `WARNING: Unrecognized srs callback pattern: srs:remember:123:456` and `answer_callback_query` with a neutral acknowledgement. No crash, no data corruption. For 10 test users, this is an acceptable edge case.

---

## 4. Final File Structure

### 4.1 Created

| File | Purpose |
|---|---|
| `services/session/__init__.py` | Public API: `build_session()`, `build_session_list()`, `generate_tier3_node()`, `SessionNode` |
| `services/session/assembly.py` | 3-tier priority generator, Tier-3 refill function |
| `services/session/grade_policy.py` | `GradePolicy`, `GRADE_POLICIES`, `ACTIVITY_REGISTRY`, `resolve_grade()`, activity handler renderers |
| `services/scheduling.py` | `daily_session_budget()`, `consume_session_slot()`, `release_session_slot()`, `PLAN_SESSION_CONFIG` |
| `services/db/schema.py` | `init_db()`, `CREATE TABLE` statements, migration functions |
| `services/db/words.py` | `add_saved_word()`, `grade_word_review()`, `grade_first_exposure()`, `due_words_for_user()`, `get_pre_first_exposure_words()`, `get_saved_word()`, `migrate_saved_words_to_fsrs()` |
| `services/db/reviews.py` | `record_review_event()` |
| `services/db/users.py` | User CRUD functions |
| `tests/test_integration/test_srs_callback_routing.py` | End-to-end callback dispatch integration tests |

### 4.2 Modified

| File | Change |
|---|---|
| `services/fsrs_core.py` | Add `FSRSConfig`, `FIRST_EXPOSURE_STABILITY`, `initial_stability_first_exposure()`, `config` param on all functions |
| `services/db/__init__.py` | Thin to connection + re-export from submodules |
| `config/keyboards.py` | 3 old IBTN constants deleted, 8 new added; 3 keyboard functions rewritten, 1 new added |
| `handlers/srs_handler.py` | `_handle_srs_review()` rewritten, `_handle_first_exposure_grade()` added, `_handle_srs_reveal/prepare` modified |
| `handlers/study_handler.py` | `handle_study_start()` fully implemented |
| `handlers/user.py` | `show_status()`, `start_srs_review()` updated for new keyboard |
| `bot.py` | `srs:fe:` route added; `srs:` catch-all rewritten for integer grades; imports updated |
| `services/utils/formatting.py` | `SRS_HIDDEN_INSTRUCTION` text updated |
| `tests/test_fsrs_core.py` | New tests for FSRSConfig + first-exposure |
| `tests/test_keyboards.py` | Rewritten for 4-grade patterns |
| `tests/test_srs_staged_reveal.py` | Rewritten for integer grades |
| `tests/test_custom_word_query.py` | Updated callback assertions |
| `tests/test_reliability.py` | Updated for `grade_word_review()` |

### 4.3 Deleted

| File | Replaced By |
|---|---|
| `services/srs_engine.py` | `services/session/` package |

### 4.4 Unchanged (zero changes needed)

| File | Reason |
|---|---|
| `services/utils/helpers.py` | No SRS-specific logic |
| `config/catalog.py` | No SRS-specific content |
| `tests/test_wiring.py` | Auto-scan detects new patterns; ALLOWLIST verified in Phase 1g |

---

## 5. Owner Decision Log

| # | Decision | Choice | Date | Source |
|---|---|---|---|---|
| 1 | Short-term formula | Include + gated `enable_short_term=False` | 2026-07-28 | v1 plan |
| 2 | Desired retention default | 0.9 (FSRS-6 standard) | 2026-07-28 | v1 plan |
| 3 | Grade labels | 4-button: Again(1)/Hard(2)/Good(3)/Easy(4) | 2026-07-28 | v1 plan |
| 4 | Easy threshold | Included as "Easy" button — full 4-grade system | 2026-07-28 | v1 plan |
| 5 | Session priority | Tier 1 (due) → Tier 2 (pre-first-exposure) → Tier 3 (new AI) | 2026-07-28 | v1 plan |
| 6 | Migration scope | All three unified (daily cards + SRS + study sessions) | 2026-07-28 | v1 plan |
| 7 | Quiz fail → FSRS grade | Incorrect → grade 1 (Again) | 2026-07-28 | v1 plan |
| 8 | AI judgment → FSRS grade | AI maps directly to 1-4 | 2026-07-28 | v1 plan |
| 9 | Grade policy framework | Every activity type has GradePolicy + ACTIVITY_REGISTRY entry + test | 2026-07-28 | v1 plan |
| 10 | First-exposure grade=1 | 1-day forced interval (not FSRS-computed) | 2026-07-28 | v1 plan |
| 11 | Module boundary — Algorithm | `services/fsrs_core.py`: pure functions + `FSRSConfig`, no class | 2026-07-31 | Consultant |
| 12 | Module boundary — Session engine | `services/session/` package: `__init__.py`, `assembly.py`, `grade_policy.py` | 2026-07-31 | Consultant |
| 13 | Module boundary — Scheduling | `services/scheduling.py` standalone (separate from session engine) | 2026-07-31 | Consultant |
| 14 | Module boundary — Data layer | `services/db/` split: `schema.py`, `users.py`, `reviews.py`, `words.py` | 2026-07-31 | Consultant |
| 15 | First-exposure — API | Separate wrapper `initial_stability_first_exposure()` (not a bool flag) | 2026-07-31 | Consultant |
| 16 | Session assembly | Generator internally, list externally; Tier 3 as refill function | 2026-07-31 | Consultant |
| 17 | Keyboard location | `ActivityHandler.get_interaction_ui()`, not handler layer | 2026-07-31 | Consultant |
| 18 | Import strategy | No backward-compat shim; update all sites directly | 2026-07-31 | Consultant |
| 19 | Frontend coupling | Session engine is frontend-agnostic (no Telegram objects) | 2026-07-31 | Consultant |
| 20 | Interactive flow state | Handlers own `context.user_data['current_flow']`; engine never touches it | 2026-07-31 | Consultant |
| 21 | First-exposure button labels | Familiarity-based: کاملاً ناآشنا / کمی آشنا / آشنایی خوب / کاملاً بلدمش | 2026-07-29 | Owner |
| 22 | First-exposure stability weights | `FIRST_EXPOSURE_STABILITY = {1: 0.212, 2: 1.5, 3: 3.0, 4: 12.0}` | 2026-07-29 | Owner |
| 23 | Data migration | Save word records; reset SRS fields; drop `interval_idx`; no rollback column | 2026-07-31 | Owner + Consultant |
| 24 | Review events schema | Store raw_signal (JSON), not just final grade | 2026-07-31 | Consultant |
| 25 | Cutover strategy | Atomic — bot is off; all changes land together; no transitional dual-write | 2026-07-31 | Owner + Consultant |
| 26 | Tier 3 in this migration | Stub only (`generate_tier3_node()` returns None); session ends gracefully at Tiers 1+2 exhaustion | 2026-07-31 | Consultant |
| 27 | Auto-advance lives in | `study_handler.advance_session()`, called from grade handlers after grading | 2026-07-31 | Consultant |
| 28 | Auto-advance UX | Direct chain — grade press → next card via `edit_message_text`; no separate "next" button | 2026-07-31 | Consultant |
| 29 | Session quota storage | `settings` table, key `sessions_used_{user_id}_{date}`, integer count (not boolean) | 2026-07-31 | Consultant |
| 30 | Session = one invocation | Quota consumed once at top of `handle_study_start`, before `build_session_list()` | 2026-07-31 | Consultant |
| 31 | SessionState fields | `nodes`, `total_cards`, `tier3_context`, `study_msg_id`, `plan` — no `index` field | 2026-07-31 | Consultant |
| 32 | advance_session failure boundary | Wrap render+advance in try/except; on failure show Persian error message | 2026-07-31 | Consultant |
| 33 | Empty session slot release | If Tiers 1+2 empty after build, call `release_session_slot()` before "no cards" message | 2026-07-31 | Consultant |
| 34 | Double-tap guard | Accepted risk at 10 test users; revisit if real users report skipped cards | 2026-07-31 | Consultant |

---

## 6. Rollback Appendix

### 6.1 Per-File Rollback

| File | Rollback Action |
|---|---|
| `services/fsrs_core.py` | Revert additions (`git checkout main -- services/fsrs_core.py`) |
| `services/session/` | Delete directory |
| `services/scheduling.py` | Delete file |
| `services/db/schema.py` | Revert to old `init_db()` in `services/db/__init__.py` |
| `services/db/words.py` | Revert to old `add_saved_word()`, `due_words_for_user()` in `services/db/__init__.py` |
| `services/db/reviews.py` | Revert to old `record_review_event()` in `services/db/__init__.py` |
| `services/db/users.py` | Revert user CRUD to `services/db/__init__.py` |
| `config/keyboards.py` | Revert SRS keyboard section |
| `handlers/srs_handler.py` | Revert to old 2-button handler |
| `handlers/study_handler.py` | Revert to stub |
| `handlers/user.py` | Revert `show_status()`, `start_srs_review()` |
| `bot.py` | Revert callback_router SRS routes + imports |
| `services/utils/formatting.py` | Revert `SRS_HIDDEN_INSTRUCTION` |
| All test files | Revert to old versions |

### 6.2 Data Rollback

If FSRS scheduling produces worse results than the old 5-step ladder:

```python
# Re-run old init_db() (before migration code)
# Re-create interval_idx column
# UPDATE saved_words SET interval_idx = CASE
#   WHEN stability <= 2 THEN 0
#   WHEN stability <= 5 THEN 1
#   WHEN stability <= 12 THEN 2
#   WHEN stability <= 24 THEN 3
#   ELSE 4 END,
# next_review = date('now', '+' || INTERVALS_DAYS[interval_idx] || ' days')
# Restore advance_word_review() and defer_word_review() from git history
```

**Note:** This is a lossy back-conversion. With only 10 test users and no production data, it's acceptable. In production, this level of rollback would destroy difficulty-tracking information that never existed in the old system anyway.

---

## 7. Forward Reference: Parameter Optimization (Deferred)

**Phase 3 (parameter optimization) is intentionally deferred to a separate document**, contingent on reaching ~500+ review events across all users. This plan (V2) covers only the architecture and migration. The future document (`docs/plans/plan_fsrs_optimization.md`, not yet written) will specify:

- Anti-gaming detection thresholds (response time, grade-vs-retrievability mismatch, grade distribution variance)
- Pre-filtering heuristics vs. robust statistical down-weighting
- Validation methodology (cross-validation on historical holdout, then live A/B if user base grows)
- Per-user vs. global fitting decision (revisit if DAU exceeds 1,000+)

**What V2 locks now for Phase 3's benefit:**

| Item | Where | Why now |
|---|---|---|
| `response_time_ms` column in `review_events` | Phase 1a.2 schema | Can't retroactively measure how fast a button was pressed |
| Gamification `activity_type` constraint (1a.14) | `record_review_event()` docstring | Contaminated training data is irreversible once mixed |
| Raw signal storage (`raw_signal` column) | Decision 0.8 | Enables grade re-derivation under different policies without re-running AI |

All three are cheap now and expensive to retrofit. The actual filtering logic, optimizer pipeline, and validation gates are deferred.
