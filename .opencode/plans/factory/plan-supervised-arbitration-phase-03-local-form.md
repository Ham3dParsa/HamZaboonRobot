# Phase 03 — Local-provider registration form (P03)

Gates: R7 (UI-only, existing endpoint, no model-calling code).
Blocking: none (W1). Touches existing UI files (our branch only — PR 831 overlap accepted per R8).

## Scope

- `factory/webui/index.html`: extend provider-add card with protocol select (`openai_compat` only for local), `base_url` endpoint input (placeholder `http://localhost:1234/v1`, configurable — LM Studio/Ollama/any OpenAI-compat), key field OPTIONAL for local (empty → `key_vars: []`).
- `static/js/providers/provider_registry_controller.js`: submit to existing `POST /api/managed_providers` (no new route); honest note when keyless: model-listing is key-gated server-side so «دریافت فهرست» will refuse — run path does not need listing (stated, never faked).
- Persian labels via `services/utils/formatting` conventions; BiDi isolation for endpoint LTR text; busy-state + 3-part error on failure.

## Tests

- No new pytest (UI-only, endpoint already covered by `test_managed_routes_crud_and_exact_counts`); verify existing suite still green; manual click checklist recorded in commit message.

## Wiring rows

| Type | Item | Disposition |
|---|---|---|
| Existing UI | `index.html` provider-add card | extend (additive section) |
| Existing JS | `provider_registry_controller.js` | extend (additive handler) |
| Existing route | `POST /api/managed_providers` | keep (reuse, no change) |

## Acceptance

Form creates a keyless local provider visible in provider list; keyless model-list refusal renders honest error; no other console behavior changed.
