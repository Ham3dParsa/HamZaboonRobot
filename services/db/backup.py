"""Database backup/restore leaves (verbatim split from services/db/__init__.py).

Owns snapshot export (``export_db_bytes``) and validated restore
(``import_db_bytes``) plus the storage-error helpers. The live ``DB_PATH`` is
read from the ``services.db`` facade at call time (same precedent as
``schema.get_conn``/``init_db``) so ``db.DB_PATH`` overrides keep working;
everything else comes from ``services.db.schema`` (never the facade at
module top level) per the leaf-import law.
"""

import logging
import os
import shutil
import sqlite3
import stat
import tempfile
from contextlib import closing

from services.db.schema import (
    get_conn,
    maintenance,
    init_db,
    _LEGACY_DAILY_TABLES,
    _check_test_mode_guard,
    _guard_destructive_op,
)

logger = logging.getLogger(__name__)


def _active_db_path() -> str:
    """Read the live path from the services.db facade (where tests set
    db.DB_PATH) instead of an import-time copy, so test DB isolation is
    actually honored — same precedent as schema.get_conn/init_db."""
    from services.db import DB_PATH as _path

    return _path
_RESTORE_CORE_TABLES = frozenset(
    {"users", "saved_words", "settings", "review_events", "llm_requests"}
)
# Stable SQLite primary result codes; Python 3.10 does not expose all of the
# corresponding sqlite3.SQLITE_* constants.
_STORAGE_SQLITE_CODES = frozenset(
    {
        7,   # SQLITE_NOMEM
        8,   # SQLITE_READONLY
        10,  # SQLITE_IOERR
        13,  # SQLITE_FULL
        14,  # SQLITE_CANTOPEN
    }
)


def _is_storage_error(exc: BaseException) -> bool:
    error_code = getattr(exc, "sqlite_errorcode", None)
    if error_code is not None and error_code & 0xFF in _STORAGE_SQLITE_CODES:
        return True
    return any(
        phrase in str(exc).lower()
        for phrase in ("disk is full", "i/o error", "readonly", "read-only")
    )


def export_db_bytes() -> bytes:
    db_path = _active_db_path()
    snapshot_fd, snapshot_path = tempfile.mkstemp(
        suffix=".sqlite",
        dir=os.path.dirname(os.path.abspath(db_path)),
    )
    os.close(snapshot_fd)
    try:
        # Exclusive hold: wait for active connections, block new ones, so the
        # snapshot reflects a stable DB (A2-1-6).
        with maintenance(), get_conn() as source, closing(sqlite3.connect(snapshot_path)) as target:
            source.backup(target)
        with open(snapshot_path, "rb") as snapshot_file:
            return snapshot_file.read()
    finally:
        try:
            if os.path.exists(snapshot_path):
                os.remove(snapshot_path)
        except OSError:
            logger.exception("Could not remove temporary database snapshot: %s", snapshot_path)


def import_db_bytes(data: bytes, backup_path: str | None = None) -> None:
    candidate_path = None
    reference_path = None
    db_path = _active_db_path()
    try:
        with maintenance():
            try:
                # MUST 1: validate target safety BEFORE any FS side effect.
                try:
                    _guard_destructive_op(db_path)
                except RuntimeError as exc:
                    raise ValueError(str(exc)) from exc
                candidate_fd, candidate_path = tempfile.mkstemp(
                    suffix=".sqlite",
                    dir=os.path.dirname(os.path.abspath(db_path)),
                )
                original_stat = os.stat(db_path)
                with os.fdopen(candidate_fd, "wb") as candidate_file:
                    candidate_file.write(data)
                with closing(sqlite3.connect(candidate_path)) as candidate_conn:
                    quick_check = candidate_conn.execute("PRAGMA quick_check").fetchone()
                    candidate_tables = {
                        row[0]
                        for row in candidate_conn.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                if not quick_check or quick_check[0] != "ok":
                    raise ValueError("فایل پشتیبان معتبر نیست.")
                if _LEGACY_DAILY_TABLES & candidate_tables:
                    raise ValueError(
                        "نسخه پشتیبان قدیمی است و قابل بازگردانی نیست."
                    )
                if not _RESTORE_CORE_TABLES.issubset(candidate_tables):
                    raise ValueError("فایل پشتیبان معتبر نیست.")
                init_db(candidate_path)
                reference_fd, reference_path = tempfile.mkstemp(
                    suffix=".sqlite",
                    dir=os.path.dirname(os.path.abspath(db_path)),
                )
                os.close(reference_fd)
                init_db(reference_path)
                with closing(sqlite3.connect(candidate_path)) as candidate_conn, closing(
                    sqlite3.connect(reference_path)
                ) as reference_conn:
                    required_tables = {
                        row[0]
                        for row in reference_conn.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                    candidate_tables = {
                        row[0]
                        for row in candidate_conn.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                    def _quoted_ident(name: str) -> str:
                        # Caller filters to required_tables ∩ candidate_tables, so
                        # injection is blocked by the intersection + quote-doubling.
                        return '"' + name.replace('"', '""') + '"'

                    missing_columns = {
                        table: {
                            row[1]
                            for row in reference_conn.execute(
                                f"PRAGMA table_info({_quoted_ident(table)})"
                            )
                        }
                        - {
                            row[1]
                            for row in candidate_conn.execute(
                                f"PRAGMA table_info({_quoted_ident(table)})"
                            )
                        }
                        for table in required_tables & candidate_tables
                    }
                if any(missing_columns.values()):
                    raise RuntimeError("incomplete schema")
            except ValueError:
                raise
            except (OSError, MemoryError) as exc:
                raise ValueError(
                    "فضای ذخیره‌سازی یا دسترسی فایل برای بازگردانی کافی نیست."
                ) from exc
            except Exception as exc:
                if _is_storage_error(exc):
                    raise ValueError(
                        "فضای ذخیره‌سازی یا دسترسی فایل برای بازگردانی کافی نیست."
                    ) from exc
                raise ValueError(
                    "نسخه پشتیبان با نسخه فعلی ربات سازگار نیست."
                ) from exc
            try:
                # Candidate must not be the production path. Target already
                # validated at the top of the operation; re-checking here
                # would be after mkstemp.
                try:
                    _check_test_mode_guard(candidate_path)
                except RuntimeError as exc:
                    raise ValueError(str(exc)) from exc
                os.chmod(candidate_path, stat.S_IMODE(original_stat.st_mode))
                if hasattr(os, "chown"):
                    try:
                        os.chown(candidate_path, original_stat.st_uid, original_stat.st_gid)
                    except PermissionError:
                        pass
                if backup_path:
                    shutil.copy2(db_path, backup_path)
                os.replace(candidate_path, db_path)
            except OSError as exc:
                raise ValueError(
                    "جایگزینی دیتابیس در حال حاضر ممکن نیست. دوباره تلاش کنید."
                ) from exc
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = f"{db_path}{suffix}"
                try:
                    if os.path.exists(sidecar):
                        os.remove(sidecar)
                except OSError:
                    logger.exception("Could not remove stale SQLite sidecar: %s", sidecar)
    finally:
        for path in (candidate_path, reference_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    logger.exception("Could not remove temporary restore file: %s", path)
