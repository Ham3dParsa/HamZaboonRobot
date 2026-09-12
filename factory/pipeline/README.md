# factory/pipeline — PishCard v13 precard line

Live line code (package `factory.pipeline`, run with `python -m` from repo root):

- `precard_pipeline.py` — the line (preprocess/inflection/anchor/judge/vectors/label/enrich stages,
  gates G1–G6, resume). Reuses `card_pilot` + `archive/v14_v16` transports by import.
- `card_pilot.py` — anchor scorer, kaikki readers, run logger, gallery render.
- `blind50.py` — 4-way judge comparison on the frozen 50 (needs keys).

```powershell
python -m factory.pipeline.precard_pipeline --sample W:\hamzaban_data_factory\pilot\sample200b.json `
  --out out\precard.jsonl --progress-dir out\prog --limit 20 --dry-run
```

Stage ids (`s0..s5`) are stable data literals (progress keys, filenames);
human prose — including `run.log` and `dropped.log` — speaks domain terms (see `../core/stage_glossary.py` + `../README.md`
§Namespace rule).
