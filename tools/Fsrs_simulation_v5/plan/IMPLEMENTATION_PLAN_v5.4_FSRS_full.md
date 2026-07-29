# v5.4 Implementation Plan — True FSRS-6 Full Implementation

**Target file:** `tools/Fsrs_simulation_v5/v5.4_FSRS_full.py` (new file)
**Base:** `v5.2_FSRSv6.py` stripped of lite/legacy + formulas corrected per `docs/FSRS_v6.md`
**Size:** 566 lines (from 781; -215 net)
**Status:** ✅ COMPLETED — all decisions locked per owner, file written and verified

---

## What v5.2 Currently Is vs What v5.4 Needs to Be

| Aspect | v5.2 ("FSRS-6 inspired") | v5.4 (true FSRS-6) |
|---|---|---|
| Models | 3: `dsr`, `lite`, `legacy` | 1: `dsr` only |
| Parameters | w0–w15 (missing w3, w16–w20) | w0–w20 (complete) |
| Decay | Hardcoded `DSR_DECAY = -0.5` (FSRS-5 style) | Derived from w20 (`DECAY = -w20`) |
| FACTOR | Hardcoded `19/81` | `0.9^(-1/w20) - 1` |
| Grades | 3 (no Easy) | 4 (Again, Hard, Good, Easy) |
| Mean reversion | Toward `D0(3)` (Good) | Toward `D0(4)` (Easy) — FSRS-6 §2.7 |
| Easy bonus | None | w16 multiplier in stability growth |
| Short-term formula | Not implemented | Optional (gated) — FSRS-6 §2.6 |
| Summary metrics | Conditional per model | Always DSR metrics + tier counts |

---

## Implementation Steps

### Step 1 — Strip Lite & Legacy Code

#### 1a. Remove lite constants (lines 84–101)
Delete from `STABILITY_INITIAL` through `LEARNED_MIN_REVIEWS`. These are only referenced by `_review_outcome_lite`, `_review_outcome_legacy`, and non-DSR summary branches — all of which are removed.

#### 1b. Remove `_review_outcome_legacy()` (lines 254–267)
Delete the entire function.

#### 1c. Remove `_review_outcome_lite()` (lines 273–325)
Delete the entire function.

#### 1d. Simplify `_handle_first_exposure()` — remove non-DSR else branch
Current:
```python
if cfg.mastery_model == "dsr":
    card.stability = _dsr_s0(grade)
    card.difficulty = _dsr_d0(grade)
    ...
else:
    card.stability = STABILITY_INITIAL
    interval = 1.0
```
Becomes:
```python
card.stability = _dsr_s0(grade)
card.difficulty = _dsr_d0(grade)
if grade == 1:
    interval = 1.0
else:
    interval = _dsr_interval_days(card.stability, cfg.desired_retention)
```

#### 1e. Remove lite/legacy dispatch branches in `simulate()`
- Remove the `if cfg.mastery_model != "dsr": c.difficulty = user_avg_difficulty` overwrite (line 571–572)
- Remove `elif` / `else` branches in the review dispatch (lines 576–579): only `_review_outcome_dsr` remains
- Same for bonus dispatch (lines 596–599)

#### 1f. Remove non-DSR summary block (lines 628–637)
Only DSR summary computation remains (the `if cfg.mastery_model == "dsr"` block becomes unconditional).

#### 1g. Remove lite/legacy branches in `format_table()` (lines 723–726, 754–755)
Always show DSR-specific fields (stability, difficulty, retrievability, tier counts).

#### 1h. Simplify `MasteryModel` type
Change `Literal["legacy", "lite", "dsr"]` to `Literal["dsr"]` or remove entirely if SimConfig no longer has `mastery_model`.

---

### Step 2 — Complete DSR_W with w0–w20

Add 6 missing parameters to match `docs/FSRS_v6.md` §1:

```python
DSR_W = {
    "w0": 0.212,      # S0(Again)
    "w1": 1.2931,     # S0(Hard)
    "w2": 2.3065,     # S0(Good)
    "w3": 8.2956,     # S0(Easy)              ← NEW
    "w4": 6.4133,
    "w5": 0.8334,
    "w6": 3.0194,
    "w7": 0.001,
    "w8": 1.8722,
    "w9": 0.1666,
    "w10": 0.796,
    "w11": 1.4835,
    "w12": 0.0614,
    "w13": 0.2629,
    "w14": 1.6483,
    "w15": 0.6014,
    "w16": 1.8729,    # Easy bonus            ← NEW
    "w17": 0.5425,    # Short-term grade      ← NEW
    "w18": 0.0912,    # Short-term offset     ← NEW
    "w19": 0.0658,    # Short-term S^-w19     ← NEW
    "w20": 0.1542,    # Decay exponent        ← NEW
}
```

---

### Step 3 — Replace Hardcoded Decay with w20-derived Values

Current (FSRS-5 style, lines 71–72):
```python
DSR_FACTOR = 19.0 / 81.0
DSR_DECAY = -0.5
```

New (FSRS-6 style, derived from w20):
```python
DSR_DECAY = -DSR_W["w20"]         # -0.1542
DSR_FACTOR = 0.9 ** (-1.0 / DSR_W["w20"]) - 1.0  # 0.9^(-1/0.1542) - 1
```

These are used by `_dsr_retrievability()`, `_dsr_interval_days()`, and the interval formula. No function signature changes needed — the formulas remain the same, just the constants change.

**Impact on results:** Under FSRS-6 defaults (w20=0.1542), DECAY is shallower (-0.1542 vs -0.5) and FACTOR is larger. This means:
- R decays more slowly at the same t/S ratio
- Intervals for the same desired retention will be longer
- The model is more optimistic about long-term memory

---

### Step 4 — Upgrade to 4 Grades

#### 4a. `_dsr_s0()` — add Easy grade
```python
def _dsr_s0(grade: int) -> float:
    return {1: DSR_W["w0"], 2: DSR_W["w1"], 3: DSR_W["w2"], 4: DSR_W["w3"]}[grade]
```

#### 4b. `_handle_first_exposure()` — 4-grade mapping
After computing performance:
```python
if performance >= 0.90:          # threshold for Easy
    grade = 4
elif performance >= PERFORMANCE_SUCCESS_THRESHOLD:  # 0.75
    grade = 3
elif performance >= PERFORMANCE_PARTIAL_THRESHOLD:  # 0.40
    grade = 2
else:
    grade = 1
```
Return mapping: `{1: "forget", 2: "hold", 3: "advance", 4: "master"}`

#### 4c. `_review_outcome_dsr()` — 4-grade mapping
Same performance→grade mapping as above. Difficulty update and stability update receive `grade` in {1,2,3,4}.

#### 4d. `_dsr_update_difficulty()` — mean reversion toward D0(4)
Current: mean reverts toward `_dsr_d0(3)` (Good).
FSRS-6 §2.7: mean reverts toward `D0(4)` (Easy).

```python
def _dsr_update_difficulty(d: float, grade: int) -> float:
    delta_d = -DSR_W["w6"] * (grade - 3)
    d_damped = d + delta_d * (10.0 - d) / 9.0
    d0_easy = _dsr_d0(4)  # = w4 - exp(w5 * 3) + 1
    d_reverted = DSR_W["w7"] * d0_easy + (1.0 - DSR_W["w7"]) * d_damped
    return max(1.0, min(10.0, d_reverted))
```

#### 4e. `_dsr_update_stability()` — add Easy bonus
Current: `hard_penalty = DSR_W["w15"] if grade == 2 else 1.0`
FSRS-6 §2.4: also `easy_bonus = DSR_W["w16"] if grade == 4 else 1.0`

```python
def _dsr_update_stability(d: float, s: float, r: float, grade: int) -> float:
    s = max(0.1, s)
    if grade == 1:
        s_new = (
            DSR_W["w11"]
            * (d ** -DSR_W["w12"])
            * (((s + 1.0) ** DSR_W["w13"]) - 1.0)
            * math.exp(DSR_W["w14"] * (1.0 - r))
        )
        return max(0.1, min(s_new, s))
    hard_penalty = DSR_W["w15"] if grade == 2 else 1.0
    easy_bonus = DSR_W["w16"] if grade == 4 else 1.0
    s_inc = (
        1.0
        + math.exp(DSR_W["w8"])
        * (11.0 - d)
        * (s ** -DSR_W["w9"])
        * (math.exp(DSR_W["w10"] * (1.0 - r)) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    return s * max(1.0, s_inc)
```

---

### Step 5 — Add Short-Term Stability Formula (FSRS-6 §2.6)

Not currently used by any review path in the simulation (no same-day reviews modeled). Add as an available function:

```python
def _dsr_short_term_stability(s: float, grade: int) -> float:
    """Same-day review stability per FSRS-6 §2.6."""
    s_inc = math.exp(DSR_W["w17"] * (grade - 3 + DSR_W["w18"])) * (s ** -DSR_W["w19"])
    if grade >= 3:
        s_inc = max(1.0, s_inc)
    return s * s_inc
```

**Decision needed:** Gate behind `enable_short_term` flag (default `False`), or omit entirely and only add when same-day reviews are modeled?

---

### Step 6 — Simplify SimConfig

| Field | Action |
|---|---|
| `mastery_model` | Remove — only DSR exists |
| `desired_retention` | Keep (default `0.9` per FSRS-6) |
| `plan`, `persona`, `proficiency` | Keep |
| `enable_rejection`, `enable_catchup` | Keep |
| `enable_session_rate_limit` | Keep |
| `enable_continuous_mastery` | Keep |
| `sessions_override`, `session_size_override` | Keep |
| `enable_short_term` | Add (optional, default `False`) — only if we include short-term formula |

---

### Step 7 — Clean Up Card Dataclass

Remove fields that were only used by legacy/lite models:
- `idx` — was for idx-based learned detection (legacy)
- `score` — was for score-based learned detection (legacy)
- `streak` — was for streak-based continuous mastery (lite)
- `ease` — was from even older SM-2 style

Keep: `id`, `origin`, `stability`, `difficulty`, `last_review`, `next_review`, `due_since`, `reviews`, `first_exposure_done`

---

### Step 8 — Unconditional Summary & Formatting

- Summary always computes: `stabilities`, `difficulties`, `retrievabilities`, `tier_counts` (removes all `if cfg.mastery_model == "dsr"` guards)
- `format_table` always shows: stability, difficulty, retrievability, tier counts

---

## Key Decisions (Owner Must Choose)

| # | Topic | Option A (Recommended) | Option B |
|---|---|---|---|
| 1 | Short-term formula | Include `_dsr_short_term_stability()` + `enable_short_term=False` flag — ready for future but off by default | Omit entirely — no same-day reviews in simulation, keep it simple |
| 2 | Desired retention default | `0.9` — matches FSRS-6 standard (retention=0.9 means interval=S) | Keep `0.85` — matches v5.2 behavior, more aggressive intervals |
| 3 | Grade→outcome mapping | 4 grades with new label `"master"` for Easy — requires updating callers that expect `{1,2,3}` → `{forget, hold, advance}` | Map grade 4 → `"advance"` (lose the distinction but no caller changes) |
| 4 | Performance threshold for Easy | `0.90` — only top 10% of performances get Easy grade | `0.85` — more permissive Easy assignment |

---

## Verification

After implementation, run:

```bash
cd tools/Fsrs_simulation_v5
python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('v5_4', 'v5.4_FSRS_full.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# Basic sanity: default config
cfg = m.SimConfig(plan='silver', persona='average', days=180, seed=42)
_, s = m.simulate(cfg)
print('learned:', s['learned_words'])
print('avg_stability:', s['avg_stability_days'])
print('avg_retrievability:', s['avg_retrievability'])
print('avg_difficulty:', s['avg_difficulty'])
print('tier_counts:', s['tier_counts'])

# Edge case: lazy persona, long duration
cfg2 = m.SimConfig(plan='free', persona='lazy', days=720, seed=42)
_, s2 = m.simulate(cfg2)
print('lazy/720 learned:', s2['learned_words'])
print('lazy/720 max_backlog:', s2['max_due_backlog'])

# Edge case: gold plan, eager
cfg3 = m.SimConfig(plan='gold', persona='eager', days=90, seed=42)
_, s3 = m.simulate(cfg3)
print('gold/eager learned:', s3['learned_words'])
"
```

Cross-check: same config on v5.2 DSR model should show slightly different (hopefully better) results due to correct FSRS-6 formulas, not identical.

---

## Files to Create

| File | Action |
|---|---|
| `tools/Fsrs_simulation_v5/v5.4_FSRS_full.py` | NEW — the module |
| `tools/Fsrs_simulation_v5/plan/IMPLEMENTATION_PLAN_v5.4_FSRS_full.md` | This plan |

---

## Rollback

Since this is a new file, no rollback needed for existing modules. If v5.4 has regressions, simply delete the file and revert to v5.2 for simulations.

---

## Status Tracker

| Item | Status | Notes |
|------|--------|-------|
| Owner decisions on 4 items | ✅ LOCKED | Short-term=gated-off, DR=0.9, grade4="master", Easy threshold=0.90 |
| Strip lite/legacy code | ✅ DONE | Removed ~130 lines of lite/legacy functions, constants, branches |
| Complete DSR_W w0–w20 | ✅ DONE | Added w3, w16–w20 to parameter dict |
| w20-based decay/factor | ✅ DONE | FACTOR and interval derived from w20=0.1542 |
| 4-grade system | ✅ DONE | Again/Hard/Good/Easy with "master" label for grade 4 |
| Mean reversion to D0(Easy) | ✅ DONE | `_dsr_update_difficulty` uses `_dsr_d0(4)` |
| Easy bonus (w16) | ✅ DONE | Added to `_dsr_update_stability` success formula |
| Short-term formula | ✅ DONE | `_dsr_short_term_stability()` added, gated behind `enable_short_term=False` |
| Cleaned Card dataclass | ✅ DONE | Removed idx, score, streak, ease (legacy/lite only) |
| Removed mastery_model | ✅ DONE | SimConfig has no mastery_model field |
| Summary and format always DSR | ✅ DONE | Unconditional DSR metrics and tier display |
| Verification: compile | ✅ PASS | No import/syntax errors |
| Verification: v5.4 default config | ✅ PASS | learned=426, avg_stability=154d, avg_difficulty=2.0 |
| Verification: v5.4 vs v5.2 DSR | ✅ PASS | Delta: learned +60, stability +65d (expected — w20 decay is shallower) |
| Verification: lazy/720 edge case | ✅ PASS | learned=190, avg_lateness=2.8d |
| Verification: gold/eager/90 | ✅ PASS | learned=760, avg_stability=107d |
| Verification: format_table | ✅ PASS | Full output renders correctly |
| File size | ✅ 566 lines | 28% reduction from v5.2 (781 lines)
