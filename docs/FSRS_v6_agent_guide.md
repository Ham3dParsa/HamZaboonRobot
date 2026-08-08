# FSRS-6 Coding Agent Readiness & Integration Guide

## Why `FSRS_v6.md` is Now 100% Ready for AI Coding Agents

AI Coding Agents (such as OpenCode, Cursor, GitHub Copilot Workspace, and Devin) thrive on **unambiguous, deterministic specifications**. The revised reference file eliminates the common pitfalls that cause LLMs to generate bugs or hallucinations:

### 1. Single Source of Truth for Formulas

* **Previous Issue:** Having multiple variations of the forgetting curve $R(t,S)$ or ambiguous Iverson bracket syntax ($[G=2]$) forced LLMs to "guess" which logic branch to implement.

* **Now:** Standardized to a single canonical formula with explicit `hard_penalty` and `easy_bonus` conditions.

### 2. Concrete Reference Implementation (`update_state` Pseudocode)

* **Agent Benefit:** Section 3 provides a production-ready Python function. Coding agents can perform direct 1:1 transpilation into target languages (TypeScript, Rust, Go, C#, C++) with zero architectural ambiguity.

### 3. Explicit Boundary Conditions & Clamping

* **Agent Benefit:** LLMs often forget to clamp intermediate calculation results. Explicit guards are now embedded directly in the pseudocode:

  * $D \in [1.0, 10.0]$

  * $S_0 \ge 0.1$

  * $S'_f \le S$ (Post-lapse stability bound)

  * Short-term stability growth bounds ($S'_s \ge S$ for $G \ge 3$)

## Recommended Prompts for OpenCode / Coding Agents

When passing `FSRS_v6.md` to your coding agent, use the following structured prompt templates to achieve maximum code precision:

### Template 1: Generating a Core Engine Module (e.g., TypeScript / Rust)

> "Act as a Senior Software Engineer. Read the complete algorithm reference in `FSRS_v6.md`. Implement the FSRS-6 algorithm as a self-contained module in [TypeScript/Rust/Go/C#]. Strictly follow the `update_state` execution flow in Section 3, ensuring all clamping guards ($D \in [1,10]$, post-lapse bounds, and short-term rules) are enforced. Include comprehensive type definitions for `Card`, `ReviewLog`, `Parameters`, and `State`."

### Template 2: Generating Unit Tests

> "Based on `FSRS_v6.md`, generate a comprehensive suite of unit tests covering:
>
> 1. Initial review state creation for grades 1 through 4.
>
> 2. Success state transitions (Good/Easy) with diminishing stability returns ($S^{-w_9}$).
>
> 3. Failure/Lapse state transitions (Again) checking that post-lapse stability never exceeds pre-lapse stability.
>
> 4. Short-term intraday review bounds (elapsed_days = 0).
>
> 5. Difficulty damping and mean-reversion clamping ($1.0 \le D \le 10.0$)."

## Parameter Defaults Checklist for Testing

| **Test Case** | **Inputs** | **Expected Behavior** |
|---|---|---|
| First Review (Again) | Grade = 1 | $S = w_0 = 0.212$, $D = w_4 = 6.4133$ |
| First Review (Good) | Grade = 3 | $S = w_2 = 2.3065$, $D = 6.4133 - e^{2 w_5} + 1 \approx 2.146$ |
| Lapse Guard | High $S$, Grade = 1 | $S_{new} \le S_{old}$ always enforced |
| Difficulty Clamping | Grade = 1 repeatedly | $D$ capped at maximum $10.0$ |