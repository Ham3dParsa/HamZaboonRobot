# v5.3 Enhanced Report Plan — Percentile Metrics & v4-Inspired Structure

**Target:** `tools/Fsrs_simulation_v5/report_v5_compare.html` (overwrite with enhanced version)
**Input:** `v5.2_FSRSv6.py` (now fixed), `v5.1_dsr_mid.py`, `v5.0_dsr_lite.py`
**Scope:** Run all 40 scenarios × 3 versions, compute full percentile distributions, regenerate HTML with v4-style sections

---

## 1. Simulation Run Specification

### 1.1 Scenario Matrix (40 scenarios × 3 versions = 120 runs)

| Plan | Persona | Days | Proficiency | Rejection | Catchup | Rate Limit |
|------|---------|------|-------------|-----------|---------|------------|
| silver | eager/average/fluctuating/lazy | 90,180,360,540,720 | intermediate | false | true | true |
| gold | eager/average/fluctuating/lazy | 90,180,360,540,720 | intermediate | false | true | true |

**Seed:** 42 (fixed for reproducibility)
**Output per run:** Full daily log + summary + per-card state for percentile analysis

### 1.2 Metrics to Collect Per Run

From `simulate()` return value (already available):
- `learned_words`, `total_active_words`, `total_ai_calls`, `total_ai_cost_usd`, `learned_words_per_dollar`
- `max_due_backlog`, `median_due_backlog`, `p90_due_backlog`
- `max_query_backlog`
- `avg_lateness_days`, `median_lateness_days`, `p90_lateness_days`, `max_lateness_days`
- `avg_stability_days`, `median_stability_days`, `p90_stability_days`
- `avg_retrievability`, `median_retrievability`
- `avg_difficulty`
- `tier_counts` (DSR model only)

**Additional per-day metrics** (compute from daily log + card states):
- Daily lateness distribution (percentiles p50, p90, p95, p99)
- Daily due backlog distribution
- Daily active card count distribution
- Daily review count distribution
- Cards by tier per day (DSR only)

---

## 2. Required HTML Report Sections (v4-Inspired)

### Section 1: Scenario Matrix (v4 §1)
**Table:** All 40 scenarios × 3 versions with core metrics
**Columns:** Plan | Persona | Days | v5.0 Learned | v5.1 Learned | v5.2 Learned | v5.1/v5.0 | v5.2/v5.0 | v5.1/v5.2
**Color coding:** Green = best in row, Red = worst in row, Yellow = middle

### Section 2: Feature Toggle Isolation (v4 §2)
**Test:** gold/eager/intermediate, 360 days, all 3 versions
**Toggles per version:**
- DSR-mid (v5.1): rejection ON/OFF, catchup ON/OFF, continuous_mastery ON/OFF, session_rate_limit ON/OFF
- FSRS-6 Full (v5.2): same toggles (if applicable)
- DSR-lite (v5.0): rejection ON/OFF, catchup ON/OFF, continuous_mastery ON/OFF, session_rate_limit ON/OFF
**Columns:** Config | Learned | Avg Stability | Max Due | AI$ | Learned/$

### Section 3: Premium Config Override Band (v4 §3)
**Test:** gold plan defaults (4 sessions × 7 cards), test override requests
**Scenarios:** 4×7 (baseline), 5×9 (+30%), 6×12 (clamped), 2×4 (clamped), 1×1 (floor)
**Versions:** All 3 versions

### Section 4: Long-Run Stress Test — 720 Days (v4 §4)
**Table:** Plan × Persona with full metrics
**Columns:** Plan | Persona | Learned | Learned/$ | Max Due | Max QBL | Avg Late | Max Late | AI$ Total | p90 Late | p95 Late | p99 Late

### Section 5: Learning Curves Over Time (v4 §5)
**Checkpoints:** 30, 90, 180, 360, 720 days
**Persona:** gold/average/intermediate
**Metrics per checkpoint:** Active Words | Learned | Avg Stability | Avg Retrievability | AI$ Cumulative | Tier Distribution (DSR)
**Versions:** All 3 side-by-side

### Section 6: Version Comparison — 360 Days (v4 §6)
**Table:** Persona × Version with full metrics
**Columns:** Persona | Version | Learned | Avg Stability | Max Due | AI Calls | AI$ | Learned/$ | Avg Retrievability | Avg Difficulty | p90 Due Backlog | p90 Late

### Section 7: Percentile Deep-Dive (NEW)
**Per scenario (40 × 3 = 120 cards):**
- Lateness percentiles: p50, p90, p95, p99, max
- Due backlog percentiles: p50, p90, p95, p99, max
- Query backlog percentiles
- Active cards percentiles per day
- Review count distribution per day

### Section 8: Worst-Case Analysis (NEW)
**For each version, identify:**
- Top 5 scenarios by max lateness
- Top 5 scenarios by max due backlog
- Top 5 scenarios by max query backlog
- Top 5 scenarios by lowest learned/$

---

## 3. Implementation Plan

### Step 1: Create Data Collection Script
**File:** `tools/Fsrs_simulation_v5/generate_enhanced_report.py`
- Load all 3 modules via importlib
- Run all 120 simulations, collect:
  - Summary dict (from `simulate()`)
  - Full daily log
  - Debug data: active cards, lateness samples (when `debug=True`)
- Compute percentile metrics from debug data
- Store all in structured dict → JSON for HTML generation

### Step 2: Compute Percentile Metrics
For each run with `debug=True`:
```python
_, summary, debug = simulate(cfg, debug=True)
active = debug["active"]
lateness_samples = debug["lateness_samples"]

# Per-card lateness at final day
final_day = cfg.days - 1
card_lateness = [final_day - (c.last_review or final_day) for c in active if c.next_review and c.next_review <= final_day]

# Daily lateness samples already collected
# Compute percentiles (use statistics.quantiles for stdlib-only)
import statistics
def percentile(data, p):
    if not data: return 0
    return statistics.quantiles(sorted(data), n=100)[p-1]

p50 = percentile(lateness_samples, 50)
p90 = percentile(lateness_samples, 90)
p95 = percentile(lateness_samples, 95)
p99 = percentile(lateness_samples, 99)
max_late = max(lateness_samples) if lateness_samples else 0
```

### Step 3: Build Enhanced HTML Template
**Sections in order:**
1. Header + metadata
2. Scenario Matrix (Section 1)
3. Summary Dashboard (stat boxes per version)
4. Feature Toggle Isolation (Section 2)
5. Premium Config Override (Section 3)
6. Long-Run Stress 720d (Section 4)
7. Learning Curves (Section 5)
8. Version Comparison 360d (Section 6)
9. Percentile Deep-Dive (Section 7)
10. Worst-Case Analysis (Section 8)
11. Version Notes

**CSS enhancements:**
- `.p99 { background: #f8d7da; }` — red for p99
- `.p95 { background: #fff3cd; }` — yellow for p95
- `.p90 { background: #d1ecf1; }` — blue for p90
- `.best-row { background: #d4edda; }` — green row for best version
- `.worst-row { background: #f8d7da; }` — red row for worst version
- Sticky table headers
- Sortable tables (simple JS click-to-sort)

### Step 4: Regenerate HTML
- Run `generate_enhanced_report.py`
- Output overwrites `report_v5_compare.html`
- Also save raw data JSON for future analysis

---

## 4. Verification Checklist

| Check | Target |
|-------|--------|
| All 120 runs complete without error | ✓ |
| Scenario Matrix has 40 rows × 3 versions | ✓ |
| Feature Toggle table has 6 rows × 3 versions | ✓ |
| Override Band has 5 rows × 3 versions | ✓ |
| Long-Run 720d has 10 rows × 3 versions | ✓ |
| Learning Curves has 5 checkpoints × 3 versions | ✓ |
| Version Comparison 360d has 4 personas × 3 versions | ✓ |
| Percentile tables have p50/p90/p95/p99/max for lateness, backlog | ✓ |
| Worst-Case tables populated | ✓ |
| Color coding: green=best, red=worst per row/segment | ✓ |
| HTML opens in browser without JS errors | ✓ |
| Data matches v4 report structure where applicable | ✓ |

---

## 5. Files to Modify/Create

| File | Action |
|------|--------|
| `tools/Fsrs_simulation_v5/generate_enhanced_report.py` | **NEW** — main script |
| `tools/Fsrs_simulation_v5/report_v5_compare.html` | **OVERWRITE** — enhanced report |
| `tools/Fsrs_simulation_v5/enhanced_report_data.json` | **NEW** — raw data cache |

---

## 6. Dependencies

- Python standard library only (`importlib`, `json`, `statistics`, `csv`, `datetime`)
- No external deps (no numpy — use `statistics.quantiles` or manual percentile)
- Existing v5.0, v5.1, v5.2 modules unchanged

---

## 7. Rollback

```bash
git checkout tools/Fsrs_simulation_v5/report_v5_compare.html
```

---

## Status Tracker

| Step | Status | Notes |
|------|--------|-------|
| 1. Create data collection script | ⬜ TODO | |
| 2. Run all 120 simulations + percentile calc | ⬜ TODO | ~2-3 min |
| 3. Build enhanced HTML template | ⬜ TODO | |
| 4. Generate & verify report | ⬜ TODO | |
| 5. Cross-check against v4 report structure | ⬜ TODO | |