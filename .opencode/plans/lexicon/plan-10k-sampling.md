---
name: plan-10k-sampling
description: Sample 3000 EN lemmas (~10k cards) with checkpoints; download Kaikki English-words dump
created: 2026-09-04
base_commit: 6ad2fb6
branch: research/lexicon-5k
status: in-progress
---
STATE: phase 0/3 — status: contract PENDING (owner chose all rules, lock word awaited) — focus: download dump + sampling script

## CONTRACT LOCK TEMPLATE

Rule #1 — Target size
Decision: sample 3000 lemmas for ~10,000 cards, built in resumable checkpoint batches
Option Chosen: 3000 + checkpoints (500 pilot gave 1676 cards = 3.35/lemma; 5000 would give ~16.7k, double the pool target)
Alternatives Rejected: 5000 lemmas (double LLM cost later for coverage we cannot review); 2400/8000 (below owner's 10k target)
Trade-offs: 3000 = ~1.5-2x pilot LLM cost later vs 5000 = ~3x; checkpoints cap any single run
Owner Confirmation: "Yes, 3000 + checkpoints" (awaiting final "locked")
GATE STATUS: PENDING

Rule #2 — CEFR mix
Decision: scale pilot mix x6 to 364/485/667/727/454/303 per level (sums 3000)
Option Chosen: scaled pilot proportions
Alternatives Rejected: even split 500/level (over-serves rare advanced words)
Trade-offs: preserves proven coverage shape; advanced tail stays thin by design
Owner Confirmation: scale pilot (awaiting final "locked")
GATE STATUS: PENDING

Rule #3 — Raw source
Decision: one-time download of kaikki.org-dictionary-English-words.jsonl (~3GB, text only, no audio) to W: on owner's PC
Option Chosen: download (< 10GB cap, PC faster)
Alternatives Rejected: Colab (upload/download dance every run); per-lemma fetch (repeats work)
Trade-offs: ~3GB disk once; all future sampling offline and free
Owner Confirmation: "ok dl them, text only" (awaiting final "locked")
GATE STATUS: PENDING

Rule #4 — Overlap with pilot 500
Decision: include the existing 500 lemmas in the 3000 (registry dedups by lemma_key)
Option Chosen: include (continuity check on pipeline stability)
Alternatives Rejected: fresh 3000 (clean split but no stability signal)
Trade-offs: overlap rows reused, not rebuilt; any drift shows as new rows
Owner Confirmation: include (awaiting final "locked")
GATE STATUS: PENDING

## Dependency & Wiring Map
| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | none | keep |
| Router branches | none | keep |
| Keyboard builders | none | keep |
| DB tables / columns | none (factory pack + W: fixtures only) | keep |
| Handler functions | none | keep |
| Seams (SEAMS.md) | none — factory-only, no canonical seam touched; claims file holds only docs/help | no claim needed |
| Tests referencing them | new focused test for sampler determinism | add |

## Phases
1. Download + verify dump (~3GB, checksum/count) on W:.
2. Sampling script (seeded, checkpointed) -> lemmas.csv (3000) + pack.json bump.
3. Evidence: determinism re-run (same seed = same list), overlap count with pilot 500, per-level counts.

## Blocked Questions
- (none yet)
