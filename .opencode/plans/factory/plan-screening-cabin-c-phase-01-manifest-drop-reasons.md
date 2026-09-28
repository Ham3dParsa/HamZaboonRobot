---
name: plan-screening-cabin-c-phase-01-manifest-drop-reasons
description: T01 — manifest drop_reasons aggregation (twin-R3 / proper-R2 / other)
created: 2026-09-27
base_commit: 03c6af6f30696b176d04c53fbaca70a2a8e92840
branch: refactor/webui-static-phase1
status: locked
---

STATE: phase 1/7 — status: implemented-uncommitted — focus: T01 manifest drop_reasons, code+tests+screenshots in worktree feat/screening-cabin-c (no commit)

## Ticket T01 — manifest `drop_reasons` (UX-26, OQ-7) [Wave 1 · PARALLEL-safe vs T02]

- **Blocking edges:** none (first wave). Downstream: T07 (cards), T10 (render).
- **Scope (files):** `factory/linking/export_screened.py` (`export_words` manifest dict `:113-121` + `screened.drops.jsonl` reasons `:101-106` — aggregate, never re-derive); `factory/webui/server.py` `_screening_manifest_summary` (`:5019-5046` — surface new keys); `tests/factory/test_screening_manifest_drops.py` (new).
- **Rule (locked):** manifest gains `drop_reasons: {twin_r3, proper_r2, other}` counted from the drops sidecar `reason` strings (twin/dedup/dup→twin_r3; proper/propn/name→proper_r2; rest→other); invariant `twin+proper+other == dropped_total`. Missing/unreadable sidecar → key absent (honest empty downstream, never zeros). Frontend `splitDropReasons` stays as fallback reader — deleted only when T10 proves the key present (route-delete rule).
- **Tests:** golden: fake `screen_fn` with known twin/proper/other drops → manifest sums + invariant; absent sidecar → no key; `server.py` summary surfaces `drop_reasons` verbatim, drops it when absent.
- **Wiring rows:** `export_screened.export_words → screened.manifest.json(+drop_reasons)`; `manifest → _screening_manifest_summary → /api/screening/status.screening.manifest`.
- **Changed / not changed / uncertain:** changes manifest schema (additive) + summary reader. NOT changed: prune logic, sidecar format, per-lemma rows (OQ-7 sense_id+reason detail comes from sidecar via T07). Uncertain: none — reason taxonomy reuses the controller's existing regex classes.

### Acceptance criteria

- **Interaction tests (named):** IT-T01-01 run 5 smoke words → `GET /api/screening/status` shows `manifest.drop_reasons` with `twin_r3+proper_r2+other == dropped_total`; IT-T01-02 legacy manifest without key → twins/proper cards render `—` titled «سرور تفکیک علت ثبت نکرد» (no crash, no zeros).
- **Screenshots:** `shot-t01-drops-desktop.png` (metric cards with split values) + `shot-t01-drops-tablet.png` (same, accordion layout).
- **pytest:** `python -m pytest tests/factory/test_screening_manifest_drops.py -n 8`
