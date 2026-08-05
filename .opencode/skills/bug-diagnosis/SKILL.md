---
name: bug-diagnosis
description: Bug Diagnosis — systematic reproduce → minimize → hypothesize → instrument → fix loop. Adapted from mattpocock/skills (diagnosing-bugs) and AGENTS.md error recovery. Load when debugging a failure, test failure, or unexpected behavior.
license: MIT
compatibility: opencode
metadata:
  category: debugging
  source: mattpocock/skills (diagnosing-bugs)
---
# Bug Diagnosis Skill (Pocock + AGENTS.md §7 Error Recovery adaptation)

## Purpose
Structured, evidence-based debugging that prevents thrashing and escalation. Aligns with AGENTS.md §7 Error Recovery Protocol.

## When to load
- Test failure (unit, integration, wiring, formatting)
- Unexpected runtime behavior
- CI failure on PR
- Any "it doesn't work" situation

## Diagnosis Loop (5 Steps)

### 1. REPRODUCE — Minimal deterministic repro
- Isolate the failure: specific test, command, or user flow
- Capture exact error output (stack trace, API error, assertion diff)
- Create minimal repro case if not already a test

### 2. MINIMIZE — Reduce to essence
- Strip away unrelated code/config
- Identify the smallest change that triggers the failure
- Binary search: bisect commits if regression, bisect code paths if new

### 3. HYPOTHESIZE — Root cause theory
- List candidate causes ranked by probability
- For each: predict what evidence would confirm/deny
- **Do NOT fix yet** — only theorize

### 4. INSTRUMENT — Targeted evidence gathering
- Add logging, assertions, or temporary test probes
- Run focused tests / commands to validate/invalidate hypotheses
- Use `graphify query "..."` / `graphify path A B` if structural
- Check wiring guards: `test_wiring.py`, `test_dead_code_guard.py`

### 5. FIX — Targeted correction
- Fix ONLY the demonstrated root cause
- No opportunistic "extra fixes" or speculative hardening (AGENTS.md §2.2)
- If safe workaround exists → document it, don't convert to permanent rule
- Write regression test if not already covered

## AGENTS.md §7 Error Recovery Protocol Integration

### After a validation failure:
1. **Analyze** stack trace/diff → identify root cause (Steps 1-3 above)
2. **Attempt fix** targeting specific failure (Step 5)
3. **Retry** full validation suite (Step 4 evidence)
4. **Only after 2 consecutive failed attempts**:
   - Reset state (`git reset HEAD~1` or discard staged)
   - Report exact error + context
   - HALT for human input

### This skill enforces:
- No immediate escalation to human
- Max 2 autonomous fix attempts per failure
- Evidence-based, not guess-based
- Debugging targets demonstrated root cause only

## Output
- Root cause statement with evidence
- Targeted fix (minimal diff)
- Regression test added/updated
- Validation suite passes
- Plan file updated with phase status