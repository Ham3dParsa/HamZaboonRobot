# Windows pytest reliability — field findings (2026-09-28, HamZaban shared box)

Proven by repeated observation on `feat/supervised-arbitration` validation.
Intended for any session running pytest on this machine.

## 1. Silent-death pattern (the headline)

Full-suite runs die mid-run at RANDOM percentages (seen: 24/51/65/66/73%)
with ZERO output: no traceback, no FAILED line, no Windows event-log
entry, nothing from `python -X faulthandler`. Foreground AND background
(`Start-Process` file-redirected) runs die alike. A dead run is
recognized by: pid gone + log mtime frozen + no DONE marker.

## 2. Causes (separated by evidence)

### 2a. Harness reaps long silent foreground commands (CERTAIN)
Any foreground command silent for ~30–60s+ (even `Start-Sleep 45` or a
file read issued at the wrong moment) can return `(no output)`.
Mitigation: keep every foreground call short with visible output;
long work goes to a log FILE; poll the file with short reads.

### 2b. External console control events kill console-attached trees (PROVEN)
A background pytest log contained `KeyboardInterrupt` inside
`subprocess.py` at 0.51s with zero tests run. Hidden-window processes
started via `Start-Process` still share the invoker's console, so a
Ctrl+C broadcast (e.g. the harness cancelling a stuck call) murders the
test run AND any sibling background job on that console. WMI-spawned
(`Win32_Process.Create`) processes survive this specific vector.
Mitigation: launch long runs via WMI `Win32_Process.Create` writing to
a file; poll with short commands. A `KeyboardInterrupt` in a pytest log
is an ENVIRONMENTAL kill, never a test failure — rerun, don't "fix".

### 2c. Real product bug found en route (FIXED, merged in #832)
`factory/webui/server.py::_pid_alive`: on Windows, `os.kill(pid, 0)`
raises generic `OSError WinError 87` (not `ProcessLookupError`) for dead
pids; the blanket `except Exception: return True` reported EVERY dead
pid alive, so restart-settle never fired. Fix: `except OSError: return
False` before the generic handler. Lesson: a hanging suite near
`test_screening_runstatus` / restart-recovery tests is a suspect, not
proof of environment flakiness — reproduce the single test first.

### 2d. Orphaned test servers accumulate (OBSERVED: 25 copies)
Wake/sleep + live-console fixtures spawn real `supervisor.py --port
18789` / webui servers that leak on teardown and fight over the same
port. Before a validation run, list `python.exe` processes and kill
ONLY ones attributable to your own runs (match YOUR worktree path in
the command line). Never kill: PID 27328-class scratch consoles in
active use, other sessions' worktree paths, `5561`/`5571` consoles
whose owner is unknown, VSCode helpers.

## 3. Suite-specific traps

- `tests/factory/test_webui_live_browser.py` full-file vs solo: the file
  is heavy (chromium); prefer targeted runs + CI for the full pass.
- `t04_02_restart_console_recovers_run` is INNOCENT (passes solo ~3.5s);
  do not quarantine it on a hunch.
- The suite REWRITES `.opencode/plans/factory/shots/shot-t11-*.png`
  (bytes shrink). Always `git checkout --` those before commit; they
  are review evidence, never your change.
- LF→CRLF warnings on `git add`/`git status` are noise; `git diff
  --check` clean is the real signal.
- `faulthandler` prints nothing on kills (expected — kills aren't
  Python faults). Its silence proves nothing either way.

## 4. Recommended validation loop on this box

1. Sweep orphans yours-only (§2d). 2. Targeted fast suites foreground
(short). 3. Full suite ONLY via WMI-detached-to-file; poll log tail +
pid + mtime. 4. Death with frozen log + no traceback → check for
`KeyboardInterrupt` (environmental, rerun) vs reproducible stall point
(bisect to file, then to test, solo). 5. Single-test repro before ANY
quarantine/fix (test-sync rule). 6. CI (`-n 4`, clean machine) is the
arbiter of record — local green here is supporting evidence, and local
red must be classified (environmental vs real) before it blocks a PR.
