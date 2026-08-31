<#
.SYNOPSIS
    Kilo + OpenCode — CI loop — delta-optimal poll for both reviewers + CI + mergeable (per kilo-ci-loop skill).

.DESCRIPTION
    Implements `.opencode/skills/kilo-ci-loop/SKILL.md` exactly:
    - Sleep 90-120s between polls, 30m overall timeout (configurable)
    - Reviewer delta: only id+body-length+user via `gh api ... --jq '{id,h:(.body|length),user:.user.login}'`, persist to $env:TEMP/opencode/reviewer_seen_<PR>.json (fallback legacy kilo_seen)
      Surface only new id or changed h; fetch full body only for deltas (token-efficient). Tags each delta as Kilo vs OpenCode.
    - CI: requires label, test (3.10), test (3.13), ram-gate, Kilo Code Review, review (opencode-review) = pass
    - Merge conflict: git fetch origin; rebase origin/main with verify (compile_all.py + diff --check), push --force-with-lease
    Each fix commit must be pushed — both reviewers re-review only after push.

.PARAMETER PR
    Pull request number.

.PARAMETER SleepSeconds
    Seconds between polls (default 90, skill allows 90-120).

.PARAMETER TimeoutMinutes
    Overall timeout minutes (default 30).

.PARAMETER WorkDir
    Working directory (default current). Must be a git repo with gh auth.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/kilo_ci_loop.ps1 -PR 486
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/kilo_ci_loop.ps1 -PR 486 -SleepSeconds 100 -TimeoutMinutes 30

.NOTES
    Completion: every reviewer delta (Kilo + OpenCode) fetched once + triaged, all required checks pass (including both Kilo Code Review and review), mergeable=MERGEABLE.
    Evidence is `gh pr checks <n>` output. Use after `gh pr create`/`git push` and before `gh pr merge --squash`.
#>
param(
    [Parameter(Mandatory)][int]$PR,
    [int]$SleepSeconds = 90,
    [int]$TimeoutMinutes = 30,
    [string]$WorkDir = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($SleepSeconds -lt 90 -or $SleepSeconds -gt 120) {
    Write-Warning "SleepSeconds $SleepSeconds outside skill range 90-120; clamping to 90-120"
    $SleepSeconds = [Math]::Clamp($SleepSeconds, 90, 120)
}

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$seenPath = Join-Path $env:TEMP "opencode\reviewer_seen_$PR.json"
$legacySeenPath = Join-Path $env:TEMP "opencode\kilo_seen_$PR.json"
$null = New-Item -ItemType Directory -Force -Path (Split-Path $seenPath) -ErrorAction SilentlyContinue

function Load-Seen {
    $p = $seenPath
    if (-not (Test-Path $p) -and (Test-Path $legacySeenPath)) { $p = $legacySeenPath }
    if (Test-Path $p) {
        try { return (Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable) } catch { return @{} }
    }
    return @{}
}
function Save-Seen([hashtable]$h) {
    $tmp = "$seenPath.tmp"
    ($h | ConvertTo-Json -Compress) | Set-Content -Path $tmp -Encoding UTF8 -NoNewline
    Move-Item -Path $tmp -Destination $seenPath -Force
}
function Get-ReviewerDelta {
    param([hashtable]$seen)
    $deltas = @()
    # Pull review comments (inline) and Issue comments (summary) — include user for Kilo/OpenCode tagging
    $pullJson = gh api "repos/Ham3dParsa/HamZaboonRobot/pulls/$PR/comments" --jq '.[] | {id, h:(.body|length), user:.user.login, path, line}' 2>&1
    $issueJson = gh api "repos/Ham3dParsa/HamZaboonRobot/issues/$PR/comments" --jq '.[] | {id, h:(.body|length), user:.user.login}' 2>&1
    $rows = @()
    if ($pullJson) { $rows += ($pullJson | ForEach-Object { $_ | ConvertFrom-Json }) }
    if ($issueJson) { $rows += ($issueJson | ForEach-Object { $_ | ConvertFrom-Json }) }
    foreach ($r in $rows) {
        $id = "$($r.id)"
        $h = [int]$r.h
        $prev = $seen[$id]
        if ($null -eq $prev -or $prev -ne $h) {
            $deltas += @{ id = $id; h = $h; prev = $prev; row = $r }
        }
    }
    return @{ rows = $rows; deltas = $deltas }
}

function Test-Checks {
    $out = gh pr checks $PR 2>&1 | Out-String
    Write-Host $out
    $required = @('label','test (3.10)','test (3.13)','ram-gate','Kilo Code Review','review')
    $missingPass = @()
    foreach ($name in $required) {
        if ($out -notmatch [regex]::Escape($name) + '\s+pass') { $missingPass += $name }
    }
    $fail = $out -match '\bfail\b' -or $missingPass.Count -gt 0
    return @{ out = $out; missing = $missingPass; fail = $fail }
}

function Test-Mergeable {
    $j = gh pr view $PR --json mergeable,mergeStateStatus 2>&1 | ConvertFrom-Json
    return $j
}

$seen = Load-Seen
if ($seen.Count -eq 0) { Write-Host "[init] seen empty -> will capture baseline on first poll" }

$iteration = 0
while ((Get-Date) -lt $deadline) {
    $iteration++
    Write-Host "`n=== poll #$iteration @ $(Get-Date -Format 'HH:mm:ss') (deadline $($deadline.ToString('HH:mm')) ) ===" -ForegroundColor Cyan

    # 1. Reviewer delta (token-tight — Kilo + OpenCode)
    $deltaRes = Get-ReviewerDelta -seen $seen
    $rows = $deltaRes.rows
    $deltas = $deltaRes.deltas

    # Build new seen map from current rows (id->h)
    $newSeen = @{}
    foreach ($r in $rows) { $newSeen["$($r.id)"] = [int]$r.h }

    if ($deltas.Count -gt 0) {
        Write-Host "[reviewer] $($deltas.Count) delta(s):" -ForegroundColor Yellow
        foreach ($d in $deltas) {
            $id = $d.id; $h = $d.h; $prev = $d.prev
            $bot = if ($d.row.user) { $d.row.user } else { "unknown" }
            $where = if ($d.row.path) { "$($d.row.path):$($d.row.line)" } else { "issue-comment" }
            Write-Host "  + id $id [$bot] h $prev -> $h @ $where"
            # Fetch full body only for deltas
            $isPull = $null -ne $d.row.path
            if ($isPull) {
                $body = gh api "repos/Ham3dParsa/HamZaboonRobot/pulls/comments/$id" --jq '.body' 2>&1 | Out-String
            } else {
                $body = gh api "repos/Ham3dParsa/HamZaboonRobot/issues/comments/$id" --jq '.body' 2>&1 | Out-String
            }
            $preview = ($body | Select-Object -First 1) -replace "`n"," " 
            if ($preview.Length -gt 400) { $preview = $preview.Substring(0,400) + " ..." }
            Write-Host "    preview: $preview" -ForegroundColor DarkGray
            # Persist full body for audit if needed: $env:TEMP/opencode/reviewer_body_<id>.md
            $bodyPath = Join-Path $env:TEMP "opencode\reviewer_body_${id}.md"
            $body | Set-Content -Path $bodyPath -Encoding UTF8
        }
        $seen = $newSeen
        Save-Seen $seen
    } else {
        Write-Host "[reviewer] no delta (seen $($seen.Count) ids)" -ForegroundColor DarkGray
        # Keep seen in sync if rows changed due to deletions
        if ($newSeen.Count -ne $seen.Count) { $seen = $newSeen; Save-Seen $seen }
    }

    # 2. CI checks
    $checkRes = Test-Checks
    $checksPass = -not $checkRes.fail

    # 3. Mergeable
    $m = Test-Mergeable
    $mergeable = $m.mergeable
    $mergeState = $m.mergeStateStatus
    Write-Host "[mergeable] $mergeable / $mergeState" -ForegroundColor $(if ($mergeable -eq 'MERGEABLE' -and $mergeState -eq 'CLEAN') {'Green'} else {'Yellow'})

    if ($mergeable -eq 'CONFLICTING') {
        Write-Host "[conflict] CONFLICTING -> git fetch origin; rebase origin/main" -ForegroundColor Red
        Push-Location $WorkDir
        try {
            git fetch origin 2>&1 | Write-Host
            git rebase origin/main 2>&1 | Write-Host
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[rebase] conflicts — resolve keeping both seams, then verify" -ForegroundColor Red
                git status 2>&1 | Write-Host
                break
            }
            python scripts/compile_all.py 2>&1 | Write-Host
            git diff --check 2>&1 | Write-Host
            if ($LASTEXITCODE -ne 0) { Write-Host "[verify] diff --check failed" -ForegroundColor Red; break }
            # Continue rebase if needed
            $rebaseOngoing = git status 2>&1 | Select-String -Pattern "rebase in progress"
            if ($rebaseOngoing) { GIT_EDITOR=true git rebase --continue 2>&1 | Write-Host }
            git push --force-with-lease 2>&1 | Write-Host
            Write-Host "[rebase] pushed --force-with-lease, next poll will re-check reviewers" -ForegroundColor Green
        } finally { Pop-Location }
    }

    $allChecksPass = $checksPass -and ($mergeState -eq 'CLEAN' -or $mergeState -eq 'UNSTABLE' -and $mergeable -eq 'MERGEABLE')
    # Skill completion: all deltas fetched + all required checks pass + mergeable MERGEABLE
    if ($checksPass -and $mergeable -eq 'MERGEABLE' -and ($mergeState -eq 'CLEAN' -or $mergeState -eq 'UNSTABLE')) {
        # Verify both reviewers explicitly pass
        if ($checkRes.out -match 'Kilo Code Review\s+pass' -and $checkRes.out -match 'review\s+pass') {
            Write-Host "`n[done] All required checks pass + MERGEABLE + Kilo & OpenCode pass — ready to merge" -ForegroundColor Green
            Write-Host "      Evidence: gh pr checks $PR"
            exit 0
        }
    }

    if ((Get-Date) -ge $deadline) { break }

    # On fail, fetch failed log for triage before next sleep
    if ($checkRes.fail) {
        Write-Host "[ci] fail/missing: $($checkRes.missing -join ', ') — fetching log on next fail poll" -ForegroundColor Yellow
    }

    $sleep = $SleepSeconds
    Write-Host "[sleep] $sleep`s (skill 90-120s) ..." -ForegroundColor DarkGray
    Start-Sleep -Seconds $sleep
}

Write-Host "`n[timeout] $($TimeoutMinutes)m deadline reached @ $(Get-Date -Format 'HH:mm:ss') — not merge-ready" -ForegroundColor Red
Write-Host "  Last checks: gh pr checks $PR and mergeable=$mergeable/$mergeState"
exit 1
