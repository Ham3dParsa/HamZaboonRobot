# TICKETS — namespace teeth (D2 + teeth, locked 2026-09-11)

Done (PR feat/namespace-teeth): kind-prefix rule for new outputs,
namespace sections in factory/README + W: README, loud-missing default
Tatoeba pool + 2 tests.

| Ticket | Goal | State |
|---|---|---|
| N1 | Kind-prefix rule (`precard-*`, `pilot-final*`, never v-numbers for new outputs) | DONE (docs) |
| N2 | Loud-missing default pool (`load_tatoeba_pool` warns on pinned default) + tests | DONE (code) |
| N3 | Namespace sections in both READMEs + pinned live set | DONE (docs) |
| N4 | Next line generation: ship under a new kind prefix (not bare `v14`); move snapshot v14a/b/c under `archive/` WITH the code-default fix in the same PR | DATED — triggers the day line-gen-14 ships |
| N5 | Coverage habit: any PR adding a reason literal updates REASON_SLUGS in the same PR (T7 enshrines; the #631/#629 race proved why) | STANDING RULE |

Rules: N4 needs its own contract lock at trigger time (data move +
default change). N5 is enforced by test_reason_slugs_cover_pipeline_literals.
