# Phase 03 — P2 TUI (`judge` CLI — final name in-phase)

Gates: spec stage 3 TUI. Blocking: P1.
Scope: `factory/linking/cli.py` new subcommand over the P1 runner
(input: screened/queue file; output: verdicts file; flags: preset,
limit, timeout). Receipt-printing (replayable command) like other
console flows. Name candidates: `judge` (short) — verify no collision
with precard `judge` wording in help texts before locking.
Tests: CLI happy + bad-args + missing-file cases (stub transport).
Acceptance: owner can run a real model from terminal (builder never does).
