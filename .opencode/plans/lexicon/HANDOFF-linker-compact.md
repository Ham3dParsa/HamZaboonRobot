# COMPACTION — linker session state (2026-09-19, pre-compact)

Owner order: preserve everything needed for next steps. This file + CONTRACT-linker.md + tickets are the session memory.

## 1. Methodology (how we implement — locked practice)

- **Evidence-first:** no number without quoted rows (kid + gloss + winner + evidence). Samples beat aggregates; aggregates need denominators.
- **Gates:** contract lock (§2, owner says locked/proceed per rule) BEFORE any code; reviewer gate (`hamzaban-reviewer`) before every commit; OC (opencode-agent) authoritative — merge only on OC APPROVED + green CI (Kilo informational); Kilo/OC loops delegated to subagents.
- **Scratch-first R&D:** all linker experiments live on W:\hamzaban_data_factory\proof-linker\ (never in repo until gated); frozen versions never modified (v0.1–0.8, link tables); VERSIONS.md changelog per calibration; SHAs prove byte-identical outputs.
- **TDD at seams:** witness rows first (TRUE must-link + FALSE must-park quoted), then code; one change → measure → keep/revert; no blanket approvals; fast-track ONLY for test-only/docs with explicit statement.
- **Parallel discipline:** worktree isolation (primary main stays clean); claims file `<git-common-dir>/parallel-work-claims.json` checked at every lock; max 2 simultaneous workers (disk); one task one worker; neighbor sessions own disjoint files (see HANDOFF-run-config.md).
- **Honesty rules:** REVIEW≠demote; unanimous≠correct; precision reported with denominator + sample size; over-extrapolation called out even when it's ours (70-75% affair); stale-file findings re-verified on disk, never memory.

## 2. State: linker line (numbers with denominators)

- **Deterministic core** (factory/linker/linker.py on origin/main, pure stdlib): candidates (top-12, cut top-3) → signals Sa/Sb/Sc/Sd (GENERIC deweight in SCORING only — no gate lists) → decide LINK/PENDING/UNMAPPED + flags.
- **Judge** (local Gemma-4-E2B Q6_K, temp-0, seeds 42/43/44, N=3 majority; budget 2000 locked — 350/0 regimes REJECTED with evidence; batching REJECTED; 8 models bake-offed, all others rejected with rows).
- **run20 v4.1b** (807 rows, SHA-recorded): 133 LINK (138 judge-v2 + 46 linker − applied NONEs/corrections) / 94 REVIEW / 100 NONE / 401 UNMAPPED / 32 twin / 1 quarantine. Precision band: 90% floor (soft, n≈10) – 96±1% ceiling (confirmed falses 7–10/235). Working number on randoms: ~65%.
- **R-gates** (judgeops/gates_r.py, REVIEW-routers never silent): A rank≥2&j≤0 (+j>0/Sb guard), B winner_gloss containment (+j≥0.20/==1.0 bailout), C DECOMMISSIONED (generic_set + carveout DELETED, grep-proven), rank-1-only-generic-Sd → PROVISIONAL.
- **Hybrid scorer** (calib/, locked weights w=2.0/0.5/0.25/0.25, T=0.75/0.10/0.20): triage ONLY (Fast-NONE + routing). Fast-LINK rejected (19.5% recall). Full-table scoring: below-0.10 = 104 rows but only 15 fresh LINKs (rest already parked); T_high pool = 22.
- **Whitelist doctrine:** whitelist = never-NONE (not never-REVIEW); idx80/idx65 intact proof. Quarantine (book-hoaZwz7Y) total blackout. Twins/NONEs keep keys + status gate + guard test.
- **Viewer/gallery** (factory/linker/viewer.py, merged #771): stage trace, OR-filters, key:/kid: search, per-record export, natural Persian vocab; sample gallery on W:.
- **Unseen-50 slice:** local 19 LINK/28 NONE/3 FAILED vs golden 17/33 → recall 82%, precision 74%; winner-level comparison with Gemini pending.
- **Merged PRs:** #763 core+table, #765 registry, #770 identity (factory/linker/ + CLI + Readme + changelog), #771 gallery, #774 flowtrace, #772 run_leg, #773 anchor view, #758/#761/#764 viewer, #769 catalog. #751 Q4, #750 Q5, #756 Q3, #749 entry, #755 zen-kill earlier.

## 3. Open loops (ordered)

1. **F3 enrich wiring** — ALL locks done (R1-R8 + G1'/C1-C4 + G2 + G3 + G4' + G5' in CONTRACT-linker.md). Single worker (enrich is shared heart). Then F4 hermetic tests, F5 errorwords diff.
2. **G6 Oxford third leg** — recorded direction only (clue-only topics, self-minted keys, judge-matched, copyright caution). Needs lock round.
3. **Human queue:** 28 rows (29-hold + flips + idx132-parked) + entry-16 tiebreak → JUDGE-NONE locked.
4. **Flash Lite track** (deferred): batch 6-8 + real system prompt + GEMINI_API_KEY in local .env.
5. **Neighbor sessions:** run-config (PR-C→D→E per HANDOFF-run-config.md) owns pipeline.py/run.py; viewer-survival owns precard viewer. Do NOT touch: enrich.py, factory/linker/*, W: proof-linker writes, LM Studio :1234.
6. **Losers archive (do NOT retry without new evidence):** Se-rerank (-37/+0), 10-pack single (6.7×), ministral prescreen (0.30 true/call lost), Llama/Granite/spark/minicpm judges, budget-350/0, batching, single-example prompt, Fast-LINK authority, gate-C, hardcode lists.

## 4. Key paths

- Repo: factory/linker/{linker.py,viewer.py,cli.py,__init__.py,table.tsv,table.meta.json,Readme.md,changelog.md}, tests/factory/test_linker*.py, CONTRACT: .opencode/plans/lexicon/CONTRACT-linker.md, tickets: TICKETS-linker-transfer.md / TICKETS-linker-v1.md / TICKETS-run-config.md / TICKETS-quality-141.md, handoffs: HANDOFF-run-config.md.
- Scratch: proof-linker/{v1 (frozen 0.1-0.8 + VERSIONS.md + JUDGE_AUDIT_06 + PROMPT_PACK), run20 (v1..v4.1b tables + verdicts + batches + G1G5_LOCK_PACK + SCORE_PASS + EVAL_03/04/05 + PROMPT_PACK), witness25/50 (SET/MATRIX + versions), judgeops (gates_r + SET50r + fuzzy/twostage/attractor + ab harness), calib (weights), candprobe (Se-reject + pass-2 rule), build{2000,10000} (drivers + PERF.md), gallery/ (sample), flowproto/{a,b,c} (6 prototypes), slice files, gemini_*.txt audits + renames}.
- Judge infra: LM Studio :1234 (Gemma-4-E2B Q6_K, full offload; thinking budget FULL/2000-locked; temp 0; context 8448). HTTP gallery :8001 (may be dead — restart: `python -m http.server 8001 --bind 10.95.232.139` in proof-linker/).
- Ground-truth sets: SET50r (47T/51F/2B), gemini_sample_30x30 (30/30, 14 fresh lemmas), slice_unseen_50 + golden (17/33, Gemini holds winners), 18 anchors + witness rows (REPORTs).
2026-09-20 (feat/row-surface-gate-ctx): gate_ctx surfaced on precard rows (primary+extras) with enrich stage counters; honest-signals-only, no legacy backfill, SignalQuality log-only unchanged.
