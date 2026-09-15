---
name: detached-run
description: Run a long job detached so the chat stays live. Use when a command is expected to exceed ~2 minutes, for a factory run over network, for an egress probe or sweep command, or on an explicit owner order to run in background.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  gate: pre-run
  author: Ham3dParsa
  author_url: https://github.com/Ham3dParsa
---
# Detached Run

A launcher spawns a detached process, output goes to a log file, and the agent polls the log tail between conversation turns. The chat never stalls on a 10 to 30 minute job.

## Scope

Fire on these branches only:

- a command expected to exceed ~2 minutes
- a factory run over network
- an egress probe or sweep command
- an explicit owner order to run in background

Out of scope: local fast tests and short commands. Run those inline.

## Steps

### 1. Sweep stale runs

Every time this skill fires, sweep before launching. Under `$env:TEMP/opencode/detached-run/`, delete any run dir whose pid points to a dead process, and any run dir whose log is untouched for more than 7 days. If the sweep removed anything, say one line about what was removed.

### 2. Launch

Create `$env:TEMP/opencode/detached-run/<job-name>/` holding exactly three files: the launcher, the pid file, and the log. Conventional names are `launcher.ps1`, `run.pid`, `run.log`. Nothing else goes in this dir.

Real job outputs (for example `precard.jsonl`) go to their own data dirs, never mixed into the run dir.

Write helpers outside the repo under the temp dir. A run never touches repo code: no edits, no writes, no deletes inside the repo checkout.

Keep secrets off command lines. Read keys from files inside the process instead of passing them as arguments.

Name the expected artifact and where it will appear before launching. Completion depends on it (see step 4).

Start the launcher detached with all output appended to the log, record the process id in the pid file, then return to the conversation at once:

```powershell
$runDir = "$env:TEMP/opencode/detached-run/<job-name>"
New-Item -ItemType Directory -Path $runDir -Force
$launcher = Join-Path $runDir "launcher.ps1"
$log = Join-Path $runDir "run.log"
$pidFile = Join-Path $runDir "run.pid"
$p = Start-Process powershell -ArgumentList @("-NoProfile", "-Command", "& '$launcher' >> '$log' 2>&1") -PassThru -WindowStyle Hidden
$p.Id | Set-Content $pidFile
```

From launch until delivery, make no code edits while its run is in flight.

### 3. Poll

Between conversation turns, check liveness and read the tail:

```powershell
Get-Process -Id (Get-Content $pidFile) -ErrorAction SilentlyContinue
Get-Content $log -Tail 20
```

Report one short line of progress, then keep chatting. Never block the turn waiting for the job.

### 4. Deliver

Completion means the expected artifact was observed, not just process exit. A dead pid with no artifact is a failed run, not a done one. When the artifact exists, verify it briefly (present, non-empty, parses if structured), then deliver the report with the artifact path.

### 5. Clean up

A successful run is deleted right after its report is delivered and seen. A failed run is kept until the cause is diagnosed and the owner accepts it, then deleted. Deletion removes launcher, pid file, and log together. Never delete a run whose report is still unseen.

## Completion

All of these hold: the expected artifact was named at launch and observed at the end; the report was delivered; a successful run dir was deleted after the report was seen, or a failed run dir is kept with its cause and the owner acceptance recorded; the sweep in step 1 ran, with a one-line notice if it removed anything.
