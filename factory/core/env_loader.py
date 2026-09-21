# Shared factory env loader (stdlib only). Fail-closed: missing file or empty
# value => KeyError with a clear message. Never prints values.
import os
import pathlib

KEYS = ("OPENCODE_ZEN_API_KEY", "OPENCODE_ZEN_API_KEY_2",
        "OPENROUTER_API_KEY", "GOOGLE_AI_API_KEY", "AVALAI_API_KEY")

def load_factory_env(required=()):
    env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"  # factory/.env (not core/)
    wanted = set(KEYS) | set(required or ())
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k in wanted and v and k not in os.environ:
                os.environ[k] = v
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise KeyError("factory/.env missing keys: " + ", ".join(missing)
                       + " (copy factory/.env.example to factory/.env and fill values)")
    names = list(KEYS) + [k for k in required if k not in KEYS]
    return {k: os.environ.get(k, "") for k in names}
