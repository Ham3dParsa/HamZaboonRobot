import datetime
import json
import logging
import os
import secrets
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from config.catalog import DEFAULT_LEVEL, DISPLAY_TOGGLE_DEFAULTS

from config import (
    DB_PATH,
    LLM_INPUT_COST_USD_PER_MILLION,
    LLM_OUTPUT_COST_USD_PER_MILLION,
    APP_TZ,
    USD_TO_TOMAN_RATE,
)

_app_timezone = APP_TZ
_LEGACY_DAILY_TABLES = frozenset(
    {"daily_cards", "daily_progress", "daily_card_sessions"}
)

# Canonical ai_presets column set. This is the single source of truth for the
# table definition, reused by every CREATE so the fresh-DB schema and the
# table-rebuild migration can never drift.
_AI_PRESETS_COLUMNS = (
    "name TEXT PRIMARY KEY",
    "base_url TEXT",
    "model TEXT",
    "api_key TEXT NOT NULL DEFAULT ''",
    "daily_batch_size INTEGER DEFAULT 6",
    "max_concurrency INTEGER DEFAULT 2",
    "max_rpm INTEGER DEFAULT 30",
    "max_tpm INTEGER DEFAULT 0",
    "max_daily_req INTEGER DEFAULT 0",
    "timeout_seconds REAL DEFAULT 30.0",
    "temperature REAL DEFAULT 0.6",
    "max_output_tokens INTEGER DEFAULT 4096",
    "priority INTEGER DEFAULT 0",
    "enabled INTEGER DEFAULT 1",
    "is_emergency INTEGER DEFAULT 0",
    "input_cost_per_million REAL",
    "output_cost_per_million REAL",
    "group_label TEXT DEFAULT ''",
    "in_fallback_chain INTEGER DEFAULT 1",
    "reasoning_effort TEXT DEFAULT 'none'",
)

# Canonical column names derived from _AI_PRESETS_COLUMNS (single source of truth).
_AI_PRESETS_COLUMN_NAMES = tuple(col.split()[0] for col in _AI_PRESETS_COLUMNS)


def ai_presets_column_names() -> list[str]:
    """Return the canonical ai_presets column names (derived from
    _AI_PRESETS_COLUMNS)."""
    return list(_AI_PRESETS_COLUMN_NAMES)


def _ai_presets_create_sql(if_not_exists: bool = False) -> str:
    """Return a CREATE TABLE statement for ai_presets from the canonical column
    set (single source of truth), so the fresh schema and the rebuild migration
    can never drift. The rebuild uses a plain CREATE (no IF NOT EXISTS)."""
    cols = ",\n                ".join(_AI_PRESETS_COLUMNS)
    prefix = "CREATE TABLE IF NOT EXISTS " if if_not_exists else "CREATE TABLE "
    return f"{prefix}ai_presets (\n                {cols}\n            );"


def _today() -> datetime.date:
    return datetime.datetime.now(_app_timezone).date()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def normalize_word(word: str) -> str:
    """Collapse a word to its single canonical dedup key (A2-3 / R2).

    Single source of truth for saved_words.normalized_word and the query-dedup
    key. ``unicodedata.NFC`` folds canonically-equivalent codepoints (precomposed
    vs decomposed accents), ``casefold()`` lowercases in a Unicode-aware way, and
    whitespace is collapsed to a single space. Applied identically on insert and
    lookup so a prior card is found for case/Unicode variants instead of
    re-spending quota + AI.
    """
    return " ".join(unicodedata.normalize("NFC", word).split()).casefold()


def _backfill_saved_word_normalization(conn):
    """One-time migration: re-normalize saved_words.normalized_word (A2-3 / R2).

    Runs on the first ``init_db`` after deploy: recomputes every row's
    ``normalized_word`` from its original ``word`` via ``normalize_word`` and
    resolves collisions where NFC folds two previously-distinct keys into one.
    On a collision within ``(user_id, lang)``, the most-recently-active row
    (COALESCE(last_review_at, added_at), ordered by parsed timestamp desc) is kept
    and the older duplicate is deleted. Idempotent, and gated by a ``_migration_word_normalization_done``
    marker (``_migration_word_normalization_done``) so the full table scan happens
    only once: after it, every row already equals ``normalize_word(word)`` and
    the unique index (created after this backfill) prevents new NFC collisions.
    """
    done = conn.execute(
        "SELECT 1 FROM settings WHERE key='_migration_word_normalization_done'"
    ).fetchone()
    if done:
        return
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(saved_words)").fetchall()
    }
    activity_cols = [c for c in ("last_review_at", "added_at") if c in columns]
    select_cols = ", ".join(["id", "user_id", "lang", "word", "normalized_word"] + activity_cols)
    rows = conn.execute(f"SELECT {select_cols} FROM saved_words").fetchall()

    def _parse_activity(value):
        """Best-effort timestamp for keeper ordering; unparseable/absent => oldest.

        Naive values are interpreted as UTC so ordering is host-timezone
        independent; aware values are converted to epoch directly.
        """
        if not value:
            return float("-inf")
        try:
            dt = datetime.datetime.fromisoformat(value)
        except ValueError:
            return float("-inf")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()

    def _activity(r):
        for c in activity_cols:
            if r[c]:
                return _parse_activity(r[c])
        return float("-inf")

    groups: dict[tuple, list] = {}
    for r in rows:
        if r["word"] is None:
            # NULL word cannot be normalized; leave the row untouched (it cannot
            # participate in an NFC collision). Empty-string rows ARE folded so
            # that '' and a whitespace-only sibling still collapse to one key
            # before the unique index is created.
            continue
        key = (r["user_id"], r["lang"], normalize_word(r["word"]))
        groups.setdefault(key, []).append(r)
    deletes: list[int] = []
    updates: list[tuple[str, int]] = []
    for items in groups.values():
        items.sort(key=_activity, reverse=True)
        keeper = items[0]
        normalized = normalize_word(keeper["word"])
        if keeper["normalized_word"] != normalized:
            updates.append((normalized, keeper["id"]))
        for dup in items[1:]:
            deletes.append(dup["id"])
    for wid in deletes:
        conn.execute("DELETE FROM saved_words WHERE id=?", (wid,))
    for nkey, wid in updates:
        conn.execute("UPDATE saved_words SET normalized_word=? WHERE id=?", (nkey, wid))
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, '1') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("_migration_word_normalization_done",),
    )


def _backfill_query_results_normalization(conn):
    """One-time migration: re-normalize query_results query_text/word (R7a).

    Recomputes ``query_text`` and ``word`` via ``normalize_word`` (NFC +
    casefold + whitespace-collapse) and resolves collisions where normalization
    folds two previously-distinct keys into one within ``(user_id, lang,
    query_text)``. On collision the most-recent row (``created_at`` desc) is
    kept and older duplicates are deleted. Idempotent, gated by
    ``_migration_query_results_normalization_done`` so the full table scan
    happens only once.
    """
    done = conn.execute(
        "SELECT 1 FROM settings WHERE key='_migration_query_results_normalization_done'"
    ).fetchone()
    if done:
        return
    rows = conn.execute(
        "SELECT token, user_id, lang, query_text, word, created_at FROM query_results"
    ).fetchall()

    def _parse_created(value):
        if not value:
            return float("-inf")
        try:
            dt = datetime.datetime.fromisoformat(value)
        except ValueError:
            return float("-inf")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()

    groups: dict[tuple, list] = {}
    for r in rows:
        norm_q = normalize_word(r["query_text"] or "")
        key = (r["user_id"], r["lang"], norm_q)
        groups.setdefault(key, []).append(r)

    deletes: list[str] = []
    updates: list[tuple[str, str, str]] = []
    for items in groups.values():
        items.sort(key=lambda x: _parse_created(x["created_at"]), reverse=True)
        keeper = items[0]
        new_q = normalize_word(keeper["query_text"] or "")
        new_w = normalize_word(keeper["word"] or "")
        if keeper["query_text"] != new_q or keeper["word"] != new_w:
            updates.append((new_q, new_w, keeper["token"]))
        for dup in items[1:]:
            deletes.append(dup["token"])
    for token in deletes:
        conn.execute("DELETE FROM query_results WHERE token=?", (token,))
    for new_q, new_w, token in updates:
        conn.execute(
            "UPDATE query_results SET query_text=?, word=? WHERE token=?",
            (new_q, new_w, token),
        )
    # Update non-duplicate rows that still need normalization (outside collision groups)
    # Already handled keeper updates; remaining singletons with no collision but
    # stale normalization were covered as keepers. No extra pass needed.
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, '1') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("_migration_query_results_normalization_done",),
    )


# Rows per commit for the one-time review-counter backfill below: small
# enough that startup never holds a long write transaction on large DBs.
_BACKFILL_BATCH = 2000


def _backfill_review_counters(conn) -> None:
    """One-time migration: seed saved_words.total_reviews/lapses from history.

    Sets each card's counters to its lifetime review_events totals so the
    retention prune (which deletes old raw events) stays exact: counters are
    bumped atomically alongside the event insert going forward, and this
    backfill covers everything inserted before the counters existed. Lapse =
    grade 1, with a legacy fallback (grade NULL + outcome 'again') for rows
    written before the grade column existed. Idempotent via the
    ``_migration_review_counters_done`` settings marker; monotonic by
    construction (runs once, before any prune can delete rows). Row-preserving:
    only UPDATEs the two counter columns. Batched by saved_words id ranges
    (``_BACKFILL_BATCH`` rows per commit) so startup never holds one long
    write transaction on large DBs; the absolute SET (not increment) form
    makes a crashed re-run recompute identical values.
    """
    done = conn.execute(
        "SELECT 1 FROM settings WHERE key='_migration_review_counters_done'"
    ).fetchone()
    if done:
        return
    review_cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(review_events)").fetchall()
    }
    if "grade" in review_cols:
        lapse_pred = (
            "(review_events.grade = 1 OR (review_events.grade IS NULL "
            "AND review_events.outcome = 'again'))"
        )
    else:
        # Very old DBs predate the grade column: outcome-only fallback.
        lapse_pred = "(review_events.outcome = 'again')"
    bounds = conn.execute(
        "SELECT MIN(id) AS lo, MAX(id) AS hi FROM saved_words"
    ).fetchone()
    if bounds["lo"] is None:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, '1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("_migration_review_counters_done",),
        )
        return
    for start in range(int(bounds["lo"]), int(bounds["hi"]) + 1, _BACKFILL_BATCH):
        conn.execute(
            "UPDATE saved_words SET total_reviews = COALESCE("
            "(SELECT COUNT(*) FROM review_events "
            "WHERE review_events.word_id = saved_words.id "
            "AND review_events.user_id = saved_words.user_id), 0), "
            "lapses = COALESCE("
            "(SELECT COUNT(*) FROM review_events "
            "WHERE review_events.word_id = saved_words.id "
            "AND review_events.user_id = saved_words.user_id "
            f"AND {lapse_pred}), 0) "
            "WHERE saved_words.id >= ? AND saved_words.id < ?",
            (start, start + _BACKFILL_BATCH),
        )
        conn.commit()
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, '1') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("_migration_review_counters_done",),
    )


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _require_daily_cards_migrated(conn: sqlite3.Connection) -> None:
    """Refuse destructive daily-table cleanup on an unmigrated database."""
    tables = _table_names(conn)
    if not (_LEGACY_DAILY_TABLES & tables):
        return
    if "settings" not in tables:
        raise RuntimeError(
            "Refusing to drop legacy daily tables: "
            "settings.fsrs_migration_done=1 is missing."
        )
    migrated = conn.execute(
        "SELECT value FROM settings WHERE key='fsrs_migration_done'"
    ).fetchone()
    if not migrated or migrated["value"] != "1":
        raise RuntimeError(
            "Refusing to drop legacy daily tables: "
            "settings.fsrs_migration_done=1 is required."
        )


def _current_daily_count(asked_value, asked_date) -> int:
    today = _today().isoformat()
    if asked_date != today:
        return 0
    return asked_value or 0


def _can_consume_daily_count(
    asked_value,
    asked_date,
    daily_limit: int,
    *,
    bypass_limits: bool = False,
) -> bool:
    if bypass_limits or daily_limit < 0:
        return True
    return _current_daily_count(asked_value, asked_date) < daily_limit


def _check_test_mode_guard(path: str) -> None:
    """Refuse to open the production DB while the test suite is running.

    Every database operation funnels through get_conn(), so one guard here
    protects the real database from any test that forgets to override
    db.DB_PATH. HAMZABAN_TEST_MODE is set by tests/__init__.py and CI.

    P0.1 kill-switch: when the guard fires it aborts *before* any filesystem or
    database operation, and reports worker id, PID, resolved path and the
    offending test so a CI failure is immediately actionable.
    """
    if os.environ.get("HAMZABAN_TEST_MODE") == "1":
        from config import DB_PATH as _config_db_path
        _production_path = os.environ.get(
            "HAMZABAN_PRODUCTION_DB_PATH", _config_db_path
        )
        if os.path.abspath(path) == os.path.abspath(_production_path):
            worker = os.environ.get("PYTEST_XDIST_WORKER", "local")
            current_test = os.environ.get("HAMZABAN_CURRENT_TEST", "<unknown>")
            raise RuntimeError(
                "KILL-SWITCH: test mode refuses to touch the production "
                f"database. worker={worker} pid={os.getpid()} "
                f"resolved_path={os.path.abspath(path)!r} test={current_test!r}"
            )


# A 32-bit marker stamped into the header of every test database via
# ``PRAGMA application_id`` (R1). Destructive operations (restore, replace)
# verify both the path *and* this database identity in test mode, so an
# accidentally-derived or unmarked database can never be overwritten.
_TEST_APP_ID = 0x48414D5A  # "HAMZ"


def _test_mode_on() -> bool:
    return os.environ.get("HAMZABAN_TEST_MODE") == "1"


def _set_test_db_marker(conn) -> None:
    """Stamp the active connection's database as a test database (test mode only).

    Stamped at the end of a successful init_db so the value is committed with
    the schema. Never applied outside test mode, so production databases keep
    their default application_id and production admin restore is unaffected.
    """
    if _test_mode_on():
        conn.execute(f"PRAGMA application_id={_TEST_APP_ID}")


def _db_application_id(path: str) -> int | None:
    """Return the SQLite application_id of an existing database, or None.

    Returns:
        int: application_id value (``_TEST_APP_ID`` for a marked test DB,
             ``0`` for a genuinely unmarked DB).
        None: identity unknown — probe failure, non-regular path, or
              uncertain WAL state.

    Opens strictly read-only so the main database file itself is never
    modified. Uses Path.as_uri() for correct Windows-safe URI construction.
    Reads WAL-visible state (?mode=ro) so a non-checkpointed marker is not
    missed. No immutable fallback is used — uncertain WAL state fails closed.
    """
    try:
        uri = Path(os.path.abspath(path)).as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            row = conn.execute("PRAGMA application_id").fetchone()
            return int(row[0]) if row else None
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return None


def _guard_destructive_op(path: str) -> None:
    """Path + identity safety gate for destructive DB operations (R1).

    Distinguishes three states explicitly:
        MARKED_TEST_DB   (application_id == _TEST_APP_ID) -> allowed
        UNMARKED_DB      (application_id != _TEST_APP_ID) -> refuse
        IDENTITY_UNKNOWN (probe returns None)              -> refuse

    Never treats a probe failure as proof of unmarked, and never allows
    an uncertain identity to pass. Never enforced outside test mode so
    production admin restore keeps working.
    """
    _check_test_mode_guard(path)
    if _test_mode_on() and os.path.exists(path):
        # Only probe regular files; non-regular paths are UNKNOWN.
        app_id = _db_application_id(path) if os.path.isfile(path) else None
        if app_id is None:
            raise RuntimeError(
                "Test mode refuses a destructive operation — database identity "
                f"is UNKNOWN (probe failed): {path!r}."
            )
        if app_id != _TEST_APP_ID:
            raise RuntimeError(
                "Test mode refuses a destructive operation on a non-test "
                f"database: {path!r} (application_id={app_id!r})."
            )


# How long a writer waits for a busy database before raising "database is
# locked" (milliseconds). Matches the PRAGMA and the sqlite3.connect timeout.
# Trade-off (Kilo #477): 25s + asyncio.to_thread on the bounded default executor
# (min(32, cpu+4) workers) means a burst of contended writes can hold pool
# slots up to 25s; keep DB ops short (no long transaction across await) and
# consider a dedicated DB executor if contention grows (deferred to A-track).
# Contract lock 2026-09-05 (consultant): 10s→25s with BEGIN IMMEDIATE to bring
# "database is locked" risk near-zero under concurrent load.
_DB_BUSY_TIMEOUT = 25000


class _MaintenanceGate:
    """Shared/exclusive gate for DB access (locked contract A2-1-6).

    Normal reads/writes take a *shared* hold so they run concurrently; entering
    maintenance / backup / restore takes an *exclusive* hold that waits for all
    active connections and blocks new ones. The owning thread may re-enter
    shared inside its own exclusive hold (reentrant writer), so restore can call
    get_conn/init_db without deadlocking.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0
        self._writer_thread: int | None = None
        # Set while an exclusive writer is waiting, so new shared readers stop
        # arriving and the writer cannot starve under sustained read traffic.
        self._writer_waiting = False

    @contextmanager
    def shared(self):
        tid = threading.get_ident()
        reentrant = False
        with self._cond:
            if tid == self._writer_thread:
                reentrant = True
            else:
                while self._writer_thread is not None or self._writer_waiting:
                    self._cond.wait()
                self._readers += 1
        if reentrant:
            yield
            return
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @contextmanager
    def exclusive(self):
        tid = threading.get_ident()
        with self._cond:
            if tid == self._writer_thread:
                # Reentrant exclusive from the owning thread: yield directly so
                # a nested maintenance()/export()/import() cannot self-deadlock.
                reentrant = True
            else:
                reentrant = False
                self._writer_waiting = True
                try:
                    while self._writer_thread is not None or self._readers > 0:
                        self._cond.wait()
                    self._writer_thread = tid
                finally:
                    self._writer_waiting = False
        if reentrant:
            yield
            return
        try:
            yield
        finally:
            with self._cond:
                self._writer_thread = None
                self._cond.notify_all()

    def is_exclusive(self) -> bool:
        with self._cond:
            return self._writer_thread is not None


_DB_GATE = _MaintenanceGate()


@contextmanager
def maintenance():
    """Exclusive access: blocks all normal DB operations until the block exits.

    Used for maintenance mode and around backup/restore so they never race an
    active connection. Nested normal access from the owning thread is allowed.
    """
    with _DB_GATE.exclusive():
        yield


def is_maintenance() -> bool:
    """True while maintenance/exclusive access is active."""
    return _DB_GATE.is_exclusive()


@contextmanager
def get_conn(path: str | None = None):
    # Read the path live from services.db (where tests set db.DB_PATH) instead
    # of the import-time copy below, so test DB isolation is actually honored.
    if path is None:
        from services.db import DB_PATH as _active_db_path
    else:
        _active_db_path = path
    _check_test_mode_guard(_active_db_path)
    with _DB_GATE.shared():
        # sqlite3.connect(timeout=...) is in SECONDS; busy_timeout PRAGMA is in
        # MILLISECONDS. Keep both at _DB_BUSY_TIMEOUT (25000 ms == 25 s) so they
        # agree and a busy write never hangs far beyond the intended wait.
        conn = sqlite3.connect(_active_db_path, timeout=_DB_BUSY_TIMEOUT / 1000)
        # WAL lets readers and writers proceed concurrently; busy_timeout makes
        # a contending writer wait instead of failing with "database is locked".
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={_DB_BUSY_TIMEOUT}")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


@contextmanager
def transaction(path: str | None = None):
    """Single atomicity seam: immediate-transaction write context.

    Wraps ``get_conn`` + ``BEGIN IMMEDIATE`` and commits on clean exit or rolls
    back on any exception. Callers never manage commit/rollback themselves —
    this is the one place atomic-write policy lives. Use it for every write
    that may contend (quota reservations, delivery queue, saved words, plans).
    """
    with get_conn(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def is_missing_table_error(exc: BaseException) -> bool:
    """True for a missing-table OperationalError (pre-migration DB).

    Single source for the fail-soft read policy: only this case returns a
    silent fallback; every other error must be logged before falling back so
    dashboards never silently show wrong totals.
    """
    return isinstance(exc, sqlite3.OperationalError) and "no such table" in str(exc)


def init_db(path: str | None = None):
    if path is None:
        from services.db import DB_PATH as _active_path
    else:
        _active_path = path
    # R1/P0.1: abort before any schema work if the target is production.
    _check_test_mode_guard(_active_path)
    with get_conn(path) as conn:
        _require_daily_cards_migrated(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                target_lang TEXT,
                goal TEXT,
                level TEXT NOT NULL DEFAULT 'beginner',
                plan TEXT DEFAULT 'free',
                streak INTEGER DEFAULT 0,
                last_active_date TEXT,
                words_asked_today INTEGER DEFAULT 0,
                words_asked_date TEXT,
                grammar_tips_asked_today INTEGER DEFAULT 0,
                grammar_tips_asked_date TEXT,
                presentation_preference TEXT,
                display_toggles TEXT,
                display_toggles_forced TEXT,
                first_exposure_mode TEXT,
                review_mode TEXT,
                onboarded INTEGER DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS saved_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                word TEXT,
                lang TEXT,
                normalized_word TEXT,
                card_data TEXT,
                next_review TEXT,
                review_status TEXT DEFAULT 'idle',
                review_requested_at TEXT,
                added_at TEXT,
                first_exposure_done INTEGER DEFAULT 0,
                stability REAL DEFAULT 0.0,
                difficulty REAL DEFAULT 5.0,
                entry_source TEXT DEFAULT 'manual',
                last_review_at TEXT,
                next_review_at TEXT,
                total_reviews INTEGER NOT NULL DEFAULT 0,
                lapses INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS query_results (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                query_text TEXT NOT NULL,
                word TEXT NOT NULL,
                lang TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                saved_at TEXT,
                saved_word_id INTEGER
            );
            CREATE INDEX IF NOT EXISTS query_results_user_lang_text_idx
                ON query_results(user_id, lang, query_text);
            CREATE INDEX IF NOT EXISTS query_results_user_lang_word_idx
                ON query_results(user_id, lang, word);
            CREATE TABLE IF NOT EXISTS grammar_tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tip_date TEXT NOT NULL,
                title TEXT NOT NULL,
                lang TEXT NOT NULL,
                goal TEXT NOT NULL,
                level TEXT NOT NULL,
                tip_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS llm_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                request_date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                plan TEXT NOT NULL,
                request_kind TEXT NOT NULL,
                model TEXT NOT NULL,
                outcome TEXT NOT NULL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                input_cost_usd_per_million REAL NOT NULL,
                output_cost_usd_per_million REAL NOT NULL,
                usd_to_toman_rate REAL NOT NULL,
                cost_usd REAL NOT NULL,
                cost_toman REAL NOT NULL,
                latency_ms INTEGER,
                error_class TEXT,
                error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS review_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                revealed_before_answer INTEGER NOT NULL DEFAULT 0,
                outcome TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS preset_hourly_usage (
                preset_name TEXT NOT NULL,
                hour_bucket TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                token_count INTEGER DEFAULT 0,
                PRIMARY KEY (preset_name, hour_bucket)
            );
            CREATE TABLE IF NOT EXISTS llm_daily_rollup (
                request_date TEXT PRIMARY KEY,
                request_count INTEGER NOT NULL DEFAULT 0,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0,
                cost_toman REAL NOT NULL DEFAULT 0,
                input_cost_usd REAL NOT NULL DEFAULT 0,
                output_cost_usd REAL NOT NULL DEFAULT 0,
                input_cost_toman REAL NOT NULL DEFAULT 0,
                output_cost_toman REAL NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                billed_failure_count INTEGER NOT NULL DEFAULT 0,
                zero_cost_failure_count INTEGER NOT NULL DEFAULT 0,
                billed_failure_cost_usd REAL NOT NULL DEFAULT 0,
                billed_failure_cost_toman REAL NOT NULL DEFAULT 0,
                latency_sum_ms INTEGER NOT NULL DEFAULT 0,
                latency_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS config_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_type TEXT,
                preset_name TEXT,
                prompt TEXT,
                result TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS study_sessions (
                user_id INTEGER PRIMARY KEY,
                session_date TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_grade_ledger (
                user_id INTEGER NOT NULL,
                word_id INTEGER NOT NULL,
                activity_type TEXT NOT NULL,
                graded_at TEXT NOT NULL,
                PRIMARY KEY (user_id, word_id, activity_type)
            );
            CREATE TABLE IF NOT EXISTS session_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                report_json TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_session_reports_user_created
                ON session_reports(user_id, created_at);
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "level" not in columns:
            conn.execute(
                f"ALTER TABLE users ADD COLUMN level TEXT NOT NULL DEFAULT "
                f"'{DEFAULT_LEVEL.replace(chr(39), chr(39) * 2)}'",
            )
        user_columns = {
            "grammar_tips_asked_today": "INTEGER DEFAULT 0",
            "grammar_tips_asked_date": "TEXT",
            "presentation_preference": "TEXT",
            "display_toggles": "TEXT",
            "display_toggles_forced": "TEXT",
            "first_exposure_mode": "TEXT",
            "review_mode": "TEXT",
        }
        for name, definition in user_columns.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        if "bot_blocked" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN bot_blocked INTEGER DEFAULT 0")
        if "full_name" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
        conn.commit()
        saved_word_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(saved_words)").fetchall()
        }
        if "normalized_word" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN normalized_word TEXT")
        if "card_data" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN card_data TEXT")
        if "review_status" not in saved_word_columns:
            conn.execute(
                "ALTER TABLE saved_words ADD COLUMN review_status TEXT DEFAULT 'idle'"
            )
        if "review_requested_at" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN review_requested_at TEXT")
        if "retry_at" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN retry_at TEXT")
        if "srs_retry_attempts" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN srs_retry_attempts INTEGER NOT NULL DEFAULT 0")
        if "first_exposure_done" not in saved_word_columns:
            conn.execute(
                "ALTER TABLE saved_words ADD COLUMN first_exposure_done INTEGER DEFAULT 0"
            )
        if "stability" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN stability REAL DEFAULT 0.0")
        if "difficulty" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN difficulty REAL DEFAULT 5.0")
        if "entry_source" not in saved_word_columns:
            conn.execute(
                "ALTER TABLE saved_words ADD COLUMN entry_source TEXT DEFAULT 'manual'"
            )
        added_timestamp_columns = False
        if "last_review_at" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN last_review_at TEXT")
            added_timestamp_columns = True
        if "next_review_at" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN next_review_at TEXT")
            added_timestamp_columns = True
        if added_timestamp_columns and "next_review" in saved_word_columns:
            # A row marked first_exposure_done=1 with a NULL last_review_at is
            # inconsistent (exposed without a grade time). Reset it to a
            # deterministic first-exposure state and clear transient review
            # fields, without fabricating a review timestamp. Runs only when
            # the timestamp columns are introduced (idempotent on re-init).
            conn.execute(
                """
                UPDATE saved_words
                SET first_exposure_done = 0,
                    stability = 0.0,
                    difficulty = 5.0,
                    last_review_at = NULL,
                    next_review_at = NULL,
                    next_review = ?,
                    review_status = 'idle',
                    review_requested_at = NULL,
                    retry_at = NULL,
                    srs_retry_attempts = 0
                WHERE COALESCE(first_exposure_done, 0) = 1
                  AND last_review_at IS NULL
                """,
                (_today().isoformat(),),
            )
        if "total_reviews" not in saved_word_columns:
            conn.execute(
                "ALTER TABLE saved_words ADD COLUMN total_reviews INTEGER NOT NULL DEFAULT 0"
            )
        if "lapses" not in saved_word_columns:
            conn.execute(
                "ALTER TABLE saved_words ADD COLUMN lapses INTEGER NOT NULL DEFAULT 0"
            )
        review_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(review_events)").fetchall()
        }
        for col, col_def in (
            ("grade", "INTEGER"),
            ("activity_type", "TEXT"),
            ("grade_source", "TEXT"),
            ("raw_signal", "TEXT"),
            ("response_time_ms", "INTEGER"),
        ):
            if col not in review_columns:
                conn.execute(f"ALTER TABLE review_events ADD COLUMN {col} {col_def}")
        _backfill_review_counters(conn)
        conn.execute(
            "UPDATE saved_words SET normalized_word=lower(trim(word)) "
            "WHERE normalized_word IS NULL"
        )
        conn.execute(
            "UPDATE saved_words SET review_status='idle' "
            "WHERE review_status IS NULL"
        )
        conn.execute(
            "DELETE FROM saved_words WHERE id NOT IN ("
            "SELECT MIN(id) FROM saved_words "
            "GROUP BY user_id, lang, normalized_word)"
        )
        _backfill_saved_word_normalization(conn)
        _backfill_query_results_normalization(conn)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS saved_words_user_lang_word "
            "ON saved_words(user_id, lang, normalized_word)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS saved_words_review_status_at_idx "
            "ON saved_words(review_status, review_requested_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS saved_words_due_idx "
            "ON saved_words(user_id, lang, next_review_at)"
        )
        # F3: filter/order index for recent_events_for_words(user_id, word_id)
        # ORDER BY word_id, created_at DESC, id DESC. Matches its WHERE
        # (user_id=? AND word_id IN (...)) plus created_at ordering, so the
        # per-word newest-first scan is index-backed on fresh and upgraded DBs.
        # Not a covering index: the query also SELECTs grade/activity_type and
        # uses the id DESC tiebreaker, which are resolved from the row/sort step.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS review_events_user_word_created_idx "
            "ON review_events(user_id, word_id, created_at)"
        )
        defaults = {
            "llm_input_cost_usd_per_million": str(LLM_INPUT_COST_USD_PER_MILLION),
            "llm_output_cost_usd_per_million": str(LLM_OUTPUT_COST_USD_PER_MILLION),
            "usd_to_toman_rate": str(USD_TO_TOMAN_RATE),
            "display_toggle_defaults": json.dumps(DISPLAY_TOGGLE_DEFAULTS),
            "first_exposure_mode": "staged",
            "review_mode": "staged",
            "first_exposure_mode_gate": "premium",
            "review_mode_gate": "premium",
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        # Retire the audio-pronunciation (tts_access) and admin IPA toggle state.
        # Both features are always-on (#390); any stored toggle value is stale and
        # must not linger in the settings table or display_toggle_defaults.
        conn.execute("DELETE FROM settings WHERE key = 'tts_access'")
        dtd_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'display_toggle_defaults'"
        ).fetchone()
        if dtd_row:
            try:
                dtd = json.loads(dtd_row["value"])
            except (TypeError, ValueError):
                dtd = {}
            if isinstance(dtd, dict) and "phonetic" in dtd:
                dtd.pop("phonetic", None)
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    ("display_toggle_defaults", json.dumps(dtd)),
                )
        for tbl, col, col_def in (
            ("grammar_tips", "provenance", "TEXT DEFAULT ''"),
        ):
            existing = {
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({tbl})").fetchall()
            }
            if col not in existing:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}")

        # Initialize ai_presets table with built-in presets
        _init_ai_presets_table(conn)

        # Initialize config_tests table for audit logging
        _init_config_tests_table(conn)

        # Initialize plans table with default plan specs (admin-editable)
        _init_plans_table(conn)

        # Initialize fallback-related settings
        fallback_defaults = {
            "ai_fallback_active": "false",
            "ai_fallback_since": "",
            "ai_consecutive_failures": "0",
            "auto_backup_enabled": "true",
        }
        for k, v in fallback_defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        existing_primary = conn.execute("SELECT value FROM settings WHERE key='ai_primary_preset'").fetchone()
        if not existing_primary:
            first = conn.execute(
                "SELECT name FROM ai_presets WHERE enabled=1 AND is_emergency=0 ORDER BY priority ASC, name ASC LIMIT 1"
            ).fetchone()
            if first:
                conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('ai_primary_preset', ?)", (first["name"],))
        existing_fallback = conn.execute("SELECT value FROM settings WHERE key='ai_fallback_preset'").fetchone()
        if not existing_fallback:
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('ai_fallback_preset', '')")

        llm_request_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(llm_requests)").fetchall()
        }
        if llm_request_columns:
            for index_sql in (
                "CREATE INDEX IF NOT EXISTS llm_requests_request_date_idx ON llm_requests(request_date)",
                "CREATE INDEX IF NOT EXISTS llm_requests_user_id_idx ON llm_requests(user_id)",
                "CREATE INDEX IF NOT EXISTS llm_requests_plan_idx ON llm_requests(plan)",
                "CREATE INDEX IF NOT EXISTS llm_requests_model_idx ON llm_requests(model)",
                "CREATE INDEX IF NOT EXISTS llm_requests_kind_idx ON llm_requests(request_kind)",
                "CREATE INDEX IF NOT EXISTS llm_requests_outcome_idx ON llm_requests(outcome)",
            ):
                conn.execute(index_sql)
        conn.execute(
            "DELETE FROM query_results WHERE expires_at<=?",
            (_utc_now().isoformat(),),
        )

        # Phase 5 (R3): encrypt any API keys still at rest as plaintext or
        # "$ENV" references (see _encrypt_key_columns). Runs before the
        # destructive cleanup commit below.
        _encrypt_key_columns(conn)

        # Commit all additive migrations before the destructive cleanup so a
        # failure in DROP COLUMN/TABLE rolls back the destructive transaction.
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        saved_word_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(saved_words)").fetchall()
        }
        if "interval_idx" in saved_word_columns:
            conn.execute("ALTER TABLE saved_words DROP COLUMN interval_idx")
        # Q-26: retire dead optional_daily_limit and auto-delivery window columns
        # (single source is plans table; no live code reads these)
        user_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        for col in (
            "optional_daily_limit",
            "preferred_delivery_minute",
            "active_window_start_minute",
            "active_window_end_minute",
        ):
            if col in user_cols:
                try:
                    conn.execute(f"ALTER TABLE users DROP COLUMN {col}")
                except sqlite3.OperationalError as e:
                    logging.getLogger(__name__).warning(
                        "DROP COLUMN %s failed (likely older SQLite): %s", col, e
                    )
        for table in sorted(_LEGACY_DAILY_TABLES):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        # R1: stamp the database as a test database (test mode only) so
        # destructive operations can verify identity, not just path.
        _set_test_db_marker(conn)
        conn.commit()


def _init_ai_presets_table(conn):
    """Create ai_presets table and run migrations.

    Does NOT auto-seed or modify existing presets — all preset management is
    manual through the AI Preset Manager tool or the admin panel. A fresh
    database starts with zero presets.
    """
    conn.execute(_ai_presets_create_sql(if_not_exists=True))
    # Migrate missing columns for existing databases
    preset_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(ai_presets)").fetchall()
    }
    for col_name, col_def in {
        "api_key": "TEXT NOT NULL DEFAULT ''",
        "max_tpm": "INTEGER DEFAULT 0",
        "max_daily_req": "INTEGER DEFAULT 0",
        "priority": "INTEGER DEFAULT 0",
        "enabled": "INTEGER DEFAULT 1",
        "is_emergency": "INTEGER DEFAULT 0",
        "input_cost_per_million": "REAL",
        "output_cost_per_million": "REAL",
        "group_label": "TEXT DEFAULT ''",
        "in_fallback_chain": "INTEGER DEFAULT 1",
        "reasoning_effort": "TEXT DEFAULT 'none'",
    }.items():
        if col_name not in preset_columns:
            conn.execute(f"ALTER TABLE ai_presets ADD COLUMN {col_name} {col_def}")
    # Migrate preset_name column on llm_requests
    llm_request_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(llm_requests)").fetchall()
    }
    if "preset_name" not in llm_request_columns:
        conn.execute("ALTER TABLE llm_requests ADD COLUMN preset_name TEXT")
    # Create preset_hourly_usage table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_hourly_usage (
            preset_name TEXT NOT NULL,
            hour_bucket TEXT NOT NULL,
            request_count INTEGER DEFAULT 0,
            token_count INTEGER DEFAULT 0,
            PRIMARY KEY (preset_name, hour_bucket)
        );
        """
    )
    # Additive optional group-key table. A group shares one default API key;
    # a preset uses its own key if set, else its group's key. Empty by default.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_groups (
            group_label TEXT PRIMARY KEY,
            api_key TEXT NOT NULL DEFAULT ''
        );
        """
    )
    # Phase 4 migration: drop the now-obsolete is_custom column. Existing DBs
    # (created before Phase 4, or reintroduced via an admin restore of a
    # pre-Phase-4 backup) may still have it; a fresh DB never does. Because
    # SQLite cannot always DROP COLUMN portably, rebuild the table without the
    # column when it is present. All rows are preserved (they become ordinary
    # presets). We rebuild with the full new column set and copy every remaining
    # column by name so migrated columns (costs, group_label, in_fallback_chain,
    # etc.) are never lost.
    _cols = {row["name"] for row in conn.execute("PRAGMA table_info(ai_presets)").fetchall()}
    if "is_custom" in _cols:
        _keep = [c for c in _cols if c != "is_custom"]
        _cols_sql = ", ".join(_keep)
        # api_key is NOT NULL in the canonical schema; coerce any legacy NULL to
        # '' so the INSERT can never raise IntegrityError and block startup.
        _sel_sql = ", ".join(
            "COALESCE(api_key, '')" if c == "api_key" else c for c in _keep
        )
        conn.execute("ALTER TABLE ai_presets RENAME TO ai_presets_old")
        conn.execute(_ai_presets_create_sql())
        conn.execute(
            f"INSERT INTO ai_presets({_cols_sql}) SELECT {_sel_sql} FROM ai_presets_old"
        )
        conn.execute("DROP TABLE ai_presets_old")
    # Data fix (R3A): historical databases seeded before the "$ENV" convention
    # stored the HpOF env-var name bare (e.g. "HpOF_API_KEY" without the "$"
    # prefix), so resolve_api_key treated it as a literal key and the provider
    # rejected it. Prefix "$" idempotently — only for these known HP presets
    # and only when the stored value is exactly the bare env name (never
    # touching custom/ELI/GAPGPT keys or real literal key values). Kept as the
    # repair path for never-migrated DBs and admin restores of pre-R3A backups.
    conn.execute(
        "UPDATE ai_presets SET api_key = '$' || api_key "
        "WHERE name IN ('g3_6_f_HP', 'g3_5_f_HP', 'g3_5_FL_HP', 'g3_1_FL_HP') "
        "AND api_key = 'HpOF_API_KEY'"
    )
    conn.commit()


def _encrypt_key_columns(conn):
    """Phase 5 (R3): encrypt API keys at rest across all storage sites.

    Converts any still-plaintext or ``$ENV`` reference stored in
    ``ai_presets.api_key`` and ``preset_groups.api_key``
    into Fernet ciphertext. Idempotent: a value that already decrypts under the
    current master key is left untouched (so an unchanged re-run, a plaintext
    value, or a token from a *previous* key after rotation are all handled by
    ``encrypt_for_storage``). A ``$ENV`` reference is resolved to the real
    environment value before encryption; if the env var is unset the stored
    value becomes empty (R3). Fail-closed: when no master key is configured we
    MUST NOT destroy existing values, so the migration is skipped entirely and
    re-runs once a key is added.
    """
    from services.db.key_crypto import encrypt_for_storage, _fernet, _resolve_env

    if _fernet() is None:
        return

    def _encrypt(raw: str) -> str:
        if not raw:
            return ""
        env = _resolve_env(raw)
        if env is not None:
            return encrypt_for_storage(env)
        return encrypt_for_storage(raw)

    for row in conn.execute("SELECT name, api_key FROM ai_presets").fetchall():
        enc = _encrypt(row["api_key"] or "")
        if enc != (row["api_key"] or ""):
            conn.execute(
                "UPDATE ai_presets SET api_key=? WHERE name=?", (enc, row["name"])
            )
    for row in conn.execute(
        "SELECT group_label, api_key FROM preset_groups"
    ).fetchall():
        enc = _encrypt(row["api_key"] or "")
        if enc != (row["api_key"] or ""):
            conn.execute(
                "UPDATE preset_groups SET api_key=? WHERE group_label=?",
                (enc, row["group_label"]),
            )


def _init_config_tests_table(conn):
    """Create config_tests table for audit logging."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS config_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_type TEXT,
            preset_name TEXT,
            prompt TEXT,
            result TEXT,
            created_at TEXT
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS config_tests_created_at_idx ON config_tests(created_at)"
    )


def _init_plans_table(conn):
    """Create the administrative plans table and seed default plans.

    Plan specs are admin-editable; the seed only runs when the table is empty
    (fresh database / upgrade), so admin edits persist across restarts.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            name TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            price INTEGER NOT NULL DEFAULT 0,
            query_quota INTEGER NOT NULL DEFAULT 0,
            max_sessions INTEGER NOT NULL DEFAULT 1,
            cards_per_session INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            first_exposure_mode TEXT,
            review_mode TEXT
        );
        """
    )
    plan_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(plans)").fetchall()
    }
    for col in ("first_exposure_mode", "review_mode"):
        if col not in plan_columns:
            conn.execute(f"ALTER TABLE plans ADD COLUMN {col} TEXT")
    count = conn.execute("SELECT COUNT(*) AS c FROM plans").fetchone()["c"]
    if count == 0:
        from services.db.plans import DEFAULT_PLANS
        for name, (display_name, price, query_quota, max_sessions,
                   cards_per_session, sort_order) in DEFAULT_PLANS.items():
            conn.execute(
                "INSERT INTO plans("
                "name, display_name, price, query_quota, max_sessions, "
                "cards_per_session, is_active, sort_order"
                ") VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    name, display_name, price, query_quota, max_sessions,
                    cards_per_session, sort_order,
                ),
            )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS plans_sort_idx ON plans(sort_order)"
    )
    conn.commit()
