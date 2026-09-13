"""Cached custom-word query results (verbatim split from services/db/__init__.py).

Owns the ``query_results`` cache table: dedup-keyed card payloads with TTL,
per-user+lang LRU cap, and save-link bookkeeping. Imports only from
``services.db.schema`` (never the facade) per the leaf-import law.
"""

import datetime
import json
import secrets

from services.db.schema import get_conn, transaction, normalize_word, _utc_now


def _query_result_expired(row) -> bool:
    return row is not None and row["expires_at"] <= _utc_now().isoformat()


def _normalize_query_text(text: str) -> str:
    """Normalize the dedup key exactly as saved words are normalized (R7a).

    Delegates to the single-source ``schema.normalize_word`` (A2-3 / R2) so the
    query-dedup key and ``saved_words.normalized_word`` always agree (NFC +
    casefold + whitespace-collapse). Used identically on insert and lookup so a
    prior card is found for case/Unicode variants instead of re-spending quota +
    AI.
    """
    return normalize_word(text)


_QUERY_RESULTS_CAP = 100


def _enforce_query_results_cap(
    conn, user_id: int, lang: str, cap: int = _QUERY_RESULTS_CAP, exclude_token: str | None = None
) -> None:
    """Enforce per-user+lang cap (cap=100) via LRU eviction on unexpired rows.

    Counts only unexpired rows so not-yet-purged expired rows don't evict fresh
    ones. ``exclude_token`` keeps the dedup source alive when alias insert would
    otherwise evict it. Bounded by cap size.
    """
    now = _utc_now().isoformat()
    if exclude_token:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM query_results WHERE user_id=? AND lang=? AND expires_at>?",
            (user_id, lang, now),
        ).fetchone()["c"]
        if total <= cap:
            return
        to_delete = total - cap
        conn.execute(
            "DELETE FROM query_results WHERE rowid IN ("
            "SELECT rowid FROM query_results WHERE user_id=? AND lang=? AND expires_at>? AND token!=? "
            "ORDER BY created_at ASC, rowid ASC LIMIT ?)",
            (user_id, lang, now, exclude_token, to_delete),
        )
    else:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM query_results WHERE user_id=? AND lang=? AND expires_at>?",
            (user_id, lang, now),
        ).fetchone()["c"]
        if count > cap:
            to_delete = count - cap
            conn.execute(
                "DELETE FROM query_results WHERE rowid IN ("
                "SELECT rowid FROM query_results WHERE user_id=? AND lang=? AND expires_at>? "
                "ORDER BY created_at ASC, rowid ASC LIMIT ?)",
                (user_id, lang, now, to_delete),
            )


def create_query_result(
    user_id: int,
    query_text: str,
    word: str,
    lang: str,
    result_data: dict,
    ttl_seconds: int = 30 * 24 * 60 * 60,
    exclude_token: str | None = None,
) -> str:
    token = secrets.token_hex(16)
    now = _utc_now()
    expires_at = now + datetime.timedelta(seconds=ttl_seconds)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO query_results("
            "token, user_id, query_text, word, lang, result_json, created_at, expires_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                user_id,
                _normalize_query_text(query_text),
                normalize_word(word),
                lang,
                json.dumps(result_data, ensure_ascii=False),
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        _enforce_query_results_cap(conn, user_id, lang, exclude_token=exclude_token)
    return token


def get_query_result(token: str, user_id: int | None = None, include_expired: bool = False):
    with get_conn() as conn:
        params = [token]
        query = "SELECT * FROM query_results WHERE token=?"
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        row = conn.execute(query, params).fetchone()
    if row and not include_expired and _query_result_expired(row):
        return None
    return row


def find_unexpired_query(user_id: int, query_text: str, lang: str):
    """Return the most recent unexpired query_result for the same user + lang +
    normalized query_text, or None.

    R7a dedup key: the stored ``query_text`` column is normalized on insert via
    ``_normalize_query_text`` (NFC + casefold + whitespace-collapse), so this
    lookup normalizes the incoming text the same way and matches exactly. Runs
    before quota/AI, so the caller can offer retrieve-vs-new for a word the user
    already asked.
    Indexed lookup first; fallback scan handles legacy rows stored before
    normalization (pre-#501).
    """
    normalized = _normalize_query_text(query_text)
    now = _utc_now().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM query_results "
            "WHERE user_id=? AND lang=? AND query_text=? AND expires_at>? "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id, lang, normalized, now),
        ).fetchone()
        if row is not None:
            return row
        # Fallback for legacy rows stored before normalization (pre-#501).
        rows = conn.execute(
            "SELECT * FROM query_results "
            "WHERE user_id=? AND lang=? AND expires_at>? "
            "ORDER BY created_at DESC",
            (user_id, lang, now),
        ).fetchall()
    for r in rows:
        if _normalize_query_text(r["query_text"] or "") == normalized:
            try:
                json.loads(r["result_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            return r
    return None


def find_unexpired_query_by_word(user_id: int, word: str, lang: str):
    """Return the most recent unexpired query_result for same user+lang+normalized word.

    Indexed lookup: ``word`` column stores ``normalize_word(word)`` (see
    ``create_query_result``), so SQL equality can use
    ``query_results_user_lang_word_idx``. Legacy rows with non-normalized word
    are handled via fallback scan.
    """
    normalized = normalize_word(word)
    if not normalized:
        return None
    now = _utc_now().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM query_results "
            "WHERE user_id=? AND lang=? AND word=? AND expires_at>? "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id, lang, normalized, now),
        ).fetchone()
        if row is not None:
            return row
        # Fallback for legacy rows stored before normalization (pre-#501).
        rows = conn.execute(
            "SELECT * FROM query_results "
            "WHERE user_id=? AND lang=? AND expires_at>? "
            "ORDER BY created_at DESC",
            (user_id, lang, now),
        ).fetchall()
    for r in rows:
        if normalize_word(r["word"] or "") == normalized:
            try:
                json.loads(r["result_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            return r
    return None


def mark_query_result_saved(token: str, saved_word_id: int | None = None):
    with transaction() as conn:
        conn.execute(
            "UPDATE query_results SET saved_at=COALESCE(saved_at, ?), "
            "saved_word_id=COALESCE(saved_word_id, ?) WHERE token=?",
            (_utc_now().isoformat(), saved_word_id, token),
        )


def clear_query_result_saved(token: str):
    with transaction() as conn:
        conn.execute(
            "UPDATE query_results SET saved_at=NULL, saved_word_id=NULL WHERE token=?",
            (token,),
        )


def update_query_result_fields(
    token: str,
    user_id: int,
    patch: dict,
) -> bool:
    with transaction() as conn:
        row = conn.execute(
            "SELECT result_json FROM query_results WHERE token=? AND user_id=?",
            (token, user_id),
        ).fetchone()
        if not row:
            return False
        try:
            result_data = json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(result_data, dict):
            return False
        result_data.update(patch)
        conn.execute(
            "UPDATE query_results SET result_json=? WHERE token=? AND user_id=?",
            (json.dumps(result_data, ensure_ascii=False), token, user_id),
        )
        return True


def cleanup_expired_query_results(*, deadline: float | None = None):
    """Single short DELETE — ``deadline`` accepted for the uniform nightly
    call-site and ignored (nothing to interrupt)."""
    with transaction() as conn:
        conn.execute(
            "DELETE FROM query_results WHERE expires_at<=?",
            (_utc_now().isoformat(),),
        )
