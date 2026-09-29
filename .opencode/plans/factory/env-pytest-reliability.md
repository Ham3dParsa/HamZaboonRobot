# Windows pytest reliability — field findings (2026-09-28, HamZaban shared box)


## 1. Silent-death pattern
Full-suite runs die mid-run at random percentages (seen 24/51/65/66/73%) with zero output: no traceback, no FAILED, no event log, faulthandler silent. Foreground AND background runs die alike. Dead = pid gone + log mtime frozen + no DONE marker.


## 2. Causes
**2a. Harness reaps long silent foreground commands (certain).** Anything silent ~30–60s+ may return empty. Keep foreground calls short with visible output; long work to a log file; poll with short reads.
**2b. External console Ctrl+C kills console-attached trees (proven).** A background log caught `KeyboardInterrupt` in `subprocess.py` at 0.51s with no tests run. Hidden-window `Start-Process` jobs still share the invoker console. Launch long runs via WMI `Win32_Process.Create` to a file. A `KeyboardInterrupt` in a pytest log is environmental — rerun, never "fix".
**2c. Real product bug found en route (fixed, merged #832).** `_pid_alive`: Windows `os.kill(pid,0)` raises `OSError WinError 87` (not `ProcessLookupError`) for dead pids; blanket `except → True` reported every dead pid alive. Fix: `except OSError: return False`. Lesson: a stall near restart-recovery tests is a suspect — reproduce solo first.
**2d. Orphaned test servers (observed: 25 copies).** Wake/sleep fixtures leak real `supervisor.py --port 18789` servers fighting over one port. Before validating, kill ONLY processes matching YOUR worktree path. Never touch others' worktrees, unknown `556x` consoles, or editor helpers.


## 3. Suite traps
- `test_webui_live_browser.py`: heavy file; targeted runs + CI, not full local.
- `t04_02` is innocent (~3.5s solo). No hunch-quarantines.
- Suite rewrites `shots/shot-t11-*.png` — always `git checkout --` them before commit.
- LF→CRLF warnings are noise; `git diff --check` is the signal.
- faulthandler silence proves nothing about kills.


## 4. Loop
Sweep own orphans → targeted fast suites → full suite WMI-detached-to-file only → on death, classify (KeyboardInterrupt = rerun; reproducible stall = bisect to test, solo repro) → CI is arbiter of record; local red must be classified before it blocks anything.
