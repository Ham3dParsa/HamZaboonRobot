# Deploying HamZaboon to a VPS

Recommended, low-maintenance setup (per issue #490): **Linux VPS + `systemd` +
GitHub Actions SSH deploy**. No extra listener runs on the server; on every push
to `main` a workflow SSHes in and runs `deploy/redeploy.sh`.

## 1. Server (one-time)

```bash
# clone onto the server (must stay on a clean main)
git clone <your-repo> /home/ubuntu/HamZaboonRobot
cd /home/ubuntu/HamZaboonRobot
python3 -m pip install -r requirements.txt
cp .env.example .env   # then fill in real secrets (NEVER commit .env)
```

Install the service unit:

```bash
sudo cp deploy/systemd/hamzaboon.service /etc/systemd/system/hamzaboon.service
sudo systemctl daemon-reload
sudo systemctl enable --now hamzaboon
# logs:
sudo journalctl -u hamzaboon -f
```

`Restart=always` brings the bot back automatically after a crash and after each
redeploy (`systemctl restart`).

## 2. GitHub secrets (one-time)

Add these repository secrets (Settings → Secrets → Actions):

| Secret            | Value                                              |
|-------------------|----------------------------------------------------|
| `VPS_HOST`        | Server IP or hostname                              |
| `VPS_USER`        | SSH user (e.g. `ubuntu`)                           |
| `SSH_DEPLOY_KEY`  | Private key whose public half is in `authorized_keys` on the server |

Generate a dedicated deploy key (no passphrase) and append the public half to
`~/.ssh/authorized_keys` on the server.

## 3. Manual or automatic redeploy

- **Automatic:** push/merge to `main` → `.github/workflows/deploy.yml` runs
  `deploy/redeploy.sh` (pull → pip install → restart).
- **Manual:** `bash deploy/redeploy.sh` on the server, or trigger the
  "Deploy to VPS" workflow manually from the Actions tab.

Override paths via env vars `APP_DIR`, `SERVICE_NAME`, `BRANCH`, `PYTHON`.

## Why not Windows / on-server webhook?

Windows (NSSM/Task Scheduler) works but is more fragile for auto-restart and
webhooks; Linux `systemd` is simpler and standard. The webhook approach (a Flask
listener) is also viable but adds a hardening/TLS burden, so SSH-from-CI is
preferred here.
