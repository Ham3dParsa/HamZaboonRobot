---
name: plan-supervised-arbitration
description: Operator-supervised arbitration batches (Gemini/Claude/ChatGPT answer sheets) + gallery viewing + local-provider form + clean screening-to-linking wiring
created: 2026-09-28
base_commit: 25190a7ccbe9a3ed51bf14919cc92e73db84c254
branch: feat/supervised-arbitration
status: in-progress
---

STATE: phase 0/6 — status: in-progress — focus: W1 tickets (P01/P02/P03) in progress

## Locked rules (owner-confirmed 2026-09-28)

| # | Rule | Decision |
|---|---|---|
| R1 | Vote authority | AI answers are final **but** import-time operator review: per-item checkboxes + select-all; only approved finalize (`annotator=gemini:<batch-id>`, reviewer=operator); rejected return to queue intact |
| R2 | Batch carrier | Markdown primary (copy straight into any AI chat) with separate copyable system-prompt block + version + hash + exact answer-sheet template; JSON of same data alongside |
| R3 | Answer sheet + import | AI must declare model name + prompt hash (mandatory fields); strict import (whole-batch reject with precise error, never partial) + «repair request» composer (error text ready to copy back to the AI) |
| R4 | Batch lifecycle | exported → awaiting → partial/complete → in_review → imported/cancelled; no re-export until explicit cancel (anti-rework); oldest-unjudged-first; size 10–50, default 25; progress in run history |
| R5 | Section identity | Human-review section renamed «داوری تحت نظارت اپراتور»; batches guided there from previous step's input file (webui-only, zero Telegram callback impact) |
| R6 | Gallery + mechanical path | «Build gallery» button via existing `viewer.build_linker_gallery` for current AND old runs (rebuild from stored TSV + verdicts); supervised arbitration reachable with AI or mechanical-only, within current linker logic |
| R7 | Kept from earlier lock | Local-provider registration form (UI-only over existing `POST /api/managed_providers`); real model execution stays with owner — this phase writes NO model-calling code |
| R8 | Placement | Separate branch/worktree from `origin/main`; additive changes; zero live interference with PR 831; textual merge conflicts possible in `server.py`/`index.html`/`provider_registry_controller.js` (accepted) |

## Frozen API contracts (waves build against these — do not invent variants)

- `POST /api/batches {size=25}` → `{batch:{id,size,status:"exported",md,json,prompt_version,prompt_hash,created_at}}` | errors `VALIDATION-*`
- `GET /api/batches` → list `{id,size,status,answered,approved,created_at}`
- `GET /api/batches/<id>` → batch + md text + items (for copy/download)
- `POST /api/batches/<id>/import {answer_sheet}` → `{staged:n}` + status `in_review`, or 422 `{error, repair_request}`
- `POST /api/batches/<id>/approve {ids:[...]}` → `{finalized:n, returned:m}` (appends `labels.jsonl`)
- `POST /api/batches/<id>/cancel`
- `GET /api/gallery?run=<run-id-or-path>` → gallery HTML (build-if-missing from stored TSV + verdicts; honest 404 when sources absent)
- Batch item: `{sense_id,lemma,definition,example,tags[],candidates:[{synset_id,definition,example,tags[]}]}` from screened JSONL + mechanical candidates
- Answer sheet (JSON): `{model,prompt_hash,verdicts:[{sense_id,verdict:link|none,target_synset|null}]}` — unknown id / bad enum / link-without-target / version mismatch → whole-batch reject
- Batch store: `<data_root>/webui/batches/<id>/` (batch.json + batch.md + batch.json-data + answers/)
- System prompt: versioned file `factory/webui/supervised_prompt_v1.txt` (sha256 = prompt_hash)

## Tickets & waves

| Wave | Ticket | Files (new unless noted) | Skills |
|---|---|---|---|
| W1 ∥ | P01 batch export builder | `factory/webui/batches.py`, `supervised_prompt_v1.txt`, `tests/factory/test_webui_batches.py` | tdd-enforcement |
| W1 ∥ | P02 gallery build module | `factory/webui/gallery.py`, `tests/factory/test_webui_gallery.py` | tdd-enforcement |
| W1 ∥ | P03 local-provider form | `index.html` (provider-add section), `provider_registry_controller.js` | persian-formatting |
| W1 serial | route mounting (coordinator) | `server.py` (mount P01/P02 blueprints) | — |
| W2 ∥ | P04 import+approve | `factory/webui/batch_import.py`, tests | tdd-enforcement |
| W2 ∥ | P05 supervised UI | `index.html`, new `js/sense_linking/supervised_batch_controller.js` | persian-formatting, ui-ux-pro-max |
| W2 ∥ | P06 repair composer | `factory/webui/batch_repair.py`, tests | tdd-enforcement |
| W3 ∥ | P07 clean-wiring + mechanical verify | UI edits, report | integration-test-proto |
| W3 ∥ | P08 flow integration tests | `tests/test_integration/test_supervised_arbitration.py` | integration-test-proto |
| W3 ∥ | P09 run guide FA | `factory/webui/RUN_GUIDE.md` | — |

Rules: subagents do NOT commit (coordinator verifies + reviewer-gates + commits per wave); disjoint files per ticket; `server.py` touched only by coordinator.
Validation per wave: `pytest` (own tests), `compile_all.py`, `ruff F821/F811`, `git diff --check`. Reviewer gate (`hamzaban-reviewer`) before each wave commit.

## Phases

- `plan-supervised-arbitration-phase-01-batch-export.md` (P01, R1/R2/R4)
- `plan-supervised-arbitration-phase-02-gallery.md` (P02, R6)
- `plan-supervised-arbitration-phase-03-local-form.md` (P03, R7)
- `plan-supervised-arbitration-phase-04-import-repair.md` (P04+P06, R1/R3)
- `plan-supervised-arbitration-phase-05-supervised-ui.md` (P05, R4/R5)
- `plan-supervised-arbitration-phase-06-wiring-tests-guide.md` (P07+P08+P09, R4/R6)

## Blocked Questions

- [2026-09-28] PR 831 overlap (factory/webui files, other session). Decision: proceed on separate branch with additive changes; live interference zero, textual merge conflicts accepted. (R8)
- [2026-09-28] Batch authority/carrier/lifecycle (3 grill questions). Decisions: R1 final-with-review, R2 md+json, R4 status machine + default 25.
