#!/bin/bash
set -euo pipefail
SUB="${XRAY_SUB_URL:-}"
LOCK=/tmp/xray_update.lock
LOG=/var/log/xray_update.log
exec 9>"$LOCK"; flock -n 9 || { echo "$(date) busy" >> "$LOG"; exit 0; }
if [ -z "$SUB" ]; then echo "$(date) XRAY_SUB_URL empty - skip" >> "$LOG"; exit 0; fi
echo "=== $(date) fetch ===" >> "$LOG"
if ! python3 /usr/local/bin/sub2xray.py "$SUB" > /tmp/outs.new 2>>"$LOG"; then echo "fetch fail" >> "$LOG"; exit 0; fi
CNT=$(python3 -c "import json; print(len(json.load(open('/tmp/outs.new'))))")
if [ "$CNT" -lt 5 ]; then echo "too few $CNT" >> "$LOG"; exit 0; fi
mv /tmp/outs.new /tmp/outs.json
cp -f /tmp/outs.json /app/hamzaban/.xray/outs.json 2>&1 | head || true
K=$(PYTHONPATH=/app/hamzaban python3 -c "from services.db import get_active_preset, resolve_preset_key; print(resolve_preset_key(get_active_preset()) or '')" 2>/dev/null || echo "")
MODEL=$(PYTHONPATH=/app/hamzaban python3 -c "from services.db import get_active_preset; import services.ai.preset_fields as pf; v=pf.resolve(get_active_preset(),'model'); print(v if v else '')" 2>/dev/null || echo "")
if [ -z "$MODEL" ]; then MODEL=$(PYTHONPATH=/app/hamzaban python3 -c "from config import DEFAULT_AI_MODEL; print(DEFAULT_AI_MODEL)" 2>/dev/null || echo ""); fi
if [ -z "$K" ]; then echo "no K" >> "$LOG"; exit 0; fi
if [ -z "$MODEL" ]; then echo "no MODEL" >> "$LOG"; exit 0; fi
export K; export MODEL
python3 << 'PY' 2>&1 | tee -a "$LOG"
import json, subprocess, time, pathlib, os, tempfile
with open("/tmp/outs.json") as f:
    outs=json.load(f)
K=os.environ["K"]; MODEL=os.environ["MODEL"]
# write auth header to temp file to avoid key on argv (visible via ps)
hdr_file = tempfile.mktemp(prefix="xray_hdr_")
try:
    pathlib.Path(hdr_file).write_text(f"Authorization: Bearer {K}\n")
    clean=[]
    for o in outs:
        tag=o["tag"]
        cfg={"inbounds":[{"port":1081,"protocol":"socks","settings":{"auth":"noauth"}}],"outbounds":[o,{"protocol":"freedom","tag":"direct"}]}
        open(f"/tmp/xray_{tag}.json","w").write(json.dumps(cfg))
        proc=subprocess.Popen(["xray","run","-c",f"/tmp/xray_{tag}.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.6)
        if proc.poll() is not None:
            continue
        try:
            # curl reads header file via -H @file is not standard; use python-safe: read header and pass via file include
            # Use subprocess with header file content not on argv by using shell expansion via file
            # Fallback: use curl with header file via reading file content into env is still argv; use --header @file via curl config
            # Easiest: use curl --config with header line from file
            # use curl config file to keep Bearer token out of argv/ps
            curl_cfg = hdr_file + ".cfg"
            pathlib.Path(curl_cfg).write_text(f'header = "Authorization: Bearer {K}"\nheader = "Content-Type: application/json"\n')
            try:
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
    open("/tmp/clean.json","w").write(json.dumps(clean))
    open("/app/hamzaban/.xray/clean.json","w").write(json.dumps(clean))
    print(f"CLEAN {len(clean)}/{len(outs)}")
finally:
    try: pathlib.Path(hdr_file).unlink()
    except: pass
PY
# clear key from env
unset K MODEL
if [ ! -s /tmp/clean.json ]; then echo "no clean" >> "$LOG"; exit 0; fi
cp -f /tmp/clean.json /app/hamzaban/.xray/clean.json 2>&1 | head || true
python3 /usr/local/bin/rebuild-xray.py 2>>"$LOG"
# Validate config without killing live supervised process: use xray test if available, else timeout with temp log
if xray test -c /app/hamzaban/.xray/config.json > /tmp/xray_test.log 2>&1; then
  echo "config test ok" >> "$LOG"
else
  # fallback: try run with timeout on distinct temp port config (no pkill of live)
  timeout 3 xray run -test -c /app/hamzaban/.xray/config.json > /tmp/xray_test.log 2>&1 || true
  if grep -qi "Failed\|error" /tmp/xray_test.log; then echo "config test failed" >> "$LOG"; cat /tmp/xray_test.log >> "$LOG"; exit 1; fi
fi
if command -v supervisorctl >/dev/null 2>&1; then
  supervisorctl restart xray 2>&1 | head || { pkill -f "xray run" || true; sleep 1; nohup /usr/local/bin/xray run -c /app/hamzaban/.xray/config.json > /var/log/xray/xray.log 2>&1 & }
else
  pkill -f "xray run" || true; sleep 1; nohup /usr/local/bin/xray run -c /app/hamzaban/.xray/config.json > /var/log/xray/xray.log 2>&1 &
fi
sleep 2; pgrep -f "xray" && echo "$(date) ok $(python3 -c "import json; print(len(json.load(open('/app/hamzaban/.xray/clean.json'))))") nodes" >> "$LOG"
