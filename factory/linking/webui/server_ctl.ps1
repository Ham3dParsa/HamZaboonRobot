<#
.SYNOPSIS
  Start / stop / status for the linker-judge WebUI server (127.0.0.1:5561).

.STANDING SAFETY LAW (non-negotiable, owner-ordered)
  NEVER stop processes by blanket name. This script contains ZERO
  blanket kills on purpose: no `Stop-Process -Name`, no
  `taskkill /IM`, no `pkill`, no `Get-Process <name> | Stop-Process`.
  A stop targets EXACTLY the process id recorded in the Temp pid file
  (`$env:TEMP\webui-5561.pid`) via `Stop-Process -Id <that-pid>` and
  nothing else. Missing/stale pid file => refuse and report; never scan
  for substitute victims.

.USAGE
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
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..\..")).Path
$ServerScript = Join-Path $ScriptDir "server.py"
$TempDir = $env:TEMP
if (-not $TempDir) { $TempDir = [System.IO.Path]::GetTempPath() }
$PidFile = Join-Path $TempDir ("webui-{0}.pid" -f $Port)
$OutLog = Join-Path $TempDir ("webui-{0}.out.log" -f $Port)
$ErrLog = Join-Path $TempDir ("webui-{0}.err.log" -f $Port)

function Test-PortOpen([string]$HostName, [int]$TcpPort) {
  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $iar = $client.BeginConnect($HostName, $TcpPort, $null, $null)
    if ($iar.AsyncWaitHandle.WaitOne(500)) {
      $client.EndConnect($iar)
      return $true
    }
    return $false
  } catch { return $false } finally { $client.Close() }
}

function Get-RecordedPid {
  if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
  $raw = (Get-Content -LiteralPath $PidFile -TotalCount 1).Trim()
  $pidInt = 0
  if ([int]::TryParse($raw, [ref]$pidInt) -and $pidInt -gt 0) { return $pidInt }
  return $null
}

function Get-Status {
  $pidVal = Get-RecordedPid
  $alive = $false
  if ($pidVal) {
    try { $null = Get-Process -Id $pidVal -ErrorAction Stop; $alive = $true }
    catch { $alive = $false }
  }
  return [pscustomobject]@{
    Port    = $Port
    PidFile = $PidFile
    Pid     = $pidVal
    Alive   = $alive
    PortOpen = (Test-PortOpen "127.0.0.1" $Port)
  }
}

function Show-Status {
  $s = Get-Status
  if ($s.Alive) {
    "status: RUNNING pid={0} port={1} port_open={2} pidfile={3}" -f $s.Pid, $s.Port, $s.PortOpen, $s.PidFile
  } elseif ($s.Pid) {
    "status: STALE pidfile pid={0} (process gone) port_open={1} pidfile={2}" -f $s.Pid, $s.PortOpen, $s.PidFile
  } else {
    "status: STOPPED port={0} port_open={1} (no pidfile)" -f $s.Port, $s.PortOpen
  }
}

function Start-Server {
  $s = Get-Status
  if ($s.Alive) {
    Show-Status
    "start: already running — refusing a second instance (stop it first via this script)."
    return
  }
  if ($s.PortOpen) {
    "start: REFUSED — port {0} is held by a process this script did not start (no pidfile). Free it manually, then retry." -f $Port
    exit 1
  }
  if (-not (Test-Path -LiteralPath $ServerScript)) {
    "start: server script missing: {0}" -f $ServerScript
    exit 1
  }
  $proc = Start-Process -FilePath "python" `
    -ArgumentList @("factory\linking\webui\server.py") `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog `
    -WindowStyle Hidden -PassThru
  # Record the EXACT pid: the only id `stop` is ever allowed to signal.
  Set-Content -LiteralPath $PidFile -Value ("{0}" -f $proc.Id) -NoNewline
  $deadline = (Get-Date).AddSeconds(30)
  while ((Get-Date) -lt $deadline) {
    try { $null = Get-Process -Id $proc.Id -ErrorAction Stop } catch {
      "start: process {0} exited early; tail of {1}:" -f $proc.Id, $ErrLog
      Get-Content -LiteralPath $ErrLog -Tail 10 -ErrorAction SilentlyContinue
      Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue
      exit 1
    }
    if (Test-PortOpen "127.0.0.1" $Port) { break }
    Start-Sleep -Milliseconds 500
  }
  Show-Status
}

function Stop-Server {
  # SAFETY LAW: the ONLY process this function may signal is the exact
  # id read from the pid file. No name-based lookup exists in this file.
  $pidVal = Get-RecordedPid
  if (-not $pidVal) {
    "stop: REFUSED — no valid pid in {0}. Blanket kills are forbidden; nothing was signaled." -f $PidFile
    "status: port_open={0}" -f (Test-PortOpen "127.0.0.1" $Port)
    exit 1
  }
  $target = $null
  try { $target = Get-Process -Id $pidVal -ErrorAction Stop } catch { $target = $null }
  if (-not $target) {
    "stop: pid {0} already gone (stale pidfile) — removing pidfile, nothing signaled." -f $pidVal
    Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue
    "status: port_open={0}" -f (Test-PortOpen "127.0.0.1" $Port)
    return
  }
  # Signal exactly this id — never a name, never a group.
  Stop-Process -Id $pidVal -Force
  $deadline = (Get-Date).AddSeconds(15)
  while ((Get-Date) -lt $deadline) {
    try { $null = Get-Process -Id $pidVal -ErrorAction Stop; Start-Sleep -Milliseconds 300 }
    catch { break }
  }
  Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue
  "stop: signaled pid {0} only; pidfile removed." -f $pidVal
  "status: port_open={0} (want False)" -f (Test-PortOpen "127.0.0.1" $Port)
}

switch ($Action) {
  "start"   { Start-Server }
  "stop"    { Stop-Server }
  "status"  { Show-Status }
  "restart" { Stop-Server; Start-Server }
}
