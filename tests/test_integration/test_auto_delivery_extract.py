import pathlib


def test_legacy_batch_module_exists_and_unwired():
    p = pathlib.Path("services/legacy_batch.py")
    assert p.exists(), "services/legacy_batch.py must exist (Q-25 extraction)"
    text = p.read_text(encoding="utf-8")
    assert "Unwired" in text or "unwired" in text
    # no live code should import it
    live_imports = []
    for f in pathlib.Path("services").rglob("*.py"):
        if f.name == "legacy_batch.py":
            continue
        t = f.read_text(encoding="utf-8", errors="ignore")
        if "legacy_batch" in t:
            live_imports.append(str(f))
    for f in pathlib.Path("handlers").rglob("*.py"):
        t = f.read_text(encoding="utf-8", errors="ignore")
        if "legacy_batch" in t:
            live_imports.append(str(f))
    for f in [pathlib.Path("bot.py"), pathlib.Path("config/__init__.py")]:
        if f.exists() and "legacy_batch" in f.read_text(encoding="utf-8", errors="ignore"):
            live_imports.append(str(f))
    assert not live_imports, f"live code still imports legacy_batch: {live_imports}"


def test_no_live_daily_card_scheduling_import():
    # bot.py and scheduling should not drive daily push
    bot = pathlib.Path("bot.py").read_text(encoding="utf-8", errors="ignore")
    # legacy scheduling import for push should be absent or not used
    assert "daily_card" not in bot.lower() or "legacy_batch" not in bot
