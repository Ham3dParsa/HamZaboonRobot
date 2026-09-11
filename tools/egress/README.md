# Egress supervisor (`tools/egress/`)

Gives factory scripts foreign internet (VPN servers) without touching
the system VPN. One program, three jobs: rank servers, find
provider-friendly egress, lease tunnels to scripts.

## Files here

- `supervisor.py` — pool + ranking + probes + lease server (loopback API).
- `tunnel.py` — one xray child per server (needs `bin/xray.exe`, gitignored).
- `client.py` — `lease()` / `report()` / `health()` against the server.
- `run_with_lease.py` — runs any command with HTTPS_PROXY set from a lease.
- `xrayconf.py` — link → xray config builder.
- `.env` (gitignored) — EGRESS_SUB_URL(S) + EGRESS_SUP_TOKEN (see `.env.example`).
- `egress_pool.json` (gitignored) — ranked whitelist cache.
- `bin/` (gitignored) — xray.exe + data files (download once, never commit).

## Runbook (repo root, needs tools/egress/.env)

```powershell
# rank all SUB servers by latency (both SUBs, dupes collapsed)
python tools\egress\supervisor.py --probe --top-n 30
# find Google-accepted egress (free pings, needs GOOGLE key)
python tools\egress\supervisor.py --probe --top-n 30 --probe-google 15
# serve leases (keep running in its own window)
python tools\egress\supervisor.py
# run anything through a tunneled lease (second window)
python tools\egress\run_with_lease.py zen -- python factory\blind50.py ...
```

SUB format: one link per line or comma-separated (both work); a bare
URL on the line after `EGRESS_SUB_URLS=` counts too. A link with a
literal comma inside is unsupported. One dead source never blocks the
others; per-source status prints with host only (never full links).

## Key rule

`--probe-zen` / `--probe-google` nest under `--probe`. An empty probe
never overwrites the whitelist. In factory callers (blind50/precard),
three consecutive 429s stop the run, never long-backoff (the supervisor
itself only cools per-server).
