# Phase 04 — P3 console endpoint + progress

Gates: spec stage 3 WUI. Blocking: P1.
Scope (additive, `factory/webui/server.py` + thin runner glue):
`POST /api/arbiter/runs {preset, senses?}` → run record under runs/
(detached run like screening: status polling, abort); verdicts land
next to the run; disagreements surface in supervised queue scope.
Preset resolution reuses judge-preset store (provider+model+endpoint).
Timeouts/concurrency explicit; secrets never in responses.
Tests: route tests with stubbed runner (no live calls) + status/abort.
Acceptance: endpoint drives P1 over fixtures end-to-end via test client.
