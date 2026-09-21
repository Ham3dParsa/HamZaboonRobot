# factory/linking — offline build-time sense linker

## What / why

`factory/linking` is the linker's own identity (M1-M3 structural move): the
Kaikki → WordNet sense-link core plus its frozen vendor table, moved verbatim
out of `factory/precard/` with zero logic change. The precard line keeps its
pipeline; the linker keeps its truth — one owner per concept.

## Scope: offline build-time linker

- **Pure + hermetic.** `linker.py` is stdlib only: no I/O, no network, no
  model, no nltk/torch/embeddings. Candidates, tables and scores are injected
  as plain dicts/lists by the caller (R37 pattern).
- **Build-time, not serve-time.** Linking runs when vendor tables are built.
  Study sessions only *read* the frozen `table.tsv` — they never call a model.
- **Judges as data.** The embedding signal (`Se`, all-MiniLM-L6-v2) and the
  judge leg cross the seam only as *numbers/rows*: injected `se_value`
  floats and `judge_link` verdict dicts. The model and the judge live outside
  the repo (see History).

## Inputs / outputs

Input (injected by the caller, never loaded here):

- Kaikki sense rows: `kid`, `lemma`, `pos`, `gloss`, `tags`, synonyms, examples
- WordNet candidates: sensekeys, lemmas, definitions, hypernyms, topics
- Optional: `se_value` float per candidate, `judge_link` verdict rows,
  `manual_none` / `manual_override` owner locks

Output (per sense): `arbitrate_link(...)` → `{sensekey, method, evidence, flags}` —
`method` ∈ `LINK_METHOD_VOCAB` (see `__init__.py`), `flags` ⊆
`twin-pending / quarantined-known-false / manual-none /
provisional_consensus`.

CLI (offline table tools, `python -m factory.linking.cli`):

- `link --words WORDS --out OUT [--table T] [--progress]` — subset the
  vendor table to a wordlist (headword or exact-kid lines).
- `lookup KID [--table T]` — print row(s) for one `kaikki_sense_id`.
- `stats [TABLE]` — method distribution + flag counts.
- `validate [TABLE]` — `validate_table_rows` pretty report.

## Table schema + sidecar

`table.tsv` columns (tab-separated, UTF-8, header row):

| column | meaning |
|---|---|
| `kaikki_sense_id` | Kaikki sense key (`en-<lemma>-en-<pos>-<id>`; `TSV:`-prefixed inventory rows) |
| `wordnet_sensekey` | Linked WordNet sensekey, or `-` for `MANUAL-NONE` |
| `method` | ∈ `LINK_METHOD_VOCAB` |
| `evidence` | `Sa:/Sb:/Sc:/Sd:` signals + `Se:` score + provenance tags |
| `provenance` | which frozen run produced the row (`linker-v0.6:…`, `judge-v2:…`, `owner-manual:…`) |

141 data rows. Pins, blob SHA and the `factory/precard/…` origin live in
`table.meta.json` (OEWN build-label is a visibly-marked `TBD-OPEN-3`
placeholder until resolved).

## Judges-as-data note

`LINK:judge-v2` rows (13) carry verdict tags like
`judge-v2:idx16:3/3:wear%2:29:04::` inside `evidence`; `provisional_consensus`
flags mark flip-family LINKs (REPORT_v0_8 JOB5 rule). The verdict JSONs stay
on `W:` — only the tags ship.

## Gallery viewer (`viewer.py`, stdlib only)

Flowtrace gallery (`GALLERY_VERSION = 4.1.0`): one card per sense — S-flow
3-col RTL flow (input → signals → gates → judge → decision), verdict-first
wires + status badges, unanimous/concordant/split tiers, sticky toolbar with
filter+search panel, per-record export capsule. Footer carries the dated
gallery changelog (`GALLERY_CHANGELOG` in `viewer.py`).

Regen (run20 paths on `W:`, outputs beside the inputs):

- Full (807 rows):
  `python -m factory.linking.viewer --table W:\hamzaban_data_factory\proof-linker\run20\link_table_run20_v3.tsv --verdicts W:\hamzaban_data_factory\proof-linker\run20\judge_verdicts_run20.json --candidates W:\hamzaban_data_factory\proof-linker\run20\candidates_run20.json --out W:\hamzaban_data_factory\proof-linker\run20\linker_gallery_run20.html`
- Sample (331-row subset, `--words get,light,run,take`):
  same command with `--table ...\run20\link_table_run20.tsv --words get,light,run,take --out W:\hamzaban_data_factory\proof-linker\gallery\linker_gallery_sample.html`

## History pointer

Full per-version history stays on the drive (READ-ONLY, never imported):

- `W:\hamzaban_data_factory\proof-linker\` — `v1\linker_v0_6.py`,
  `v1\link_table_v0_7.tsv`, `v1\REPORT_v0_5.md` … `v1\REPORT_v0_8.md`,
  `v1\VERSIONS.md` (0.5.x–0.8.x log), top-level `VERSIONS.md` (0.1–0.8.x)
- `changelog.md` (next to this file) is the faithful in-repo condensation
  (0.1 → 0.8: what changed, LINK precision, LINK counts each version).
