<#
.SYNOPSIS
    Acquire, update, release, and prune parallel-work-claims.json
    under an exclusive file lock. Uses native [System.IO.FileStream] lock.
    Normalizes paths via [System.IO.DirectoryInfo].FullName to avoid
    [IO.File]::Replace mixed-slash path failures.
#>
param(
    [Parameter(Mandatory)]
    [ValidateSet("acquire","release","prune")]
    [string]$Command,

    [string]$Branch,
    [string]$Seams = "",
    [string]$RuleIds = "",
    [int]$OlderThanDays = 14
)

$ErrorActionPreference = 'Stop'

function Get-CommonDir {
    $raw = git rev-parse --git-common-dir 2>$null
    if (-not $raw) { throw "git rev-parse --git-common-dir failed" }
    return [System.IO.DirectoryInfo]::new($raw).FullName
}

function Get-ClaimsPath {
    $common = Get-CommonDir
    return Join-Path $common "parallel-work-claims.json"
}

function Get-LockPath {
    $common = Get-CommonDir
    return Join-Path $common ".parallel-work-claims.lock"
}

function Read-ClaimsFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return @{ claims = @() }
    }
    $json = Get-Content $Path -Raw -Encoding UTF8
    return $json | ConvertFrom-Json
}

function Write-ClaimsFile {
    param(
        [string]$Path,
        [psobject]$Data
    )
    $json = $Data | ConvertTo-Json -Depth 5 -Compress
    $tmp = "$Path.tmp"
    Set-Content -Path $tmp -Value $json -Encoding UTF8 -NoNewline
    Move-Item -Path $tmp -Destination $Path -Force
}

function Acquire-Claim {
    param([string]$Branch, [string]$Seams, [string]$RuleIds)
    if (-not $Branch) {
        throw "acquire requires -Branch"
    }
    $claimsPath = Get-ClaimsPath
    $lockPath   = Get-LockPath
    $fs = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    try {
        $data = Read-ClaimsFile -Path $claimsPath
        $seamsList  = $Seams  -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        $ruleIdList = $RuleIds -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        $now = (Get-Date).ToUniversalTime().ToString("o")

        $existing = $data.claims | Where-Object { $_.branch -eq $Branch }
        if ($existing) {
            $existing.seams     = $seamsList
            $existing.rule_ids  = $ruleIdList
            $existing.locked_at = $now
        } else {
            $claim = @{
                branch    = $Branch
                seams     = $seamsList
                rule_ids  = $ruleIdList
                locked_at = $now
            }
            $data.claims += $claim
        }
        Write-ClaimsFile -Path $claimsPath -Data $data
    } finally {
        $fs.Close()
        $fs.Dispose()
    }
}

function Release-Claim {
    param([string]$Branch)
    if (-not $Branch) { throw "release requires -Branch" }
    $claimsPath = Get-ClaimsPath
    $lockPath   = Get-LockPath
    $fs = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    try {
        $data = Read-ClaimsFile -Path $claimsPath
        $data.claims = @($data.claims | Where-Object { $_.branch -ne $Branch })
        Write-ClaimsFile -Path $claimsPath -Data $data
    } finally {
        $fs.Close()
        $fs.Dispose()
    }
}

function Prune-Claims {
    param([int]$OlderThanDays = 14)
    $claimsPath = Get-ClaimsPath
    $lockPath   = Get-LockPath
    $fs = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    try {
        $data = Read-ClaimsFile -Path $claimsPath
        $cutoff = (Get-Date).ToUniversalTime().AddDays(-$OlderThanDays)
        foreach ($claim in $data.claims) {
            $ts = [DateTime]::MinValue
            $parsed = [DateTime]::TryParse($claim.locked_at, [ref]$ts)
            if (-not $parsed) {
                Write-Warning "Malformed locked_at in claim: branch=$($claim.branch) locked_at=$($claim.locked_at)"
                continue
            }
            if ($ts -lt $cutoff) {
                Write-Warning "Stale claim: branch=$($claim.branch) locked_at=$($claim.locked_at)"
            }
        }
    } finally {
        $fs.Close()
        $fs.Dispose()
    }
}

switch ($Command) {
    "acquire" { Acquire-Claim -Branch $Branch -Seams $Seams -RuleIds $RuleIds }
    "release" { Release-Claim -Branch $Branch }
    "prune"   { Prune-Claims  -OlderThanDays $OlderThanDays }
    default   { throw "Unknown command: $Command" }
}
