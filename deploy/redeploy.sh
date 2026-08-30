#!/usr/bin/env bash
#
# HamZaboon redeploy script.
# Safe to run manually (`bash deploy/redeploy.sh`) or from CI over SSH.
# Pulls the latest `main`, syncs Python deps, and restarts the systemd service.
#
# Override defaults via environment variables:
#   APP_DIR      path to the cloned repo          (default: /home/ubuntu/HamZaboonRobot)
#   SERVICE_NAME systemd unit name                (default: hamzaboon)
#   BRANCH       branch to deploy                 (default: main)
#   PYTHON       python interpreter               (default: python3)
#
set -euo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/HamZaboonRobot}"
SERVICE_NAME="${SERVICE_NAME:-hamzaboon}"
BRANCH="${BRANCH:-main}"
PYTHON="${PYTHON:-python3}"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "[redeploy] ERROR: $APP_DIR is not a git checkout." >&2
  exit 1
fi

cd "$APP_DIR"

echo "[redeploy] Pulling latest origin/$BRANCH ..."
git fetch --all --prune
git reset --hard "origin/$BRANCH"

# Sync dependencies only if requirements changed (cheap guard, avoids churn).
if [ -f requirements.txt ]; then
  echo "[redeploy] Syncing dependencies ..."
  "$PYTHON" -m pip install --upgrade -r requirements.txt
fi

echo "[redeploy] Restarting $SERVICE_NAME ..."
if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
  sudo systemctl restart "$SERVICE_NAME"
else
  systemctl restart "$SERVICE_NAME"
fi

echo "[redeploy] Done. Recent status:"
systemctl --no-pager status "$SERVICE_NAME" --lines=0 || true
