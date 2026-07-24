# Plan: Segment-Level Content Pooling

> **STATUS:** active (locked, not implemented)
> **Canonical references:** this file, `ROADMAP.md`, [GitHub Issues #40](https://github.com/Ham3dParsa/HamZaboonRobot/issues/40)

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
