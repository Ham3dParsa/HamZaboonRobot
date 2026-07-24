import os
import shutil
import tempfile
from datetime import datetime
from services import db


_SESSION_SNAPSHOT_PATH = None


def create_db_snapshot():
    global _SESSION_SNAPSHOT_PATH
    if _SESSION_SNAPSHOT_PATH is not None:
        return _SESSION_SNAPSHOT_PATH
    if not os.path.isfile(db.DB_PATH):
        _SESSION_SNAPSHOT_PATH = None
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _SESSION_SNAPSHOT_PATH = os.path.join(
        tempfile.gettempdir(), f"hamzaban_test_snapshot_{ts}.sqlite"
    )
    shutil.copy2(db.DB_PATH, _SESSION_SNAPSHOT_PATH)
    return _SESSION_SNAPSHOT_PATH


def fresh_db_from_snapshot():
    snapshot = create_db_snapshot()
    tmpdir = tempfile.TemporaryDirectory()
    if snapshot is not None:
        dest = os.path.join(tmpdir.name, "test.sqlite")
        shutil.copy2(snapshot, dest)
    else:
        dest = os.path.join(tmpdir.name, "test.sqlite")
        db.DB_PATH = dest
        db.init_db()
    return tmpdir, dest


def cleanup_session():
    global _SESSION_SNAPSHOT_PATH
    if _SESSION_SNAPSHOT_PATH is not None and os.path.isfile(_SESSION_SNAPSHOT_PATH):
        os.remove(_SESSION_SNAPSHOT_PATH)
    _SESSION_SNAPSHOT_PATH = None
