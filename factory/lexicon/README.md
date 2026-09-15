# factory/lexicon — sample/index/pool/judge/AWL builders

Package `factory.lexicon` (run with `python -m` from repo root):

- `sample_lemmas.py` — level-stratified lemma sampler (single source for keep/classify/pack rules).
- `build_kaikki_index.py` — kaikki offset index builder (resume-safe).
- `download_kaikki.py` — byte-range-resume kaikki downloader (atomic rename, dry-run writes nothing).
- `phrase_pool.py` — phrase pool builder (reuses `sample_lemmas.shape_verdict`, never redefines).
- `phrase_judge.py` — phrase-type judge (`KeyRing` rotation, resume progress).
- `fetch_awl.py` — AWL families fetcher; `awl_coverage.py` — pool-vs-AWL coverage report.

Single-source rule: lemma normalization lives in `../core/registry.py`;
`shape_verdict` lives in `sample_lemmas.py`. Never duplicate here.

## Phrase quota recipe (T5 v14)

The word sampler never emits phrases (whitespace routes to
`phrase_candidates`); the precard line consumes them fine
(`kind=phrase` rows + `phrase_type_log.jsonl` `applied_keep` gate —
covered end-to-end in `tests/test_precard_pipeline.py`). To activate a
~10% phrase share in test runs, merge after sampling: take the word CSV
from `sample_lemmas.py`, append `{"kind": "phrase", "text", "pool_level"}`
rows picked from the `phrase_pool.py` pool (live log holds 500 judged
types: 234 keep — collocation 81, idiom 77, slang 52, phrasal-verb 16,
proverb 1, applied 7; 266 drop — term 162, proper-noun 78, other 26),
then run `precard_pipeline.py` on the merged sample unchanged.
