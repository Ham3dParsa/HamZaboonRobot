<#
.SYNOPSIS
    OC merge loop (چرخه مرج) — delta-optimal poll for OpenCode reviewer + CI + mergeable (per oc-merge-loop skill).

.DESCRIPTION
    Implements `.opencode/skills/oc-merge-loop/SKILL.md` exactly:
    - Sleep 90-120s between polls, 30m overall timeout (configurable)
    - Reviewer delta: only id + body-length + login via simple `gh api ... --jq '.[] | [.id, (.body|length), .user.login] | @tsv'`,
      filtered to `opencode-agent[bot]` inside PowerShell (never complex jq select with brackets — breaks on PowerShell 5.1).
      Persist to per-PR state file (default $env:TEMP/opencode/reviewer_seen_<PR>.json, overridable via -SeenPath).
      Surface only new id or changed h; fetch full body only for deltas (token-efficient).
    - CI: requires label, test (3.10), test (3.13), ram-gate, review = pass
    - Merge conflict: git fetch origin; rebase origin/main with verify (compile_all.py + diff --check), push --force-with-lease
    - APPROVED triple: latest opencode-agent comment says APPROVED, 0 must-fix open, green checks on the same head
    - Startup: base-freshness gate (fetch + rev-list; behind origin/main = stop before polling)
Each fix commit must be pushed — OC re-reviews only after push. Kilo is OFF and stays ignored.

.PARAMETER PR
    Pull request number.

.PARAMETER SleepSeconds
    Seconds between polls (default 90, skill allows 90-120).

.PARAMETER TimeoutMinutes
    Overall timeout minutes (default 30).

.PARAMETER WorkDir
    Working directory (default current). Must be a git repo with gh auth.

.PARAMETER SeenPath
    Per-PR reviewer state file (default $env:TEMP/opencode/reviewer_seen_<PR>.json).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/oc_merge_loop.ps1 -PR 486
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/oc_merge_loop.ps1 -PR 486 -SleepSeconds 100 -TimeoutMinutes 30

.NOTES
    Completion: every OC delta fetched once + triaged, all required checks pass, APPROVED triple holds, mergeable=MERGEABLE.
    Evidence is `gh pr checks <n>` output. Use after `gh pr create`/`git push` and before `gh pr merge --squash`.
#>
param(
    [Parameter(Mandatory)][int]$PR,
    [int]$SleepSeconds = 90,
    [int]$TimeoutMinutes = 30,
    [string]$WorkDir = (Get-Location).Path,
    [string]$SeenPath = ""
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($SleepSeconds -lt 90 -or $SleepSeconds -gt 120) {
    Write-Warning "SleepSeconds $SleepSeconds outside skill range 90-120; clamping to 90-120"
    $SleepSeconds = [Math]::Clamp($SleepSeconds, 90, 120)
}

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)

# §0 base-freshness gate: never loop from a stale checkout.
try {
    git fetch origin --quiet
    if ($LASTEXITCODE -ne 0) { throw "git fetch origin failed with exit $LASTEXITCODE" }
    $behindRaw = git rev-list --count HEAD..origin/main
    if ($LASTEXITCODE -ne 0) { throw "git rev-list --count HEAD..origin/main failed with exit $LASTEXITCODE" }
    $behind = [int]$behindRaw
    if ($behind -gt 0) {
        throw "Base is $behind commits behind origin/main — refresh (rebase or recreate the worktree) before looping."
    }
} catch {
    Write-Error "Freshness gate failed: $_"
    exit 1
}
if ([string]::IsNullOrWhiteSpace($SeenPath)) {
    $SeenPath = Join-Path $env:TEMP "opencode\reviewer_seen_$PR.json"
}
$seenPath = $SeenPath
$null = New-Item -ItemType Directory -Force -Path (Split-Path $seenPath) -ErrorAction SilentlyContinue

$Repo = "Ham3dParsa/HamZaboonRobot"
$BotLogin = "opencode-agent[bot]"

function Load-Seen {
    if (Test-Path $seenPath) {
        try {
            $data = Get-Content $seenPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
            return $data
        } catch { return @{} }
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
    $apiFailed = $false
    $pullTsv = gh api "repos/$Repo/pulls/$PR/comments" --jq '.[] | [.id, (.body|length), .user.login] | @tsv' 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Warning "gh api pulls/comments failed: $pullTsv"; $apiFailed = $true }
    $issueTsv = gh api "repos/$Repo/issues/$PR/comments" --jq '.[] | [.id, (.body|length), .user.login] | @tsv' 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Warning "gh api issues/comments failed: $issueTsv"; $apiFailed = $true }
    if ($apiFailed) { return @{ rows=@(); deltas=@(); apiFailed=$true } }
    $rows = @()
    if ($pullTsv) {
        foreach ($line in $pullTsv) {
            $parts = ($line -split "`t")
            if ($parts.Count -lt 3) { Write-Warning "skip bad pull tsv: $line"; continue }
            if ($parts[2] -ne $BotLogin) { continue }
            $rows += @{ id = $parts[0]; h = [int]$parts[1]; user = $parts[2]; src = 'pull' }
        }
    }
    if ($issueTsv) {
        foreach ($line in $issueTsv) {
            $parts = ($line -split "`t")
            if ($parts.Count -lt 3) { Write-Warning "skip bad issue tsv: $line"; continue }
            if ($parts[2] -ne $BotLogin) { continue }
            $rows += @{ id = $parts[0]; h = [int]$parts[1]; user = $parts[2]; src = 'issue' }
        }
    }
    foreach ($r in $rows) {
        $id = "$($r.id)"
        $h = [int]$r.h
        $prev = $seen[$id]
        if ($null -eq $prev -or $prev -ne $h) {
            $deltas += @{ id = $id; h = $h; prev = $prev; row = $r }
        }
    }
    return @{ rows = $rows; deltas = $deltas; apiFailed = $false }
}

function Test-Checks {
    try {
        $out = gh pr checks $PR 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "gh pr checks exit $LASTEXITCODE : $out" }
    } catch {
        Write-Warning "Test-Checks failed: $_"
        $required = @('label','test (3.10)','test (3.13)','ram-gate','review')
        return @{ out = ""; missing = $required; fail = $true }
    }
    Write-Host $out
    $required = @('label','test (3.10)','test (3.13)','ram-gate','review')
    $missingPass = @()
    foreach ($name in $required) {
        $pattern = "(?m)^\s*$([regex]::Escape($name))(?!\w)\s+pass"
        if ($out -notmatch $pattern) { $missingPass += $name }
    }
    $fail = $out -match '\bfail\b' -or $missingPass.Count -gt 0
    return @{ out = $out; missing = $missingPass; fail = $fail }
}

function Test-Mergeable {
    try {
        $j = gh pr view $PR --json mergeable,mergeStateStatus 2>&1 | ConvertFrom-Json
        return $j
    } catch {
        Write-Warning "Test-Mergeable failed: $_"
        return @{ mergeable='UNKNOWN'; mergeStateStatus='UNKNOWN' }
    }
}

function Test-OCApproval {
    try {
        $tsv = gh api "repos/$Repo/issues/$PR/comments" --jq '.[] | [.id, (.body|length), .user.login] | @tsv' 2>&1
        if ($LASTEXITCODE -ne 0) { throw $tsv }
        $lastId = $null
        foreach ($line in $tsv) {
            $parts = ($line -split "`t")
            if ($parts.Count -ge 3 -and $parts[2] -eq $BotLogin) { $lastId = $parts[0] }
        }
        if ($null -eq $lastId) { return $false }
        $body = gh api "repos/$Repo/issues/comments/$lastId" --jq '.body' 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw $body }
        return ($body -match 'APPROVED')
    } catch {
        Write-Warning "Test-OCApproval failed: $_"
        return $false
    }
}

$seen = Load-Seen
if ($seen.Count -eq 0) { Write-Host "[init] seen empty -> will capture baseline on first poll" }

$iteration = 0
while ((Get-Date) -lt $deadline) {
    $iteration++
    Write-Host "`n=== poll #$iteration @ $(Get-Date -Format 'HH:mm:ss') (deadline $($deadline.ToString('HH:mm')) ) ===" -ForegroundColor Cyan

    # 1. Reviewer delta (token-tight — OpenCode only)
    $deltaRes = Get-ReviewerDelta -seen $seen
    $rows = $deltaRes.rows
    $deltas = $deltaRes.deltas

    $apiFailed = $deltaRes.apiFailed
    if ($apiFailed) {
        Write-Warning "[reviewer] api failed — skip seen update, retry next poll"
    } else {
        # Build new seen map from current rows (id->h)
        $newSeen = @{}
        foreach ($r in $rows) { $newSeen["$($r.id)"] = [int]$r.h }

        if ($deltas.Count -gt 0) {
            Write-Host "[reviewer] $($deltas.Count) delta(s):" -ForegroundColor Yellow
            $failedIds = @()
            foreach ($d in $deltas) {
                $id = $d.id; $h = $d.h; $prev = $d.prev
                $where = if ($d.row.src -eq 'pull') { "pull-comment" } else { "issue-comment" }
                Write-Host "  + id $id [$BotLogin] h $prev -> $h @ $where"
                # Fetch full body only for deltas
                try {
                    if ($d.row.src -eq 'pull') {
                        $body = gh api "repos/$Repo/pulls/comments/$id" --jq '.body' 2>&1 | Out-String
                        if ($LASTEXITCODE -ne 0) { throw $body }
                    } else {
                        $body = gh api "repos/$Repo/issues/comments/$id" --jq '.body' 2>&1 | Out-String
                        if ($LASTEXITCODE -ne 0) { throw $body }
                    }
                } catch {
                    Write-Warning "fetch body $id failed: $_"; $failedIds += $id; continue
                }
                $preview = ($body | Select-Object -First 1) -replace "`n"," "
                if ($preview.Length -gt 400) { $preview = $preview.Substring(0,400) + " ..." }
                Write-Host "    preview: $preview" -ForegroundColor DarkGray
                # Persist full body for audit if needed: $env:TEMP/opencode/reviewer_body_<id>.md
                $bodyPath = Join-Path $env:TEMP "opencode\reviewer_body_${id}.md"
                $body | Set-Content -Path $bodyPath -Encoding UTF8
            }
            # Don't mark failed bodies as seen — retry next poll
            $seenToSave = $newSeen.Clone()
            foreach ($fid in $failedIds) { $seenToSave.Remove($fid) }
            $seen = $seenToSave
            Save-Seen $seen
            if ($failedIds.Count -gt 0) { Write-Warning "[reviewer] $($failedIds.Count) body fetch failed — not marked seen, will retry" }
        } else {
            Write-Host "[reviewer] no delta (seen $($seen.Count) ids)" -ForegroundColor DarkGray
            # Keep seen in sync if rows changed due to deletions
            if ($newSeen.Count -ne $seen.Count) { $seen = $newSeen; Save-Seen $seen }
        }
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
            Write-Host "[rebase] pushed --force-with-lease, next poll will re-check reviewer" -ForegroundColor Green
        } finally { Pop-Location }
    }

    $allChecksPass = $checksPass -and $mergeable -eq 'MERGEABLE' -and ($mergeState -eq 'CLEAN' -or $mergeState -eq 'UNSTABLE')
    # Skill completion: all deltas fetched + required checks pass + APPROVED triple holds + mergeable MERGEABLE
    if ($allChecksPass) {
        if ($checkRes.out -match '(?m)^\s*review(?!\w)\s+pass') {
            $approved = Test-OCApproval
            if ($approved) {
                Write-Host "`n[done] APPROVED triple holds + all required checks pass + MERGEABLE — ready to merge" -ForegroundColor Green
                Write-Host "      Evidence: gh pr checks $PR"
                exit 0
            } else {
                Write-Host "[approval] required checks pass but latest OC comment does not say APPROVED yet" -ForegroundColor Yellow
            }
        }
    }

    if ((Get-Date) -ge $deadline) { break }

    # On fail, note missing checks for triage before next sleep
    if ($checkRes.fail) {
        Write-Host "[ci] fail/missing: $($checkRes.missing -join ', ')" -ForegroundColor Yellow
    }

    $sleep = $SleepSeconds
    Write-Host "[sleep] $sleep`s (skill 90-120s) ..." -ForegroundColor DarkGray
    Start-Sleep -Seconds $sleep
}

Write-Host "`n[timeout] $($TimeoutMinutes)m deadline reached @ $(Get-Date -Format 'HH:mm:ss') — not merge-ready" -ForegroundColor Red
Write-Host "  Last checks: gh pr checks $PR and mergeable=$mergeable/$mergeState"
exit 1
