<#
.SYNOPSIS
  Start / stop / status for the linker-judge WebUI server (0.0.0.0:5561).

.STANDING SAFETY LAW (non-negotiable, owner-ordered)
  NEVER stop processes by blanket name. This script contains ZERO
  blanket kills on purpose: no `Stop-Process -Name`, no
  `taskkill /IM`, no `pkill`, no `Get-Process <name> | Stop-Process`.
  A stop targets EXACTLY the process id recorded in the Temp pid file
  (`$env:TEMP\webui-5561.pid`) via `Stop-Process -Id <that-pid>` and
  nothing else. Missing/stale pid file => refuse and report; never scan
  for substitute victims.

.USAGE
  powershell -ExecutionPolicy Bypass -File factory\webui\server_ctl.ps1 start [-Port 5561]
  powershell -ExecutionPolicy Bypass -File factory\webui\server_ctl.ps1 status [-Port 5561]
  powershell -ExecutionPolicy Bypass -File factory\webui\server_ctl.ps1 stop [-Port 5561]
  powershell -ExecutionPolicy Bypass -File factory\webui\server_ctl.ps1 restart [-Port 5561]
  (no action defaults to status plus this help — never blocks on input.)
  Tablet (LAN) access — plain `start` binds all interfaces (0.0.0.0),
  so it is LAN-visible with no -BindHost needed; -BindHost <ip> still
  overrides it (e.g. -BindHost 127.0.0.1 for loopback-only).
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [string]$Action = "",
  [int]$Port = 5561,
  # Empty means bind all interfaces (0.0.0.0 — loopback and LAN
  # both work, plain start is LAN-visible); a non-empty value binds
  # exactly that interface and overrides the default.
  [string]$BindHost = "",
  # Catcher for dashed action forms (--status/--restart): PowerShell's
  # own binder would otherwise reject them as unknown named params
  # before this script runs. Stray tokens land here instead of erroring.
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Extra = @()
)

$ErrorActionPreference = "Stop"

# A dashed action never binds to $Action (the binder treats it as a
# name); promote the first stray token so --status maps to status.
if ((-not $Action) -and $Extra -and $Extra.Count -gt 0) { $Action = $Extra[0] }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
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

function Get-NormalizedAction([string]$Raw) {
  # Tolerate the dashed forms operators actually type (--status,
  # -status, /status) plus case variation: strip leading -/--//,
  # lowercase, then map to the canonical action. Never throws.
  $t = ""
  if ($Raw) { $t = $Raw.Trim().ToLowerInvariant() }
  while ($t.StartsWith("-") -or $t.StartsWith("/")) { $t = $t.TrimStart("-", "/") }
  return $t
}

function Get-LanIpv4 {
  # Machine LAN IPv4 for the open-link line only (loopback when
  # detection provably fails). Local-only, zero traffic: UDP
  # Connect() never transmits — it only selects the outbound
  # interface whose address is read back. Fallback is the platform
  # address list. Never throws. It no longer selects the bind
  # address (plain start binds all interfaces).
  try {
    $sock = New-Object System.Net.Sockets.UdpClient
    try {
      $sock.Connect("8.8.8.8", 80)
      $hit = ($sock.Client.LocalEndPoint -as [System.Net.IPEndPoint]).Address.ToString()
    } finally { $sock.Close() }
    if ($hit -and -not $hit.StartsWith("127.") -and $hit -ne "0.0.0.0") { return $hit }
  } catch { }
  try {
    foreach ($addr in [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName())) {
      if ($addr.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
        $s = $addr.ToString()
        if (-not $s.StartsWith("127.") -and -not $s.StartsWith("169.254.")) { return $s }
      }
    }
  } catch { }
  return "127.0.0.1"
}

function Resolve-BindHost([string]$Want) {
  # Explicit -BindHost wins; empty means all interfaces (0.0.0.0 —
  # loopback and LAN both work, plain start is LAN-visible).
  # Never throws.
  if ($Want -and $Want.Trim()) { return $Want.Trim() }
  return "0.0.0.0"
}

function Get-ProbeHost([string]$BoundHost) {
  # A port probe cannot target all-interfaces; probe loopback instead
  # (the server answers there whenever it binds 0.0.0.0). Single owner
  # of this mapping — every probing call site uses it. Never throws.
  if ($BoundHost -eq "0.0.0.0" -or $BoundHost -eq "" -or $BoundHost -eq "::") {
    return "127.0.0.1"
  }
  return $BoundHost
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
  $effHost = Resolve-BindHost $BindHost
  $probeHost = Get-ProbeHost $effHost
  return [pscustomobject]@{
    Port    = $Port
    BindHost = $effHost
    PidFile = $PidFile
    Pid     = $pidVal
    Alive   = $alive
    PortOpen = (Test-PortOpen $probeHost $Port)
  }
}

function Show-Links([string]$BoundHost, [int]$TcpPort) {
  # Correct open links for the effective bind: all-interfaces prints
  # both the LAN address (tablet) and loopback (this machine), each
  # with its own live port probe; an explicit bind prints exactly that
  # address with its probe. Never throws.
  if ($BoundHost -eq "0.0.0.0" -or $BoundHost -eq "" -or $BoundHost -eq "::") {
    $lan = Get-LanIpv4
    "open (tablet/LAN): http://{0}:{1} port_open={2}  — plain start is LAN-visible" -f $lan, $TcpPort, (Test-PortOpen $lan $TcpPort)
    "open (this machine): http://127.0.0.1:{0} port_open={1}" -f $TcpPort, (Test-PortOpen "127.0.0.1" $TcpPort)
  } else {
    "open: http://{0}:{1} port_open={2}" -f $BoundHost, $TcpPort, (Test-PortOpen $BoundHost $TcpPort)
  }
}

function Show-Status {
  $s = Get-Status
  if ($s.Alive) {
    "status: RUNNING pid={0} host={1} port={2} port_open={3} pidfile={4}" -f $s.Pid, $s.BindHost, $s.Port, $s.PortOpen, $s.PidFile
  } elseif ($s.Pid) {
    "status: STALE pidfile pid={0} host={1} (process gone) port_open={2} pidfile={3}" -f $s.Pid, $s.BindHost, $s.PortOpen, $s.PidFile
  } else {
    "status: STOPPED host={0} port={1} port_open={2} (no pidfile)" -f $s.BindHost, $s.Port, $s.PortOpen
  }
  Show-Links $s.BindHost $s.Port
}

function Start-Server {
  $s = Get-Status
  # Effective bind: explicit -BindHost wins, else all interfaces
  # (0.0.0.0 — plain start is LAN-visible). Passed explicitly to the
  # server so the boot receipt proves the exact address.
  $effHost = $s.BindHost
  if ($s.Alive) {
    Show-Status
    "start: already running — refusing a second instance (stop it first via this script)."
    Show-Example
    return
  }
  if ($s.PortOpen) {
    "start: REFUSED — port {0} is held by a process this script did not start (no pidfile). Free it manually, then retry." -f $Port
    Show-Example
    exit 1
  }
  if (-not (Test-Path -LiteralPath $ServerScript)) {
    "start: server script missing: {0}" -f $ServerScript
    Show-Example
    exit 1
  }
  $proc = Start-Process -FilePath "python" `
    -ArgumentList @("factory\webui\server.py", "--host", "$effHost", "--port", "$Port") `
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
      Show-Example
      exit 1
    }
    if (Test-PortOpen (Get-ProbeHost $effHost) $Port) { break }
    Start-Sleep -Milliseconds 500
  }
  Show-Status
  Show-Example
}

function Stop-Server {
  # SAFETY LAW: the ONLY process this function may signal is the exact
  # id read from the pid file. No name-based lookup exists in this file.
  $pidVal = Get-RecordedPid
  $effHost = Resolve-BindHost $BindHost
  $probeHost = Get-ProbeHost $effHost
  if (-not $pidVal) {
    "stop: REFUSED — no valid pid in {0}. Blanket kills are forbidden; nothing was signaled." -f $PidFile
    "status: port_open={0}" -f (Test-PortOpen $probeHost $Port)
    Show-Example
    exit 1
  }
  $target = $null
  try { $target = Get-Process -Id $pidVal -ErrorAction Stop } catch { $target = $null }
  if (-not $target) {
    "stop: pid {0} already gone (stale pidfile) — removing pidfile, nothing signaled." -f $pidVal
    Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue
    "status: port_open={0}" -f (Test-PortOpen $probeHost $Port)
    Show-Example
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
  "status: port_open={0} (want False)" -f (Test-PortOpen $probeHost $Port)
  Show-Example
}

function Show-Example {
  # One correct usage example, printed on EVERY invocation (all paths).
  "example: powershell -ExecutionPolicy Bypass -File factory\webui\server_ctl.ps1 status -Port {0}" -f $Port
}

function Show-Usage {
  "usage: server_ctl.ps1 <start|stop|status|restart> [-Port <n>] [-BindHost <ip>]  (defaults: port 5561, all-interfaces bind — plain start is LAN-visible)"
  "  start   — launch the console server on <host>:-Port (refuses a second instance; host is 0.0.0.0 unless -BindHost, e.g. -BindHost 127.0.0.1 for loopback-only)"
  "  stop    — signal ONLY the pid recorded in the Temp pid file (never blanket kills)"
  "  status  — current port/server state for <host>:-Port"
  "  restart — stop, then start"
  "  (no action shows status plus this help; --status/--restart dashed forms map to the action)"
  "  tablet (LAN): plain start binds all interfaces and is LAN-visible — open the tablet/LAN link printed above (loopback link is for this machine only)"
  "  caution: operator-only — plain start exposes key-accepting endpoints with no auth (trusted LAN only); -BindHost 127.0.0.1 for loopback-only"
  Show-Example
}

$NormalizedAction = Get-NormalizedAction $Action
switch ($NormalizedAction) {
  "start"   { Start-Server }
  "stop"    { Stop-Server }
  "status"  { Show-Status; Show-Example }
  "restart" { Stop-Server; Start-Server }
  ""        { Show-Status; Show-Usage }
  default   { "unknown action: {0}" -f $Action; Show-Status; Show-Usage; exit 2 }
}
