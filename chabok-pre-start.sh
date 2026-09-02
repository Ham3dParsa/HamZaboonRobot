#!/bin/bash
set -e
# HamZaban - persistent Xray bootstrap for Chabokan Python hosting
# Runs on every deploy, before app start. Idempotent.
export DEBIAN_FRONTEND=noninteractive
XRAY_DIR="/var/lib/xray"
mkdir -p "$XRAY_DIR" /var/log/xray

# 1) Install Xray if missing (console installs are ephemeral)
if ! command -v xray >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y --no-install-recommends unzip jq curl ca-certificates cron supervisor
  curl -fsSL https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip -o /tmp/xray.zip
  unzip -o /tmp/xray.zip -d /usr/local/bin/ xray
  chmod +x /usr/local/bin/xray
  rm -f /tmp/xray.zip
fi

# 2) Ensure cron is running (container has no systemd)
service cron start 2>&1 | head -5 || cron 2>&1 | head -5 || true

# 3) Restore persistent subscription state
[ -f "$XRAY_DIR/clean.json" ] && cp -f "$XRAY_DIR/clean.json" /tmp/clean.json 2>&1 | head || true
[ -f "$XRAY_DIR/outs.json" ] && cp -f "$XRAY_DIR/outs.json" /tmp/outs.json 2>&1 | head || true

# 4) Rebuild Xray config from clean list (fallback to outs if clean missing)
if [ -f /tmp/clean.json ] || [ -f /var/lib/xray/clean.json ]; then
  python3 /usr/local/bin/rebuild-xray.py 2>&1 | head -5 || true
fi

# 5) Verify proxy env (set in Chabokan dashboard, not console)
if [ -z "$AI_PROXY_URL" ]; then echo "[chabok-pre-start] WARN: AI_PROXY_URL empty - geoblock bypass OFF"; else echo "[chabok-pre-start] AI_PROXY_URL=$AI_PROXY_URL"; fi

echo "[chabok-pre-start] done"
