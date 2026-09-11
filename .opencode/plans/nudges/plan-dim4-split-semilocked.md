---
name: plan-dim4-split-semilocked
description: Semi-locked entitlement split for dimension 4 (free vs premium, #467)
created: 2026-09-07
base_commit: ab8163d
branch: docs/dim1-lock
status: in-progress
---
STATE: dim 4/7 — status: SEMI-LOCKED (awaiting owner confirmation) — focus: resolve conflicts with earlier locks, then Contract Lock Gate

## Semi-locked rules (owner + Gemini text, verbatim substance)

- RULE-SPLIT-01 effort/retention FREE: streak + last_active read for all; S/D 4-stage distribution (garden labels) full in /status + summaries; tomorrow-due count free; heat engine visible to free; base XP (1/graded card) open to all (explicitly overriding ROADMAP #108 restriction for base tier).
- RULE-SPLIT-02 shields/rescue (BF-3): source of truth = `plans.streak_shields` integer column. Free: 2 max, refill via 7-day streak challenge or monthly boundary. Premium (Bronze/Silver/Gold/Emerald): 4 max, auto-refill monthly. Retroactive rescue: Free DISABLED (reset to 1); Premium up to 48h post-lapse, max 1/month.
- RULE-SPLIT-03 leeches: difficult = consecutive fail grades >= threshold. Count visible free (session + /status). Drill session [backlog bypass, targeted] = premium only.
- RULE-SPLIT-04 analytics: free = session + current-day only; premium = 30-day trends, stability curves, velocity. Guardrail: review_events aggregations never on hot path; async + cached daily.
- RULE-SPLIT-05: forecast simulation DROPPED (bounded sessions make it irrelevant; zero cost).

## Conflicts with earlier locks (flagged, not decided)
1. Shield capacity/source: earlier lock said free 1 / premium 2 per 30d window in `streak_events` table with auto-consume on 1-day miss for ALL. This doc says `plans.streak_shields` column, free 2 / premium 4 monthly, free rescue DISABLED. Source, numbers, and free behavior all differ — needs reconciliation before implementation.
2. ROADMAP #108 override for base XP needs explicit owner confirmation against ROADMAP (AGENTS.md: roadmap is product direction; issues are registry).
3. Leech drill session bypassing quota is NEW scope (quota bypass needs atomicity design + tests).
4. BF-1/BF-4 + SPEC-STREAK-2026-08-19-V3 referenced for reconciliation — those docs must be read at implementation time.

## Evidence
- Owner + Gemini dimension-4 text 2026-09-07.
- dims 1,5,6 LOCKED; dim 2 HALF-LOCKED; dims 3,7 PENDING.

## Blocked Questions
- Conflict 1 (shield source/numbers/free-rescue), conflict 2 (#108 override), plus pre-lock checks from dim 2.
