# Implementation Plan: Interactive Time-Lapse Simulator v1.2

> Status: **locked** — owner confirmed 2026-07-30
> Target file: `tools/Fsrs_simulation_v5/fsrs_simulator_v1.2.htm`
> Source base: `tools/Fsrs_simulation_v5/archive/fsrs_simulator_v1.1.html`

---

## 1. Plan Defaults Update

| Plan | Sessions | Session Size | AI Cap | Query Cap | Queue Days |
|------|----------|-------------|--------|-----------|------------|
| Free | 2 | 3 | 3 | 3 | 2 |
| Silver | 3 | 5 | 5 | 7 | 3 |
| Gold | 4 | 7 | 12 | 10 | 4 |
| **Platinum** 🆕 | **5** | **9** | **20** | **16** | **6** |

### AI Cap: Soft Boost for New Users

On `day <= 2`, if the user has `< ai_daily_cap × 2` active cards AND no due cards, the AI cap is doubled (bounded by total daily slots) to bootstrap the card pool. This only applies when there is no backlog pressure.

---

## 2. Full v5.4 Persona Model (Ported to JS)

### Persona definitions — Hebrew names and characteristics

| Persona | Attend | q_lo/q_hi | Save% | Grade Probs [A,H,G,E] | Completion | Response Time |
|---------|--------|-----------|-------|----------------------|------------|---------------|
| Eager | 0.92 | 2 / 6 | 0.70 | [0.02, 0.05, 0.60, 0.33] | 1.0 | (2, 5) |
| Average | 0.70 | 0 / 3 | 0.50 | [0.08, 0.15, 0.55, 0.22] | 0.85 | (3, 7) |
| Lazy | 0.35 | 0 / 1 | 0.30 | [0.15, 0.20, 0.50, 0.15] | 0.40 | (8, 15) |
| Fluctuating | 0.55±0.30 | 0 / 3 | 0.50 | [0.10, 0.15, 0.55, 0.20] | 0.60 | (4, 10) |
| **Gamer** 🆕 | **0.90** | **3 / 8** | **0.85** | **[0.01, 0.04, 0.35, 0.60]** | **1.0** | **(1, 3)** |

### Gamer Persona Design

- High attendance (90%) and query volume (3-8 daily)
- Saves almost everything (85%)
- **Grades aggressively:** 60% Easy base, almost never Again (1%)
- Fast response time (1-3s) — blasts through cards without thought
- At low retrievability (r ≈ 0.1), the gamer's Easy rate should drop to ~35-45% (vs ~5-10% for honest personas) — the gap is what the anti-gaming filter detects
- Purpose: compare with honest personas under same seed/plan → isolate the effect of grade inflation on learning outcomes and AI budget

### Grade Sampling (`_sample_grade`)

JavaScript implementation of the v5.4 Python logic:

```
GRADE_RETRIEVABILITY_SHIFT = 0.30
DIFFICULTY_GRADE_SHIFT = 0.25  (NEW: difficulty modulates grade choice)

shift_r = (1 - r) * GRADE_RETRIEVABILITY_SHIFT
d_norm = (d - 5.5) / 4.5  // -1 (easy) to +1 (hard)
shift_d = d_norm * DIFFICULTY_GRADE_SHIFT

probs[Again] += shift_r * 0.6 + shift_d * 0.5
probs[Hard]  += shift_r * 0.4 + shift_d * 0.5
probs[Good]  -= shift_r * 0.5 + shift_d * 0.5
probs[Easy]  -= shift_r * 0.5 + shift_d * 0.5

→ clamp to [0.01], renormalize, weighted sample
```

### First Exposure

Use `r = 0.5` instead of `1.0` for first-exposure grading (new cards should have higher Again probability than "perfect recall").

---

## 3. Time-Lapse Panel

### Position

Insert between `<div class="stat-tiers" id="tierBadges">` and the first `<div class="stats-group-title">` in the right sidebar.

### Controls

| Control | Type | Behavior |
|---------|------|----------|
| **Speed** | Slider (continuous) | 1s/card → MAX (instant). Magnetic preset stops at: 1s, 500ms, 200ms, 100ms, 50ms, 10ms, MAX |
| **Seed** | Number input | Default 42 |
| **🎲 Random** | Button | Generates random seed, updates input |
| **🔒 Lock** | Toggle button | Locked → seed persists across resets; unlocked → new random seed each reset |
| **▶ Play** | Button | Starts auto-play at current speed |
| **⏸ Pause** | Button | Pauses auto-play (same button toggles) |
| **⏭ Step** | Button | Advances exactly one card (works in pause or manual mode) |
| **Status indicator** | Label | Shows "Auto" / "Manual" / "Paused" + current speed label |

### Time-Lapse Behavior

| State | Behavior |
|-------|----------|
| **Auto-play (▶)** | At each card: `_sample_grade` runs → grade button highlights with glow animation (duration = speed) → `submitGrade` fires → auto-advance |
| **Manual click** | Interrupts auto-play → applies manual grade → pauses. User can hit Resume (▶) |
| **Resume (▶ after pause)** | Continues auto-play from current card |
| **MAX speed** | Runs entire simulation instantly, renders final state + all charts |
| **Step (⏭)** | Advances one card, stays in pause after |
| **Seed changed mid-sim** | Does nothing until next reset |

### Grade Button Highlight

When auto-play selects a grade, the button gets a temporary glow effect:
- `.grade-btn.again { box-shadow: 0 0 20px var(--again); }`
- Duration = speed setting (min 100ms, max 1s)
- Plays a brief CSS animation, then auto-advances

---

## 4. Day Options

Update `<select id="daysSelect">`:

```html
<option value="15">۱۵ روز</option>
<option value="30" selected>۳۰ روز</option>
<option value="90">۹۰ روز</option>
<option value="180">۶ ماه</option>
<option value="360">۱۲ ماه</option>
<option value="720">۲۴ ماه</option>
```

Default changes from 45 to 30.

---

## 5. Anti-Gaming Monitor (Research-Configurable)

### Design Principle

This is a **research tool** for studying the effect of grade inflation, not a production anti-abuse system. The penalty is OFF by default and toggleable.

### Monitor

- **Per-session Easy%:** After each session ends, compute `easy_count / session_total`
- **Window:** Last 3 sessions. If ANY of the last 3 sessions exceeds the threshold → flag
- **Threshold:** Easy > **50%** in a single session (configurable)
- **Live display:** In the time-lapse panel, show:
  ```
  Easy Rate (last 3 sess): 72% ⚠️ FLAGGED
  Penalty: -30% (effective AI cap: 8/day)
  ```

### Penalty

| If triggered | Effect | Affects |
|-------------|--------|---------|
| Any of last 3 sessions > 50% Easy | `ai_daily_cap *= (1 - penalty_ratio)` | Both AI daily cards AND AI query budget |

- **Default penalty ratio:** 0% (disabled)
- **Configurable:** Threshold (%), penalty ratio (%), on/off — all in the time-lapse panel

### Why Per-Session

| Approach | What it catches | Misses |
|----------|----------------|--------|
| Last 30-50 cards | Long-term trend | Burst gaming in one session |
| Per-session | Session with 7/9 Easy (78%) | Isolated bad sessions |
| **Hybrid: per-session + last 3** | Both burst and pattern | Single-session fluke (tolerated) |

The hybrid approach: flag if ANY session in the last 3 exceeds 50% Easy. A gamer will always have at least one such session.

---

## 6. UI Layout Changes

### Header controls update
- Add `platinum` option to plan select
- Replace day options (15, 30, 90, 180, 360, 720)
- Default day: 30

### Right sidebar
- Keep tier badges at top
- **Insert time-lapse panel** (collapsible section with controls + anti-gaming monitor)
- Then existing stats groups

---

## 7. Implementation Tracking

| Step | Component | Status |
|------|-----------|--------|
| 7.1 | Create new file as copy of v1.1, rename to `.htm` | Pending |
| 7.2 | Update PLAN_DEFAULTS + add platinum plan | Pending |
| 7.3 | Update day options dropdown | Pending |
| 7.4 | Port `_sample_grade` with difficulty modulation to JS | Pending |
| 7.5 | Add gamer persona to PERSONA + GRADE_PROBS | Pending |
| 7.6 | First exposure: change r=1.0 to r=0.5 | Pending |
| 7.7 | Build time-lapse panel HTML + CSS | Pending |
| 7.8 | Build time-lapse JS engine (play/pause/step/speed) | Pending |
| 7.9 | Build seed + lock UI + logic | Pending |
| 7.10 | Build grade button highlight animation for auto-play | Pending |
| 7.11 | Build anti-gaming monitor (per-session Easy%, window, display) | Pending |
| 7.12 | Wire everything: reset, play, step, speed change all update UI | Pending |
| 7.13 | Test: run each persona × 2 plans, verify grade distributions | Pending |
| 7.14 | Test: gamer persona triggers filter when penalty is ON | Pending |
| 7.15 | Final: verify file loads, no console errors, charts render | Pending |

---

## 8. Contract Lock Summary

```
Rule #: 1
Decision: Build interactive time-lapse simulator v1.2 from v1.1 base
Option Chosen: Full v5.4 model ported to JS + new UI features
Alternatives Rejected: Simpler JS-only approach (less accurate)
Trade-offs: Implementation effort higher, but simulation fidelity matches Python model
Owner Confirmation: "yeah lock it"
GATE STATUS: LOCKED
```
