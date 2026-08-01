"""Test-suite bootstrap: force DB safety guards on and prove zero damage.

- Sets HAMZABAN_TEST_MODE=1 so schema.get_conn() refuses to open the
  production database during any test run (see services/db/schema.py).
- Records the production database's checksum before the suite and verifies
  at process exit that it is byte-identical afterwards. Skipped when no
  production database exists (e.g., fresh CI checkouts).
"""

import atexit
import hashlib
import os

from config import DB_PATH as _PRODUCTION_DB_PATH

os.environ["HAMZABAN_TEST_MODE"] = "1"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


_PROD_EXISTS_BEFORE = os.path.isfile(_PRODUCTION_DB_PATH)
_PROD_HASH_BEFORE = _sha256(_PRODUCTION_DB_PATH) if _PROD_EXISTS_BEFORE else None


@atexit.register
def _verify_production_db_untouched():
    exists_after = os.path.isfile(_PRODUCTION_DB_PATH)
    if not _PROD_EXISTS_BEFORE:
        if exists_after:
            raise AssertionError(
                "A test created the production database during the test run. "
                "This must never happen; check test DB_PATH isolation."
            )
        return
    if not exists_after or _sha256(_PRODUCTION_DB_PATH) != _PROD_HASH_BEFORE:
        raise AssertionError(
            "Production database was modified during the test run. "
            "Some test bypassed db.DB_PATH isolation."
        )
