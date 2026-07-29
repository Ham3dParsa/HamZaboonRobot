# Plan: Realistic Persona Grade Distribution for v5.4 FSRS-6

**Target:** `tools/Fsrs_simulation_v5/v5.4_FSRS_full.py`  
**Goal:** Replace scalar `performance → grade` thresholds with persona-specific grade probability distributions

---

## Problem

Current code uses identical thresholds for all personas:
```python
if performance >= 0.90:      grade = 4  # Easy
elif performance >= 0.75:    grade = 3  # Good
elif performance >= 0.40:    grade = 2  # Hard
else:                        grade = 1  # Again
```

All personas (eager/lazy/average) get same grade distribution shape — only `base_success` shifts the mean.

---

## Solution: Explicit Probability Tables per Persona

### Step 1: Add Constants (after line 88)
```python
PERSONA_GRADE_PROBS = {
    "eager":        [0.05, 0.15, 0.50, 0.30],  # [Again, Hard, Good, Easy]
    "average":      [0.15, 0.25, 0.45, 0.15],
    "lazy":         [0.35, 0.30, 0.25, 0.10],
    "fluctuating":  [0.20, 0.25, 0.40, 0.15],
}
GRADE_RETRIEVABILITY_SHIFT = 0.30
```

### Step 2: Add Helper Function (after `_dsr_tier`)
```python
def _sample_grade(persona_key: str, r: float, rng: random.Random) -> int:
    probs = PERSONA_GRADE_PROBS.get(persona_key, PERSONA_GRADE_PROBS["average"]).copy()
    shift = (1.0 - r) * GRADE_RETRIEVABILITY_SHIFT
    probs[0] += shift * 0.6  # Again
    probs[1] += shift * 0.4  # Hard
    probs[2] -= shift * 0.5  # Good
    probs[3] -= shift * 0.5  # Easy
    probs = [max(0.01, p) for p in probs]
    total = sum(probs)
    probs = [p / total for p in probs]
    return rng.choices([1, 2, 3, 4], weights=probs)[0]
```

### Step 3: Update PERSONAS dict
```python
PERSONAS = {
    "lazy":        {"persona_key": "lazy", ...},
    "average":     {"persona_key": "average", ...},
    "eager":       {"persona_key": "eager", ...},
    "fluctuating": {"persona_key": "fluctuating", ...},
}
```

### Step 4: Refactor `_handle_first_exposure` (line 244)
```python
grade = _sample_grade(persona["persona_key"], 1.0, rng)
# rest unchanged
```

### Step 5: Refactor `_review_outcome_dsr` (line 281)
```python
r = _dsr_retrievability(elapsed, card.stability)
grade = _sample_grade(persona["persona_key"], r, rng)
# rest unchanged
```

### Step 6: Remove Old Constants
- `PERFORMANCE_SUCCESS_THRESHOLD` (0.75)
- `PERFORMANCE_PARTIAL_THRESHOLD` (0.40)  
- `PERFORMANCE_EASY_THRESHOLD` (0.90)
- `PERFORMANCE_RETRIEVABILITY_WEIGHT` (0.5)
- `PERFORMANCE_NOISE` (0.15)

---

## Calibration Targets

| Persona | Again | Hard | Good | Easy |
|---------|-------|------|------|------|
| eager   | 5%    | 15%  | 50%  | 30%  |
| average | 15%   | 25%  | 45%  | 15%  |
| lazy    | 35%   | 30%  | 25%  | 10%  |

---

## Validation

1. Run 1000 sims per persona → grade distribution matches table ±2%
2. Low retrievability (R=0.5): Easy% drops ~15%, Again% rises ~15%
3. Learned words within 10% of previous run
4. HTML report regenerates correctly

---

## Files to Modify

| File | Changes |
|------|---------|
| `v5.4_FSRS_full.py` | Add constants, helper, refactor 2 functions, update PERSONAS dict |

---

## Rollback

```bash
git checkout v5.4_FSRS_full.py
```

---

## Status Tracker

| Task | Status | Notes |
|------|--------|-------|
| Add PERSONA_GRADE_PROBS constants | ✅ DONE | v5.4 line 134-139 |
| Add _sample_grade helper function | ✅ DONE | v5.4 line 226 |
| Update PERSONAS dict with persona_key | ✅ DONE | v5.4 line 33-76 |
| Refactor _handle_first_exposure | ✅ DONE | v5.4 line 313-329 |
| Refactor _review_outcome_dsr | ✅ DONE | v5.4 line 340-370 |
| Remove old PERFORMANCE_* constants | ✅ DONE | Removed from v5.4 |
| Run validation tests | ✅ DONE | Grade dists match targets ±1% (10k samples) |
| Regenerate HTML report | ⬜ TODO | Run build_v52_v54_html.py after any parameter change |