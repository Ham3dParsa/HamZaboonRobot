#!/bin/bash
set -euo pipefail
SUB="${XRAY_SUB_URL:-https://paste-this-link-into-your-client.xirix.li/subscription/ZWhzYW4sMTc4MDQ4OTY4NwbiZ3QGgpea}"
LOCK=/tmp/xray_update.lock
LOG=/var/log/xray_update.log
exec 9>"$LOCK"; flock -n 9 || { echo "$(date) busy" >> "$LOG"; exit 0; }
echo "=== $(date) fetch ===" >> "$LOG"
if ! python3 /usr/local/bin/sub2xray.py "$SUB" > /tmp/outs.new 2>>"$LOG"; then echo "fetch fail" >> "$LOG"; exit 0; fi
CNT=$(python3 -c "import json; print(len(json.load(open('/tmp/outs.new'))))")
if [ "$CNT" -lt 5 ]; then echo "too few $CNT" >> "$LOG"; exit 0; fi
mv /tmp/outs.new /tmp/outs.json
cp -f /tmp/outs.json /app/hamzaban/.xray/outs.json 2>&1 | head || true
K=$(PYTHONPATH=/app/hamzaban python3 -c "from services.db import get_active_preset, resolve_preset_key; print(resolve_preset_key(get_active_preset()))" 2>/dev/null || cat /app/hamzaban/.xray/k2 2>/dev/null || echo "")
MODEL=$(PYTHONPATH=/app/hamzaban python3 -c "from services.db import get_active_preset; import services.ai.preset_fields as pf; print(pf.resolve(get_active_preset(),'model'))" 2>/dev/null || echo "gemini-3.5-flash-lite")
if [ -z "$K" ]; then echo "no K" >> "$LOG"; exit 0; fi
export K; export MODEL
python3 << 'PY' 2>&1 | tee -a "$LOG"
import json, subprocess, time, pathlib, os
outs=json.load(open("/tmp/outs.json"))
K=os.environ["K"]; MODEL=os.environ["MODEL"]
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
        out=subprocess.run(["curl","--proxy","socks5h://127.0.0.1:1081","-s","--max-time","8","https://generativelanguage.googleapis.com/v1beta/openai/chat/completions","-H",f"Authorization: Bearer {K}","-H","Content-Type: application/json","-d",f'{{"model":"{MODEL}","messages":[{{"role":"user","content":"ping"}}]}}'], capture_output=True, text=True, timeout=10).stdout
        if "User location is not supported" in out:
            print(tag,"DIRTY")
        elif "429" in out or '"choices"' in out:
            print(tag,"CLEAN"); clean.append(o)
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except: proc.kill()
        time.sleep(0.2)
open("/tmp/clean.json","w").write(json.dumps(clean))
open("/app/hamzaban/.xray/clean.json","w").write(json.dumps(clean))
open("/app/hamzaban/.xray/outs.json","w").write(json.dumps(clean))
print(f"CLEAN {len(clean)}/{len(outs)}")
PY
if [ ! -s /tmp/clean.json ]; then echo "no clean" >> "$LOG"; exit 0; fi
cp -f /tmp/clean.json /app/hamzaban/.xray/clean.json 2>&1 | head || true
python3 /usr/local/bin/rebuild-xray.py 2>>"$LOG"
timeout 3 xray run -c /app/hamzaban/.xray/config.json > /tmp/xray_test.log 2>&1 & sleep 2; pkill -f "xray.*xray_test" 2>&1 | head
if grep -q "Failed" /tmp/xray_test.log; then echo "config test failed" >> "$LOG"; exit 1; fi
if command -v supervisorctl >/dev/null 2>&1; then supervisorctl restart xray 2>&1 | head || pkill -f "xray run" || true; sleep 1; nohup /usr/local/bin/xray run -c /app/hamzaban/.xray/config.json > /var/log/xray.log 2>&1 & else pkill -f "xray run" || true; sleep 1; nohup /usr/local/bin/xray run -c /app/hamzaban/.xray/config.json > /var/log/xray.log 2>&1 & fi
sleep 2; pgrep -f "xray" && echo "$(date) ok $(python3 -c "import json; print(len(json.load(open('/app/hamzaban/.xray/clean.json'))))") nodes" >> "$LOG"
