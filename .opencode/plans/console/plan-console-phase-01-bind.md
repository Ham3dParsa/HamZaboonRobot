---
name: plan-console-phase-01-bind
description: T1 all-interfaces default bind plus override plus LAN note (P0)
created: 2026-09-24
base_commit: 79d6763
branch: feat/webui-v5
status: planned
---

STATE: phase 1 — status: done (uncommitted, no push) — default bind 0.0.0.0 + env/flag override + LAN note; evidence: tests/factory/test_factory_webui_host_port.py 7 passed (pinned: test_default_binds_all_interfaces, test_env_overrides_default_bind, test_flags_override_env_bind), console suites 149 passed (host_port + webui_interface + webui + review810 + egress_fix), both server_ctl.ps1 parse 0 errors, git diff --check clean

## Blocking edges

- Blocks: phase-03-ctl-output (same `server_ctl.ps1` seam), phase-08-wake-sleep.
- Blocked by: — (foundation; Wave 1 with T3).

## Scope (exact files)

- `factory/webui/server.py`: `_default_host()` → all-interfaces default;
  `HAMZABAN_WEBUI_HOST` env + `--host` flag keep explicit-override precedence;
  `parse_server_args()` help text updated.
- `factory/webui/server_ctl.ps1`: `Resolve-BindHost`/`Get-LanIpv4` to match
  (explicit `-BindHost` wins, else all-interfaces).
- `factory/linking/webui/server_ctl.ps1`: shim mirror of the same change.
- `factory/webui/index.html`: LAN-visibility note on the boot/boot-receipt line
  (which address to open from tablet vs loopback).
- `tests/factory/test_factory_webui_host_port.py`: update per test-sync rule
  (current tests assert LAN-autodetect default — that behavior is superseded
  by this locked rule).

## Test-first tests (names)

- `test_default_binds_all_interfaces` (no env, no flags → all-interfaces)
- `test_env_overrides_default_bind` (`HAMZABAN_WEBUI_HOST` wins)
- `test_flags_override_env_bind` (`--host` wins over env)
- Keep/adjust: port fallback test, loopback-only explicit test.

## Acceptance (verifiable artifacts)

- `pytest tests/factory/test_factory_webui_host_port.py` green.
- Boot receipt shows the bound address + LAN-visibility note; explicit
  override reproduces exactly in receipt.
- Forbidden zone untouched; secrets names-only; pid logic not in scope.

## Wiring

- Rule: locked bind rule. No callback/router change.
