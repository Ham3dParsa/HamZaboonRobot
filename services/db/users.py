import datetime

from services.db.plans import valid_plan_name
from services.db.schema import get_conn, _today, _utc_now, _current_daily_count, _can_consume_daily_count


def get_user(user_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def get_quota_status(user_id: int) -> dict | None:
    """Return today's remaining word-query and grammar-tip quota for a user.

    Returns a dict with two keys, ``"word_query"`` and ``"grammar_tip"``, each
    holding ``{"used": int, "limit": int}``. ``limit`` comes from the user's
    plan query quota. Returns ``None`` when the user does not exist.
    Rule C: the word-query reply and the settings panel both read this single
    seam so they can never drift.
    """
    from config import _app_today, daily_word_query_limit_for_plan
    row = get_user(user_id)
    if not row:
        return None
    limit = daily_word_query_limit_for_plan(row["plan"] or "free")

    wq_used = row["words_asked_today"] or 0
    if row["words_asked_date"] != _app_today():
        wq_used = 0
    gt_used = row["grammar_tips_asked_today"] or 0
    if row["grammar_tips_asked_date"] != _app_today():
        gt_used = 0

    return {
        "word_query": {"used": wq_used, "limit": limit},
        "grammar_tip": {"used": gt_used, "limit": limit},
    }


def create_user_if_needed(user_id: int, username: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id, username, created_at) VALUES (?, ?, ?)",
            (user_id, username, _utc_now().isoformat()),
        )
        conn.commit()


def set_user_lang_goal(user_id: int, lang: str, goal: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET target_lang=?, goal=? WHERE user_id=?",
            (lang, goal, user_id),
        )
        conn.commit()


def set_user_level(user_id: int, level: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET level=?, onboarded=1 WHERE user_id=?",
            (level, user_id),
        )
        conn.commit()


def set_presentation_preference(user_id: int, preference: str):
    if preference not in {"brief", "detailed"}:
        raise ValueError(f"Unknown presentation preference: {preference}")
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET presentation_preference=? WHERE user_id=?",
            (preference, user_id),
        )
        conn.commit()


def set_user_lang(user_id: int, lang: str):
    """تغییر فقط زبان"""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET target_lang=? WHERE user_id=?",
            (lang, user_id),
        )
        conn.commit()


def set_user_goal(user_id: int, goal: str):
    """تغییر فقط هدف"""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET goal=? WHERE user_id=?",
            (goal, user_id),
        )
        conn.commit()


def touch_streak(user_id: int) -> int:
    today = _today().isoformat()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT streak, last_active_date FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            return 0
        streak, last_date = row["streak"] or 0, row["last_active_date"]
        if last_date == today:
            new_streak = streak
        else:
            yesterday = (_today() - datetime.timedelta(days=1)).isoformat()
            new_streak = streak + 1 if last_date == yesterday else 1
        conn.execute(
            "UPDATE users SET streak=?, last_active_date=? WHERE user_id=?",
            (new_streak, today, user_id),
        )
        conn.commit()
        return new_streak


def can_ask_word(user_id: int, daily_limit: int, bypass_limits: bool = False) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT plan, words_asked_today, words_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        return _can_consume_daily_count(
            row["words_asked_today"],
            row["words_asked_date"],
            daily_limit,
            bypass_limits=bypass_limits,
        )


def reserve_word_query(user_id: int, daily_limit: int, bypass_limits: bool = False) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT words_asked_today, words_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        asked = _current_daily_count(row["words_asked_today"], row["words_asked_date"])
        if not bypass_limits and daily_limit >= 0 and asked >= daily_limit:
            return False
        today = _today().isoformat()
        conn.execute(
            "UPDATE users SET words_asked_today=?, words_asked_date=? WHERE user_id=?",
            (asked + 1, today, user_id),
        )
        conn.commit()
        return True


def release_word_query(user_id: int):
    today = _today().isoformat()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET words_asked_today=MAX(words_asked_today - 1, 0) "
            "WHERE user_id=? AND words_asked_date=?",
            (user_id, today),
        )
        conn.commit()


def can_ask_grammar_tip(user_id: int, daily_limit: int, bypass_limits: bool = False) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT grammar_tips_asked_today, grammar_tips_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        return _can_consume_daily_count(
            row["grammar_tips_asked_today"],
            row["grammar_tips_asked_date"],
            daily_limit,
            bypass_limits=bypass_limits,
        )


def reserve_grammar_tip(user_id: int, daily_limit: int, bypass_limits: bool = False) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT grammar_tips_asked_today, grammar_tips_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        asked = _current_daily_count(row["grammar_tips_asked_today"], row["grammar_tips_asked_date"])
        if not bypass_limits and daily_limit >= 0 and asked >= daily_limit:
            return False
        today = _today().isoformat()
        conn.execute(
            "UPDATE users SET grammar_tips_asked_today=?, grammar_tips_asked_date=? WHERE user_id=?",
            (asked + 1, today, user_id),
        )
        conn.commit()
        return True


def release_grammar_tip(user_id: int):
    today = _today().isoformat()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET grammar_tips_asked_today="
            "MAX(grammar_tips_asked_today - 1, 0) "
            "WHERE user_id=? AND grammar_tips_asked_date=?",
            (user_id, today),
        )
        conn.commit()


def all_active_users():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE onboarded=1 AND (bot_blocked IS NULL OR bot_blocked=0)"
        ).fetchall()


def count_users():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def count_users_overview() -> dict:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN onboarded=1 THEN 1 ELSE 0 END) AS onboarded,
                SUM(CASE WHEN bot_blocked=1 THEN 1 ELSE 0 END) AS blocked
            FROM users
        """).fetchone()
        return dict(row)


def count_users_grouped(field: str) -> list[dict]:
    allowed = {"plan", "target_lang", "goal", "level"}
    if field not in allowed:
        return []
    with get_conn() as conn:
        return conn.execute(
            f"SELECT {field} AS val, COUNT(*) AS cnt FROM users GROUP BY {field} ORDER BY cnt DESC"
        ).fetchall()


def count_active_users_since(date: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE last_active_date >= ?", (date,)
        ).fetchone()
        return row["cnt"] if row else 0


def count_saved_words_total() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM saved_words").fetchone()
        return row["cnt"] if row else 0


def count_llm_requests_since(date: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM llm_requests WHERE request_date >= ?", (date,)
        ).fetchone()
        return row["cnt"] if row else 0


def set_plan(user_id: int, plan: str):
    if not valid_plan_name(plan):
        raise ValueError(f"Unknown plan: {plan}")
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE users SET plan=? WHERE user_id=?", (plan, user_id))
        conn.commit()


def find_user(identifier: str):
    identifier = identifier.strip()
    if identifier.startswith("@"):
        identifier = identifier[1:]
    if identifier.isdigit():
        return get_user(int(identifier))
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (identifier,),
        ).fetchone()


def set_user_blocked(user_id: int):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE users SET bot_blocked=1 WHERE user_id=?", (user_id,))
        conn.commit()


def reset_user_blocked(user_id: int):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE users SET bot_blocked=0 WHERE user_id=?", (user_id,))
        conn.commit()
