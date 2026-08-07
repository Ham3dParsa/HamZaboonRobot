# System Architecture Alignment & Technical Blueprint
**Document Reference:** `docs/audit/pool_semantic_cache_audit_2026-08-06.md`
**Status:** Under Revision
**Target Architecture:** Tier-3 Integration (Phase 3b+)

---

## 🎯 Problem Understanding & Core Objective

The audit report provides definitive clarity on system constraints. Specifically, the original `docs/plans/content/plan_pooling.md` relied on `daily_cards` (a construct currently slated for removal). Additionally, evaluating vectorization for semantic caching highlighted its dependency overhead (`sentence-transformers` brings PyTorch, adding ~190MB to Linux build packages). Rather than discarding previous designs, existing parameters are adjusted to align with verified repository metrics.

**Key Alignment:** Tier-3 generation (`generate_tier3_node` in `study_handler.py:315-334`) is confirmed as the exact entry point where both the content pool lookup and semantic caching layers must reside.

---

## 🧠 Educational Approach & Technical Edge

The existing exact-match cache (`query_results`) is fully operational and thoroughly tested. Semantic caching will not replace exact matching; instead, it operates as an auxiliary lookup layer directly preceding `ask_card()`. This design isolates risk and preserves all existing delivery guarantees.

---

## 🚦 Current Project Status & Audit Findings

| Topic | Audit Findings & Evidence | Impact on System Architecture |
| :--- | :--- | :--- |
| **daily_cards** | 562 live DB rows remain, but Session Engine consumption uses `saved_words`. Deprecation pending Phase 2. | `source_kind: daily_card` is obsolete. Re-anchor pool eligibility on `saved_words.first_exposure_done`. |
| **Pool Segment Key** | `saved_words` lacks `goal` and `level` columns. Unique key is `(user_id, lang, normalized_word)`. | Design gap resolved: extract segment parameters dynamically from `tier3_context` instead of performing schema migrations. |
| **Word Normalization** | Divergence identified: `_normalize_word = casefold` vs legacy backfill using `lower(trim())`. | Eliminate `item_key` divergence by establishing `casefold` as the single canonical normalization standard. |
| **Tier-3 Node** | Currently a stub (`return None`), but call site is documented (`study_handler.py:315-334`). | Single authoritative integration point for both pool lookup and semantic caching. |
| **Production Scale** | 15 registered users, 531 `saved_words`, 33 `review_events`. | Initial `DAU ≥ 50` threshold is unsuited for current scale. Metrics re-baselined for lightweight runtime. |
| **Vector Engine** | Zero vector or ML dependencies in repo. Adding `sentence-transformers` includes PyTorch (~190MB). | Acknowledge build overhead. Phased rollout recommended (Phase 0 normalized matching first). |
| **Report / Flag UX** | No existing user report buttons or quality columns on `saved_words`. Signal lives in `review_events.raw_signal`. | Design new `quality_flag_count` column and inline callbacks using clean `report_card:` prefix. |
| **Admin Forum Group** | Flagged under `AGENTS.md §9` guardrails ("groups" policy), despite admin target audience. | Requires formal product owner sign-off and explicit entry in `ROADMAP.md`. |
| **Model Tagging** | Confirmed outside restricted category; metadata exists in `llm_requests.model`. | Add optional `llm_requests.saved_word_id` foreign key. Avoid writing model IDs into user card payloads. |

---

## ⚖️ Architectural Options & Strategy

### Option A: Unified Execution Pipeline inside `generate_tier3_node()` (Recommended)
Consolidate resolution into `resolve_tier3_content(context) -> card | None`:
1. **Exact Cache:** Existing `query_results` lookup.
2. **Semantic Cache:** Embedding lookup (Phase 1+).
3. **Content Pool:** Pre-generated pool matching segment key.
4. **AI Fallback:** `ask_card()` call behind atomic quota controls.

*Trade-off:* Zero impact on existing delivery paths, but pipeline remains dormant until Tier-3 generation moves beyond its stub phase (Phase 3b+).

### Option B: Dynamic Segment Key Resolution from Context
Extract `(target_lang, goal, level)` directly from `tier3_context` (`study_handler.py:141-147`) at runtime.

*Trade-off:* Eliminates schema migration risks on `saved_words` (531 active rows).

### Option C: Phased Vectorization (Phase 0 Rollout)
Execute Phase 0 using exact/normalized string matching (`casefold`). Defer dense embeddings (`sentence-transformers`) to Phase 1.

*Recommendation:* Lock Options A and B for overall architecture. Adopt Option C (Phase 0) for initial rollout, deferring heavy vector dependencies until Tier-3 execution is stabilized.

---

## 🔒 Contract-Lock Table

| Rule Ref | Scope / Decision | Implementation Details | Gate Status |
| :--- | :--- | :--- | :--- |
| **R0** | Reopen Pool Decision | Mark `decision-pool-deferred` as `under-revision` citing `pool_semantic_cache_audit_2026-08-06.md`. | `PENDING` |
| **R1** | Normalization Standard | Standardize on `casefold` (`schema.py:31-32`). Update legacy backfill references. | `PENDING` |
| **R2** | Tier-3 Pipeline Integration | Execute Exact Cache → Semantic Cache → Pool → AI within `generate_tier3_node()`. | `PENDING` |
| **R3** | Contextual Segment Keys | Dynamic extraction of segment keys from `tier3_context`. No schema migration on `saved_words`. | `PENDING` |
| **A1** | Vector Engine | Deploy `all-MiniLM-L6-v2` via `sentence-transformers` wrapped in `asyncio.to_thread`. Accept ~190MB build weight. | `PENDING` |
| **A2** | Feedback / Quality Signals | Add `quality_flag_count` column to `saved_words`. Register `report_card:` callback handlers. | `PENDING` |
| **A3** | Model Metadata | Add nullable `saved_word_id` to `llm_requests`. Keep card payloads clean. | `PENDING` |
| **A4** | Admin Forum Guardrail | Require explicit approval and `ROADMAP.md` entry per `AGENTS.md §9`. | `PENDING` |
| **B2** | Staging Pool CLI | CLI generator filtering on `saved_words.first_exposure_done == True`. | `PENDING` |
| **B5** | Roadmap Documentation | Annotate execution order in `ROADMAP.md` as "Blocked on Tier-3 Phase 3b+". | `PENDING` |

---

## ❓ Actionable Open Questions

1. **Embedding Pipeline Strategy:** Should full vector embeddings (A1) be deployed immediately, or should Phase 0 (normalized string matching, Option C) be approved first?
2. **Admin Forum Integration:** Should admin forum features (A4) be added to `ROADMAP.md` now or formally deferred?
3. **Pool Builder Pilot Budget:** What is the budget or card generation limit for the offline pool pilot (B3)?

---

## 🔧 Owner Amendment (2026-08-06): Tier Is a Priority Flag, Not a Storage Location

> Added by the product owner to correct a conceptual framing in the blueprint. The tier number
> describes a card's **priority for being served in a session**, not where it is stored in the
> user's box.

### The "user's box" model

A user's box of cards is the single home for everything the user has. It is filled by **two
entry sources**, and a card then moves through two **lifecycle states**:

```
[ Entry Sources ]                     [ Lifecycle States in "User Box" ]
===================                   ===================================

  T3 (AI / Pool Auto)  ──(AUTO)──┐
                                  ├──>  Tier 2 (Saved / Unexposed) ──> Tier 1 (Exposed & Due / Active FSRS)
  Manual / Query       ─(MANUAL)──┘
```

- **Entry sources (how a card gets INTO the box):**
  - **Auto:** a new card produced by Tier-3 generation (AI, or pool/semantic-cache hit) lands in the box automatically.
  - **Manual:** a card added by the user from a custom-word query ("Add to review").
- **Lifecycle states (where a card sits inside the box):**
  - **Tier 2 = Saved / Unexposed:** card is in the box but has never been shown in a session.
  - **Tier 1 = Exposed & Due / Active FSRS:** card has been shown, graded, and is scheduled on the FSRS timeline.
- **"Saved box" as history:** the full saved-word history is the box itself; Tier 2 (unexposed) and Tier 1 (exposed/due) are its two lifecycle partitions.

### The corrected rule

> **A card's tier must NOT define where in the box it lands or is saved.**

- Tier is the **priority flag that decides how soon a card gets pulled into a session**,
  not a storage partition.
- Both Auto and Manual sources converge on the same box entry point (Tier 2 / unexposed).
  Tier 3 is an **entry mechanism** ("a way for a new card to get into the user's box"), not a
  stored location — there is no "Tier-3 section" of the box.

### Consequences for the blueprint's rules

| Rule | Effect of this amendment |
| :--- | :--- |
| **R2** | The pipeline in `generate_tier3_node()` is an *entry-source* pipeline (Auto). Its output goes into the box as Tier 2 (unexposed), exactly like a manual save — it is not "stored at Tier 3". |
| **R3** | Segment keys come from session context (`tier3_context`); consistent with entry sources not implying storage location. |
| **B2** | The staging CLI filters on `saved_words.first_exposure_done` — i.e. box rows in the Tier-2 (unexposed) state are the natural pool seed; matches "tier 2 = saved/unexposed" above. |
| **B5** | Roadmap wording should say Tier-3 (entry source) is blocked on Phase 3b+; box lifecycle (Tier 1/2) is orthogonal to entry sources. |

---

## 🗂️ Owner Section 2 (2026-08-06): Verified Schema Findings → `entry_source` Rule

> Residual after the discussion: the box model maps cleanly onto the existing single
> `saved_words` table (tiers already derived, not stored). Owner decision became a candidate
> Contract-Lock rule below. **Recorded for planning — not yet implemented.**

### What the code already does (verified against source)

- `saved_words` columns (`services/db/schema.py:109-124`): `id, user_id, word, lang,
  normalized_word, card_data, interval_idx, next_review, review_status,
  review_requested_at, added_at, first_exposure_done, stability, difficulty`.
  **No source column exists.**
- Tier 1 (due/exposed) is queried, not stored: `due_words_for_user()` filters
  `next_review <= today AND first_exposure_done=1 AND review_status!='pending' AND
  retry_at IS NULL` (`services/db/words.py:259-280`).
- Tier 2 (saved/unexposed) is `get_pre_first_exposure_words()` filtering
  `first_exposure_done=0` (`services/db/words.py:295-301`).
- Assembly consumes both in priority order (`services/session/assembly.py:108-135`);
  `generate_tier3_node()` still a stub returning `None` (`assembly.py:153-167`).
  Transition 2→1 via `grade_first_exposure` (`handlers/srs_handler.py:133`).
- Migration pattern is additive + idempotent INSIDE `init_db()`: `CREATE TABLE IF NOT
  EXISTS` (fresh DB) then `PRAGMA table_info()` + `ALTER TABLE ... ADD COLUMN` per missing
  column (`schema.py:277-302`). No `.sql` migration files. `daily_cards → saved_words`
  historical reset + INSERT-SELECT lives in `migrate_saved_words_to_fsrs()`
  (`words.py:312-366`), guarded by settings key `fsrs_migration_done`.

### Candidate Contract-Lock "B" rule: additive `entry_source` (scope updated 2026-08-06)

> **Scope revision (post-research):** the read-only subagent found that B6's original Rule #2
> (backfill `'manual'`/`'auto'` inside `migrate_saved_words_to_fsrs`) conflicts with the v3/FSRS
> engine's **Phase 2b**, which deletes that function and drops `daily_cards`
> (`.opencode/plans/plan-phase-2b*`). Once Phase 2b lands, there is no `daily_cards` to source
> `'auto'` from, so the backfill becomes redundant. **Rule #2 is deferred (not implemented)
> pending Phase 2b.** B6 reduces to the independent, non-conflicting half only.

- **Rule #1 (Option A — LOCKED, independent):** add `entry_source TEXT DEFAULT 'manual'` to
  `saved_words`.
  Rejected: B (column only, no writes — weaker evidence); C (defer to Tier-3 — forces a
  later migration).
- **Rule #2 (DEFERRED pending Phase 2b):** backfill — pre-existing `saved_words` rows →
  `'manual'`; rows migrated from `daily_cards` → `'auto'`. Implemented inside
  `migrate_saved_words_to_fsrs()`: reset `UPDATE` (`words.py:329-334`) sets `'manual'`;
  `daily_cards` INSERT-SELECT (`words.py:340-364`) gains `entry_source` + literal `'auto'`.
  **Do NOT implement while Phase 2b is pending** (Phase 2b deletes `migrate_saved_words_to_fsrs`
  and drops `daily_cards`). After Phase 2b the backfill is unneeded — `DEFAULT 'manual'` +
  future Tier-3 writes cover origin tagging.
- **Rule #3 (LOCKED, independent):** wire the manual write path — `_handle_query_add`
  (`srs_handler.py:46`) → `add_saved_word(..., entry_source='manual')`; optional kwarg
  default `'manual'` in `add_saved_word` (`words.py:180-203`).

### Dependency & Wiring Map (verified post-impl via grep + `tests/test_wiring.py` + dead-ref guard)
- `schema.py:109-124` CREATE block → add `entry_source` column (fresh DB).
- `schema.py:277-302` PRAGMA/ALTER block → add ALTER line (prior-schema upgrade).
- `words.py:180-203` `add_saved_word` → optional `entry_source` kwarg.
- `srs_handler.py:46` `_handle_query_add` → pass `entry_source='manual'`.
- `words.py:259-301` Tier-1/Tier-2 queries → **keep** (tiers stay derived; unaffected).
- `config/keyboards.py`, `callback_router` → **keep** (no `callback_data` change).
- `migrate_saved_words_to_fsrs` backfill (Rule #2) → **deferred**; verify AFTER Phase 2b
  lands; do NOT implement concurrently.
- Tests required per AGENTS.md §6: schema-change test on BOTH fresh DB and prior-schema
  upgrade; extend a DB integration test for the manual-write path.

### Open (for the plan, not gated yet)
- Pool eligibility should re-anchor on `saved_words.first_exposure_done` (not deprecated
  `source_kind: daily_card`) once `daily_cards` is dropped in Phase 2b.
- `entry_source='auto'` has no write path until Tier-3 (Phase 3b+) real generation lands —
  the column is forward-prep for that seam.
- Rule #2 backfill is deferred; revisit only if Phase 2b ordering changes (else drop it).
