# factory/pipeline — pilot line (card_pilot, blind50)

Live pilot-line code (package `factory.pipeline`, run with `python -m` from repo root):

- `card_pilot.py` — anchor scorer, kaikki readers, run logger, gallery render.
- `blind50.py` — 4-way judge comparison on the frozen 50 (needs keys).
- `card_gallery.html` — gallery template (v4: narrow centered cards, faint
  topic/CEFR tags, centered examples, syn=green/ant=red). Opens standalone
  with built-in sample data; never hand-edit the data block.
- `render_gallery.py` — injects a run's rows into the template (only `word`
  required per row; safe defaults fill the rest). The caller chooses `--out`
  freely per run; run outputs are artifacts, not committed.

```powershell
python -m factory.pipeline.render_gallery --data <rows.json> --out <run.html>
```

Source of rows: card_pilot complete-card records (`cards.jsonl`) reshaped
to gallery rows. The exporter is deferred until the completion line
stabilizes; the gallery stays decoupled behind rows JSON (no precard
mapping here — precards are pre-completion input, not gallery source).

The precard line moved to its own home: `../precard/` (v1.4.1, run with
`python -m factory.precard`). Pilot-line stage ids (`s0..s5`) and the pilot's
own guard copies stay here by design (pilot versioning is T6, deferred).

```powershell
python -m factory.pipeline.blind50 --accept W:\hamzaban_data_factory\pilot\accept50.json `
  --anchor W:\hamzaban_data_factory\pilot200glm\progress\anchor.json --glm-judge W:\hamzaban_data_factory\pilot200glm\progress\sense-judge.json `
  --out W:\hamzaban_data_factory\blind50\blind50.json --progress W:\hamzaban_data_factory\blind50\progress.json --dry-run
```

Stage ids (`s0..s5`) are stable internal keys (progress state keys);
human prose — including `run.log` and `dropped.log` — speaks domain terms (see `../core/stage_glossary.py` + `../README.md`
§Namespace rule).
