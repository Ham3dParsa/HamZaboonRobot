#!/bin/bash
# NOTE: cron executes this via sh (dash), so only POSIX syntax: NO pipefail.
set -eu
SUB="${XRAY_SUB_URL:-}"
# Cron does not inherit panel env, so fall back to the file in the permanent
# path (0600, written once by the owner). Env wins when both exist.
if [ -z "$SUB" ] && [ -f /app/.xray/sub_url ]; then SUB=$(cat /app/.xray/sub_url); fi
LOCK=/tmp/xray_update.lock
LOG=/var/log/xray_update.log
exec 9>"$LOCK"; flock -n 9 || { echo "$(date) busy" >> "$LOG"; exit 0; }
if [ -z "$SUB" ]; then echo "$(date) XRAY_SUB_URL empty - skip" >> "$LOG"; exit 0; fi
echo "=== $(date) fetch ===" >> "$LOG"
if ! python3 /usr/local/bin/sub2xray.py "$SUB" > /tmp/outs.new 2>>"$LOG"; then echo "fetch fail" >> "$LOG"; exit 0; fi
CNT=$(python3 -c "import json; f=open('/tmp/outs.new'); print(len(json.load(f)))" 2>/dev/null || echo 0)
if [ "$CNT" -lt 5 ]; then echo "too few $CNT" >> "$LOG"; exit 0; fi
mv /tmp/outs.new /tmp/outs.json
cp -f /tmp/outs.json /app/.xray/outs.json 2>&1 | head || true
K=$(PYTHONPATH=/app python3 -c "from services.db import get_active_preset, resolve_preset_key; print(resolve_preset_key(get_active_preset()) or '')" 2>/dev/null || echo "")
MODEL=$(PYTHONPATH=/app python3 -c "from services.db import get_active_preset; import services.ai.preset_fields as pf; v=pf.resolve(get_active_preset(),'model'); print(v if v else '')" 2>/dev/null || echo "")
if [ -z "$MODEL" ]; then MODEL=$(PYTHONPATH=/app python3 -c "from config import DEFAULT_AI_MODEL; print(DEFAULT_AI_MODEL)" 2>/dev/null || echo ""); fi
if [ -z "$K" ]; then echo "no K" >> "$LOG"; exit 0; fi
if [ -z "$MODEL" ]; then echo "no MODEL" >> "$LOG"; exit 0; fi
export K; export MODEL
python3 << 'PY' 2>&1 | tee -a "$LOG"
import json, subprocess, time, pathlib, os, tempfile
with open("/tmp/outs.json") as f:
    outs=json.load(f)
K=os.environ["K"]; MODEL=os.environ["MODEL"]
# secure temp files 0600 to avoid world-readable Bearer token
import stat
fd, hdr_file = tempfile.mkstemp(prefix="xray_hdr_")
os.close(fd); os.chmod(hdr_file, 0o600)
try:
    pathlib.Path(hdr_file).write_text(f"Authorization: Bearer {K}\n")
    os.chmod(hdr_file, 0o600)
    clean=[]
    for o in outs:
        tag=o["tag"]
        cfg_path = f"/tmp/xray_{tag}.json"
        with open(cfg_path,"w") as cf:
            cf.write(json.dumps({"inbounds":[{"port":1081,"protocol":"socks","settings":{"auth":"noauth"}}],"outbounds":[o,{"protocol":"freedom","tag":"direct"}]}))
        proc=subprocess.Popen(["xray","run","-c",cfg_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.6)
        if proc.poll() is not None:
            try: pathlib.Path(cfg_path).unlink()
            except: pass
            continue
        try:
            fd2, curl_cfg = tempfile.mkstemp(prefix="xray_curl_", suffix=".cfg")
            os.close(fd2); os.chmod(curl_cfg, 0o600)
            try:
                pathlib.Path(curl_cfg).write_text(f'header = "Authorization: Bearer {K}"\nheader = "Content-Type: application/json"\n')
                os.chmod(curl_cfg, 0o600)
                out=subprocess.run(["curl","--proxy","socks5h://127.0.0.1:1081","-s","--max-time","8","--config",curl_cfg,"https://generativelanguage.googleapis.com/v1beta/openai/chat/completions","-d",f'{{"model":"{MODEL}","messages":[{{"role":"user","content":"ping"}}]}}'], capture_output=True, text=True, timeout=10).stdout
            finally:
                try: pathlib.Path(curl_cfg).unlink()
                except: pass
            if "User location is not supported" in out:
                print(tag,"DIRTY")
            elif "429" in out or '"choices"' in out:
                print(tag,"CLEAN"); clean.append(o)
        finally:
            proc.terminate()
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired: proc.kill()
            time.sleep(0.2)
            try: pathlib.Path(cfg_path).unlink()
            except: pass
    open("/tmp/clean.json","w").write(json.dumps(clean))
    open("/app/.xray/clean.json","w").write(json.dumps(clean))
    print(f"CLEAN {len(clean)}/{len(outs)}")
finally:
    try: pathlib.Path(hdr_file).unlink()
    except: pass
PY
unset K MODEL
if [ ! -s /tmp/clean.json ]; then echo "no clean" >> "$LOG"; exit 0; fi
cp -f /tmp/clean.json /app/.xray/clean.json 2>&1 | head || true
python3 /usr/local/bin/rebuild-xray.py 2>>"$LOG" || echo "rebuild failed - keep previous config" >> "$LOG"
if xray test -c /app/.xray/config.json > /tmp/xray_test.log 2>&1; then
  echo "config test ok" >> "$LOG"
else
  if grep -qi "Failed\|error" /tmp/xray_test.log; then echo "config test failed" >> "$LOG"; cat /tmp/xray_test.log >> "$LOG"; exit 1; fi
  echo "config test ok (fallback)" >> "$LOG"
fi
if command -v supervisorctl >/dev/null 2>&1; then
  supervisorctl restart xray 2>&1 | head || { pkill -f "xray run" || true; sleep 1; nohup /usr/local/bin/xray run -c /app/.xray/config.json > /var/log/xray/xray.log 2>&1 & }
else
  pkill -f "xray run" || true; sleep 1; nohup /usr/local/bin/xray run -c /app/.xray/config.json > /var/log/xray/xray.log 2>&1 &
fi
sleep 2; pgrep -f "xray" && echo "$(date) ok $(python3 -c "import json; print(len(json.load(open('/app/.xray/clean.json'))))") nodes" >> "$LOG"
