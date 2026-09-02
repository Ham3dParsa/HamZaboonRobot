"""Shared pytest configuration.

P1.4 warm-import: importing ``services.db`` first resolves the latent circular
import (validation -> helpers -> db -> session_reports -> session/summary ->
formatting -> back) that otherwise breaks cold single-file collection of
``test_formatting.py`` / ``test_word_query.py`` (see forensics F5).

Provides a valid ``AI_MASTER_KEY`` for every test so that any test writing an
API key goes through encryption (fail-closed) instead of raising
``MasterKeyRequiredError``. Tests that deliberately exercise no-master-key
behavior override ``config.AI_MASTER_KEY`` locally (e.g. via ``mock.patch`` in
``setUp``), which takes precedence for their own duration.

P1.1: a per-worker pre-migrated master database (built by the real
``init_db``) is copied into each test that initialises a fresh DB, replacing
the ~0.18s fsync-heavy migration with a ~1ms file copy. The copy intercept only
fires when ``init_db`` is called with *no* explicit path AND the target file
does not exist; explicit-path calls (migration, restore, ``import_db_bytes``)
fall through to the real ``init_db`` so migration/restore/idempotency tests
keep exercising genuine code paths. The master lives only in a dedicated test
sandbox under the temp dir (R3), never in the repository and never derived from
production.

Pins ``bot._telegram_offline`` to ``False`` for every test and restores the
previous value afterwards, neutralising the cross-file global leak at its
source: ``test_reliability.py`` leaves the flag ``True`` after a health-job
test, which makes ``bot.text_router``/``callback_router`` early-return offline
for later tests on the same xdist worker.
"""

import logging
import os
import shutil
import tempfile
import threading

import pytest

logger = logging.getLogger(__name__)

# P1.4: importing ``services.db`` (below) warms the DB module so cold single-file
# collection cannot hit the circular-import cycle (see module docstring).
import services.db as db
from services.db import schema as db_schema

# Fail closed if import ordering ever inverts (conftest moved to repo root).
assert os.environ.get("HAMZABAN_TEST_MODE") == "1", (
    "tests/conftest.py warm-import requires HAMZABAN_TEST_MODE==1 from tests/__init__.py"
)

import bot
import config

# R4: default test backoff base (0.1). Production default stays 1.0; 0.05 is
# reserved for explicit performance benchmarks and overrides via env.
os.environ.setdefault("HAMZABAN_RETRY_BACKOFF_BASE", "0.1")

TEST_MASTER_KEY = "sd4H8UUr5ONYISGXcx468OQwFaUxaktNGGTPs9TBESg="

_ORIGINAL_INIT_DB = db_schema.init_db

_MASTER_LOCK = threading.Lock()
_MASTER_CACHE: dict[str, str] = {}


def _ensure_master() -> str:
    """Build (once per worker) a fully-migrated test master database.

    Uses the real ``init_db`` so the master carries the complete final schema,
    seed plans/settings, empty user-space, the R1 test application_id marker
    and WAL mode — then is closed (checkpointed, sidecars removed). Tests copy
    from it; it is never the active DB_PATH and never mutated by a test.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "local")
    with _MASTER_LOCK:
        cached = _MASTER_CACHE.get(worker)
        if cached is not None:
            return cached
        area = os.path.join(
            tempfile.gettempdir(), "hamzaban_test_area", worker, str(os.getpid())
        )
        os.makedirs(area, exist_ok=True)
        master = os.path.join(area, "master.db")
        # Remove sidecars BEFORE main file; suppress only FileNotFoundError
        # so a permission/lock failure is not silently hidden.
        for p in (f"{master}-wal", f"{master}-shm", master):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
        _ORIGINAL_INIT_DB(master)
        _MASTER_CACHE[worker] = master
        return master


def _patched_init_db(path: str | None = None):
    """Snapshot-copy intercept for P1.1.

    Intercepts ONLY ``init_db()`` called with no explicit path (the universal
    fresh-DB setUp pattern): when the target file does not exist, copy the
    pre-migrated master instead of re-running the migration. Any explicit-path
    call, or a no-path call on an existing file (migration/restore/idempotency),
    falls through to the real ``init_db`` so that behavior stays genuinely
    covered.
    """
    if path is None:
        from services.db import DB_PATH as target
        # P0.1/R1: never copy to the production database, even if DB_PATH was
        # accidentally pointed at it. (Explicit-path calls are guarded inside
        # the real init_db.)
        db_schema._check_test_mode_guard(target)
        if (
            os.environ.get("HAMZABAN_TEST_MODE") == "1"
            and not os.path.exists(target)
        ):
            master = _ensure_master()
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            # Ensure stale target sidecars cannot contaminate the fresh copy
            for suffix in ("-wal", "-shm", "-journal"):
                try:
                    os.remove(f"{target}{suffix}")
                except FileNotFoundError:
                    pass
            shutil.copy2(master, target)
            return
    return _ORIGINAL_INIT_DB(path)


# Replace the re-export and the schema function so both ``db.init_db()`` and
# ``db_schema.init_db()`` call sites see the intercept.
db.init_db = _patched_init_db
db_schema.init_db = _patched_init_db


@pytest.hookimpl()
def pytest_runtest_setup(item):
    # P0.1 kill-switch diagnostics: expose the offending test to the guard.
    os.environ["HAMZABAN_CURRENT_TEST"] = item.nodeid


@pytest.hookimpl()
def pytest_runtest_teardown(item, nextitem):
    os.environ.pop("HAMZABAN_CURRENT_TEST", None)


@pytest.fixture(autouse=True)
def _ai_master_key():
    old = getattr(config, "AI_MASTER_KEY", "")
    config.AI_MASTER_KEY = TEST_MASTER_KEY
    try:
        yield
    finally:
        config.AI_MASTER_KEY = old


@pytest.fixture(autouse=True)
def _telegram_offline_pinned():
    old = getattr(bot, "_telegram_offline", False)
    bot._telegram_offline = False
    try:
        yield
    finally:
        bot._telegram_offline = old


@pytest.fixture(autouse=True)
def _per_user_rate_cleared():
    def _try_clear() -> None:
        try:
            import services.scheduling as _sched

            _clear = getattr(_sched, "_clear_rate_buckets", None)
            if _clear is None:
                _clear = getattr(_sched, "_reset_rate_buckets", None)
            if _clear is not None:
                _clear()
        except Exception:
            logger.debug("failed to clear per-user rate buckets", exc_info=True)

    _try_clear()
    try:
        yield
    finally:
        _try_clear()
