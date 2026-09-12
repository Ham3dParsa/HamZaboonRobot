# factory/archive — frozen research snapshots (read-only)

Package `factory.archive.v14_v16` — vendored scorer owners, frozen by the namespace rule:

- `run_v14_phase1.py`, `run_v14_phase2_merge.py`, `run_v14_phase3_judge.py`
- `run_v15_topics.py`, `run_v16_topics.py`, `run_v16b_topup.py`
- `DESIGN-registry-A.md`, `DESIGN-registry-B.md`, `REGISTRY_EVIDENCE.md`,
  `v15_EVIDENCE.md`, `v16_EVIDENCE.md`, `V16B_EVIDENCE.md`

Rules: v-numbers never rename, never delete the pinned live set
(see `../README.md` §Namespace rule). The live line (`../../pipeline/`)
reuses these transports by import — rank logic lives here, do not re-implement
elsewhere. `ROOT` inside these scripts resolves to `factory/` (not the archive
subdir) so `packs/` + `fixtures/` references keep working after the move.
