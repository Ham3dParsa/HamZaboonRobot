"""Pin .gitignore coverage for the factory home console secret paths.

Behavior spec: the console moved from ``factory/linking/webui/`` to
``factory/webui/`` but the ignore rules did not follow — a real pasted
key at the new ``OPERATOR_KEYS_PATH`` would be committable. Every
operator-secret / operator-local path the server writes must have a
mirrored ignore line (string-shape assertions over .gitignore, same
style as the ctl-output tests — no git subprocess, no I/O beyond the
two text reads). The tracked seed preset keeps its ``!`` exception.
"""

import os

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

GITIGNORE_PATH = os.path.join(PROJECT_ROOT, ".gitignore")

# Reviewer-prescribed mirror (PR 825 round-2 must-fix): the exact lines
# .gitignore must carry for the new console home.
REQUIRED_LINES = (
    "factory/webui/operator_keys.json",
    "factory/webui/labels.jsonl",
    "factory/webui/provider_key_vars.json",
    "factory/webui/presets/*.json",
    "!factory/webui/presets/witness_benchmark.json",
    "factory/webui/provider_profiles/*.json",
    "factory/webui/runs/",
    "factory/webui/runs.json",
)


def _gitignore_lines():
    with open(GITIGNORE_PATH, encoding="utf-8") as handle:
        return [line.strip() for line in handle.read().splitlines()]


def test_new_console_secret_paths_ignored():
    lines = _gitignore_lines()
    for required in REQUIRED_LINES:
        assert required in lines, required


def test_server_secret_constants_live_under_ignored_home():
    """The server's secret-bearing paths resolve under factory/webui,
    i.e. inside the ignored home pinned above (no second registry)."""
    from factory.webui import server as webui

    home = os.path.join(PROJECT_ROOT, "factory", "webui")
    for path in (webui.OPERATOR_KEYS_PATH, webui.KEY_VAR_MAP_PATH,
                 webui.LABELS_PATH, webui.REGISTRY_PATH, webui.RUNS_DIR,
                 webui.PRESETS_DIR, webui.PROFILES_DIR):
        assert os.path.abspath(path).startswith(home), path
