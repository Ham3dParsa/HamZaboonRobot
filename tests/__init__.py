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
- Records the production database's checksum before the suite and verifies at
  process exit that it is byte-identical afterwards. Skipped when no production
  database exists (e.g., fresh CI checkouts). A violation exits non-zero so CI
  fails hard instead of degrading to an ignored atexit warning.
"""

import atexit
import hashlib
import os
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


_PROD_EXISTS_BEFORE = os.path.isfile(_PRODUCTION_DB_PATH)
_PROD_HASH_BEFORE = _sha256(_PRODUCTION_DB_PATH) if _PROD_EXISTS_BEFORE else None


@atexit.register
def _verify_production_db_untouched():
    _cleanup_throwaway()
    exists_after = os.path.isfile(_PRODUCTION_DB_PATH)
    if not _PROD_EXISTS_BEFORE:
        if exists_after:
            _fail(
                "a test created the production database during the test run. "
                "This must never happen; check test DB_PATH isolation."
            )
        return
    if not exists_after or _sha256(_PRODUCTION_DB_PATH) != _PROD_HASH_BEFORE:
        _fail(
            "production database was modified during the test run. "
            "Some test bypassed db.DB_PATH isolation."
        )