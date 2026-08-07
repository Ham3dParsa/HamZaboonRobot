# Pool / Semantic-Cache Pre-Decision Audit

**Date:** 2026-08-06
**Scope:** Read-only fact-gathering. No implementation. Prepared so the owner (Parsa) can
review risks before any Contract Lock Rule in the "B" category is locked.
**Method:** Three independent subagents (pool-plan/FSRS, embedding infra, callback/scope)
following the audit-workflow and callback-wiring skills, then merged. Every claim carries an
evidence `file:line` citation; load-bearing citations were re-verified against source during
merge. Live DB numbers were re-measured read-only during merge.
**Target subsystems under study:** semantic query cache + pool-builder / feedback / model-tag, read
against the Tier-1/2/3 session engine (see §5 Tier-3 interconnection).

> Measured live row counts in `hamzaban.db` (read-only): `saved_words`=531, `daily_cards`=562,
> `review_events`=33, `users`=15.

---

## 1. Pool-plan vs FSRS compatibility

Source evidence: `docs/plans/content/plan_pooling.md`, `docs/plans/fsrs/plan_fsrs_migration_v2.md`,
`docs/plans/fsrs/plan_daily_cards_migration.md`, `docs/plans/fsrs/plan_fsrs_session_cleanup.md`,
`docs/archive/plan_fsrs_phase1_merge_engine.md`, `migrations/v3_cleanup.sql`,
`services/session/__init__.py`, `services/session/assembly.py`, `services/session/grade_policy.py`,
`handlers/study_handler.py`, `services/db/` (schema + words + reviews), `project_status.json`.

Findings table:

| # | Claim | Evidence (file:line) | Verdict |
|---|-------|----------------------|---------|
| Q1 | Daily cards eligible after "the existing card validation and accepted-storage path" | `docs/plans/content/plan_pooling.md:22-23` | needs owner decision — "accepted-storage path" is ambiguous; `daily_cards` is being dropped and storage migrates to `saved_words.first_exposure_done` (`services/db/words.py:312-371`) |
| Q1 | Reserved source kind `daily_card` implies the daily-card concept is pool intake | `docs/plans/content/plan_pooling.md:46-48` (`daily_card \| saved_query_card \| grammar_tip \| quiz_item`) | stale — daily-card concept is under active removal (Phase-2 in_progress) |
| Q1 | Inventory floor counts per segment/source | `docs/plans/content/plan_pooling.md:74` ("Initial default: 10 distinct eligible items per segment/source") | needs owner decision — source set must be re-derived after daily→saved first-exposure merge |
| Q1 | Sequencing step "Insert validated daily cards into the pool" | `docs/plans/content/plan_pooling.md:146` | stale — `daily_cards` table is in the removal path (`project_status.json:192`) |
| Q1 | Avoid-lists: cards "enter the same stored daily-card or personal-history paths" | `docs/plans/content/plan_pooling.md:130-132` | stale / needs owner decision — daily-card path being dropped; only personal-history path survives |
| Q1 | "How to check" SQL groups `saved_words` + `content_pool` by `(lang, goal, level)` | `docs/plans/content/plan_pooling.md:219-220` | needs owner decision — `saved_words` has no `goal`/`level` columns (see Q2) |
| Q2 | Pool identity key `(target_lang, goal, level, source_kind, item_key)` | `docs/plans/content/plan_pooling.md:41,113` (`UNIQUE(target_lang, goal, level, source_kind, item_key)`) | still valid (new table, no FK dependency) |
| Q2 | `item_key` = normalized word, casefold semantics | `docs/plans/content/plan_pooling.md:50-55` (`" ".join(value.split()).casefold()`) | still valid — matches `_normalize_word` (`services/db/schema.py:31-32`) |
| Q2 | FK / segment-key mismatch: `saved_words` no `goal`/`level` column, no FK to pool | `services/db/schema.py:109-124` (CREATE `saved_words`: `id, user_id, word, lang, normalized_word, card_data, ...`; no goal/level, no FK) | needs owner decision — pool keyed by `(goal, level)` but the learner-avoid key is only `(user_id, lang, normalized_word)` (`schema.py:330` UNIQUE), so cross-segment elimination of a user's own words is structurally incomplete |
| Q2 | Normalization duplicate: backfill vs `_normalize_word` | backfill `normalized_word=lower(trim(word))` vs `_normalize_word` = `casefold` (`schema.py:31-32`) | needs owner decision — two distinct definitions; risk of `item_key` divergence |
| Q3 | Re-entry trigger DAU ≥ 50 across a 7-day window | `docs/plans/content/plan_pooling.md:214-219` | needs owner decision — no live user-count evidence; plan cites ~10 test users |
| Q3 | Segment-density trigger (≥10 items, ≥2 users) | `docs/plans/content/plan_pooling.md:...` (~217) | still valid in intent; depends on a pool table that does not exist |
| Q3 | Phase-6 removal of `daily_cards` is in_progress | `project_status.json:191-194` ("...DROP old daily_cards table", listed under `in_progress`) | confirmed removal in flight |
| Q3 | Phase-3a migration status | `docs/plans/fsrs/plan_daily_cards_migration.md:3` ("> STATUS: Phase 3a complete (PR #252, CI green)"); implemented at `services/db/words.py:312-371`; live DB: 562 daily_cards still present (awaiting Phase-2 drop) | completed / merged — Phase 2 (DROP) is the remaining step |
| Q3 | Phase 3b / 3b+ state | `project_status.json:196-198` ("Phase 3b: wire FSRS scheduling ...", "Phase 3b+: AI Tier-3 generation ..." both in `todo`); grading stubs in `services/db/words.py` | needs owner decision — the plan's "defer entry until FSRS stable" depends on 3b |
| Q4 | `content_pool` table | grep: zero code hits (only plan + `ROADMAP.md` mentions) | not implemented / still valid (locked-not-implemented) |
| Q4 | `ENABLE_CONTENT_POOL` flag | grep: zero hits in code/settings | not implemented, consistent with plan |
| Q4 | `services/ai/cards.py` extraction target | does not exist; `services/ai/` = `__init__.py, ai.py, ai_presets.py, llm_services.py, prompts.py`; card logic still in `bot.py` | not implemented — plan treats it as a future step (`docs/plans/content/plan_pooling.md:178-183`) |
| Q4 | `daily_cards` table itself | `services/db/schema.py:129-134` still `CREATE TABLE IF NOT EXISTS daily_cards`; `words.py` still read/write it; `migrations/v3_cleanup.sql` drops `delivery_queue` but NOT `daily_cards` | still exists but scheduled for removal — needs decision |
| Q4 | `review_events` table | `services/db/schema.py:198-205` + migrated `:307-315` exist; `services/db/reviews.py` write path valid | still valid |

**Top three pool/FSRS findings**

1. **`daily_cards` is under active removal BY PLAN (the V3/FSRS session engine has already
   superseded it).** The removal is not merely a `project_status.json` intent — it is enforced by
   the FSRS plan phase ordering and already implemented in code:
   - Phase ordering is explicit: `docs/plans/fsrs/plan_daily_cards_migration.md:126-139` — `Phase 1 →
     Phase 3a (migrate daily_cards → saved_words) → Phase 2 (remove stale daily/review/old-SRS +
     DROP daily_cards) → Phase 3b`, with `:139` "why 3a before 2: Migration needs daily_cards table.
     Phase 2 drops it."
   - The migration already ran: `services/db/words.py:312-371` `migrate_saved_words_to_fsrs()`
     `SELECT ... FROM daily_cards` → `INSERT INTO saved_words` (Phase 3a complete; `fsrs_migration_done`
     guard at `:320-324,367-369`).
   - The current session engine reads ONLY `saved_words`, never `daily_cards`:
     `services/session/assembly.py:47,62,109,124` use `due_words_for_user` /
     `get_pre_first_exposure_words`. `daily_cards` is a drained source table awaiting its scheduled drop.
   - Scheduled removal is a committed stale-inventory item: `docs/plans/fsrs/plan_fsrs_session_cleanup.md:82-87
     (Phase 2)` and `:130-134 ("Stale (remove): ... DB daily_cards/daily_progress/daily_card_sessions").
     `migrations/v3_cleanup.sql:1-12` already drops `delivery_queue`: the `daily_cards` DROP is the
     pending Phase-2 half.
   - Consequence for the pooling plan: its `daily_card` source kind + eligibility path are **stale by
     plan** — the worker pool would have to re-base pool intake onto `saved_words.first_exposure_done`
     Tier-2 (already the acceptance path), and Phase-3a merged first-exposure cards are the current
     candidate source. Owner decision needed on re-derived source set.
2. **Schema mismatch between the pool's segment key and the actual word source.** The pool is keyed
   by `(target_lang, goal, level, source_kind, item_key)` (`docs/plans/content/plan_pooling.md:41-42`), but `saved_words`
   has no `goal`/`level` columns and is unique only on `(user_id, lang, normalized_word)`
   (`schema.py:124, 330`). The plan's own "check" SQL grouping by `(goal, level)` is not reducible,
   and cross-segment elimination of a user's own words needs a field that does not exist.
3. **Trigger sequencing still depends on unreleased Phase 3b state.** The re-entry trigger
   (`docs/plans/content/plan_pooling.md:214-218`) and the deferred decision both depend on FSRS scheduling wiring,
   which is a `todo` (`project_status.json:196`); grade stubs remain in `grade_policy.py`.
   The AI extraction target (`services/ai/cards.py`, Issue #180) does not exist. No upstream is landed.

---

## 2. Embedding infra feasibility

Evidence from `requirements.txt`, `README.md`, GitHub Actions CI, and read-only DB queries.

**Existing dependencies (`requirements.txt:1-10`):** `python-telegram-bot[job-queue]==22.8`,
`openai==1.51.0`, `python-dotenv==1.0.1`, `httpx==0.27.2`, `ruff>=0.16,<1`, `edge-tts>=7.2.8,<8`,
`colorlog>=6.12.0,<7`, `pytest>=8,<9`, `flask>=3,<4`, `tzdata>=2024.1`. **No numeric / ML deps**
(numpy / torch / sentence-transformers / onnxruntime / transformers are absent). Local `numpy`
exists only in the global user site-packages (not a project dependency). `import torch`,
`import sentence_transformers`, `import onnxruntime` all fail (not installed).

**Deployment model:** bare `python bot.py` process (README), no Docker, no serverless
manifest (no `Dockerfile`, `docker-compose.yml`, `Procfile`, `fly.toml`, `render.yaml`). Only CI:
`.github/workflows/ci.yml` — job on `ubuntu-latest`, python matrix 3.10/3.13, installs
requirements, runs lint/compile/tests/dashboard; no resource limits, CI is not a deploy target.
Python 3.13.5 in use; min supported 3.10 (via CI).

**BLOB / float-vector storage precedent:** none. `services/db/` has no BLOB or binary column;
`float(...)` usages are cost math (ai_presets), not vectors. Any new BLOB / float-vector column
and migration is a new persistence pattern covered by AGENTS.md §6/§7 (fresh-DB + upgrade +
wiring/dead-reference guards). No precedent exists.

**Actual measured data size (read-only sqlite3 on `hamzaban.db`):**

| Table | Rows |
|-------|------|
| `saved_words` | 531 |
| `daily_cards` | 562 |
| `delivery_queue` | 314 |
| `llm_requests` | 1576 |
| `review_events` | 33 |
| `users` | 15 |

`hamzaban.db` ≈ 2.2 MB (measured).

**Embedding-storage projection (SQLite growth only):**
- 384-dim × 4B = 1536 B/row; 531 saved_words ≈ 0.8 MB; + 562 daily_cards ≈ 1.7 MB combined;
  plus BTree/page/index overhead → ~2-3 MB DB growth.
- 768-dim × 4B = 3072 B/row → ~3.4 MB combined.
- Even indexing all `llm_requests` (1576) adds only ~2.4-4.8 MB.
- Net on a 2.2 MB DB: roughly tripled to ~5× — trivial for a VPS.

**Model footprint (CPU, single worker, resident):**

| Model | params | Disk (installed) | RAM (weights) | + runtime | Total RAM est. |
|-------|--------|------------------|---------------|-----------|----------------|
| `multilingual-e5-base` | ~110-113M | ~0.45 (FP32)/0.22 (FP16) | 0.4-0.2 | ~0.2-0.4 | ~0.8-1.2 GB |
| `all-MiniLM-L6-v2` | ~22M | ~90 MB + torch | ~90 MB | ~0.3-0.5 | ~0.5-0.8 GB |

CPU single-query latency: e5 ~50-300 ms, MiniLM ~20-80 ms (blocker-ish on a hot path).

**requirements.txt additions:** `sentence-transformers` (pulls `torch`, `numpy`, `transformers`,
`tokenizers`, `scikit-learn`, `huggingface-hub`); optionally `onnxruntime` (≥1.17/1.18 for
CPython 3.13) to avoid torch.

**Conflicts with existing pins:** openai 1.51 / httpx 0.27 / flask 3.1 / python-telegram-bot 22.8
do not overlap torch / numpy / transformers → **no version conflicts from the current lock**.
Real risk: python version — torch 3.13 wheels are fine from 2.5+; `onnxruntime` needs ≥1.17/1.18
for 3.13. CI friction: torch CPU wheel ~190 MB (Linux) / ~850 MB (Windows), vs ~80 MB onnxruntime;
would materially slow `pip install` (currently 10 lightweight deps).

**Verdict (one line):** feasible-with-constraints — VPS-approachable (<1 GB model load), but adds
a dependency set, a new BLOB/vector schema, async offloading of the blocking call (AGENTS.md §3),
and CI wheel weight.

---

## 3. Callback wiring & scope

### 3a. Existing feedback-button precedent
**No learner-facing "report"/"flag"/"غلط"/"گزارش" button exists.** Grep hits for `report|flag|feedback`
are unrelated admin cost-renderers (`handlers/admin.py:618 def _llm_cost_report_text`, `:755`) and
error strings. The only learner-facing grade buttons today are SRS:
`config/keyboards.py:314-356` (SRS grade) and `:359-401` (first-exposure), producing
`srs:N:user:word` / `srs:fe:...` callbacks. The grade/activity registry confirms no report/flag
activity type: `grade_policy.py:21-62` `GRADE_POLICIES` = `srs_review, first_exposure, new_ai_card, ...`;
`ACTIVITY_REGISTRY` = `srs_review, first_exposure`. A `report_card:*` action would be a genuinely
new precedent.

### 3b. saved_words quality-signal columns
`schema.py:109-124` (CREATE `saved_words`): `id, user_id, word, lang, normalized_word, card_data,
interval_idx, next_review, review_status, review_requested_at, added_at, first_exposure_done, stability,
difficulty`. ALTER migrations (`schema.py:281-302`) add `normalized_word`, `card_data`,
`review_status`, `review_requested_at`, `retry_at`, `srs_retry_attempts` (default 0),
`first_exposure_done`, `stability`, `difficulty`. There are **no** `is_correct`, `last_review_result`,
`error_count`, `reviewed_count`, `flag`, or `quality` columns.
Actual per-attempt quality lives separately in `review_events` (`schema.py:198-205` + migrated `:307-315`):
`word_id, user_id, revealed_before_answer, outcome, created_at, grade, activity_type, grade_source,
raw_signal, response_time_ms`. `raw_signal` (JSON; `srs_handler.py:90,143`) is the current carrier;
`users.streak` is the only other quality-adjacent metric (`schema.py:95`).

### 3c. AGENTS.md §9 guardrail analysis
Exact wording: *"Do not introduce payment automation, groups, leaderboards, AI images, ...
broad analytics, or advanced placement testing unless the user explicitly moves them into scope
through `ROADMAP.md`."* Also: *"Reliability and data correctness take priority over additional
premium features."*

- **Admin forum group — FLAG.** An admin forum group is squarely a `groups` feature, and `groups`
  is listed verbatim in the guardrail. Even if admin-only (not an open learner group), the bot
  joining/managing a Telegram group falls under the literal prohibition. Adding it requires an
  owner decision + a `ROADMAP.md` scope move to clear the guardrail.
- **Model-tagging (tag production model id)** — genuinely outside the list. None of the six
  forbidden categories is a transparency tag. The underlying data already exists
  (`llm_requests.model`, `llm_requests.preset_name`, `schema.py:184,503`) for cost tracking, and the
  model id is already a sanctioned per-request field. So tagging is attribution metadata, not one
  of the forbidden categories. Caveat: writing per-card model ids into all learners' card_data
  could drift toward "broad analytics" and should be deliberately scoped.

### 3d. `report_card:*` prefix-collision analysis
The `callback_router` (`bot.py:422-595`) dispatches by first-token prefix. Tokens in use: `study`,
`query`, `presentation`, `flow`, `srs`, `tts`, `lang`/`goal`/`level`, `settings`, `llm`, `admin`.
Router uses `data.startswith("token:")`. `report_card` shares no first-token prefix with any of
these; no existing branch string-prefix-matches `report_card:` nor is swallowed by it. Early
`srs:`/`srs:reveal:` review routes were removed and the wiring test now asserts their absence.
`report_card:` is a clean new namespace — **no collision risk**.

### 3e. Wiring-change footprint (what must change to pass the guards)
1. `config/keyboards.py` — add a `report_card:` button builder (auto-scanned by
   `_collect_all_callback_prefixes`, `tests/test_wiring.py:258-298`, SCAN_DIRS `:10`).
2. `bot.py` `callback_router` — add `elif data.startswith("report_card:"):` branch; auto-detected
   by `_collect_router_handlers` (`:301-334`); guard `_prefix_matches_handler` (`:366-378`).
3. Handler module — implement the handler (build the button in keyboards to keep single-source).
4. AGENTS.md §3 Callback Routing Map + the callback-wiring skill table (docs; not test-asserted).
5. `tests/test_wiring.py` — no manual test edit strictly needed for a new top-level branch.
6. Schema change (new flag/quality column or table) — edit `services/db/schema.py` (CREATE
   `:88-239` + ALTER `:277-302`) and possibly `words.py`; tested on fresh + upgrade DB
   (`tests/test_migration_guard.py`, banned-column guards).

---

## 4. Open questions requiring owner decision

- **Choose the pool intake source identity after the `daily_card` table is dropped** — acceptance
  path, sequencing, source-kind `daily_card`, and avoid-list wording all reference a dying concept.
- **Decide where the segment key `(goal, level)` should live**, since `saved_words` has neither
  column today and the plan's verification SQL is not reducible as written.
- **Choose one canonical normalization** (casefold vs lower-trim) so `saved_words` + `content_pool`
  `item_key` cannot diverge silently.
- **Confirm the actual current user count** (plan assumes a handful) to gate the DAU≥50 sequencing trigger.
- **Decide whether the admin group chat is worth a `ROADMAP.md` scope move out of the §9 `groups` guardrail.**
- **Decide if semantic-cache embeddings are added at all**, given the §7-strict dependency
  (sentence-transformers / torch/onnxruntime) + new BLOB schema + async-offload + CI weight).
- **If `report_card:*` proceeds**, fix intent into the routing map / skill table and choose the
  signal carrier (a `flag`/`quality` column vs the existing JSON `raw_signal` in `review_events`).
- **For the Tier-3 plan update (owner to lock):** choose cache/pool key semantics (exact
  `query_results` token vs segment key vs vector search), decide where the hit path plugs into
  `generate_tier3_node()` / `study_handler.py:318-334`, and confirm quota/eligibility rules
  (Tier-3 slot counted, provider budget untouched, intake re-derived from `saved_words` Tier-2).

---

## 5. Tier-3 interconnection (current state + what a Tier-3-with-pooling/cache plan must address)

> Added 2026-08-06 per owner direction: Tier 3 (new-card generation / cache-hit path) is the next
> implementation step of the session engine, so the pooling + semantic-cache proposals must be read
> against the Tier-3 seam, not only against Tier 1/2. Fact-gathering only — no implementation, no
> locked decision, no plan-file edit.

### 5.1 Tier 3 as currently planned

- **Stub by design:** `generate_tier3_node()` in `services/session/assembly.py:153-167` returns
  `None`; `docs/plans/fsrs/plan_fsrs_migration_v2.md:398,402,581` (Decision 26) and `:196-197` in
  `project_status.json` (Phase 3b+) defer real AI generation.
- **Invocation seam:** `handlers/study_handler.py:315-334` — `advance_session()` calls
  `generate_tier3_node(**state.tier3_context)` ONLY when `tier3_context` is populated (remaining
  slots), appends the node, and renders it in place. This is the exact point a cache/pool read
  would replace the AI call.
- **Planned prompt for Tier 3:** `docs/plans/fsrs/plan_daily_cards_migration.md:143-155` designates
  `daily_card_system_prompt` (`services/ai/prompts.py:88-...`, `avoid_words` param at `:91-105`)
  as the Tier-3 template, with `avoid_words` from already-seen words (Tier 1+2 + Tier-3 so far)
  and AI daily quota respected.
- **Generation entry point:** `services/ai/ai.py:610-650` `ask_card()` (validate + repair +
  telemetry) is the card-generation contract; `_prepare_cached_card()`
  (`services/ai/llm_services.py:195-237`) is the existing cached-card repair/validation path.

### 5.2 Existing cache precedent (not vector-based)

- **Exact-match query cache exists today:** `query_results` table
  (`services/db/schema.py:153-164`: `token` PK, `query_text`, `word`, `lang`, `result_json`,
  `expires_at`, `saved_at`, `saved_word_id`) with CRUD in `services/db/__init__.py:202-276`
  (insert/read/update/cleanup `cleanup_expired_query_results`). `token`-keyed, exact-match,
  per-user, time-boxed. This is the pragmatic predecessor any Tier-3 "cache hit" must coexist
  with or extend.
- **No vector/BLOB storage anywhere** (§2): the proposed semantic cache is a brand-new
  persistence + runtime pattern; there is no numpy/embedding dependency today.

### 5.3 Current live query pipeline (the seam any semantic cache must hook into)

> Added 2026-08-06: the audit earlier referenced `query_results`/`ask_card`/`_prepare_cached_card`

> Added 2026-08-06: the audit earlier referenced `query_results`/`ask_card`/`_prepare_cached_card`
> in isolation only. This subsection documents the **full, currently-landed custom-word query flow**
> so a semantic-cache or pooling read can be designed against the real lifecycle, not an abstraction.

The live custom-word ("ask a word") flow, end-to-end (all evidence re-verified):

1. **Entry + validation:** `awaiting == "ask_word"` branch in `bot.py:257-269`; input checked by
   `_custom_word_input_error()` (`handlers/user.py:513`).
2. **Atomic quota reservation (before any AI):** `db.reserve_word_query(user_id, limit,
   bypass_limits=...)` at `bot.py:270`; plan limit from
   `daily_word_query_limit_for_plan()` (`config/__init__.py:119-120`). A failed reservation ends
   the flow without any provider call (`bot.py:275-281`). This is the **atomic quota gate** the
   cache must not bypass (§2.2 mandate).
3. **AI generation off the async loop:** `asyncio.wait_for(asyncio.to_thread(_call_ai_limited,
   ai.ask_card, custom_word_system_prompt(...)), ...)` at `bot.py:287-305`. `ask_card()` at
   `services/ai/ai.py:610-650`; blocked behind the shared limiter per AGENTS.md §3. On timeout or
   exception, `db.release_word_query(user_id)` backs out the reservation (`bot.py:307,317`).
4. **Cache validation/repair:** `_prepare_cached_card()` at `bot.py:327-339` →
   `services/ai/llm_services.py:195-237`. Despite the name, this is currently the **validate +
   repair** step for a freshly generated card (not a cache *read*); it calls `ai.validate_card`
   and, on failure, `ai.repair_card` behind `_call_ai_limited`. The repair path is declared
   un-repairable → `CardPreparationError` → release quota (`bot.py:351-360`).
5. **Persist + count + deliver** — `db.create_query_result(user_id, text, word, lang, data)`
   (`bot.py:364-370`, impl `services/db/__init__.py:184-217`), `db.touch_streak(user_id)`
   (`bot.py:371`), render `format_card(...)` + `query_result_keyboard(token, ...)`
   (`bot.py:375-394`).
6. **Post-delivery callback actions against the persisted token:**
   - `query:prepare:{token}` → `_handle_query_prepare` (`handlers/user.py:548-577`), re-fetches
     the cached row and calls `_prepare_cached_card` (repair path) to produce prepared
     translations.
   - `query:add:{token}` → `_handle_query_add` (`handlers/srs_handler.py:34-53`), idempotent
     "Add to review": reads row, rejects if `saved_at` set (`:41-43`), `add_saved_word(user_id,
     word, lang, result_data)` + `mark_query_result_saved(token)` (`:45-47`).
   - Both routes dispatched in `callback_router` at `bot.py:540-547`.
7. **Cache row lifecycle & expiry** — `query_results` schema (`schema.py:153-164`),
   `get_query_result` with expiry check (`services/db/__init__.py:220-230`),
   `update_query_result_fields` (`:244-269`), and `cleanup_expired_query_results`
   (`:272-276`, also `schema.py:399`) purge expired rows. TTL set at creation
   (`secrets.token_hex(16)` + `expires_at`, `:196-198`).

Design-relevant facts for a semantic-cache proposal (from the above):

- **The cache today is exact-match, per-user, token-keyed, time-boxed**; it is a *delivery
  handle*, not a cross-user content store. A semantic cache is a different locus (cross-user,
  query-similarity-keyed) and must be *added*, not grafted onto `query_results`, or it risks
  breaking `query:prepare:`/`query:add:` token invariants.
- **Quota is reserved before AI and released on failure** — a cache hit must route around
  `ask_card()` only *after* the same atomic reserve gate, so a hit does not bypass §2.2/broader
  quota semantics silently (the `docs/plans/content/plan_pooling.md:61-69` rule for pool hits mirrors this).
- **The only landed repair/validation choke point for fetched cards is `_prepare_cached_card()`
  + `ai.validate_card`**; both any pooled-card read (Tier-3 or query) and a semantic-cache read
  must pass the same validation invariant (`docs/plans/content/plan_pooling.md:125-127`) or the card-repair fetch
  path `ai` again (extra provider cost — relevant to the AI-cost discipline rule).
- `cleanup_expired_query_results` lifecycle (§5.2 §5.4 item 7) is the one landed expiry/GC lifecycle a new
  cache layer must not disturb.

### 5.4 Interaction of the two proposals with Tier 3 (observed facts, not recommendations)

| Concern | Pool proposal (docs/plans/content/plan_pooling.md) | Semantic cache (proposed) | Tier-3 seam impact |
|---|---|---|---|
| Where a hit would replace AI | Pool read path planned to live in `services/ai/cards.py` (#180) per `docs/plans/content/plan_pooling.md:174,178-183` | A cache lookup would sit before `ask_card()` / `_prepare_cached_card()` | `generate_tier3_node()` is the only caller that "refills" a session; both proposals must plug into `study_handler.py:318-334` or inside `generate_tier3_node()` |
| Eligibility source | `daily_card` source-kind is stale (see §1); intake must re-base on `saved_words` Tier-2 (`first_exposure_done`) or the custom-word/saved path | Candidate set = generated/validated cards (Tier-3 output) that were ever produced | Both must agree on what "accepted/validated" content is eligible to be cached/pooled — currently only `saved_words` + `grammar_tips` carry accepted content |
| Segment key | `(target_lang, goal, level, source_kind, item_key)` — but `saved_words` lacks `goal`/`level` (§1, finding 2) | An embedding keyed by lang+query semantics | Tier-3 generation already receives `goal`/`level` via `tier3_context` (`study_handler.py:141-147`) — so a cache/pool keyed by `(lang, goal, level)` is satisfiable at the Tier-3 seam even though `saved_words` cannot supply it |
| Quota / cost | Pool hit = learner-facing feature quota, zero provider cost (`docs/plans/content/plan_pooling.md:61-69`) | Cache hit = zero provider cost, still product usage | Tier-3 quota (`consume_session_slot`) is separate from AI daily cap; a cache/pool hit must not burn AI quota but must still count as a served slot |
| AI quota interplay | `docs/plans/content/plan_pooling.md:63` — pool hit consumes learner feature quota, not provider budget | Same intent | `ask_card()` burns AI daily cap; `generate_tier3_node()` currently would too — a hit path must route around `_call_ai_limited` (see `llm_services.py:96`) |
| Validation invariant | `docs/plans/content/plan_pooling.md:125-127` — no invalid card may be shown or pooled | Cache rows must pass the same validation | `_prepare_cached_card()` already re-validates cached cards (repair via `ai.repair_card`, `llm_services.py:195-237`) — reuse this for pooled/cached Tier-3 reads |
| Avoid-lists | `docs/plans/content/plan_pooling.md:130-132` — pool-served cards enter the same stored paths so prompts avoid them | Cache hits must respect per-user `saved_words`/`grammar_tips` | Tier-3 prompt already threads `avoid_words` (`prompts.py:91-105`); a hit must bypass generation but still be excluded if it is the user's own word |

### 5.5 Sequencing observations for the future Tier-3 plan update

- Both the pooling read path (`docs/plans/content/plan_pooling.md:146-158` slices) and the semantic-cache embed
  path are **unimplemented**, and their re-entry triggers are gated on scale
  (`docs/plans/content/plan_pooling.md:210-233` DAU≥50 + segment density; §2 embedding verdict
  feasible-with-constraints).
- Tier-3 implementation (Phase 3b+, `project_status.json:197`) is a prerequisite *independent*
  seam: before either proposal can serve cards, `generate_tier3_node()` must produce real nodes,
  and the session engine must still be in the middle of its Phase-2 dead-code purge
  (daily/review/old-SRS removal, `project_status.json:192`).
- The existing `query_results` token cache (§5.2) is the one landed, test-covered cache today;
  any new Tier-3 cache layer must be added alongside it without disturbing its
  `cleanup_expired_query_results` lifecycle.
- Per §2.2/§2.4, the plan-file updates the owner is contemplating (Tier-3 plan with pooling +
  semantic cache) must be Contract-Locked with explicit owner choices (cache key vs vector search,
  where the read plugs in, quota semantics, eligibility source re-derivation) — this audit only
  records the facts above.

---

_End of audit. No source files were modified; this report is the sole output._
