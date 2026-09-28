# Phase 04 — Batch import + approve + repair (P04 + P06)

Gates: R1 (review-then-finalize), R3 (strict import + repair request).
Blocking: P01 batch shape (frozen in main plan — build against it, W2).

## Scope (new files only)

- `factory/webui/batch_import.py`: `validate_answer_sheet(batch, text)` → staged list or raise `BatchImportError` (unknown sense_id / bad enum / link-without-target / none-with-target / prompt_hash mismatch / model field missing — whole batch rejected, precise farsi message, never partial); `stage_import(batch, sheet)` (status `in_review`, answers stored, not yet labels); `approve(batch, ids, reviewer)` → append approved to `labels.jsonl` via `labels.save_label` (`annotator=f"gemini:{batch_id}"`), rejected return to pool, status `imported` (+counts); `cancel_batch(batch)`.
- `factory/webui/batch_repair.py`: `compose_repair_request(batch, error)` → copy-ready text (batch id, prompt version+hash, failing ids, exact error lines, ask-model-to-fix instruction).
- Answer sheet parsing: JSON primary (also accept the sheet wrapped in chat prose? NO — strict JSON block extraction: find first `{...}` else reject; locked: strict).

## Tests

- Extend `tests/factory/test_webui_batches.py` (or new `test_webui_batch_import.py`): happy path stage→approve→labels appended with right annotator; each rejection class; repair text contains ids + error; re-export guard (non-cancelled batch blocks rebuild — P01 exposes `active_batches()`).

## Wiring rows

| Type | Item | Disposition |
|---|---|---|
| New modules | `batch_import.py`, `batch_repair.py` | create |
| Reused | `labels.save_label`/`validate_label`, P01 store | keep (no change) |
| Routes | `POST /api/batches/<id>/import|approve|cancel` | mount by coordinator (additive) |

## Acceptance

Import→review→approve lifecycle green in tests; rejected ids re-exportable in a later batch; zero partial writes (failure leaves batch + labels untouched).
