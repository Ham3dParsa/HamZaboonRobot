# Shared factory env loader (stdlib only). Fail-closed: missing file or empty
# value => KeyError with a clear message. Never prints values.
import os
import pathlib

# Canonical provider key groups (provider-key-group convention):
# {PROVIDER}_API_KEY_{GROUP} with GROUP in (G1, G2). The generic
# provider names below are LEGACY fallbacks (kept working, documented
# in factory/.env.example) — new setups use the grouped names.
CANONICAL_GROUP_VARS = (
    "AVALAI_API_KEY_G1", "AVALAI_API_KEY_G2",
    "OPENROUTER_API_KEY_G1", "OPENROUTER_API_KEY_G2",
    "GOOGLE_API_KEY_G1", "GOOGLE_API_KEY_G2",
    "GROQ_API_KEY_G1", "GROQ_API_KEY_G2",
)

# Legacy generic names: resolve as fallback after the grouped names.
# OPENROUTER_API_KEY_2 is the older numbered style (same meaning as
# OPENROUTER_API_KEY_G2); OPENCODE_ZEN_* is retired from the run line
# but still read by archive/lexicon scripts.
LEGACY_KEY_VARS = frozenset((
    "AVALAI_API_KEY",
    "OPENROUTER_API_KEY", "OPENROUTER_API_KEY_2",
    "GOOGLE_AI_API_KEY",
    "GROQ_API_KEY",
    "OPENCODE_ZEN_API_KEY", "OPENCODE_ZEN_API_KEY_2",
))

# Fernet master for operator-stored keys (WebUI secure storage).
MASTER_KEY_VARS = ("AI_MASTER_KEY",)

# Egress supervisor secrets: canonical home is tools/egress/.env, but
# the factory file is an accepted fallback (resolved via this loader).
EGRESS_VARS = (
    "EGRESS_SUP_TOKEN", "EGRESS_SUP_URL", "EGRESS_SUP_PORT",
    "EGRESS_SUB_URL", "EGRESS_SUB_URLS",
)

KEYS = (CANONICAL_GROUP_VARS + tuple(sorted(LEGACY_KEY_VARS))
        + MASTER_KEY_VARS + EGRESS_VARS)


def _default_env_path():
    return pathlib.Path(__file__).resolve().parent.parent / ".env"  # factory/.env (not core/)


def load_factory_env(required=(), path=None, override=False):
    env_path = pathlib.Path(path) if path else _default_env_path()
    wanted = set(KEYS) | set(required or ())
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k in wanted and v and (override or k not in os.environ):
                os.environ[k] = v
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise KeyError("factory/.env missing keys: " + ", ".join(missing)
                       + " (copy factory/.env.example to factory/.env and fill values)")
    names = list(KEYS) + [k for k in required if k not in KEYS]
    return {k: os.environ.get(k, "") for k in names}
