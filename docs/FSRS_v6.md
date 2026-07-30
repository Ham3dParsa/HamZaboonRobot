Below is the comprehensive summary of the FSRS-6 algorithm, derived from the official wiki, source code (ts-fsrs, py-fsrs, fsrs-rs, fsrs-optimizer), Expertium's technical explanation, and the original KDD paper.

---

# FSRS-6: Complete Algorithm Reference

## 1. The 21 Parameters (w₀ through w₂₀)

Default values and their roles:

| Index | Default | Symbol | Meaning | Clamp Range |
|-------|---------|--------|---------|-------------|
| w₀ | 0.212 | S₀(Again) | Initial stability after rating=1 (Again) | [0.001, 100] |
| w₁ | 1.2931 | S₀(Hard) | Initial stability after rating=2 (Hard) | [0.001, 100] |
| w₂ | 2.3065 | S₀(Good) | Initial stability after rating=3 (Good) | [0.001, 100] |
| w₃ | 8.2956 | S₀(Easy) | Initial stability after rating=4 (Easy) | [0.001, 100] |
| w₄ | 6.4133 | D₀ base | Initial difficulty base value | [1.0, 10.0] |
| w₅ | 0.8334 | D₀ multiplier | Initial difficulty rating offset | [0.001, 4.0] |
| w₆ | 3.0194 | ΔD multiplier | Next difficulty rating offset | [0.001, 4.0] |
| w₇ | 0.001 | Mean reversion weight | Controls reversion toward D₀(4) | [0.001, 0.75] |
| w₈ | 1.8722 | Scale factor | Base scaling for stability growth after success | [0.0, 4.5] |
| w₉ | 0.1666 | Stability decay exponent | S^{-w₉} term — diminishing returns on high S | [0.0, 0.8] |
| w₁₀ | 0.796 | Retrievability exponent | e^{w₁₀(1-R)} term — spacing effect | [0.001, 3.5] |
| w₁₁ | 1.4835 | Fail stability multiplier | Base scale for post-lapse stability | [0.001, 5.0] |
| w₁₂ | 0.0614 | Fail difficulty exponent | D^{-w₁₂} — difficulty's role in failure | [0.001, 0.25] |
| w₁₃ | 0.2629 | Fail stability exponent | (S+1)^{w₁₃} - 1 — prior S influence | [0.001, 0.9] |
| w₁₄ | 1.6483 | Fail retrievability exponent | e^{w₁₄(1-R)} — how R affects failure S | [0.0, 4.0] |
| w₁₅ | 0.6014 | Hard penalty | Multiplier when G=2 (Hard) | [0.0, 1.0] |
| w₁₆ | 1.8729 | Easy bonus | Multiplier when G=4 (Easy) | [1.0, 6.0] |
| w₁₇ | 0.5425 | Short-term exponent | Same-day review: grade effect | [0.0, 2.0] |
| w₁₈ | 0.0912 | Short-term offset | Same-day review: grade offset | [0.0, 2.0] |
| w₁₉ | 0.0658 | Short-term S decay | Same-day review: S^{-w₁₉} | [0.01, 0.8] |
| w₂₀ | 0.1542 | Decay (forgetting curve) | Power-law decay exponent w₂₀ | [0.1, 0.8] |

---

## 2. Complete Formulas

### 2.1 Retrievability (Forgetting Curve)

\[
R(t, S) = \left(1 + \text{FACTOR} \cdot \frac{t}{9S}\right)^{\text{DECAY}}
\]

Where:
- \(\text{DECAY} = -w_{20}\) (note: in ts-fsrs formula, the exponent shows as DECAY directly, which equals \(-w_{20}\))
- \(\text{FACTOR} = 0.9^{-1/\text{DECAY}} - 1\)

This is carefully engineered so that when \(t = S\) (elapsed time equals stability), \(R = 0.9\) (90%). The proof: at \(t = S\), \(1 + \text{FACTOR} \cdot \frac{S}{9S} = 1 + \frac{\text{FACTOR}}{9} = 0.9^{-1/\text{DECAY}}\), and raising to DECAY gives exactly 0.9.

**Alternative form** (from the official wiki, more commonly cited):

\[
R(t,S) = \left(1 + \text{factor} \cdot \frac{t}{S}\right)^{-w_{20}},
\quad \text{factor} = 0.9^{-\frac{1}{w_{20}}} - 1
\]

These two forms are equivalent. The ts-fsrs uses DECAY = \(-w_{20}\), so the exponent becomes \((-w_{20})\) and the expression becomes \((1 + \text{factor} \cdot t/(9S))^{-w_{20}}\). The wiki uses \((1 + \text{factor} \cdot t/S)^{-w_{20}}\) with a different factor definition.

**Core property:** When \(t = S\), \(R = 0.9\). Stability is defined as the time it takes for retrievability to decay from 100% to 90%.

### 2.2 Initial Stability (First Review, No Prior State)

\[
S_0(G) = w_{G-1}
\]

Where \(G \in \{1, 2, 3, 4\}\) corresponding to Again, Hard, Good, Easy.

So:
- \(S_0(\text{Again}) = w_0 = 0.212\)
- \(S_0(\text{Hard}) = w_1 = 1.2931\)
- \(S_0(\text{Good}) = w_2 = 2.3065\)
- \(S_0(\text{Easy}) = w_3 = 8.2956\)

Clamped: \(S_0 = \max(S_0, 0.1)\).

### 2.3 Initial Difficulty (First Review)

\[
D_0(G) = w_4 - e^{w_5 \cdot (G-1)} + 1
\]

Then clamped: \(D_0 = \min(\max(D_0, 1), 10)\).

Note: \(D_0(3) = w_4 - e^{w_5 \cdot 2} + 1\) for Good (G=3). The formula is designed so that \(D_0(1) = w_4\) (when rating is Again, G=1, the exponential term becomes \(e^{0}=1\), so \(D_0 = w_4 - 1 + 1 = w_4\)).

### 2.4 Stability After Successful Recall (Hard/Good/Easy)

\[
S'_r(D, S, R, G) = S \cdot \bigl(1 + e^{w_8} \cdot (11-D) \cdot S^{-w_9} \cdot (e^{w_{10}(1-R)} - 1) \cdot [G=2]\cdot w_{15} \cdot [G=4]\cdot w_{16} \bigr)
\]

Where:
- \(\text{hard\_penalty} = w_{15}\) if G=2, else 1.0
- \(\text{easy\_bonus} = w_{16}\) if G=4, else 1.0

**Alternatively expressed:**

\[
S'_r = S \cdot \text{SInc}
\]

\[
\text{SInc} = 1 + e^{w_8} \cdot (11-D) \cdot S^{-w_9} \cdot (e^{w_{10}(1-R)} - 1) \cdot \text{hard\_penalty} \cdot \text{easy\_bonus}
\]

Where:
- \(\text{hard\_penalty} = w_{15}\) if G=2, else 1
- \(\text{easy\_bonus} = w_{16}\) if G=4, else 1

**Guarantee:** SInc ≥ 1 for successful reviews (G ≥ 2). Stability never decreases on success.

**Four components (the DSR decomposition):**

1. **Difficulty term:** \(f(D) = (11-D)\) — Linear penalty. Harder cards (higher D) produce smaller stability gains. When D=10, \(f(D) = 1\) (no boost); when D=1, \(f(D) = 10\) (maximum boost).

2. **Stability term:** \(f(S) = S^{-w_9}\) — Diminishing returns. Higher stability → smaller SInc. Memory saturates.

3. **Retrievability term:** \(f(R) = e^{w_{10}(1-R)} - 1\) — Spacing effect. Lower R → larger SInc. Best time to review is just before forgetting.

4. **Grade modifiers:** w₁₅ (Hard penalty), w₁₆ (Easy bonus), and the base scale \(e^{w_8}\).

### 2.5 Stability After Forgetting (Again / Lapse)

\[
S'_f(D, S, R) = w_{11} \cdot D^{-w_{12}} \cdot ((S+1)^{w_{13}} - 1) \cdot e^{w_{14}(1-R)}
\]

Then clamped:
- If `enable_short_term = true`: \(S'_f \in [\max(S'_f, 0.01), \min(S, S/e^{w_{17} \cdot w_{18}})]\)
- If `enable_short_term = false`: \(S'_f \in [\max(S'_f, 0.01), S]\)

The key constraint: **post-lapse stability cannot exceed pre-lapse stability** (the \(\min(\ldots, S)\) guard). Also, if short-term mode is on, there is an even tighter upper bound: \(S / e^{w_{17} \cdot w_{18}}\).

**Four components:**

1. **Base scale:** \(w_{11}\) — overall scale for lapse stability
2. **Difficulty:** \(D^{-w_{12}}\) — Harder cards (higher D) have slightly smaller stability after failure (nonlinear, unlike the linear \(11-D\) in the success formula)
3. **Prior stability:** \((S+1)^{w_{13}} - 1\) — More stable cards retain more stability after a lapse
4. **Retrievability:** \(e^{w_{14}(1-R)}\) — The lower R was at review time, the larger the penalty (i.e., the more you've forgotten, the more stability drops)

### 2.6 Short-Term (Same-Day) Stability

For same-day reviews (t < 1 day, usually):

\[
S'_s(S, G) = S \cdot e^{w_{17} \cdot (G - 3 + w_{18})} \cdot S^{-w_{19}}
\]

With an additional guard: if G ≥ 3 (Good or Easy), ensure SInc ≥ 1 so stability does not decrease. Hard (G=2) and Again (G=1) can decrease S.

In some implementations:

\[
\text{SInc} = e^{w_{17} \cdot (G - 3 + w_{18})} \cdot S^{-w_{19}}
\]
\[
S'_s = S \cdot \text{SInc} \quad \text{with} \quad \text{SInc} \ge 1 \text{ if } G \ge 3
\]

### 2.7 Difficulty Update

**Step 1: Compute delta**

\[
\Delta_d = -w_6 \cdot (G - 3)
\]

**Step 2: Linear damping**

\[
D_{\text{damped}} = D + \Delta_d \cdot \frac{10 - D}{9}
\]

The damping term \(\frac{10-D}{9}\) ensures difficulty stays within [1, 10]. When D is near 1, the delta is scaled up; when D is near 10, the delta is scaled down.

**Step 3: Mean reversion toward D₀(Easy)**

\[
D' = w_7 \cdot D_0(4) + (1 - w_7) \cdot D_{\text{damped}}
\]

Where \(D_0(4) = w_4 - e^{w_5 \cdot 3} + 1\) (initial difficulty for Easy). The mean reversion pulls difficulty toward the initial Easy difficulty, preventing D from drifting to extreme values.

Then clamp: \(D' = \min(\max(D', 1), 10)\).

### 2.8 Next Interval Calculation

Given a desired retention \(r\) (default 0.9 = 90%):

\[
I(r, S) = \frac{S}{\text{FACTOR}} \cdot \left(r^{\frac{1}{\text{DECAY}}} - 1\right)
\]

Where DECAY and FACTOR are the same as in the forgetting curve (Section 2.1).

**Property:** When \(r = 0.9\), \(I = S\) (interval equals stability). For \(r < 0.9\), \(I > S\) (longer intervals); for \(r > 0.9\), \(I < S\) (shorter intervals).

In practice, the `interval_modifier` is precomputed from desired retention:

\[
\text{interval\_modifier} = \frac{r^{1/\text{DECAY}} - 1}{\text{FACTOR}}
\]

Then:

\[
\text{next\_interval} = \min(\max(1, \text{round}(S \cdot \text{interval\_modifier})), \text{maximum\_interval})
\]

Optional fuzzing is applied afterward to prevent cards from clustering on the same day.

---

## 3. How the 21 Parameters Are Used (Complete Map)

| w# | Used in Formula | Role |
|----|-----------------|------|
| w₀ | \(S_0(\text{Again})\) | Initial stability for first grade=1 |
| w₁ | \(S_0(\text{Hard})\) | Initial stability for first grade=2 |
| w₂ | \(S_0(\text{Good})\) | Initial stability for first grade=3 |
| w₃ | \(S_0(\text{Easy})\) | Initial stability for first grade=4 |
| w₄ | \(D_0(G) = w_4 - e^{w_5(G-1)} + 1\) | Base for initial difficulty |
| w₅ | \(D_0(G)\) exponent | Controls how initial D varies with grade |
| w₆ | \(\Delta_d = -w_6(G-3)\) | Rating offset for difficulty change |
| w₇ | \(D' = w_7 D_0(4) + (1-w_7)D_{\text{damped}}\) | Mean reversion strength toward D₀(Easy) |
| w₈ | \(S'_r: e^{w_8}\) scale factor | Base scaling for stability growth on success |
| w₉ | \(S'_r: S^{-w_9}\) term | Stability-dependent growth reduction (diminishing returns) |
| w₁₀ | \(S'_r: e^{w_{10}(1-R)} - 1\) | Retrievability-dependent spacing effect |
| w₁₁ | \(S'_f: w_{11}\) multiplier | Base scale for post-lapse stability |
| w₁₂ | \(S'_f: D^{-w_{12}}\) | Difficulty exponent in failure formula |
| w₁₃ | \(S'_f: (S+1)^{w_{13}} - 1\) | Prior stability influence on failure |
| w₁₄ | \(S'_f: e^{w_{14}(1-R)}\) | Retrievability's effect on failure penalty |
| w₁₅ | \(S'_r:\) multiplier when G=2 | Hard penalty (< 1, reduces growth) |
| w₁₆ | \(S'_r:\) multiplier when G=4 | Easy bonus (> 1, increases growth) |
| w₁₇ | \(S'_s: e^{w_{17}(G-3+w_{18})}\) | Short-term stability: grade effect |
| w₁₈ | \(S'_s:\) offset in exponent | Short-term stability: grade baseline |
| w₁₉ | \(S'_s: S^{-w_{19}}\) | Short-term: stability-dependent reduction |
| w₂₀ | \(R(t,S):\) decay exponent | Forgetting curve decay (trainable) |

---

## 4. Key Differences Between FSRS-6 and a Simplified "DSR-Lite" Model

Your simplified model proposal would differ from true FSRS-6 in the following important ways:

### 4.1 Stability Growth on Success

**FSRS-6:**
\[
S' = S \cdot \bigl(1 + e^{w_8} \cdot (11-D) \cdot S^{-w_9} \cdot (e^{w_{10}(1-R)} - 1) \cdot \text{modifiers}\bigr)
\]

**DSR-Lite (simplified linear):**
\[
S' = S \cdot \bigl(B + K \cdot (1-R) \cdot (10-D) / 9\bigr)
\]

**Key differences:**
- **S⁻ʷ⁹ term (w₉)**: FSRS-6 has \(S^{-w_9}\) which creates diminishing returns — as stability grows, further increases become harder. DSR-lite drops this, meaning stability growth is purely linear with no saturation. This is the single most important difference.
- **e^(w₁₀(1-R)) - 1 vs (1-R)**: FSRS-6 uses an exponential spacing effect (\(e^{w_{10}(1-R)} - 1\)), which is nonlinear. For R close to 1.0, the term is near 0 (no growth for immediate review). As R drops, it accelerates. DSR-lite uses a simple linear \((1-R)\) term.
- **Difficulty scaling**: FSRS-6 uses \((11-D)\), which is a simple linear penalty. DSR-lite also uses \((10-D)/9\) which normalizes to [0,1]. Similar in spirit, different in numeric range.
- **Grade modifiers**: FSRS-6 has separate learnable w₁₅ (Hard) and w₁₆ (Easy). DSR-lite would need equivalent constants or skip them.

**Practical impact of dropping S⁻ʷ⁹:** Without the \(S^{-w_9}\) term, stability grows linearly forever. In FSRS-6, as stability reaches high values (e.g., 365+ days), the growth rate approaches a limit defined by when \(\text{SInc} \to 1\). In DSR-lite, growth continues at a constant rate indefinitely. This can cause intervals to grow faster than they should for very mature cards.

### 4.2 Stability on Failure

**FSRS-6:**
\[
S'_f = w_{11} \cdot D^{-w_{12}} \cdot ((S+1)^{w_{13}} - 1) \cdot e^{w_{14}(1-R)}
\]

**DSR-lite (simple multiplicative reduction):**
\[
S'_f = S \cdot F \quad \text{or} \quad S'_f = \max(S_0, S \cdot F)
\]

**Key differences:**
- FSRS-6 uses a **nonlinear** formula with 4 distinct terms (scale, difficulty, prior stability, retrievability).
- The \((S+1)^{w_{13}} - 1\) term means the post-lapse stability depends on the original stability — more stable cards retain more stability after a lapse.
- The \(e^{w_{14}(1-R)}\) term means the retrievability at time of failure matters: if you failed at high R (surprise failure), the penalty is smaller; if you failed at low R (expected), the penalty is larger.
- The \(\min(S'_f, S)\) guard ensures post-lapse stability never exceeds pre-lapse stability.

**Practical impact:** A simple multiplicative post-lapse reduction (e.g., \(S' = S \cdot 0.3\)) would ignore all the nuance of difficulty and retrievability. Cards with high difficulty would be treated the same as easy cards. Failures that occurred at different R values would produce the same result.

### 4.3 The S⁻ʷ⁹ Term (w₉)

This is the **most distinctive feature** of FSRS-6's stability growth model. It captures **stabilization decay** — the empirical observation that as a memory becomes more stable, each additional unit of stability becomes harder to gain. Without it, stability growth is linear (each review adds a constant multiple). With it, the growth converges to an upper limit.

In practice, w₉ ≈ 0.17 means:
- At S=1: S⁻⁰·¹⁷ = 1.0
- At S=30: 30⁻⁰·¹⁷ ≈ 0.56 (44% reduction in SInc)
- At S=365: 365⁻⁰·¹⁷ ≈ 0.37 (63% reduction)

### 4.4 The e^(w₁₀(1-R)) Term

FSRS-6 uses an exponential spacing effect: \(e^{w_{10}(1-R)} - 1\). This captures diminishing sensitivity to R as R approaches 1.0, and accelerating returns as R drops. DSR-lite's \((1-R)\) is a simple linear approximation.

At default w₁₀ ≈ 0.8:
- R=0.95: \(e^{0.04} - 1 \approx 0.041\) (small gain)
- R=0.80: \(e^{0.16} - 1 \approx 0.174\) (moderate gain)
- R=0.60: \(e^{0.32} - 1 \approx 0.377\) (larger gain)

The linear \((1-R)\) would give 0.05, 0.20, 0.40 — similar at moderate R but diverges at extremes.

### 4.5 Summary Comparison Table

| Feature | FSRS-6 | DSR-Lite | Impact |
|---------|--------|----------|--------|
| Stability growth form | \(1 + e^{w_8}(11-D)S^{-w_9}(e^{w_{10}(1-R)}-1)\cdot mods\) | \(1 + B + K(1-R)(10-D)/9\) | FSRS-6 has diminishing returns (S⁻ʷ⁹) and exponential spacing (e^{w₁₀(1-R)}); DSR-lite is purely linear |
| S⁻ʷ⁹ term | Present (w₉ ≈ 0.17) | Absent | DSR-lite overestimates growth for high-stability cards |
| e^(w₁₀(1-R)) term | Present | (1-R) linear | DSR-lite less accurate at extreme R values near 1.0 or 0.0 |
| Failure formula | 4-term nonlinear: \(w_{11}D^{-w_{12}}((S+1)^{w_{13}}-1)e^{w_{14}(1-R)}\) | Simple multiplicative: S · factor | DSR-lite ignores difficulty and retrievability at failure; much less accurate |
| Difficulty update | Linear damping + mean reversion toward D₀(4) | Simple ±Δ per outcome | Similar in spirit; DSR-lite simpler but risks drift |
| Same-day reviews | Full formula with w₁₇, w₁₈, w₁₉ | Same or skipped | DSR-lite could reuse the same formula or skip short-term entirely |
| Parameters | 21 (w₀-w₂₀) | ~4-7 (BASE, SENSITIVITY, Δ±, F) | DSR-lite much cheaper to train; less accurate |
| Optimizability | Fully optimizable via SGD/MLE | Limited expressiveness | DSR-lite may not fit individual users well |

---

## 5. Academic References and Source Code

### Papers
1. **Ye, J., Su, J., & Cao, Y. (2022).** "A Stochastic Shortest Path Algorithm for Optimizing Spaced Repetition Scheduling." *Proceedings of the 28th ACM SIGKDD Conference on Knowledge Discovery and Data Mining*, 4381–4390. DOI: [10.1145/3534678.3539081](https://doi.org/10.1145/3534678.3539081). This is the original KDD paper describing the SSP-MMC algorithm that FSRS is based on. Note: the specific formulas have evolved significantly from the paper to FSRS-6.

2. **Ye, J., Su, J., & Cao, Y.** "Optimizing Spaced Repetition Schedule by Capturing the Dynamics of Memory." *IEEE TKDE* (under review / accepted). Follow-up journal paper.

### Official Documentation and Source Code

| Resource | URL |
|----------|-----|
| **Algorithm Wiki** (canonical) | https://github.com/open-spaced-repetition/awesome-fsrs/wiki/The-Algorithm |
| **ts-fsrs** (TypeScript reference implementation) | https://github.com/open-spaced-repetition/ts-fsrs |
| **py-fsrs** (Python implementation) | https://github.com/open-spaced-repetition/py-fsrs |
| **fsrs-rs** (Rust implementation) | https://github.com/open-spaced-repetition/fsrs-rs |
| **fsrs-optimizer** (PyTorch training) | https://github.com/open-spaced-repetition/fsrs-optimizer |
| **Expertium's technical explanation** | https://expertium.github.io/Algorithm.html |
| **Implementing FSRS in 100 Lines** | https://borretti.me/article/implementing-fsrs-in-100-lines |
| **awesome-fsrs** (collection of resources) | https://github.com/open-spaced-repetition/awesome-fsrs |

### Key source files for formula verification

- **TypeScript algorithm.ts**: https://github.com/open-spaced-repetition/ts-fsrs/blob/main/packages/fsrs/src/algorithm.ts
- **PyTorch model**: https://github.com/open-spaced-repetition/fsrs-optimizer/blob/main/src/fsrs_optimizer/fsrs_optimizer.py
- **Python scheduler**: https://github.com/open-spaced-repetition/py-fsrs/blob/main/fsrs/scheduler.py
- **Rust inference**: https://github.com/open-spaced-repetition/fsrs-rs/blob/main/src/inference.rs
- **TS constants and parameter bounds**: https://github.com/open-spaced-repetition/ts-fsrs/blob/main/packages/fsrs/src/constant.ts
- **Interactive Desmos graph of forgetting curves**: https://www.desmos.com/calculator/seqokdyixj

### Datasets
- **FSRS-Anki-20k**: https://github.com/open-spaced-repetition/FSRS-Anki-20k (20,000 Anki users' review logs)
- **anki-revlogs-10k**: https://github.com/open-spaced-repetition/anki-revlogs-10k (10,000 additional logs)

---

## 6. Final Notes on FSRS-6 vs FSRS-5 Changes

FSRS-6 (Anki 25.07+, 2025) introduced these changes from FSRS-5:
1. **Trainable forgetting curve decay** (w₂₀) — previously fixed at -0.5 in FSRS-5, now optimizable per user in [0.1, 0.8]; default changed to 0.1542.
2. **Short-term stability formula changed**: Added \(S^{-w_{19}}\) term (w₁₉ is new in FSRS-6) so that short-term stability increases also have diminishing returns via the \(S^{-w_{19}}\) factor (similar to w₉ for long-term).
3. **Performance improvements**: RMSE(bins) reduced ~6% from the new decay, ~5% from optimizable decay, ~2% from short-term formula change.
4. **Total parameters**: 19 → 21 (added w₁₉ specifically for same-day stability power term; w₂₀ for decay).
