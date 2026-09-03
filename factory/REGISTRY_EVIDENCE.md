# REGISTRY EVIDENCE — locked factory registry build (2026-09-03)

Locked by plan-v14.md REGISTRY LOCK. Implements DESIGN-registry-A.md (SQLite);
proof ideas from DESIGN-registry-B.md §5. No re-decisions, no API/GPU calls.

## Files written

- `factory/registry.py` — registry module (stdlib `sqlite3` only) + `migrate_v14()`
  + `__main__` runner (`python factory/registry.py [db] [fixtures]`).
- `factory/registry.db` — live registry (WAL mode, LOCAL disk only).
- `factory/test_registry_proof.py` — proof test, plain asserts, temp-DB only.
- `factory/REGISTRY_EVIDENCE.md` — this file.

No commit, no PR (task scope). `factory/.env` never touched/read.

## Migrated counts (`en`, after `migrate_v14`, verified idempotent ×3)

| metric | value | locked expectation | delta |
|---|---|---|---|
| lemmas(en) | 499 | 500 | −1: `cast\|verb` B2+C1 fixture rows share one `lemma_key` (locked rule); last-wins cefr=C1 |
| precards total | 2098 | 2101 | −3 net: 5 exact `cast\|verb` dupes collapse by content-hash PK; +2 genuinely reworded v14b merge glosses (`outside\|preposition`) added as new active |
| active | 1671 | 1676 | −5 (the collapsed dupes were all survivors) |
| superseded | 427 | 425 (2101−1676) | +2 (row-count estimate did not account for content dedup) |
| converted | 0 | 0 | exact (v14c picks are selections, not receipts) |
| topics matched | 1676/1676 | — | all v16b labels resolve via aliases |
| merged unresolved (`merged_into` NULL, still superseded) | 5 | — | no `merged_from` link; flagged, NOT guessed |
| multi-survivor (deterministic first-sorted wins) | 1 | — | documented |

Integrity: `GROUP BY lang,pre_card_id HAVING COUNT(*)>1` → 0 rows.
Provenance: `runs` = import-v14a/b/c + import-v16b, fingerprint `v14a:legacy-import`.

## Proof test results (`python factory/test_registry_proof.py` — ALL PASS, temp DB)

- (a) import twice → stats byte-identical, dupe query empty. PASS
- (b) 20 shuffled duplicate lemmas re-imported → 0 new rows, stats unchanged. PASS
- (c) `de` + 3 fake lemmas → de=(3/3/3), en untouched; fingerprint
  reuse/reprocess ×4 cases. PASS
- (d) `FINAL-en-20260903-01` claim(10) → complete 3 → converted=3;
  double-complete/double-convert refused; fresh lease requeues 0, backdated
  lease requeues 7 (3×done kept); `…-02` reclaims all 7, no double-claim;
  converted=4. PASS

## Backup

`backup_db(db, r"W:\hamzaban_data_factory\registry")` → `VACUUM INTO`
`registry-backup-YYYYMMDD-HHMMSS.db`. Backup ONLY — live DB never on W:
(SQLite locking over network shares corrupts). Not executed in this task
(no W: write requested); helper is implemented + importable.
