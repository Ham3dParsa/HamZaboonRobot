STATE: phase 1/4 — status: locked — focus: A2-4 BUG-B1 $ENV resolver alignment

## CONTRACT LOCK TEMPLATE (agent must fill completely)

Rule #1
Decision: Single source for $ENV resolution lives in services/db/key_crypto.py
Option Chosen: A — centralize in key_crypto (resolve_env helper + decrypt_secret understands $ENV), schema.py delegates
Alternatives Rejected: B keep duplicated os.getenv in both places — leaves drift and violates single-source
Trade-offs: A one place to fix, no drift; B no file churn but bug recurs
Owner Confirmation: "proceed with A for all" (2026-08-21)
GATE STATUS: LOCKED

Rule #2
Decision: Runtime behavior for leftover $ENV_... in DB when migration was skipped (no master key)
Option Chosen: A — runtime resolves $ENV via os.getenv(name,"") same as migration (set→value, unset→"")
Alternatives Rejected: B keep current fail-closed "" without $ENV check — breaks user who stored $ENV intentionally
Trade-offs: A identical behavior on both paths; B silent breakage
Owner Confirmation: "proceed with A for all"
GATE STATUS: LOCKED

Rule #3
Decision: Unset env var handling
Option Chosen: A — unset → "" (empty, provider fails visibly)
Alternatives Rejected: B keep literal "$ENV_FOO" — never valid, confusing
Trade-offs: A consistent with migration; B leaks literal
Owner Confirmation: "proceed with A for all"
GATE STATUS: LOCKED

Rule #4
Decision: Migration skip policy when no master key
Option Chosen: A — skip _encrypt_key_columns entirely when _fernet() is None, re-run later
Alternatives Rejected: B try to encrypt anyway → abort init_db
Trade-offs: A safe restart-safe; B blocks startup without master key
Owner Confirmation: "proceed with A for all"
GATE STATUS: LOCKED

Rule #5
Decision: Scope
Option Chosen: A — fix only $ENV alignment (key_crypto + schema + ai_presets resolver)
Alternatives Rejected: B also touch unrelated BUGS/BNs — scope creep
Trade-offs: A focused PR; B harder review
Owner Confirmation: "proceed with A for all"
GATE STATUS: LOCKED

## Dependency & Wiring Map
| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | none | keep |
| Router branches | none | keep |
| Keyboard builders | none | keep |
| DB tables/columns | ai_presets.api_key, preset_groups.api_key, settings.ai_api_key | keep (values re-encrypted) |
| Handler functions | none | keep |
| Imports/re-exports | services/db/key_crypto.py (new helpers), services/db/schema.py (_encrypt), services/ai/ai_presets.py (resolve_api_key) | update |
| Prompts/formatting | none | keep |
| Tests referencing them | tests/test_key_crypto_encryption.py, tests/test_integration/* if any | update/add |
| Docs | docs/audit/Deepening/2026-08-16-db-domain-consolidated.md (informational) | keep |

## Plan
- Phase 1 RED: tests/test_key_env_resolver.py — decrypt_secret resolves $ENV with/without env set, migration skipped path, unset→empty
- Phase 2 GREEN: services/db/key_crypto.py — add _resolve_env / update decrypt_secret; services/db/schema.py — delegate; services/ai/ai_presets.py doc update if needed
- Phase 3 Validation: full suite + Kilo loop
- Phase 4 PR + merge + cleanup, update plan-2026-08-19-remaining-work.md A2-4→MERGED

## Evidence
- (pending) test names, commit hash, PR number
