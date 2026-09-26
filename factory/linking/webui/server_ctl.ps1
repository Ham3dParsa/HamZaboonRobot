<#
.SYNOPSIS
  Backward-compatible forwarder: the console moved to factory\webui.

  Thin delegation only — no start/stop logic lives here. Every argument
  (start/stop/status/restart, -Port) passes straight through to the
  canonical control script, which owns the pid-file safety law
  (process-id-only stop, never blanket kills).

.USAGE (unchanged — old command lines keep working)
  powershell -ExecutionPolicy Bypass -File factory\linking\webui\server_ctl.ps1 start
  powershell -ExecutionPolicy Bypass -File factory\linking\webui\server_ctl.ps1 status
  powershell -ExecutionPolicy Bypass -File factory\linking\webui\server_ctl.ps1 stop
  powershell -ExecutionPolicy Bypass -File factory\linking\webui\server_ctl.ps1 restart
  (no action defaults to status plus help — never blocks on input.)
  Tablet (LAN): plain `start` binds all interfaces in the canonical
  script (LAN-visible, no flags); -BindHost <ip> still overrides,
  forwarded as-is.
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [string]$Action = "",
  [int]$Port = 5561,
  # Empty means all-interfaces bind (resolved by the canonical
  # script); non-empty overrides, forwarded as-is.
  [string]$BindHost = "",
  # Same dashed-action catcher as the canonical script: stray tokens
  # (e.g. --status) land here instead of failing the bind.
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Extra = @()
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $ScriptDir "..\..\webui\server_ctl.ps1"

if (-not (Test-Path -LiteralPath $Target)) {
  "forwarder: canonical control script missing: {0}" -f $Target
  exit 1
}

$Norm = ""
$Seed = $Action
if ((-not $Seed) -and $Extra -and $Extra.Count -gt 0) { $Seed = $Extra[0] }
if ($Seed) { $Norm = $Seed.Trim().ToLowerInvariant() }
while ($Norm.StartsWith("-") -or $Norm.StartsWith("/")) { $Norm = $Norm.TrimStart("-", "/") }
if ($Norm) { & $Target $Norm -Port $Port -BindHost $BindHost } else { & $Target -Port $Port -BindHost $BindHost }
exit $LASTEXITCODE
