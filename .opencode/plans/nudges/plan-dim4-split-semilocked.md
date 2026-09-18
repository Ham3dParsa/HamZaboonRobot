---
name: plan-dim4-split-semilocked
description: Semi-locked entitlement split for dimension 4 (free vs premium, #467)
created: 2026-09-07
base_commit: ab8163d
branch: docs/dim1-lock
status: in-progress
---
STATE: dim 4/7 — status: LOCKED 2026-09-17 (owner bands 3,4,7,12; leech drill SPLIT-03 stays open scope) — focus: implementation tickets under this lock

## Locked rules (owner 2026-09-17, #467 comments 5721803668/5721810211/5721972921)

- RULE-SPLIT-01 effort/retention FREE: streak + last_active read for all; S/D 4-stage distribution (garden labels) full in /status + summaries; tomorrow-due count free; heat engine visible to free; base XP per Mode 2 lock (1/graded card + 3 completion bonus, milestone synced to ceil(N/2)) open to all. Session report + word-detail modal (#722) fully free by default, no premium gate or upsell (band 7). Review-hub concept (#106) deprecated and void (band 12).
- RULE-SPLIT-02 shields/rescue: source of truth = `plans.streak_shields` integer column. Caps: free 2, premium 3. Missed day with balance auto-consumes 1 (no 48h window, no manual rescue). Refill only via streak/milestone rewards; coin/shop deferred post-beta (band 4).
- RULE-SPLIT-03 leeches: difficult = consecutive fail grades >= threshold. Count visible free (session + /status). Drill session [backlog bypass, targeted] = premium only. OPEN: quota bypass is new scope — needs atomicity design + tests before lock.
- RULE-SPLIT-04 analytics: free = session + current-day only; premium = 30-day trends, stability curves, velocity. Future advanced analytics reviewed independently (band 7). Guardrail: review_events aggregations never on hot path; async + cached daily.
- RULE-SPLIT-05: forecast simulation DROPPED (bounded sessions make it irrelevant; zero cost).

## Conflicts with earlier locks (resolved 2026-09-17, except leech)
1. Shield capacity/source: RESOLVED by band 4 — `plans.streak_shields` column, free 2 / premium 3, auto-consume on missed day for all with balance. Earlier streak_events 1/2-per-30d text is void.
2. ROADMAP #108 vs base XP: RESOLVED by band 3 — Mode 2 XP lock is canonical; base tier open to all stands.
3. Leech drill session bypassing quota is NEW scope (quota bypass needs atomicity design + tests). OPEN.
4. BF-1/BF-4 + SPEC-STREAK-2026-08-19-V3: BF-1 resolved by band 15 (ceil(N/2)); streak spec superseded by band 1 one-sentence rule.

## Evidence
- Owner + Gemini dimension-4 text 2026-09-07.
- dims 1,5,6 LOCKED; dim 2 HALF-LOCKED; dims 3,7 PENDING.

## Blocked Questions
- SPLIT-03 leech drill quota bypass (open scope above). Everything else locked.
