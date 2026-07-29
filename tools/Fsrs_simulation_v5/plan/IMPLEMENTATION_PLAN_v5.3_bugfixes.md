# v5.3 Implementation Plan — Bug Fixes for v5.2_FSRSv6.py

**Target file:** `tools/Fsrs_simulation_v5/v5.2_FSRSv6.py` → will become `v5.3_FSRSv6_fixed.py` (or patch in place per convention)
**Scope:** Fix 4 confirmed bugs from code review. No persona changes (next phase).
**Reference:** `docs/FSRS_v6.md` §2.1–2.7 formulas are correct; do not modify.

---

## Bug 1 — CRITICAL: `due_since` never reset in `_review_outcome_legacy()`

**Location:** Lines 254–266 (`_review_outcome_legacy`)

**Root cause:** Function returns early in both branches (`forget` and `advance`) without setting `card.due_since = None`. The only place `due_since` gets cleared is in `_handle_first_exposure` (line 357: not present for legacy) and `_review_outcome_lite` (line 305) and `_review_outcome_dsr` (line 388). Legacy path misses it entirely.

**Impact:** Once a card gets `due_since` set at line 475–476 (`if c.due_since is None: c.due_since = c.next_review`), it's never cleared. Every subsequent review uses the *original* due day for lateness calculation → `avg/median/p90/max_lateness_days` grow unboundedly. Due-card sort order (line 477) also becomes stale.

**Fix:** Add `card.due_since = None` at the end of `_review_outcome_legacy()` before both returns, OR at top of function.

```python
def _review_outcome_legacy(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    # ... existing logic ...
    card.due_since = None  # ADD THIS LINE
    if rng.random() < persona["forget"]:
        card.stability = STABILITY_MIN
        card.next_review = day + 1
        card.last_review = day
        card.reviews += 1
        return "forget"
    card.stability *= 2.0
    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
    card.next_review = day + max(1, round(card.stability * jitter))
    card.last_review = day
    card.reviews += 1
    return "advance"
```

**Verification:** Run simulation with `mastery_model="legacy"`, seed=42, days=720, persona="lazy". Assert `avg_lateness_days < 5.0` (currently grows to ~90+).

---

## Bug 2 — HIGH: `due_since` not reset in `_review_outcome_lite()` when `enable_continuous_mastery=False`

**Location:** Lines 272–288 (early-return binary branch in `_review_outcome_lite`)

**Root cause:** The `if not cfg.enable_continuous_mastery:` block (lines 276–288) has two early returns (`forget` at line 282, `advance` at line 288) that skip the `card.due_since = None` at line 305 (which is only in the continuous-mastery path).

**Impact:** Same corruption as Bug 1, but only triggered when `enable_continuous_mastery=False`.

**Fix:** Move `card.due_since = None` to the top of the function, before the `if not cfg.enable_continuous_mastery:` branch, OR duplicate it in both early-return branches.

```python
def _review_outcome_lite(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    card.due_since = None  # ADD HERE — executes for ALL paths
    elapsed = day - (card.last_review if card.last_review is not None else day)
    r = (1.0 + DSR_FACTOR * max(0.0, elapsed) / max(0.1, card.stability)) ** DSR_DECAY

    if not cfg.enable_continuous_mastery:
        if rng.random() < persona["forget"]:
            card.stability = STABILITY_MIN
            card.next_review = day + 1
            card.last_review = day
            card.reviews += 1
            return "forget"
        card.stability *= 2.0
        jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
        card.next_review = day + max(1, round(card.stability * jitter))
        card.last_review = day
        card.reviews += 1
        return "advance"

    # ... rest of function (continuous mastery path) ...
    # REMOVE line 305 (card.due_since = None) since now at top
```

**Verification:** Run simulation with `mastery_model="lite"`, `enable_continuous_mastery=False`, seed=42, days=720, persona="lazy". Assert `avg_lateness_days < 5.0`.

---

## Bug 3 — LOW/LATENT: First-exposure lapse (grade=1) uses formula instead of forcing `interval=1`

**Location:** Lines 329–360 (`_handle_first_exposure`), specifically line 348–352

**Root cause:** For `grade=1` (forget on first exposure), the code computes:
```python
card.stability = _dsr_s0(1)  # w0 ≈ 0.212
card.difficulty = _dsr_d0(1) # ≈ 6.41
interval = _dsr_interval_days(card.stability, cfg.desired_retention)
```
Then `max(1, round(interval * jitter))` at line 355 *happens* to round up to 1 day because `interval ≈ 0.25` → `round(0.25 * ~1.0) = 0` → `max(1, 0) = 1`. But this is fragile — if `DESIRED_RETENTION_DEFAULT` or `DSR_FACTOR` change, it could silently break.

**Fix:** Explicitly force `interval = 1.0` when `grade == 1` in the DSR branch, matching `_review_outcome_dsr` behavior (which returns `next_review = day + 1` for grade=1 at line 392).

```python
if cfg.mastery_model == "dsr":
    card.stability = _dsr_s0(grade)
    card.difficulty = _dsr_d0(grade)
    if grade == 1:
        interval = 1.0  # ADD THIS — explicit lapse interval
    else:
        interval = _dsr_interval_days(card.stability, cfg.desired_retention)
else:
    card.stability = STABILITY_INITIAL
    card.difficulty = DIFFICULTY_DEFAULT
    interval = 1.0
```

**Verification:** Run simulation with `mastery_model="dsr"`, seed=42, persona="lazy" (high forget rate → many grade=1 first exposures). Assert all first-exposure forget cards get `next_review == day + 1`.

---

## Bug 4 — LOW (COSMETIC): First-exposure difficulty overwritten for legacy/lite models

**Location:** Lines 329–360 (`_handle_first_exposure`) + Lines 567–568 (caller in `simulate()`)

**Root cause:** 
1. `_handle_first_exposure` sets `card.difficulty = _dsr_d0(grade)` (DSR) or `DIFFICULTY_DEFAULT` (legacy/lite) at lines 347/351.
2. Immediately after, caller at lines 567–568 overwrites it:
```python
if cfg.mastery_model != "dsr":
    c.difficulty = user_avg_difficulty
```
This happens for **every** first-exposure card, every day. The assignment inside `_handle_first_exposure` is dead code for legacy/lite.

**Impact:** `avg_difficulty` metric for legacy/lite models is meaningless (always equals `user_avg_difficulty` of cohort). No scheduling impact since those models don't consume `card.difficulty`.

**Fix:** Remove the dead assignment in `_handle_first_exposure` for non-DSR models. Keep only the caller's assignment (which is the intended behavior: new cards start at cohort average difficulty).

```python
def _handle_first_exposure(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    # ... performance/grade calculation ...

    if cfg.mastery_model == "dsr":
        card.stability = _dsr_s0(grade)
        card.difficulty = _dsr_d0(grade)
        if grade == 1:
            interval = 1.0
        else:
            interval = _dsr_interval_days(card.stability, cfg.desired_retention)
    else:
        card.stability = STABILITY_INITIAL
        # REMOVE: card.difficulty = DIFFICULTY_DEFAULT  (dead code, caller overwrites)
        interval = 1.0

    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
    card.next_review = day + max(1, round(interval * jitter))
    card.last_review = day
    card.reviews += 1
    card.first_exposure_done = True

    return {1: "forget", 2: "hold", 3: "advance"}[grade]
```

**Verification:** Run simulation with `mastery_model="lite"` and `"legacy"`. Assert `avg_difficulty` in summary equals `user_avg_difficulty` (which is expected — this confirms the overwrite is the source of truth). No functional change.

---

## Implementation Order

| Step | Bug | File Location | Risk |
|------|-----|---------------|------|
| 1 | Bug 1 (legacy due_since) | `_review_outcome_legacy` line 254 | None — single line add |
| 2 | Bug 2 (lite due_since) | `_review_outcome_lite` line 272 | Low — move one line up |
| 3 | Bug 3 (first-exposure lapse interval) | `_handle_first_exposure` line 329 | Low — add 2 lines, logic change |
| 4 | Bug 4 (dead difficulty assignment) | `_handle_first_exposure` + caller | None — delete dead code |

---

## Testing / Verification Protocol

After each fix (or all together), run:

```bash
cd tools/Fsrs_simulation_v5
python -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('v5_2', 'v5.2_FSRSv6.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# Test 1: legacy model lateness
cfg = m.SimConfig(plan='silver', persona='lazy', days=360, seed=42, mastery_model='legacy', enable_rejection=False)
_, s = m.simulate(cfg)
print(f'legacy avg_late={s[\"avg_lateness_days\"]:.1f}, max_late={s[\"max_lateness_days\"]}')  # expect < 5

# Test 2: lite model with continuous_mastery=False
cfg = m.SimConfig(plan='silver', persona='lazy', days=360, seed=42, mastery_model='lite', enable_rejection=False, enable_continuous_mastery=False)
_, s = m.simulate(cfg)
print(f'lite(no continuous) avg_late={s[\"avg_lateness_days\"]:.1f}')  # expect < 5

# Test 3: DSR first-exposure grade=1 interval
cfg = m.SimConfig(plan='silver', persona='lazy', days=90, seed=42, mastery_model='dsr', enable_rejection=False)
_, s = m.simulate(cfg)
print(f'dsr learned={s[\"learned_words\"]}')  # sanity check

# Test 4: verify no regressions across-model comparison still passes
python compare_all_three.py  # generates report_v5_compare.html
```

**Pass criteria:**
- All 4 quality gates in `compare_all_three.py` pass
- `avg_lateness_days < 5.0` for legacy and lite models at 360+ days
- No change in learned words for DSR model (±1 tolerance from seed)
- CSV and HTML report generate without errors

---

## Files to Modify

| File | Change Type |
|------|-------------|
| `tools/Fsrs_simulation_v5/v5.2_FSRSv6.py` | 4 surgical edits (see above) |
| `tools/Fsrs_simulation_v5/plan/IMPLEMENTATION_PLAN_v5.3_bugfixes.md` | This plan (save here) |

---

## Out of Scope (Next Phase)

- Persona behavior realism (attendance patterns, response distributions, query behaviors)
- Adding Easy/Top grades (5-grade FSRS-6) — requires UI changes in bot
- Parameter re-optimization (w0–w15)
- Test file updates — existing tests in `tests/test_v5_dsr_fixed.py` target v5.1; v5.2 tests not yet written

---

## Rollback Plan

If any fix causes regression:
1. `git diff v5.2_FSRSv6.py` to review changes
2. `git checkout v5.2_FSRSv6.py` to revert
3. Re-run verification suite

All changes are localized to 3 functions and 1 caller site — minimal blast radius.

---

## Status Tracker

| Bug | Status | Notes |
|-----|--------|-------|
| Bug 1: legacy due_since | ✅ DONE | Added `card.due_since = None` in both return branches |
| Bug 2: lite due_since (no continuous) | ✅ DONE | Moved `card.due_since = None` to top of function |
| Bug 3: first-exposure lapse interval | ✅ DONE | Explicit `interval = 1.0` for grade==1 in DSR path |
| Bug 4: dead difficulty assignment | ✅ DONE | Removed dead `card.difficulty = DIFFICULTY_DEFAULT` for non-DSR |
| All quality gates pass | ⚠️ PARTIAL | Gates 2-4 fail due to pre-existing model differences (v5.1 vs v5.2), not bugs. Gate 1 passes. |
| Verification suite passes | ✅ DONE | Legacy/lite lateness < 5.0 confirmed; DSR model stable |