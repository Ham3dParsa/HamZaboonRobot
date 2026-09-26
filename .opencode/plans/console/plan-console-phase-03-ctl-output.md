---
name: plan-console-phase-03-ctl-output
description: T2 tidy server_ctl output, pid-only safety untouched (P1)
created: 2026-09-24
base_commit: 79d6763
branch: feat/webui-v5
status: planned
---

STATE: phase 3 — status: done (uncommitted, no push) — tidy status/URL/example lines + per-address probes + Get-ProbeHost; pid-only safety untouched; evidence: tests/factory/test_factory_webui_ctl_output.py 4 passed (pinned: test_ctl_status_line_shape, test_ctl_per_address_url_lines, test_ctl_example_line_every_path, test_ctl_pid_only_safety), console suites 155 passed (ctl_output + host_port + webui_interface + webui + review810 + egress_fix), both server_ctl.ps1 parse 0 errors, status eyeballed live (1 status + 2 probed URL + 1 example; explicit bind 1+1+1), git diff --check clean

## Blocking edges

- Blocked by: phase-01-bind (same `server_ctl.ps1` seam — serial).
- Blocks: —. Wave 2 with T6 (disjoint files).

## Scope (exact files)

- `factory/webui/server_ctl.ps1`: `Show-Status` (one status line),
  per-address URL lines on start, `Show-Example` on every path.
- `factory/linking/webui/server_ctl.ps1`: shim mirror.
- STOP-safety law untouched: pid-file-only `Stop-Process -Id`; no
  name-based kills introduced (negative requirement).
- New test file `tests/factory/test_factory_webui_ctl_output.py`
  (string-shape assertions over the ps1, same style as interface tests).

## Test-first tests (names)

- `test_ctl_status_line_shape` (RUNNING/STALE/STOPPED single line)
- `test_ctl_per_address_url_lines`
- `test_ctl_example_line_every_path`
- `test_ctl_pid_only_safety` (no `Stop-Process -Name`, no `taskkill /IM`,
  no `pkill`; only `Stop-Process -Id $pidVal`)

## Acceptance (verifiable artifacts)

- New test file green; `start`/`status`/`stop`/stale-pidfile outputs eyeballed
  once against the asserted shapes.
- `git diff --check` clean on both ps1 files.

## Wiring

- Rule: locked tidy-output rule. No callback/router change.
