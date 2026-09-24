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
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidateSet("start", "stop", "status", "restart")]
  [string]$Action,
  [int]$Port = 5561
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $ScriptDir "..\..\webui\server_ctl.ps1"

if (-not (Test-Path -LiteralPath $Target)) {
  "forwarder: canonical control script missing: {0}" -f $Target
  exit 1
}

& $Target $Action -Port $Port
exit $LASTEXITCODE
