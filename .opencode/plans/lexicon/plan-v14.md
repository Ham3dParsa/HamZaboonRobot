---
name: plan-v14
description: v14 lexicon factory — weight fix + EVP recall + merge/pick + en pack (500 pilot, then 4000)
created: 2026-09-03
base_commit: TBD-at-branch
branch: TBD
status: in-progress
---

STATE: phase 6/6 — status: registry built + proven (2026-09-03, tests re-ran green) — focus: 4000-scale sign-off (sampling + raw + card-gen pilot)

## Plans & Dependency Edges

| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-v14.md` | 1 deterministic (weights/recall/exact-merge/pack) | contract R1,R2,R3-exact,R3b,R5 | pending keys: NO |
| `plan-v14.md` | 2 LLM merge (Stage A, muse) → **v14b** | phase 1 output + R6 keys | script ready, dry-run green, blocked on keys |
| `plan-v14.md` | 3 judge pick (Stage B, muse) → **v14c** | phase 2 output + R6 keys | pending |
| `plan-v14.md` | 4 report + compare vs v13c | phases 1-3 artifacts | pending |
| `plan-v14.md` | 5 scale to 4000 (R7) | owner sign-off on pilot | pending |

## CONTRACT LOCK (owner decisions 2026-09-03, gated; researcher-cast tie-break on R3b delegated by owner)

Rule #R1 — Decision: new weight formula. Option Chosen: full package (0.30 per-sense freq + 0.35 CEFR-asym2 + 0.10 WN + 0.05 centroid + 0.10 topic + 0.10 Tatoeba-hit; gates P_REGISTER 0.5/0.6/0.8, P_POS 0.7). Alternatives Rejected: weights-unchanged (rock/flat unfixable — stone absent + Zipf dominance). Owner Confirmation: "هر دو را انجام بده" + full package context.
Rule #R2 — Decision: EVP recall guard. Option Chosen: yes (guideword without cosine match >0.60 reinstates best raw sense, before merge). Rejected: accept-current (rock stays ice-first). Owner: "بله، نگهبان EVP".
Rule #R3 — Decision: merge scope. Option Chosen: both (deterministic exact-dup free + LLM paraphrase merge, batch 8 lemmas, ~63 calls). Rejected: exact-only (paraphrases survive). Owner: "هر دو را انجام بده".
Rule #R3b — Decision: merged-sense frequency + examples. Option Chosen: synset-single (one WN/SemCor-backed count per merged meaning; zero-count senses fall back to Tatoeba evidence, never arbitrary order; survivor keeps own examples + LLM-filtered carryover only). Rejected: sum (rewards dictionary duplication — supporter 4x, communicate 7x; ties output quality to Kaikki messiness). Basis: literature (WordNet order = SemCor counts = MFS standard; McCarthy/Preiss distributional fallback for low-count senses) + real mismatched examples in v13c (communicate#5 "To share" with room-connection examples). Owner delegated: "تو تحقیق کردی".
Rule #R4 — Decision: final pick. Option Chosen: muse as judge, precise efficient prompt, 3 lists per lemma (beginner 2 / intermediate 3 / advanced 4, one call), deterministic fallback on any failure. Rejected: formula-only (generic pass stays top-1). Owner: "مدل را داور کن با پرامپتی که دقیق باشد و کارآمد".
Rule #R5 — Decision: en pack. Option Chosen: yes, create factory/packs/en/ now (data move only, zero algorithm change) + update README. Rejected: later (stays English-locked). Owner: "آره مرتب کن و اگر لازمه readme را آپدیت کن".
Rule #R6 — Decision: API keys. All 5 env keys empty this session. Deterministic phases run without keys; LLM phases blocked until owner re-supplies keys.
Rule #R7 — Decision: scope. Pilot 500 first, owner sign-off, then 4000 (~5-6h LLM). Rejected: straight-4000 (bug-burn risk). Owner: "بله مرحله‌ای".

GATE STATUS: LOCKED

## seam-claim note

v14 touches factory notebooks/fixtures/docs only — no canonical seam from SEAMS.md, no overlap with claimed seams (Admin/AwaitingFlow/Cost/TTS Provider/CallbackNotifications/docs/help). No claim acquired (nothing claimable).

## Blocked Questions

- [2026-09-03] R3b tie-break delegated to researcher after literature + data investigation. Decision: synset-single.
- [2026-09-03] Phase 2/3 blocked: need OpenRouter/Groq/Google keys re-set in env (were set pre-compaction, now empty).

## Phase 1 evidence (2026-09-03, worktree research/lexicon-v14, RTX 3080 local ~7min)

- `factory/run_v14_phase1.py` + `factory/packs/en/` (pack.json, lemmas.csv 500, evp/cefrj/tatoeba/topic files, README.md)
- `factory/fixtures/ranked_senses-v14a.json` (500 lemmas, 2101 cards; per-CEFR 311/310/360/373/393/354), `uniq_senses-v14a.json` (4093), `topic_labels-v14a.json` (Other 89.1%: evp-domain 225 + keyword 5), `probes-v14a.json`, `gap_report_free_500_v14a.md`
- W synced: fixtures/{ranked,uniq,topic}-v14a.json + fixtures-v14a.zip, reports/gap_report_free_500_v14a.md, logs/run_v14_phase1.py, README v14a section
- Probes: flat top-1 apartment (was beer); light alt-form demoted, verb-pollution gone; rock stone recalled to uniq (#12) but top-1 music (judge pending); 15 exact-dup merges with merged_from; pos=name 0 survivors
- Amendment (transparent, vetoable): alt-form shape rule (`alternative X form of` x0.5) added during run, same class as locked R1 gates
- Finding: v13c keyword-831 not reproducible from stated thr-0.50 rule (8/400 sim>=0.50 vs 217 labeled)
- [2026-09-03] Phase 2 script `factory/run_v14_phase2_merge.py` written (responses/minimal, batch 8, resume JSON, singleton fallback, example-drop filter); dry-run 24 lemmas green (86 cards, 0 failed). Real run (~63 calls) waits on keys.
- [2026-09-03] SUBAGENT executed phases 2+3 (delegated, precise context). Evidence: `factory/fixtures/ranked_senses-v14b.json` (500 lemmas, 1676 cards, 367 merged, failed 0); `factory/fixtures/ranked_senses-v14c.json` + `topic_labels-v14c.json` (judged 494, deterministic fallback 6, Other 27.0% = 453/1676, above ≤15% target); 126 calls ALL spark-1.3 via Zen (fallbacks never needed); transport fixes in worktree scripts (bare Zen model ids — opencode/ prefix gave 401; browser UA header — Cloudflare 403; double-POST bug in my phase-2 script fixed). W synced (fixtures v14b/v14c + topic v14c, reports gap v14a, logs phase2/3 scripts). .env verified gitignored, never staged. No commit/PR.
- [2026-09-03] Phase 4 done: `docs/research/lexicon/v14-final-report-2026-09-03.html` (v13c vs v14a vs v14c, judge picks, Other-27% analysis, cost) + `factory/fixtures/gap_report_free_500_v14c.md` (W reports synced, fixtures-v14c.zip). Verified from files: 1676 cards, per-CEFR 265/258/298/296/309/250, judge 494 + deterministic 6 (light/chairman/cycling/exchange/stool/drive).
- [2026-09-03] v14 findings consolidated: `.opencode/plans/lexicon/CONTEXT-v14-2026-09-03.md` (+ W reports copy). Covers chain numbers, 6 durable findings, transport fixes, key layout, full contract.
- [2026-09-03] v15 LOCKED (owner: focus v15): weighted topic vectors — up to 3 labels per sense with weights summing 1.0, spark-1.3 Zen chain, batch 8 lemmas (~63 calls), fallback = current single label @1.0, output topic_vectors-v15.json, validation (weight sum, label 1..13, id match). Delegated to team.
- [2026-09-03] v16b DONE (subagent, verified from files): top-up on 552 Others only — 39 calls all spark-1.3, 0 failed; Other 552 → 296 = 17.7% (≤20% HIT, ≤15% missed by 29); multi 116 → 314 = 18.7%; all weight-sums 1.0; `factory/fixtures/topic_labels-v16b.json` + `topic_vectors-v16b.json` (+ W zip); blemish flagged: pass#8 Travel is a stretch. Report: `factory/fixtures/gap_report_v14_v15_v16.md` (+ W reports) and v16/v16b section appended to `docs/research/lexicon/v14-final-report-2026-09-03.html` (fragment from subagent, Persian-checked). Total chain cost: 126+64+64+39 = 293 calls, all spark-1.3, zero fallbacks. No commit/PR.
- [2026-09-03] REGISTRY LOCKED (owner; 2 competing designs compared, SQLite wins — uniqueness guaranteed by DB not promised by files): dedicated factory DB, LANGUAGE as first dimension. `factory/registry.db` (WAL, local disk only, backup copy to W — never live on network share). Tables: languages(code from catalog, pack_version) / lemmas(lang, lemma_key UNIQUE, stage flags) / precards(lang, pre_card_id content-hash UNIQUE, status active|superseded, merged_into, converted_final_id) / runs / batches(lang-scoped FINAL-{lang}-YYYYMMDD-NN tickets, claim-lease-commit, 30-min stale re-queue). Stable IDs replace w#lab cluster ids (kept as alias). Invalidation: reprocess lemma only if pack_version/code-hash/raw-hash changed. Migration: import 500-lemma v14 fixtures read-only, zero reprocessing. Proof: 3 overlapping runs, zero dupes, per-language counts.
- [2026-09-03] REGISTRY BUILT+PROVEN (subagent, proof tests re-ran green by me 4/4): `factory/registry.py` (stdlib sqlite3, WAL, immediate transactions) + `factory/registry.db` (local only) + `factory/test_registry_proof.py` + `factory/REGISTRY_EVIDENCE.md`. Live en: 499 lemmas (cast verb B2+C1 share key, documented), 2098 precards (1671 active, 427 superseded, 0 converted; deltas vs 2101/1676 explained: 5 cast content-dupes collapse + 2 reworded v14b glosses; 5 merges flagged unresolved, not guessed). Integrity query empty. Backup helper present (VACUUM INTO to W, not yet executed). No commit/PR, .env untouched.
- [2026-09-03] BACKUP DONE (owner order, fast-track docs+ops): `W:\hamzaban_data_factory\backups\2026-09-03-202258\` holds registry.db + .env (RESTRICTED) + registry.py/run_v14_phase1.py/env_loader.py + NOTE. Policy reflected in W: README §Backups + worktree `factory/README.md` (three-homes map, restore rule, regeneration list). Next: narrative notebook + light PR + junk cleanup (pending approval).
- [2026-09-03] v16 LOCKED (owner: 13 labels arbitrary, unfreeze with migration map): 16 topic heads. Splits: Nature→Animals & Living Beings + Nature & Environment (plants/earth/air/water); Work & Education→Work & Careers + Education & Exams; Society & Culture→Society + Arts & Culture; rest unchanged (Daily, Food, Health, Travel, SciTech, Business, Law, Sports, Emotions, Other). Tie-breaks: living being→Animals even if edible; eating/food→Food; exam/school→Education; job/meeting→Work; art/film/music→Arts; community/tradition→Society. Migration map kept for history; fresh run re-labels everything. One combined run: primary label + weight vector (≤3, sum 1.0), ~63 calls, outputs topic_labels-v16.json + topic_vectors-v16.json.
