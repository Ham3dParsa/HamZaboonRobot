# STATE: LOCKED (2026-09-04) — F4 EN phrase pool (pilot 500)

## Locked rules
- R1: fresh deterministic pass over kaikki index (kaikki-en-index.jsonl on W:), collect spaced lemmas + frequency. Sampler untouched.
- R2: phrase = 2-5 tokens, alpha only, each token 2+ letters, no digits/symbols.
- R3: TOP 500 by index frequency (pilot; owner: 500 enough to start, quality of refinement must be recorded).
- R4: level authority = LLM batch judge (Zen responses API, Spark 1.2 -> 1.3 free chain, batch 8, resume-able progress log); deterministic max-component CEFR (pack evp_sense.json) as prefill + fail-closed fallback (`unlevelled`).
- R5: factory/packs/en/phrases.csv + pack.json `phrases` section; word pool + mix untouched.
- R6: CSV only now; registry entry in P1.

## Quality recording (owner requirement)
- judge_log.jsonl per phrase: {phrase, freq, prefill, verdict, model, batch_id} on W:/hamzaban_data_factory/fixtures/
- stats: prefill-vs-verdict agreement rate, unlevelled rate, per-level histogram -> status HTML record cell.

## Tickets
- T1: factory/phrase_pool.py collect+prefill + tests/test_phrase_pool.py (deterministic, hermetic fixtures)
- T2: factory/phrase_judge.py batch runner (env_loader, llm_json, progress resume, sleep 2.5s, tqdm) + prompt spec from hamzaban-ai
- T3: run 500 + judge_log + stats; update status HTML + TICKETS-10k.md
- Gate: hamzaban-reviewer 0 findings; full validation; squash PR.
