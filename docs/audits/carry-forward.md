# Audit carry-forward — open remainders (2026-09-24)

Source audits moved to `docs/archive/audits/`. Only the items below are still
open; everything else from those reports has landed or rotted.

| # | Remainder | Source doc | Evidence (file:line) | Suggested audit area |
|---|-----------|------------|----------------------|----------------------|
| 1 | Tier-3 generation stub open | `architecture_session_srs_audit_v1.html` RULE-SS-001 | `services/session/assembly.py:73` — `generate_tier3_node` stub returns `None` | depth |
| 2 | `llm_requests` card join key missing | `audit_content_pool_feedback_2026-08.md` §3/App B (via `docs/plans/content/plan_pooling.md:81`) | `services/db/schema.py:721` — `llm_requests` has model/preset but no `card_id`/`saved_word_id` column | depth |
| 3 | `ORDER BY is_emergency` leftovers | `architecture_ai_pipeline_audit_v1.html` RULE-AI-003 | `services/db/preset_registry.py:512` (also `:412`, `:521`, `:531`, `:599`; `services/db/schema.py:1037`) | duplication |
| 4 | staged-reveal dead code vs new engine | `ux_ui_audit_srs_language_leak_2026-08-13.md:115` + `:229` | `services/utils/formatting_cards.py:38` — #338 engine landed; confirm old `format_srs_prompt`/`SRS_HIDDEN_*` stays gone | duplication |
| 5 | `schedule_next` phantom | `architecture_session_srs_audit_v1.html` RULE-SS-003 | repo-wide grep `schedule_next` → zero `.py` hits (only audit HTML + `docs/audits/index.html:64`) — planned `fsrs_core.schedule_next` never landed | naming |
| 6 | brief/detailed parity | `ux_ui_audit_srs_language_leak_2026-08-13.md:229` (a) | `services/db/users.py:237` — `set_presentation_preference` still accepts `{brief, detailed}` while render uses display toggles | duplication |
| 7 | translations-toggle parity | `plan-srs-staged-reveal-spec.md` (toggles replace brief/detailed) | `config/catalog_toggles.py:24` — `example_translations` toggle vs per-card translation rendering | duplication |
| 8 | `avoid_words` vs pool exclusion | `pool_semantic_cache_audit_2026-08-06.md:342` | `services/ai/prompts.py:111` — `avoid_words` param threads Tier-3 exclusion; pool hits must still exclude the user's own words | duplication |
| 9 | query-vs-saved-vs-pool dedup semantics | `pool_semantic_cache_audit_2026-08-06.md` §6 open decisions | `services/db/schema.py:81` — `normalize_word` single-sources saved/query dedup; pool-layer exclusion semantics undecided | duplication |
