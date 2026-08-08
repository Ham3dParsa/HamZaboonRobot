# Plan: Segment-Level Content Pooling

> **STATUS:** active (locked, not implemented)
> **Canonical references:** this file, `ROADMAP.md`, [GitHub Issues #40](https://github.com/Ham3dParsa/HamZaboonRobot/issues/40)
> **Sequencing vetted:** 2026-07-31 — confirmed independent of FSRS migration (Phase 1a `db/` split), recommended deferred until after FSRS stabilizes + Issue #180 extraction. See [§ Sequencing](#sequencing) for trigger condition and rationale.
> **Reconciled:** 2026-08-08 — superseded assumptions re-anchored to current code. See [§ 2026-08-08 Reconciliation](#2026-08-08-reconciliation). Locked decisions below are **not** rewritten by the reconciliation; deltas that require re-derivation are flagged there as pending owner decision.

---

## 2026-08-08 Reconciliation

> Additive, docs-only note. No locked decision below is changed. This section
> records where this plan's assumptions no longer match current code and what a
> future pool-builder Contract-Lock session must re-derive. Evidence-based from
> `docs/audit/pool_semantic_cache_audit_2026-08-06.md`,
> `docs/audit/architecture_alignment_2026-08-06.md`, and source.

**Daily-card intake is obsolete.** The reserved `source_kind: daily_card`
(§ Pool identity) and the sequencing step "Insert validated daily cards into
the pool" (slice 2) reference a construct under active removal. The session
engine reads only `saved_words`; `daily_cards` is a drained source awaiting its
scheduled Phase-2 drop (`services/db/schema.py:130`,
`services/db/words.py:12-115,312-371`, `docs/plans/fsrs/plan_fsrs_session_cleanup.md`).
**Pool eligibility and intake must re-anchor on `saved_words.first_exposure_done`
Tier-2 rows** (the already-landed acceptance path). The source-kind set and the
"avoid-lists" wording in § Locked product decisions must be re-derived from
that re-anchor at contract-lock time.

**Segment key comes from session context, not a stored column.** The pool is
keyed by `(target_lang, goal, level, ...)`, but `saved_words` has no
`goal`/`level` columns and is unique only on `(user_id, lang, normalized_word)`
(`services/db/schema.py:124,330`). The plan's "How to check" SQL grouping by
`(goal, level)` over `saved_words` is not reducible as written. The resolved
design is to derive `(target_lang, goal, level)` dynamically from `tier3_context`
at runtime (`handlers/study_handler.py:141-147`) rather than migrate the schema —
see `docs/audit/architecture_alignment_2026-08-06.md` (Option B, R3).

**`entry_source` has landed.** `saved_words.entry_source TEXT DEFAULT 'manual'`
was added (`services/db/schema.py:124,304-306`), the manual write path wires
`entry_source='manual'`, and the migration backfill half (Rule #2) is deferred
pending Phase 2b. Pool writes can rely on `entry_source` for origin tagging once
Tier-3 (Phase 3b+) real generation exists; `'auto'` has no write path today.

**Normalization is confirmed.** `_normalize_word` =
`" ".join(word.split()).casefold()` (`services/db/schema.py:31-32`) is the single
canonical standard; the legacy `lower(trim(...))` backfill divergence is
resolved in favor of `casefold` (Option C / R1 in the architecture blueprint).
The pool `item_key` must reuse `_normalize_word` semantics exactly.

**Re-entry trigger still unmet and still valid in intent.** Live scale
(`saved_words`=531, `users`=15) does not reach the DAU≥50 + segment-density
trigger, so implementation remains deferred. The trigger's "How to check" query
must be restated against the Tier-2 `saved_words` re-anchor once `daily_cards`
is dropped (it cannot reference `content_pool` before the table exists and
cannot group `saved_words` by a `goal`/`level` it does not store).

**Deltas pending owner decision at the next Contract-Lock session (decision
inputs, not locked rules):** source-kind set after daily-card removal; avoid-list
wording on the surviving personal-history path; inventory-floor "per segment/
source" definition post re-anchor; and whether a bulk pool-builder CLI (~1000
cards/segment) enters scope before the DAU trigger — see
`docs/audit/architecture_alignment_2026-08-06.md` B2/B3/B5 and the Claude-decision
context note. These do not unlock implementation; they only define the
contract-lock surface.

### Claude decision context (non-normative — decision inputs, not locked rules)

> Recorded 2026-08-08 from the 2026-08-04 audit
> `docs/audit/audit_content_pool_feedback_2026-08.md` and the owner's Claude-
> conversation summary. This list is **evidence, not gate** — every item below is
> a PENDING owner decision to be locked in the next pool-builder Contract-Lock
> session, not an approved rule. The full Rules 1–12 enumeration is owned by that
> session; only evidence-backed items are listed here, and no missing rule is
> inferred (AGENTS.md §2.2).

| Evidence-backed item | Where | State |
|----------------------|-------|-------|
| Pool ownership / `content_pool` schema (Rule 2) | `plan_pooling.md` schema; `audit_content_pool_feedback_2026-08.md` §3, Appendix A | PENDING owner decision |
| Flag threshold for card quality (Rule 7) | No existing `view`/`report` field on any table — count mechanism starts from zero (`audit_content_pool_feedback_2026-08.md` §3) | PENDING owner decision |
| Cheap review model exists (Rule 8b) | `gemini-3.5-flash-lite` and `gemini-flash-lite-latest` already registered in `ai_presets.py` — no new model needed | PENDING owner decision (reuse) |
| Model tag (Rule 9) | `llm_requests.model`/`preset_name` logged per request but no `card_id`/`saved_word_id` join and no model column on cards; needs a new column/key (`audit_content_pool_feedback_2026-08.md` §3, Appendix B) | PENDING owner decision |
| Phase-8 reality (Rule 10) | Phase 8 remains `planned`; only raw grading scaffolds (`grade_policy.py`) + admin cost dashboard exist, not yet registered as started work | PENDING owner decision |
| Admin forum group with topics | No `ADMIN_GROUP_ID`/`message_thread_id` infrastructure; requires a `ROADMAP.md` scope move out of AGENTS.md §9 `groups` guardrail and design from zero | PENDING owner decision |

These items are the Claude-conversation decision surface that the next
Contract-Lock session must resolve rule-by-rule per AGENTS.md §2.3/§2.4.

## Goal

Introduce one shared SQLite content pool for AI-generated learning items
within a `(target_lang, goal, level)` segment. Vocabulary cards, saved custom
word cards, grammar tips, and future quiz items use the same storage
mechanism, separated by `source_kind`.

Pooling reduces repeated provider calls as segment membership grows. It must
not replace AI generation, per-user avoid-lists, per-user deduplication,
learner quotas, or segment boundaries.

## Locked product decisions

### Eligibility

- Daily/manual vocabulary cards are eligible after the existing card
  validation and accepted-storage path.
- A custom-word result is eligible only after the learner explicitly adds it
  to SRS/review.
- A grammar tip is always stored in the learner's personal history, but is
  eligible for the shared pool only after the learner explicitly recommends
  it.
- Grammar recommendation validation must use fields returned by the
  original grammar-generation response. A second provider call solely for
  pooling is not allowed.
- Future quiz items become eligible after their feature-specific validation.
- Failed validation, partial rejected batches, abandoned query results, and
  non-recommended grammar tips never enter the pool.

### Pool identity

The unique identity is:

```text
(target_lang, goal, level, source_kind, item_key)
```

Reserved source kinds:

```text
daily_card | saved_query_card | grammar_tip | quiz_item
```

For vocabulary, `item_key` is the existing normalized word. The canonical
normalization is:

```python
" ".join(value.split()).casefold()
```

Grammar topics use the same whitespace-collapse and casefold normalization on
the generated title until a separate topic-key contract is deliberately
introduced. Quiz key design is deferred until the quiz feature is scoped.

### Quota and telemetry

- A pool hit consumes the same learner-facing feature quota as a fresh item.
- A pool hit consumes no provider budget.
- Pool reads and misses are first-class telemetry events. A hit is recorded as
  zero-cost `pool_hit`; a provider generation retains its normal request kind
  and cost/outcome fields.
- Existing quota reservations remain atomic and must not be bypassed merely
  because content came from the pool.

### Inventory and selection

- Use one deployment-configurable inventory floor for every segment/source.
- Initial default: `10` distinct eligible items per segment/source.
- Below the floor, the existing AI generation path remains available to build
  variety. Once eligible inventory exists, pool reuse is preferred.
- Candidate selection must exclude items already present in the learner's
  own `saved_words` or `grammar_tips` data.
- Selection should prefer low `times_served` items with randomized
  tie-breaking.
- Pool candidate selection and `times_served` increment must use one
  `BEGIN IMMEDIATE` transaction.

### Lifecycle and quality

- The shared pool survives owner learner-data reset because it is not
  user-specific.
- There is no time-based expiry.
- The long-term quality policy is community-driven: ratings/reports may
  influence retirement, and owner removal requires approval.
- Rating/report thresholds, automatic retirement jobs, and admin review UI are
  later phases and must be scoped before implementation.
- Recommendation points are deferred until a reward ledger exists; this
  feature must not create an untracked balance.

## Data model

Add the table without changing existing tables or backfilling historical rows:

```sql
CREATE TABLE IF NOT EXISTS content_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_lang TEXT NOT NULL,
    goal TEXT NOT NULL,
    level TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    item_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    times_served INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_served_at TEXT,
    UNIQUE(target_lang, goal, level, source_kind, item_key)
);

CREATE INDEX IF NOT EXISTS content_pool_segment
    ON content_pool(target_lang, goal, level, source_kind);
```

Quality fields such as `quality_score`, `report_count`, and `status` are
reserved for the later community-quality phase, not required for the first
pooling slice.

## Required audits and invariants

1. **Generation paths:** cover daily batch, custom-word card, and grammar
   generation. No invalid card may be shown or pooled; grammar recommendation
   validation must not add a provider call.
2. **Normalization:** reuse `db._normalize_word` semantics exactly for word
   keys and document the grammar-title key normalization.
3. **Avoid lists:** pool-served cards must enter the same stored daily-card or
   personal-history paths used by fresh cards so later prompts still avoid
   them.
4. **Quota:** pool hits count as product usage but are zero-cost telemetry.
5. **Segment isolation:** every read and write includes target language, goal,
   and level; add a test proving an item cannot cross levels or goals.
6. **Reset:** learner reset removes user-specific data but preserves
   `content_pool`.
7. **Migration:** `init_db()` uses only guarded additive creation and index
   statements; no historical backfill is required.
8. **Concurrency:** unique conflicts use `INSERT OR IGNORE` or equivalent,
   and read/serve uses `BEGIN IMMEDIATE`.

## Implementation slices

1. Add the guarded `content_pool` table and index. No behavior change.
2. Insert validated daily cards into the pool; keep reads disabled.
3. Add a config flag with `ENABLE_CONTENT_POOL=false` by default and gate
   manual daily-card reads.
4. Add pool insertion for saved custom-word cards at the explicit SRS save
   trigger.
5. Extend grammar generation output with recommendation-validation fields,
   add the recommendation UI, and pool only accepted recommendations.
6. Record pool hits, misses, and zero-cost accounting in the existing LLM
   metrics dimensions.
7. Add inventory-floor configuration and fair candidate selection.
8. Reserve `quiz_item` in the schema only; defer quiz reads and writes.
9. Scope community ratings, reports, retirement, owner approval, and rewards
   as a separate follow-up before implementing those controls.

## Sequencing

### Status (2026-07-31)

Content pooling is **locked, designed, not implemented**. A formal sequencing
analysis was conducted during the FSRS migration (Phase 1d) to verify
independence and set a re-entry trigger.

### Independence confirmation

| Concern | Pool | FSRS Migration | Verdict |
|---------|------|---------------|---------|
| Schema | New `content_pool` table (additive) | `saved_words` + `review_events` columns | No overlap |
| DB module | New functions in `services/db/` (re-exporter unchanged) | Phase 1a split kept all re-exports intact | No overlap |
| Card generation target | Pool-read logic would live in `services/ai/cards.py` (#180) | Card-gen stayed in `bot.py` untouched by Phase 1a | No overlap — #180 extraction is independent of FSRS `db/` split |
| AI calls | Reduces call volume via pool hits | Only changes grade→interval mapping | Orthogonal |
| Handlers | Write hooks + read hooks | `srs_handler.py`, `bot.py` routes | Independent |

**Key finding** (2026-07-31 verification): Issue #180 (extract card-gen to
`services/ai/cards.py`) targets ~180 lines of domain logic in `bot.py` that
were **not moved** by the FSRS Phase 1a `db/` split. They use the `db.*`
re-export API (which Phase 1a preserved) and `services/ai/*`. Neither the
functions nor their call sites changed during the FSRS migration. The
extraction is independent of all FSRS work in flight.

### Recommended sequence

```
Phase 1a–1g  →  FSRS cutover + stabilize  →  Extract #180 (services/ai/cards.py)
    →  Pool writes (inactive, accumulating)  →  Pool reads + ENABLE_CONTENT_POOL flag
```

Updates to individual documents: this plan for pooling details, Issue #180 for
the extraction, and `ROADMAP.md` for the overall sequencing.

Intentional design notes for the inactive phase:

- **"Pool writes (inactive)"** is a deliberate separate step: accumulator
  writes to `content_pool` are active during the extraction and stabilization
  phases, but the read path is disabled. This builds real segment-inventory
  data silently, without any behavioral change. The table growing unused is
  **intended** — it must not be mistaken for dead code and removed.
- Documentation at the write-path call sites must include a comment stating
  "Write-only; reads are behind ENABLE_CONTENT_POOL." Future maintainers
  should not need to infer intent from a diff.
- The read-path flag (`ENABLE_CONTENT_POOL=false` default) is added during
  the extraction phase, even though reads are not yet implemented. This
  ensures the flag is present in `settings` and can be toggled at deployment
  without a code change.

### Re-entry trigger condition

**Do not revisit pool implementation until both conditions are met:**

| Condition | Threshold | Why this number |
|-----------|-----------|-----------------|
| Active daily users | DAU ≥ 50 across any 7-day window | Below 50, per-segment inventory rarely reaches the 10-item floor |
| Segment density | At least one `(target_lang, goal, level)` segment has ≥10 validated items with ≥2 distinct users sharing it | Confirms real sharing is occurring, not a single user filling a segment |

**How to check:** Run a simple SQL query against `saved_words` and
`content_pool` grouped by `(lang, goal, level)` — do not guess.

**Rationale:** Pooling's value scales with cross-user overlap within a
segment. With the current ~10 test users, segment inventory is too sparse to
validate selection logic or measure cost savings. The same discipline was
applied to Phase 3 parameter optimization (deferred until ≥500 review events)
— build what current data can actually validate, defer what needs scale you
don't have yet.

**If the trigger is not met after 6 months of FSRS operation:** Do not
silently shelve. File a status issue confirming the segment density query
result, note why pooling is still premature, and reset the 6-month timer.
"Later" should decay into a checked waiting state, not an indefinite
postponement.

## Definition of done

- A populated segment can serve validated pool items to new learners without
  knowingly duplicating their own saved words or grammar topics.
- Pool hits and misses are visible in cost metrics without being misclassified
  as provider generations.
- Existing avoid-lists, quotas, reset behavior, and segment isolation have
  focused tests.
- The schema supports future quiz items without another table or migration.
- All learner-facing payloads remain AI-generated and pass the applicable
  validation path.
