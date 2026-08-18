"""Test-suite bootstrap: force DB safety guards on and prove zero damage.

- Sets HAMZABAN_TEST_MODE=1 so schema.get_conn() refuses to open the
  production database during any test run (see services/db/schema.py).
- Points every subprocess spawned during tests at a unique throwaway DB path
  via DB_PATH, so a stray raw connect outside the guarded get_conn() seam can
  never create the real production database at the repo root.
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

from config import DB_PATH as _PRODUCTION_DB_PATH

os.environ["HAMZABAN_TEST_MODE"] = "1"

# Redirect subprocesses (which read DB_PATH from the environment at their own
# process import) to a unique throwaway path. Set AFTER importing config so the
# main test process keeps config.DB_PATH as the real production path; only
# subprocesses spawned from here inherit the temp override. Unique per PID so
# parallel -n workers never share one SQLite file.
os.environ["DB_PATH"] = os.path.join(
    tempfile.gettempdir(), f"hamzaban_test_{os.getpid()}.db"
)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fail(message: str) -> None:
    print(f"DB-GUARD: {message}", file=sys.stderr)
    sys.stderr.flush()
    os._exit(1)


_PROD_EXISTS_BEFORE = os.path.isfile(_PRODUCTION_DB_PATH)
_PROD_HASH_BEFORE = _sha256(_PRODUCTION_DB_PATH) if _PROD_EXISTS_BEFORE else None


@atexit.register
def _verify_production_db_untouched():
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
