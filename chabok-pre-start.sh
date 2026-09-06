#!/bin/sh
# NOTE: the platform executes this file with sh (dash), NOT bash, so only
# POSIX syntax is allowed here. In particular NO pipefail, NO [[ ]], NO
# arrays, and NO bare $VAR under `set -eu` (use ${VAR:-}).
set -eu
# HamZaban - persistent Xray bootstrap for Chabokan Python hosting
# Runs on every deploy, before app start. Idempotent.
export DEBIAN_FRONTEND=noninteractive
# Canonical server root: the repo always deploys to /app on this platform
# (single source — no override; cron-jobs and supervisor.conf use the same).
BASE_ROOT="/app"
XRAY_DIR="/app/.xray"
mkdir -p "$XRAY_DIR" /var/log/xray /var/log/supervisor
# Ensure log file exists for supervisor/cron (canonical path /var/log/xray/xray.log)
touch /var/log/xray/xray.log 2>&1 | head || true

# 1) Ensure supervisor/cron present even if xray cached
if ! command -v supervisord >/dev/null 2>&1 || ! command -v cron >/dev/null 2>&1 || ! command -v pgrep >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y --no-install-recommends cron supervisor procps || true
fi
# Install Xray if missing (console installs are ephemeral) - pin version + verify checksum
if ! command -v xray >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y --no-install-recommends unzip curl ca-certificates || true
  XRAY_VERSION="v26.3.27"
  XRAY_URL="https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/Xray-linux-64.zip"
  curl -fsSL --retry 3 --connect-timeout 10 "$XRAY_URL" -o /tmp/xray.zip
  # Optional: verify sha256 if XRAY_SHA256 is set in env
  if [ -n "${XRAY_SHA256:-}" ]; then echo "$XRAY_SHA256  /tmp/xray.zip" | sha256sum -c -; fi
  unzip -o /tmp/xray.zip -d /usr/local/bin/ xray
  chmod +x /usr/local/bin/xray
  rm -f /tmp/xray.zip
fi

# 2) Ensure cron is running (container has no systemd) and install cron-jobs.
# The repo cron-jobs file IS the /etc/cron.d content (single source, already
# carries the USER field) — copy it verbatim instead of echoing hardcoded lines.
service cron start 2>&1 | head -5 || cron 2>&1 | head -5 || true
if [ -f "$BASE_ROOT/cron-jobs" ]; then
  cp -f "$BASE_ROOT/cron-jobs" /etc/cron.d/xray-update && chmod 0644 /etc/cron.d/xray-update || true
fi

# 3) Restore persistent subscription state and install helper scripts from repo
# One-time migration from the pre-#548 layout (/app/hamzaban/.xray): copy any
# state file missing at the new path so clean/outs/sub_url survive the switch.
if [ -d /app/hamzaban/.xray ]; then
  for _f in clean.json outs.json sub_url; do
    if [ ! -s "$XRAY_DIR/$_f" ] && [ -s "/app/hamzaban/.xray/$_f" ]; then cp -f "/app/hamzaban/.xray/$_f" "$XRAY_DIR/$_f" || true; fi
  done
  unset _f
  if [ -f "$XRAY_DIR/sub_url" ]; then chmod 0600 "$XRAY_DIR/sub_url" 2>/dev/null || true; fi
fi
[ -f "$XRAY_DIR/clean.json" ] && cp -f "$XRAY_DIR/clean.json" /tmp/clean.json || true
[ -f "$XRAY_DIR/outs.json" ] && cp -f "$XRAY_DIR/outs.json" /tmp/outs.json || true
# Install helper scripts from repo (they are ephemeral in /usr/local/bin)
if [ -f "$BASE_ROOT/scripts/xray/rebuild_config.py" ]; then cp -f "$BASE_ROOT/scripts/xray/rebuild_config.py" /usr/local/bin/rebuild-xray.py; chmod +x /usr/local/bin/rebuild-xray.py; fi
if [ -f "$BASE_ROOT/scripts/xray/sub2xray.py" ]; then cp -f "$BASE_ROOT/scripts/xray/sub2xray.py" /usr/local/bin/sub2xray.py; chmod +x /usr/local/bin/sub2xray.py; fi
if [ -f "$BASE_ROOT/scripts/xray/validate_config.py" ]; then cp -f "$BASE_ROOT/scripts/xray/validate_config.py" /usr/local/bin/validate-xray.py; chmod +x /usr/local/bin/validate-xray.py; fi
if [ -f "$BASE_ROOT/scripts/xray/update_subscription.sh" ]; then cp -f "$BASE_ROOT/scripts/xray/update_subscription.sh" /usr/local/bin/update_xray_subscription.sh; chmod +x /usr/local/bin/update_xray_subscription.sh; fi

# 4) Rebuild Xray config from clean list (fallback to outs if clean missing)
if [ -f /tmp/clean.json ] || [ -f "$XRAY_DIR/clean.json" ]; then
  if [ -x /usr/local/bin/rebuild-xray.py ]; then python3 /usr/local/bin/rebuild-xray.py 2>&1 | head -5 || echo "[chabok-pre-start] WARN: rebuild-xray.py failed - keep previous config"; else echo "[chabok-pre-start] WARN: rebuild-xray.py missing"; fi
fi

# 5) Verify proxy env (set in dashboard, not console) - redact credentials.
# ${...:-} guard: under `set -eu` a bare $AI_PROXY_URL aborts when unset.
if [ -z "${AI_PROXY_URL:-}" ]; then echo "[chabok-pre-start] WARN: AI_PROXY_URL empty - geoblock bypass OFF"; else _host=$(echo "$AI_PROXY_URL" | sed -E 's|.*://||; s|.*@||; s|:.*||'); echo "[chabok-pre-start] AI_PROXY_URL set (host=$_host)"; fi

# 6) Launch supervisord if available (supervisor installed above)
if command -v supervisord >/dev/null 2>&1 && [ -f "$BASE_ROOT/supervisor.conf" ]; then
  mkdir -p /var/run /var/log/supervisor
  # install supervisor.conf to standard location if needed
  if [ "$BASE_ROOT/supervisor.conf" != "/app/supervisor.conf" ]; then cp -f "$BASE_ROOT/supervisor.conf" /app/supervisor.conf 2>&1 | head || true; fi
  if ! pgrep -f supervisord >/dev/null 2>&1; then
    supervisord -c "$BASE_ROOT/supervisor.conf" 2>&1 | head -5 || true
  else
    supervisorctl -c "$BASE_ROOT/supervisor.conf" reread 2>&1 | head -5 || true
    supervisorctl -c "$BASE_ROOT/supervisor.conf" update 2>&1 | head -5 || true
  fi
fi

# 4b) Start xray at boot when a usable config exists but nothing listens.
# Runs AFTER the section-6 supervisord launch so supervisord owns xray when
# it is available (raw nohup only when the daemon itself is unreachable).
# Fresh boots otherwise have a dead proxy until the next 6h refresh.
# No `xray test` gate: the pinned xray build has no `test` subcommand, so
# the shared validator (validate-xray.py) checks structure instead.
if ! pgrep -x xray >/dev/null 2>&1; then
  if [ -x /usr/local/bin/xray ] && [ -s "$XRAY_DIR/config.json" ]; then
    _valid=0
    if [ -x /usr/local/bin/validate-xray.py ]; then
      python3 /usr/local/bin/validate-xray.py "$XRAY_DIR/config.json" >/dev/null 2>&1 && _valid=1 || _valid=0
    elif [ -f "$BASE_ROOT/scripts/xray/validate_config.py" ]; then
      python3 "$BASE_ROOT/scripts/xray/validate_config.py" "$XRAY_DIR/config.json" >/dev/null 2>&1 && _valid=1 || _valid=0
    else
      _valid=1
    fi
    if [ "$_valid" = "1" ]; then
      if supervisorctl -c "$BASE_ROOT/supervisor.conf" status >/dev/null 2>&1; then
        supervisorctl -c "$BASE_ROOT/supervisor.conf" start xray >/dev/null 2>&1 || true
      else
        nohup /usr/local/bin/xray run -c "$XRAY_DIR/config.json" >> /var/log/xray/xray.log 2>&1 &
      fi
    else
      echo "[chabok-pre-start] WARN: xray config invalid - skip boot start, keep previous config"
    fi
    unset _valid
  fi
fi

echo "[chabok-pre-start] done"
