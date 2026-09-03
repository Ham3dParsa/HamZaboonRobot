# en pack (v14) — R5

Language pack for English. Code reads it through `pack.json` manifest only;
no English-specific logic lives in `run_v14_phase1.py`. Adding German =
adding `factory/packs/de/` with the same files, zero code change.

- `pack.json` — manifest (weights, tiers, thresholds, file pointers)
- `lemmas.csv` — 500 pilot lemmas (lemma,pos,cefr)
- `evp_sense.json` — per-sense CEFR + domain table (~2000 entries)
- `cefrj_pos.json` — pos fallback (kept for compatibility)
- `topic_prototypes.json` — 13 topic keyword strings + thr
- `tatoeba_pool_v13c.json` — example pools per lemma (461 lemmas)
- Raw Kaikki lives outside git: `W:/hamzaban_data_factory/raw/filtered_500_kaikki.jsonl`
