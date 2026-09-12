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
