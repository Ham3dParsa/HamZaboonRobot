"""Deep TTS service — single owner for lock+cache+channel+fallback (phase 01)."""

import asyncio
import logging
import re

from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut

from services import tts
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.send_pretty import _send_media_with_retry
from services.utils.helpers import _send_with_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-key speak lock — the ONLY upload-dedup lock (R1, phase 02 single lock).
# tts.pronounce() is lock-free (atomic tmp-write + os.replace, no torn file
# but no dedup of the Edge request itself); the service lock single-flights
# speak() so concurrent same-key callers share one Edge call + one channel
# upload. Direct tts.pronounce() calls outside speak() are NOT single-flighted.
# ---------------------------------------------------------------------------
_SPEAK_LOCKS: dict[str, asyncio.Lock] = {}
_SPEAK_LOCKS_GUARD = asyncio.Lock()
_MAX_SPEAK_LOCKS = 2000


async def _get_speak_lock(cache_key: str) -> asyncio.Lock:
    async with _SPEAK_LOCKS_GUARD:
        lock = _SPEAK_LOCKS.get(cache_key)
        if lock is None:
            # Bounded eviction: only idle locks are evicted; per-key
            # serialization wins over cap.
            if len(_SPEAK_LOCKS) >= _MAX_SPEAK_LOCKS:
                for k, lk in list(_SPEAK_LOCKS.items()):
                    if not lk.locked():
                        del _SPEAK_LOCKS[k]
                        if len(_SPEAK_LOCKS) < _MAX_SPEAK_LOCKS:
                            break
            lock = asyncio.Lock()
            _SPEAK_LOCKS[cache_key] = lock
        return lock


async def _send_voice(bot, chat_id: int, media, **kwargs):
    """Voice send via the unified phase-03 retry core (allowlisted send_voice)."""
    return await _send_media_with_retry(
        bot, chat_id, method="send_voice", media_kw="voice", media=media, **kwargs
    )

# ---------------------------------------------------------------------------
# Channel resolution — moved from config/__init__.py (R2)
# ---------------------------------------------------------------------------
_TTS_CACHE_CHAT_ID_RE = re.compile(r"^(?:-100\d{5,}|-\d{5,})$")


def _coerce_tts_cache_chat_id(raw: str) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    if not _TTS_CACHE_CHAT_ID_RE.match(s):
        logger.warning("TTS_CACHE_CHAT_ID invalid %r — disabling TTS cache channel", raw)
        return None
    try:
        return int(s)
    except ValueError:
        logger.warning("TTS_CACHE_CHAT_ID invalid %r — disabling TTS cache channel", raw, exc_info=True)
        return None


def get_tts_cache_chat_id_raw() -> tuple[bool, str]:
    """Return (exists, raw_value) via canonical settings accessor."""
    from services.db.settings import get_setting as _get_setting

    _sentinel = object()
    val = _get_setting("tts_cache_chat_id", _sentinel)  # type: ignore[arg-type]
    if val is _sentinel:
        return False, ""
    return True, str(val or "")


def resolve_tts_cache_chat_id() -> int | None:
    """Resolve TTS cache channel id: settings wins else env. Returns int|None."""
    try:
        exists, raw = get_tts_cache_chat_id_raw()
        if exists:
            v = (raw or "").strip()
            if not v:
                return None
            coerced = _coerce_tts_cache_chat_id(v)
            if coerced is None and v:
                logger.warning("tts_cache_chat_id setting invalid %r — disabling", v)
            return coerced
    except Exception:
        logger.warning("resolve_tts_cache_chat_id failed to read setting", exc_info=True)
    from config import TTS_CACHE_CHAT_ID as _env_raw

    return _coerce_tts_cache_chat_id(_env_raw or "")


def validate_tts_cache_chat_id(raw: str) -> int | None:
    s = (raw or "").strip()
    if not s:
        return None
    if not _TTS_CACHE_CHAT_ID_RE.match(s):
        raise ValueError("آیدی کانال نامعتبر است. مثال: -1001234567890 یا -12345")
    return int(s)


# ---------------------------------------------------------------------------
# Async cache wrappers — hide to_thread (R3)
# ---------------------------------------------------------------------------

async def _cache_get(cache_key: str) -> dict | None:
    from services import tts_cache as _tts_cache

    try:
        return await asyncio.to_thread(_tts_cache.get_cached, cache_key)
    except Exception:
        logger.warning("tts_cache get_cached failed cache_key=%r", cache_key, exc_info=True)
        return None


async def _cache_put(cache_key: str, lang: str, text: str, file_id: str, file_unique_id: str, channel_message_id: int | None) -> None:
    from services import tts_cache as _tts_cache

    try:
        await asyncio.to_thread(_tts_cache.put_cached, cache_key, lang, text, file_id, file_unique_id, channel_message_id)
    except Exception:
        logger.warning("tts_cache put_cached failed cache_key=%r", cache_key, exc_info=True)


def ensure_tts_cache_db() -> None:
    """Init tts_cache.db — called at startup (moved from bot.py:1349)."""
    try:
        from services.tts_cache import init_tts_cache_db

        init_tts_cache_db()
    except Exception:
        logger.exception("tts_cache db init failed")


# ---------------------------------------------------------------------------
# Word resolution — single owner for q/s branches
# ---------------------------------------------------------------------------

def resolve_word(source: str, parts: list[str], user_id: int) -> tuple[str | None, str | None, str | None]:
    """Resolve word+lang from callback payload.

    Returns (word, lang, error_key) — error_key is None on success, else a
    short code for the caller to map to a user message. On success word/lang
    are non-empty.
    """
    from services import db

    if source == "q":
        if len(parts) != 2:
            return None, None, "invalid"
        token = parts[1]
        qr = db.get_query_result(token, user_id=user_id)
        if not qr:
            return None, None, "expired"
        return qr["word"], qr["lang"], None
    if source == "s":
        if len(parts) != 3:
            return None, None, "invalid"
        try:
            target_user_id = int(parts[1])
            word_id = int(parts[2])
        except ValueError:
            return None, None, "invalid"
        if user_id != target_user_id:
            return None, None, "cross_user"
        sw = db.get_saved_word(word_id, user_id=user_id)
        if not sw:
            return None, None, "not_found"
        return sw["word"], sw["lang"], None
    return None, None, "invalid"


# ---------------------------------------------------------------------------
# Deep speak seam — lock+cache+channel+fallback
# ---------------------------------------------------------------------------

async def speak(word: str, lang: str, *, bot, chat_id: int, reply_to: int | None = None) -> str:
    """Generate/send voice for word+lang. Returns kind for logging.

    kind: file_id_hit | channel_upload | direct_fallback
    """
    caption = tts.tts_caption(word)
    cache_key = tts.tts_cache_key(word, lang)
    channel_id = resolve_tts_cache_chat_id()
    lock = await _get_speak_lock(cache_key)
    async with lock:
        return await _speak_locked(word, lang, caption=caption, cache_key=cache_key, channel_id=channel_id, bot=bot, chat_id=chat_id, reply_to=reply_to)


async def _speak_locked(word: str, lang: str, *, caption: str, cache_key: str, channel_id: int | None, bot, chat_id: int, reply_to: int | None = None) -> str:
    # hit path: DB lookup -> send file_id
    if channel_id:
        cached = await _cache_get(cache_key)
        if cached and cached.get("file_id"):
            fid_prefix = str(cached["file_id"])[:12]
            logger.info("tts file_id hit lang=%s key=%r file_id_prefix=%r word=%r", lang, cache_key, fid_prefix, word)
            try:
                await _send_voice(bot, chat_id, cached["file_id"], caption=caption, reply_to_message_id=reply_to)
                return "file_id_hit"
            except (TimedOut, NetworkError):
                # Non-idempotent send: may already be delivered — never re-send.
                raise
            except (Forbidden, BadRequest):
                logger.warning("cached file_id send failed, falling back to generate lang=%s word=%r key=%r", lang, word, cache_key, exc_info=True)

    # miss -> generate (the speak lock above single-flights concurrent
    # same-key callers, so no post-pronounce cache re-check is needed)
    path = await tts.pronounce(word, lang)

    # channel upload
    if channel_id:
        try:
            voice_bytes = await asyncio.to_thread(path.read_bytes)
            msg = await _send_voice(bot, channel_id, voice_bytes, caption=caption)
            fid = None
            fuid = ""
            try:
                v = getattr(msg, "voice", None)
                if v is not None:
                    fid = getattr(v, "file_id", None)
                    fuid = getattr(v, "file_unique_id", "") or ""
            except Exception:
                pass
            if fid:
                await _cache_put(cache_key, lang, caption, fid, fuid, getattr(msg, "message_id", None))
                await _send_voice(bot, chat_id, fid, caption=caption, reply_to_message_id=reply_to)
                logger.info("tts speak kind=channel_upload lang=%s key=%r word=%r", lang, cache_key, word)
                return "channel_upload"
        except (Forbidden, BadRequest) as exc:
            logger.warning("TTS channel cache upload blocked/bad request channel_id=%s word=%r lang=%s key=%r exc=%s", channel_id, word, lang, cache_key, exc, exc_info=True)
        except (TimedOut, NetworkError):
            # Non-idempotent send: may already be delivered — never fall
            # through to a second direct send.
            raise
        except Exception:
            logger.exception("TTS channel cache upload failed channel_id=%s word=%r lang=%s key=%r", channel_id, word, lang, cache_key)

    # fallback direct
    voice_bytes = await asyncio.to_thread(path.read_bytes)
    await _send_voice(bot, chat_id, voice_bytes, caption=caption, reply_to_message_id=reply_to)
    logger.info("tts speak kind=direct_fallback lang=%s key=%r word=%r", lang, cache_key, word)
    return "direct_fallback"


# ---------------------------------------------------------------------------
# Callback entry — thin handler called from bot.py
# ---------------------------------------------------------------------------

async def handle_callback(update, context, data: str) -> None:
    """Handle tts:pronounce:<payload> callbacks. Validates, resolves word, calls speak."""
    user_id = update.effective_user.id
    chat_id_eff = getattr(getattr(update, "effective_chat", None), "id", None)
    logger.info("tts pronounce entry user_id=%s chat_id=%s data=%r", user_id, chat_id_eff, data)
    parts = data.split(":")
    if len(parts) < 2:
        logger.warning("tts pronounce invalid data user_id=%s chat_id=%s data=%r", user_id, chat_id_eff, data)
        await notify_callback(update.callback_query, "دکمه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    source = parts[0]
    if source not in {"q", "s"}:
        logger.warning("tts pronounce invalid source user_id=%s data=%r", user_id, data)
        await notify_callback(update.callback_query, "دکمه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    from services import db

    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        logger.info("tts pronounce not onboarded user_id=%s", user_id)
        await notify_callback(update.callback_query, "ابتدا /start را بزنید.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    word, lang, err = resolve_word(source, parts, user_id)
    if err == "expired":
        logger.info("tts pronounce expired token user_id=%s data=%r", user_id, data)
        await notify_callback(update.callback_query, "این نتیجه منقضی شده است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if err == "cross_user":
        logger.warning("tts pronounce cross-user user_id=%s data=%r", user_id, data)
        await notify_callback(update.callback_query, "این مرور برای کاربر دیگری است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if err == "not_found":
        logger.info("tts pronounce saved_word not found user_id=%s data=%r", user_id, data)
        await notify_callback(update.callback_query, "واژه در مرور شما پیدا نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if err == "invalid" or not word or not lang:
        logger.warning("tts pronounce missing word/lang user_id=%s word=%r lang=%r data=%r", user_id, word, lang, data)
        await notify_callback(update.callback_query, "دکمه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    await notify_callback(update.callback_query, "🎧 در حال آماده‌سازی تلفظ…", intent=CallbackNoticeIntent.INFO)
    try:
        kind = await speak(word, lang, bot=context.bot, chat_id=update.effective_chat.id, reply_to=update.callback_query.message.message_id)
        logger.info("tts speak done user_id=%s lang=%s word=%r kind=%s", user_id, lang, word, kind)
    except (Forbidden, BadRequest) as exc:
        cache_key = tts.tts_cache_key(word, lang) if word and lang else None
        logger.warning("TTS pronunciation blocked/bad request user_id=%s lang=%s word=%r key=%r exc=%s", user_id, lang, word, cache_key, exc, exc_info=True)
        try:
            await _send_with_retry(context.bot, update.effective_chat.id, "متأسفانه تولید تلفظ با خطا مواجه شد. لطفاً کمی بعد دوباره تلاش کنید.")
        except Exception:
            logger.exception("TTS fallback notice failed (Forbidden/BadRequest path) user_id=%s lang=%s word=%r", user_id, lang, word, exc_info=True)
    except Exception:
        cache_key = tts.tts_cache_key(word, lang) if word and lang else None
        logger.exception("TTS pronunciation failed user_id=%s lang=%s word=%r cache_key=%r", user_id, lang, word, cache_key)
        try:
            await _send_with_retry(context.bot, update.effective_chat.id, "متأسفانه تولید تلفظ با خطا مواجه شد. لطفاً کمی بعد دوباره تلاش کنید.")
        except Exception:
            logger.exception("TTS fallback notice failed user_id=%s lang=%s word=%r", user_id, lang, word, exc_info=True)
    except BaseException:
        cache_key = tts.tts_cache_key(word, lang) if word and lang else None
        logger.exception("TTS pronunciation BaseException user_id=%s lang=%s word=%r cache_key=%r", user_id, lang, word, cache_key)
        raise
