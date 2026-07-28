# Implementation Plan: v5_dsr_fixed.py

**Target file:** `tools/Fsrs_simulation_v5/v5_dsr_fixed.py`  
**Test file:** `tools/Fsrs_simulation_v5/tests/test_v5_dsr_fixed.py`  
**Reference implementations:** `v5_dsr.py` (lite), `v5_dsr_2.py` (full FSRS-6), real FSRS-6 algorithm

---

## 0. LOCKED ARCHITECTURE DECISIONS (Contract)

| Decision | Value | Rationale |
|----------|-------|-----------|
| `mastery_model` default | `"dsr"` | DSR is the target; legacy/lite kept for benchmark only |
| `desired_retention` | `0.85` (overrideable via SimConfig) | FSRS default for language learning; 0.9 too aggressive |
| FSRS parameter set | 12 params (w0,w1,w2, w4,w5, w6,w7, w8,w9,w10, w11,w12,w13,w14, w15) | w3 (Easy S0), w16 (Easy bonus), w17-w20 (short-term/decay) excluded — 3-button UI |
| Grade mapping | forget=1, hold=2, advance=3 | Matches هم‌زبان 3 buttons exactly |
| First-exposure grading | **YES — new feature** | User sees 3 buttons on first view; grade determines S0/D0 |
| Learned threshold (DSR) | `stability >= 21.0` days | From v5_2.py DSR_TIER_THRESHOLDS |
| Tier thresholds | `[(0, "learning"), (7, "familiar"), (21, "learned"), (60, "consolidated")]` | For summary tier_counts |
| Legacy `enable_continuous_mastery` | Maps to `mastery_model="lite"` | Backward compat |
| `enable_rejection` | Applies to all models | Same AI rejection logic |
| `enable_catchup` | Applies to all models | Same catch-up logic |
| `enable_session_rate_limit` | Applies to all models | Same session cap logic |

---

## 1. FILE STRUCTURE OVERVIEW

```
v5_dsr_fixed.py
├── Imports & Constants
├── DSR_PARAMS (DSR_W dict + FACTOR/DECAY/RETENTION)
├── DSR Helper Functions (_dsr_*)
├── PLAN_DEFAULTS, PERSONAS, PROFICIENCY (copied from v5)
├── Feature flag constants
├── Card dataclass (DSR + legacy fields + first_exposure_done)
├── MasteryModel / SimConfig
├── _clamp_override, _resolve_plan, _attend_prob
├── _review_outcome_legacy (binary)
├── _review_outcome_lite (DSR-lite with first-exposure)
├── _review_outcome_dsr (FSRS-6 with first-exposure)
├── simulate(cfg) → (daily_rows, summary)
├── format_table, write_csv
```

---

## 2. CONSTANTS — EXACT VALUES (LOCKED)

```python
# ============================================================
# DSR / FSRS-6 PARAMETERS (from v5_2.py, validated against py-fsrs defaults)
# ============================================================
DSR_W = {
    # Initial stability by first grade (Again=1, Hard=2, Good=3)
    "w0": 0.212,       # S0(Again)
    "w1": 1.2931,      # S0(Hard)
    "w2": 2.3065,      # S0(Good)
    # w3 (S0_Easy) EXCLUDED — no Easy button
    # Initial difficulty: D0(G) = w4 - exp(w5*(G-1)) + 1
    "w4": 6.4133,
    "w5": 0.8334,
    # Difficulty update: ΔD = -w6*(G-3); damped; mean-revert w7 toward D0(3)
    "w6": 3.0194,
    "w7": 0.001,       # 0.1% reversion — NOT 5% like lite
    # Stability growth on success: SInc = 1 + exp(w8)*(11-D)*S^-w9*(exp(w10*(1-R))-1)*hard_penalty
    "w8": 1.8722,
    "w9": 0.1666,
    "w10": 0.796,
    # Post-lapse: S' = w11 * D^-w12 * ((S+1)^w13 - 1) * exp(w14*(1-R)), capped at S
    "w11": 1.4835,
    "w12": 0.0614,
    "w13": 0.2629,
    "w14": 1.6483,
    # Hard penalty (grade=2)
    "w15": 0.6014,
    # w16 (Easy bonus) EXCLUDED
    # w17-w19 (short-term) EXCLUDED
    # w20 (decay) EXCLUDED — use fixed -0.5
}

# Forgetting curve: R = (1 + FACTOR * t/S)^DECAY
# With DECAY=-0.5: FACTOR = 0.9^(-1/DECAY) - 1 = 0.9^2 - 1 = -0.19 → use alt form
# v5_2.py uses: FACTOR = 19/81, DECAY = -0.5  →  R = (1 + 19/81 * t/S)^-0.5
# At t=S: R = (1 + 19/81)^-0.5 = (100/81)^-0.5 = 0.9 exactly
DSR_FACTOR = 19.0 / 81.0      # 0.234567...
DSR_DECAY = -0.5
DESIRED_RETENTION_DEFAULT = 0.85

# Interval modifier for desired_retention:
# I = S * ((r^(1/DECAY) - 1) / FACTOR)
# For r=0.85, DECAY=-0.5, FACTOR=19/81:
# I = S * ((0.85^-2 - 1) / (19/81)) = S * ((1/0.7225 - 1) * 81/19)
#   = S * ((1.384 - 1) * 4.263) = S * 1.637
```

---

## 3. HELPER FUNCTIONS — EXACT SIGNATURES & LOGIC

```python
def _dsr_retrievability(elapsed_days: float, stability: float) -> float:
    """R(t, S) = (1 + FACTOR * t/S)^DECAY, clamp S>=0.1, t>=0"""
    stability = max(0.1, stability)
    t = max(0.0, elapsed_days)
    return (1.0 + DSR_FACTOR * t / stability) ** DSR_DECAY


def _dsr_interval_days(stability: float, desired_retention: float = DESIRED_RETENTION_DEFAULT) -> float:
    """Invert R(t,S) for desired_retention → interval in days"""
    # r = (1 + FACTOR * I/S)^DECAY
    # r^(1/DECAY) = 1 + FACTOR * I/S
    # I = S * (r^(1/DECAY) - 1) / FACTOR
    stability = max(0.1, stability)
    inv = desired_retention ** (1.0 / DSR_DECAY) - 1.0
    return stability * inv / DSR_FACTOR


def _dsr_s0(grade: int) -> float:
    """Initial stability from first review grade (1=Again, 2=Hard, 3=Good)"""
    return {1: DSR_W["w0"], 2: DSR_W["w1"], 3: DSR_W["w2"]}[grade]


def _dsr_d0(grade: int) -> float:
    """Initial difficulty from first review grade: D0 = w4 - exp(w5*(G-1)) + 1, clamped [1,10]"""
    d0 = DSR_W["w4"] - math.exp(DSR_W["w5"] * (grade - 1)) + 1.0
    return max(1.0, min(10.0, d0))


def _dsr_update_difficulty(d: float, grade: int) -> float:
    """
    FSRS-6 difficulty update:
      Δd = -w6 * (G - 3)
      d_damped = d + Δd * (10 - d) / 9
      d_reverted = w7 * D0(3) + (1 - w7) * d_damped
    Clamped [1, 10].
    """
    delta_d = -DSR_W["w6"] * (grade - 3)
    d_damped = d + delta_d * (10.0 - d) / 9.0
    d0_good = _dsr_d0(3)  # D0 for Good grade — reversion target
    d_reverted = DSR_W["w7"] * d0_good + (1.0 - DSR_W["w7"]) * d_damped
    return max(1.0, min(10.0, d_reverted))


def _dsr_update_stability(d: float, s: float, r: float, grade: int) -> float:
    """
    FSRS-6 stability update:
      If grade == 1 (Again/lapse):
        S' = w11 * d^-w12 * ((s+1)^w13 - 1) * exp(w14*(1-r))
        return max(0.1, min(S', s))  # cap: never exceed pre-lapse stability
      Else (Hard=2, Good=3):
        hard_penalty = w15 if grade == 2 else 1.0
        SInc = 1 + exp(w8) * (11-d) * s^-w9 * (exp(w10*(1-r)) - 1) * hard_penalty
        return s * max(1.0, SInc)  # SInc>=1: passing grade never shrinks S
    """
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
    s_inc = (
        1.0
        + math.exp(DSR_W["w8"])
        * (11.0 - d)
        * (s ** -DSR_W["w9"])
        * (math.exp(DSR_W["w10"] * (1.0 - r)) - 1.0)
        * hard_penalty
    )
    return s * max(1.0, s_inc)
```

---

## 4. CARD DATACLASS — EXACT FIELDS

```python
@dataclass
class Card:
    id: int
    origin: Literal["query", "ai"] = "ai"
    
    # DSR fields (used when mastery_model="dsr")
    stability: float = 0.0          # 0 = not initialized; set after first exposure
    difficulty: float = 0.0         # 0 = not initialized
    last_review: Optional[int] = None
    
    # Legacy fields (used by legacy/lite models)
    idx: int = -1                   # -1 = pending (never reviewed)
    score: float = 2.0
    streak: int = 0
    next_review: Optional[int] = None
    due_since: Optional[int] = None
    ease: float = 1.0
    
    # First-exposure flag (NEW — used by all models)
    first_exposure_done: bool = False
```

**Initialization rules:**
- `Card(...)` creates pending card: `idx=-1`, `next_review=None`, `stability=0`, `difficulty=0`, `first_exposure_done=False`
- On first exposure (in review loop), stability/difficulty initialized from grade via `_dsr_s0`/`_dsr_d0`

---

## 5. SIMCONFIG — EXACT DEFINITION

```python
MasteryModel = Literal["legacy", "lite", "dsr"]

@dataclass
class SimConfig:
    plan: str = "free"
    persona: str = "average"
    proficiency: str = "intermediate"
    days: int = 180
    seed: Optional[int] = 42
    jitter: float = 0.15
    
    # Feature flags (all models)
    enable_rejection: bool = True
    enable_catchup: bool = True
    enable_session_rate_limit: bool = True
    
    # Legacy/lite specific
    enable_continuous_mastery: bool = True   # used when mastery_model="lite"
    
    # DSR specific
    mastery_model: MasteryModel = "dsr"
    desired_retention: float = DESIRED_RETENTION_DEFAULT
    
    # Premium overrides
    sessions_override: Optional[int] = None
    session_size_override: Optional[int] = None
```

---

## 6. FIRST-EXPOSURE GRADING — THE NEW FEATURE

**This is the key behavioral change.** In `simulate()` review loop, when a card has `first_exposure_done=False`:

```python
def _handle_first_exposure(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> tuple[str, float, float]:
    """
    Returns (grade_label, stability, difficulty) for first exposure.
    grade_label in {"forget", "hold", "advance"} → maps to grade 1/2/3.
    """
    # Performance draw: same blend as subsequent reviews
    base_success = 1.0 - persona["forget"]
    r_at_first = 1.0  # brand new card: retrievability = 1.0
    noise = rng.uniform(-PERFORMANCE_NOISE, PERFORMANCE_NOISE)
    performance = max(0.0, min(1.0,
        (1 - PERFORMANCE_RETRIEVABILITY_WEIGHT) * base_success
        + PERFORMANCE_RETRIEVABILITY_WEIGHT * r_at_first
        + noise))
    
    # Map to grade
    if performance >= PERFORMANCE_SUCCESS_THRESHOLD:      # 0.75
        grade = 3      # advance
    elif performance >= PERFORMANCE_PARTIAL_THRESHOLD:    # 0.40
        grade = 2      # hold
    else:
        grade = 1      # forget
    
    # Initialize DSR state from grade
    if cfg.mastery_model == "dsr":
        stability = _dsr_s0(grade)
        difficulty = _dsr_d0(grade)
    else:
        # Lite/legacy: use their init logic (stability=1.0, difficulty=5.0 etc)
        stability = STABILITY_INITIAL  # 1.0
        difficulty = DIFFICULTY_DEFAULT  # 5.0
    
    # Compute first interval
    if cfg.mastery_model == "dsr":
        interval = _dsr_interval_days(stability, cfg.desired_retention)
        next_review = day + max(1, round(interval * (1.0 + rng.uniform(-cfg.jitter, cfg.jitter))))
    else:
        # Lite/legacy: first interval = 1 day
        next_review = day + 1
    
    grade_label = {1: "forget", 2: "hold", 3: "advance"}[grade]
    return grade_label, stability, difficulty, next_review
```

**In `simulate()` review loop:**
```python
if c.first_exposure_done is False or c.next_review is None:
    # First exposure — grade it!
    grade_label, stability, difficulty, next_review = _handle_first_exposure(...)
    c.stability = stability
    c.difficulty = difficulty
    c.next_review = next_review
    c.last_review = day
    c.first_exposure_done = True
    c.reviews = 1 if grade_label != "forget" else 0  # only count non-forget?
    if grade_label != "forget":
        c.idx = 0  # or whatever the model expects
    # add to active if not already
    if c.id not in active_ids:
        active.append(c)
        active_ids.add(c.id)
        total_active_words += 1
    continue  # skip rest of review logic
```

---

## 7. _REVIEW_OUTCOME_DSR — SUBSEQUENT REVIEWS

```python
def _review_outcome_dsr(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    """Returns grade label: 'forget'|'hold'|'advance'. Mutates card in place."""
    elapsed = day - (card.last_review if card.last_review is not None else day)
    r = _dsr_retrievability(elapsed, card.stability)
    
    # Performance draw
    base_success = 1.0 - persona["forget"]
    noise = rng.uniform(-PERFORMANCE_NOISE, PERFORMANCE_NOISE)
    performance = max(0.0, min(1.0,
        (1 - PERFORMANCE_RETRIEVABILITY_WEIGHT) * base_success
        + PERFORMANCE_RETRIEVABILITY_WEIGHT * r
        + noise))
    
    # Grade mapping
    if performance >= PERFORMANCE_SUCCESS_THRESHOLD:      # 0.75
        grade = 3      # advance
    elif performance >= PERFORMANCE_PARTIAL_THRESHOLD:    # 0.40
        grade = 2      # hold
    else:
        grade = 1      # forget
    
    # Update DSR state
    card.difficulty = _dsr_update_difficulty(card.difficulty, grade)
    card.stability = _dsr_update_stability(card.difficulty, card.stability, r, grade)
    card.last_review = day
    card.reviews += 1
    card.due_since = None
    
    # Next interval
    interval = _dsr_interval_days(card.stability, cfg.desired_retention)
    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
    card.next_review = day + max(1, round(interval * jitter))
    
    return {1: "forget", 2: "hold", 3: "advance"}[grade]
```

**Constants used (defined at module top):**
```python
PERFORMANCE_NOISE = 0.15
PERFORMANCE_RETRIEVABILITY_WEIGHT = 0.5
PERFORMANCE_SUCCESS_THRESHOLD = 0.75
PERFORMANCE_PARTIAL_THRESHOLD = 0.40
```

---

## 8. SIMULATE() — DISPATCH LOGIC

```python
def simulate(cfg: SimConfig, debug: bool = False):
    # ... setup same as v5 ...
    
    for day in range(cfg.days):
        # ... queries, due collection, slot allocation (IDENTICAL to v5) ...
        
        # REVIEW LOOP — dispatch by mastery_model
        for c in candidates:
            if cfg.mastery_model == "dsr":
                if not c.first_exposure_done:
                    _handle_first_exposure(c, persona, cfg, day, rng)
                else:
                    _review_outcome_dsr(c, persona, cfg, day, rng)
            elif cfg.mastery_model == "lite":
                # v5 lite logic with first-exposure added
                _review_outcome_lite(c, persona, cfg, day, rng)
            else:  # legacy
                _review_outcome_legacy(c, persona, cfg, day, rng)
        
        # ... catch-up, row append ...
    
    # SUMMARY — unified fields
    if cfg.mastery_model == "dsr":
        learned = sum(1 for c in active if c.stability >= 21.0)
        avg_stability = mean(c.stability for c in active) if active else 0
        avg_difficulty = mean(c.difficulty for c in active if c.difficulty > 0) if active else 0
        retrievabilities = [_dsr_retrievability(cfg.days - 1 - (c.last_review or cfg.days-1), c.stability) for c in active]
        avg_retrievability = mean(retrievabilities) if retrievabilities else 0
        tier_counts = Counter(_dsr_tier(c.stability) for c in active)
    else:
        # legacy/lite existing logic
        learned = sum(1 for c in active if c.stability >= LEARNED_MIN_STABILITY_DAYS or c.reviews >= LEARNED_MIN_REVIEWS)
        avg_stability = mean(c.stability for c in active) if active else 0
        # ... etc
```

---

## 9. SUMMARY FIELDS — UNIFIED OUTPUT

Both models return same keys (DSR adds extras):

```python
summary = {
    # Common
    "plan", "persona", "proficiency",
    "enable_rejection", "enable_catchup", "enable_session_rate_limit",
    "mastery_model": cfg.mastery_model,
    "desired_retention": cfg.desired_retention if cfg.mastery_model == "dsr" else None,
    "sessions_effective", "session_size_effective",
    "days",
    "total_active_words",
    "created_by_query", "created_by_ai",
    "total_ai_calls", "total_rejected_ai", "total_bonus_due",
    "final_active_cards", "learned_words",
    "avg_stability_days", "median_stability_days", "p90_stability_days",
    "avg_retrievability", "median_retrievability",
    "avg_difficulty",
    "max_due_backlog", "median_due_backlog", "p90_due_backlog",
    "max_query_backlog",
    "avg_lateness_days", "median_lateness_days", "p90_lateness_days", "max_lateness_days",
    "archived_lost_words": 0,
    "avg_ai_gen_per_day", "total_ai_cost_usd", "learned_words_per_dollar",
    # DSR-only
    "tier_counts": dict(tier_counts) if cfg.mastery_model == "dsr" else None,
}
```

---

## 10. TEST SPEC — `tests/test_v5_dsr_fixed.py`

```python
# test_dsr_helpers.py
def test_dsr_s0():
    assert _dsr_s0(1) == 0.212
    assert _dsr_s0(2) == 1.2931
    assert _dsr_s0(3) == 2.3065

def test_dsr_d0():
    # D0(G) = w4 - exp(w5*(G-1)) + 1
    # G=1: 6.4133 - exp(0) + 1 = 6.4133
    # G=2: 6.4133 - exp(0.8334) + 1 = 6.4133 - 2.301 + 1 = 5.112
    # G=3: 6.4133 - exp(1.6668) + 1 = 6.4133 - 5.294 + 1 = 2.119
    d1 = _dsr_d0(1)
    d2 = _dsr_d0(2)
    d3 = _dsr_d0(3)
    assert abs(d1 - 6.4133) < 0.001
    assert 5.1 < d2 < 5.2
    assert 2.1 < d3 < 2.2

def test_retrievability():
    # R(S, S) = 0.9 exactly
    r = _dsr_retrievability(10.0, 10.0)
    assert abs(r - 0.9) < 0.001

def test_interval():
    # At r=0.85, I = S * 1.637
    i = _dsr_interval_days(10.0, 0.85)
    assert abs(i - 16.37) < 0.1

def test_stability_growth_first_review():
    # First review Good: S0=2.3065
    s = _dsr_s0(3)
    assert abs(s - 2.3065) < 0.001

def test_stability_growth_subsequent():
    # S=30, D=5, R=0.9, grade=3 (Good)
    # SInc = 1 + exp(1.8722)*(11-5)*30^-0.1666*(exp(0.796*0.1)-1)
    # exp(1.8722)=6.503; 30^-0.1666=0.556; exp(0.0796)-1=0.0829
    # SInc = 1 + 6.503*6*0.556*0.0829 = 1 + 1.79 = 2.79
    # S_new = 30 * 2.79 = 83.7
    s_new = _dsr_update_stability(5.0, 30.0, 0.9, 3)
    assert 80 < s_new < 90

def test_lapse_cap():
    # Post-lapse S never exceeds pre-lapse S
    s_new = _dsr_update_stability(5.0, 100.0, 0.5, 1)
    assert s_new <= 100.0
    assert s_new >= 0.1

# test_first_exposure.py
def test_first_exposure_dsr():
    # Simulate first exposure with known seed
    # Verify stability/difficulty set from grade

# test_compare_three_models.py
def test_quality_gates():
    for plan in ["silver", "gold"]:
        for persona in ["lazy", "average", "eager"]:
            for days in [90, 180, 360]:
                cfg_lite = SimConfig(plan, persona, "intermediate", days, seed=42, mastery_model="lite")
                cfg_dsr = SimConfig(plan, persona, "intermediate", days, seed=42, mastery_model="dsr")
                _, s_lite = simulate(cfg_lite)
                _, s_dsr = simulate(cfg_dsr)
                
                # DSR learned >= Lite - 10%
                assert s_dsr["learned_words"] >= s_lite["learned_words"] * 0.9
                # DSR learned/$ >= Lite
                assert s_dsr["learned_words_per_dollar"] >= s_lite["learned_words_per_dollar"] * 0.9
                # DSR backlog <= Lite + 10%
                assert s_dsr["max_due_backlog"] <= s_lite["max_due_backlog"] * 1.1
                # DSR lateness <= Lite
                assert s_dsr["avg_lateness_days"] <= s_lite["avg_lateness_days"] * 1.1
```

---

## 11. MIGRATION CHECKLIST FROM v5_dsr.py

| Component | Action |
|-----------|--------|
| Module docstring | Replace with v5_dsr_fixed description |
| Constants | Replace with DSR_W + FACTOR/DECAY/RETENTION |
| Card dataclass | Add `stability`, `difficulty`, `last_review`, `first_exposure_done`; keep legacy |
| SimConfig | Add `mastery_model`, `desired_retention`; keep `enable_continuous_mastery` |
| `_review_outcome` | Split into `_review_outcome_legacy`, `_review_outcome_lite`, `_review_outcome_dsr` + `_handle_first_exposure` |
| `simulate()` | Add dispatch by `cfg.mastery_model`; unify summary fields |
| `format_table` | Handle `tier_counts` for DSR |
| `write_csv` | Unchanged |

---

## 12. EXECUTION ORDER

1. **Create plan file** ← THIS FILE
2. **Write v5_dsr_fixed.py** — constants, helpers, Card, SimConfig, review functions, simulate
3. **Write tests/test_v5_dsr_fixed.py** — all test modules
4. **Run tests** — verify quality gates pass
5. **Run benchmark** — compare three models across matrix
6. **Write README_DSR_FIXED.md**

---

## 13. SAFETY / ROLLBACK

- Original `v5_dsr.py` and `v5_dsr_2.py` **unchanged**
- New file `v5_dsr_fixed.py` independent
- Tests in `tests/test_v5_dsr_fixed.py` isolated
- If DSR fails quality gates → `mastery_model="lite"` remains default in production config

---

*Plan locked. Ready for implementation.*