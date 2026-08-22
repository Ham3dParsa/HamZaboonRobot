"""R6: ai_presets column single source — preset_registry imports canonical list."""

import ast
from pathlib import Path


def test_column_names_helper():
    from services.db.schema import _AI_PRESETS_COLUMNS, _AI_PRESETS_COLUMN_NAMES, ai_presets_column_names

    assert len(_AI_PRESETS_COLUMNS) == len(_AI_PRESETS_COLUMN_NAMES)
    assert _AI_PRESETS_COLUMN_NAMES == tuple(c.split()[0] for c in _AI_PRESETS_COLUMNS)
    assert ai_presets_column_names() == list(_AI_PRESETS_COLUMN_NAMES)
    # name must be first, as PK
    assert _AI_PRESETS_COLUMN_NAMES[0] == "name"


def test_preset_registry_uses_canonical():
    src = Path("services/db/preset_registry.py").read_text(encoding="utf-8")
    assert "_AI_PRESETS_COLUMN_NAMES" in src
    # no hardcoded INSERT column list should remain for set_preset / clone
    assert "INSERT INTO ai_presets(name, base_url, model, api_key" not in src


def test_set_preset_roundtrip_via_canonical():
    # functional: insert via set_preset with all fields succeeds
    # Note: AI_MASTER_KEY is resolved lazily at call time by key_crypto._fernet(),
    # so setting it here before set_preset is sufficient; import order does not matter.
    import services.db as db
    import tempfile, os
    from services.db.schema import init_db

    # master key needed for encrypt_for_storage; generate a valid Fernet key
    from cryptography.fernet import Fernet

    os.environ["AI_MASTER_KEY"] = Fernet.generate_key().decode()
    import config as _cfg

    _cfg.AI_MASTER_KEY = os.environ["AI_MASTER_KEY"]

    from services.db.preset_registry import set_preset, get_preset

    # use isolated DB
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    orig = db.DB_PATH
    db.DB_PATH = path
    try:
        init_db(path)
        set_preset(
            "test_preset",
            base_url="https://example.com",
            model="m",
            api_key="k123",
            daily_batch_size=5,
            max_concurrency=2,
            max_rpm=30,
            max_tpm=100,
            max_daily_req=10,
            timeout_seconds=30.0,
            temperature=0.6,
            max_output_tokens=512,
            is_emergency=0,
            priority=0,
            enabled=1,
            input_cost_per_million=1.0,
            output_cost_per_million=2.0,
            in_fallback_chain=1,
            group_label="g",
        )
        row = get_preset("test_preset")
        assert row is not None
        assert row["base_url"] == "https://example.com"
        assert row["group_label"] == "g"
    finally:
        db.DB_PATH = orig
        try:
            os.unlink(path)
        except OSError:
            pass
        os.environ.pop("AI_MASTER_KEY", None)
        import config as _cfg2

        _cfg2.AI_MASTER_KEY = os.getenv("AI_MASTER_KEY", "")


def test_preset_registry_settings_via_conn():
    src = Path("services/db/preset_registry.py").read_text(encoding="utf-8")
    assert "set_setting_via_conn" in src
    # ensure activate_preset no longer has direct INSERT INTO settings
    # isolate activate_preset block
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "activate_preset",
            "set_fallback_active",
            "increment_consecutive_failures",
            "reset_consecutive_failures",
        ):
            func_src = ast.get_source_segment(src, node)
            assert "set_setting_via_conn" in func_src, f"{node.name} must use set_setting_via_conn"
