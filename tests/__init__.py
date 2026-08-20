"""Test-suite bootstrap: force DB safety guards on and prove zero damage.

- Sets HAMZABAN_TEST_MODE=1 so schema.get_conn() refuses to open the
  production database during any test run (see services/db/schema.py).
- Captures the real production DB path once (in the controller process) into
  HAMZABAN_PRODUCTION_DB_PATH and never overwrites it, so every spawned process
  (xdist workers + subprocesses) still knows which path is production even
  though its active DB_PATH is a throwaway.
- Points the active DB_PATH of every spawned process at a unique throwaway DB,
  so a stray raw connect outside the guarded get_conn() seam can never create
  the real production database at the repo root.
- P0.2: marks the production database file read-only for the duration of the
  suite (whenever possible), so accidental writes/replacements/restores are
  blocked by the operating system in addition to the application guard.
- P0.3: records the production database's checksum, size, modification time and
  file identity before the suite and verifies all four at process exit that they
  are unchanged. Skipped when no production database exists (e.g., fresh CI
  checkouts). A violation exits non-zero so CI fails hard instead of degrading
  to an ignored atexit warning.
"""

import atexit
import hashlib
import os
import stat
import sys
import tempfile

os.environ["HAMZABAN_TEST_MODE"] = "1"

# The real production path, captured from the environment BEFORE any DB_PATH
# override. setdefault makes the controller the single source: workers inherit
# the value and never overwrite it, so every process protects the real DB.
os.environ.setdefault(
    "HAMZABAN_PRODUCTION_DB_PATH", os.getenv("DB_PATH", "hamzaban.db")
)
_PRODUCTION_DB_PATH = os.environ["HAMZABAN_PRODUCTION_DB_PATH"]

# Active DB_PATH for every spawned process (workers + subprocesses): a unique
# throwaway per process so a stray raw connect never touches the real DB.
_THROWAWAY_DB = os.path.join(
    tempfile.gettempdir(), f"hamzaban_test_{os.getpid()}.db"
)
os.environ["DB_PATH"] = _THROWAWAY_DB


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _cleanup_throwaway() -> None:
    try:
        os.remove(_THROWAWAY_DB)
    except OSError:
        pass


def _fail(message: str) -> None:
    print(f"DB-GUARD: {message}", file=sys.stderr)
    sys.stderr.flush()
    _cleanup_throwaway()
    os._exit(1)


# ---- P0.2: read-only protection --------------------------------------------
# Only the controller process (no PYTEST_XDIST_WORKER) marks and restores the
# production file. Workers must not chmod it: if a worker captured the
# read-only mode as its "original", its exit restore could leave the shared
# production DB permanently read-only. The controller is the single owner of
# the mode flip.
_IS_WORKER = os.environ.get("PYTEST_XDIST_WORKER") is not None
_READONLY_APPLIED = False
_ORIGINAL_PROD_MODE = None


def _apply_readonly() -> None:
    global _READONLY_APPLIED, _ORIGINAL_PROD_MODE
    if _IS_WORKER:
        return
    if not os.path.isfile(_PRODUCTION_DB_PATH):
        return
    try:
        st = os.stat(_PRODUCTION_DB_PATH)
        _ORIGINAL_PROD_MODE = stat.S_IMODE(st.st_mode)
        os.chmod(_PRODUCTION_DB_PATH, stat.S_IREAD)
        _READONLY_APPLIED = True
    except OSError:
        # "whenever possible" — if we cannot mark it read-only, the application
        # guard and snapshot verification still protect it.
        _READONLY_APPLIED = False


def _restore_readonly() -> None:
    if _READONLY_APPLIED and _ORIGINAL_PROD_MODE is not None:
        try:
            os.chmod(_PRODUCTION_DB_PATH, _ORIGINAL_PROD_MODE)
        except OSError:
            pass


# ---- P0.3: snapshot verification (hash, size, mtime, identity) -------------
_PROD_SNAPSHOT = None


def _snapshot_prod() -> dict:
    if not os.path.isfile(_PRODUCTION_DB_PATH):
        return None
    st = os.stat(_PRODUCTION_DB_PATH)
    return {
        "sha256": _sha256(_PRODUCTION_DB_PATH),
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "st_ino": st.st_ino,
        "st_dev": st.st_dev,
    }


_apply_readonly()
_PROD_SNAPSHOT = _snapshot_prod()


@atexit.register
def _verify_production_db_untouched():
    _cleanup_throwaway()
    if _PROD_SNAPSHOT is None:
        if os.path.isfile(_PRODUCTION_DB_PATH):
            _fail(
                "a test created the production database during the test run. "
                "This must never happen; check test DB_PATH isolation."
            )
        return
    _restore_readonly()
    if not os.path.isfile(_PRODUCTION_DB_PATH):
        _fail("production database was deleted during the test run.")
        return
    after = _snapshot_prod()
    for key in ("sha256", "size", "mtime_ns", "st_ino", "st_dev"):
        if after[key] != _PROD_SNAPSHOT[key]:
            _fail(
                "production database %s changed during the test run "
                "(before=%r after=%r). Some test bypassed db.DB_PATH "
                "isolation." % (key, _PROD_SNAPSHOT[key], after[key])
            )