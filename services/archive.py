"""Archive backup service — deep module owner of backup caption/send/validation."""
import datetime
import io
import re
import logging
import asyncio
import subprocess

from telegram import InputFile

from config import ARCHIVE_CHAT_ID, APP_TZ
from services import db
from services.utils.helpers import _send_document_with_retry

logger = logging.getLogger(__name__)

_ARCHIVE_RE = re.compile(r"^-100\d{5,}$|^-\d{5,}$")


def validate_archive_chat_id(value: str) -> bool:
    if not value:
        return False
    return bool(_ARCHIVE_RE.match(value.strip()))


def resolved_archive_chat_id() -> int | None:
    raw = db.get_setting("archive_chat_id", "")
    if raw and raw.strip():
        raw = raw.strip()
        if validate_archive_chat_id(raw):
            try:
                return int(raw)
            except ValueError:
                return None
        # invalid stored value -> treat as disabled (do not fallback)
        return None
    # no settings value -> fallback to env
    env = (ARCHIVE_CHAT_ID or "").strip()
    if env and validate_archive_chat_id(env):
        try:
            return int(env)
        except ValueError:
            return None
    return None


def _get_git_version() -> str:
    """Return short git HEAD, with timeout and FileNotFound handling. Cheap; call via to_thread."""
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, timeout=2).strip()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def build_backup_caption(data_len: int) -> str:
    """Build caption synchronously — MUST be called via asyncio.to_thread (DB + git)."""
    now_app = datetime.datetime.now(APP_TZ)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    size_mb = data_len / (1024 * 1024)
    try:
        users = db.count_users()
    except Exception:
        users = -1
    table_counts: dict[str, int | str] = {}
    schema_version: str | int = "?"
    try:
        from services.db.schema import get_conn
        with get_conn() as conn:
            for t in ("users", "saved_words", "settings", "review_events", "llm_requests"):
                try:
                    table_counts[t] = conn.execute(f"SELECT COUNT(*) as c FROM {t}").fetchone()["c"]
                except Exception:
                    table_counts[t] = -1
            try:
                row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
                schema_version = row["v"] if row and row["v"] is not None else "?"
            except Exception:
                schema_version = "?"
    except Exception:
        pass
    git_version = _get_git_version()
    lines = [
        "📦 پشتیبان دیتابیس",
        f"🕐 {now_app.strftime('%Y-%m-%d %H:%M:%S')} {getattr(APP_TZ, 'key', str(APP_TZ))} / {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"📏 {data_len} bytes ({size_mb:.2f} MB)",
        f"👥 users: {users}",
    ]
    for k, v in table_counts.items():
        lines.append(f"  {k}: {v}")
    lines.append(f"🗄 schema: {schema_version}")
    if git_version:
        lines.append(f"🔖 git: {git_version}")
    return "\n".join(lines)


async def is_bot_admin(bot, chat_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, (await bot.get_me()).id)
        return getattr(member, "status", "") in ("administrator", "creator")
    except Exception:
        return False


async def do_backup(bot, owner_user_id: int, dest_chat_id: int | None = None):
    target = dest_chat_id if dest_chat_id is not None else resolved_archive_chat_id()
    if target is None:
        target = owner_user_id
    # Guard: never send to 0 (unconfigured OWNER_ID + no archive)
    if not target:
        logger.warning("do_backup: no valid target (archive unset and owner_id==0), skipping")
        return None
    data = await asyncio.to_thread(db.export_db_bytes)
    caption = await asyncio.to_thread(build_backup_caption, len(data))
    fname = f"hamzaban_backup_{datetime.datetime.now(APP_TZ).strftime('%Y%m%d_%H%M%S')}.db"

    await _send_document_with_retry(
        bot, target, document=InputFile(io.BytesIO(data), filename=fname), caption=caption
    )
    return target
