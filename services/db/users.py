import datetime

from services.db.plans import get_plan, valid_plan_name
from services.db.schema import get_conn, transaction, _today, _utc_now, _current_daily_count, _can_consume_daily_count
from services.db.settings import get_setting, set_setting
from services.db.display_toggles import (
    get_effective as _get_display_toggles,
    set_user_toggle as _set_display_toggle,
    set_forced as _set_display_toggle_forced,
)

# Card-mode registry re-exported from config.catalog (single source, R1).
# Kept as module-level aliases so existing imports (services/db/users.py) keep
# working without a breaking change; the canonical definitions live in catalog.
from config.catalog import (
    CARD_MODE_GATES,
    CARD_MODES,
    CARD_TYPES,
    DEFAULT_CARD_MODE,
    DEFAULT_CARD_MODE_GATE,
)


def _validate_card_type(card_type: str) -> None:
    if card_type not in CARD_TYPES:
        raise ValueError(f"Unknown card type: {card_type}")


def _validate_card_mode(mode: str) -> None:
    if mode not in CARD_MODES:
        raise ValueError(f"Unknown card mode: {mode}")


def _validate_card_mode_gate(gate: str) -> None:
    if gate not in CARD_MODE_GATES:
        raise ValueError(f"Unknown card-mode gate: {gate}")


def get_user(user_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def get_display_toggles(user_id: int, row=None) -> dict[str, bool]:
    """Resolve a user's effective display toggles (R10).

    Thin delegate to ``services.db.display_toggles.DisplayToggleService`` (R3) —
    precedence (forced > user > global > catalog) lives there.
    """
    return _get_display_toggles(user_id, row)


def set_display_toggle(user_id: int, field: str, enabled: bool):
    """Set a user's own display-toggle override (wins over admin defaults)."""
    return _set_display_toggle(user_id, field, enabled)


def set_display_toggle_forced(user_id: int, field: str, enabled: bool):
    """Set an admin-forced per-user display toggle (wins over user override)."""
    return _set_display_toggle_forced(user_id, field, enabled)


def _sanitize_mode(value) -> str | None:
    """Return a valid card mode or None so unknown stored values fall through."""
    if value in CARD_MODES:
        return value
    return None


def resolve_card_mode(user_id: int, card_type: str, row=None) -> str:
    """Resolve the effective card mode for a user and card type (CARD-MODES R4).

    Precedence: user override > plan value > admin-global > built-in
    ``DEFAULT_CARD_MODE``. Unknown stored values fall through to the next
    level (never crash). ``row`` is an optional pre-fetched users row reused to
    avoid an extra SELECT (callers that already hold one pass it in).
    """
    _validate_card_type(card_type)
    if row is None:
        row = get_user(user_id)
    if row:
        user_mode = _sanitize_mode(row[f"{card_type}_mode"])
        if user_mode:
            return user_mode
        plan = get_plan(row["plan"] or "free")
        if plan:
            plan_mode = _sanitize_mode(plan[f"{card_type}_mode"])
            if plan_mode:
                return plan_mode
    global_mode = get_setting(f"{card_type}_mode", "")
    return _sanitize_mode(global_mode) or DEFAULT_CARD_MODE


def resolve_card_mode_gate(card_type: str) -> str:
    """Return the admin-global availability gate for a card type (CARD-MODES R6)."""
    _validate_card_type(card_type)
    gate = get_setting(f"{card_type}_mode_gate", "")
    if gate in CARD_MODE_GATES:
        return gate
    return DEFAULT_CARD_MODE_GATE


def card_mode_available(user_id: int, card_type: str, row=None) -> bool:
    """Whether a user may use the per-user control for ``card_type`` (R6).

    ``all`` → everyone; ``premium`` → paid plans only. Mirrors
    ``feature_audience``'s gate semantics.
    """
    from config import _user_plan
    from config.plan_identity import has_feature
    gate = resolve_card_mode_gate(card_type)
    if gate == "all":
        return True
    if row is None:
        row = get_user(user_id)
    if not row:
        return False
    return has_feature(_user_plan(row), "card_modes")


def set_user_card_mode(user_id: int, card_type: str, mode: str):
    """Persist a user's own card-mode override (wins over plan/global)."""
    _validate_card_type(card_type)
    _validate_card_mode(mode)
    with transaction() as conn:
        conn.execute(
            f"UPDATE users SET {card_type}_mode=? WHERE user_id=?",
            (mode, user_id),
        )


def set_plan_card_mode(plan_name: str, card_type: str, mode: str):
    """Persist a per-plan card-mode value (wins over the admin-global mode)."""
    _validate_card_type(card_type)
    _validate_card_mode(mode)
    if not valid_plan_name(plan_name):
        raise ValueError(f"Unknown plan: {plan_name}")
    with transaction() as conn:
        conn.execute(
            f"UPDATE plans SET {card_type}_mode=? WHERE name=?",
            (mode, plan_name),
        )


def set_global_card_mode(card_type: str, mode: str):
    """Persist the admin-global card mode for a card type."""
    _validate_card_type(card_type)
    _validate_card_mode(mode)
    set_setting(f"{card_type}_mode", mode)


def set_card_mode_gate(card_type: str, gate: str):
    """Persist the admin-global availability gate for a card type."""
    _validate_card_type(card_type)
    _validate_card_mode_gate(gate)
    set_setting(f"{card_type}_mode_gate", gate)


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
    with transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id, username, created_at) VALUES (?, ?, ?)",
            (user_id, username, _utc_now().isoformat()),
        )


def set_user_lang_goal(user_id: int, lang: str, goal: str):
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET target_lang=?, goal=? WHERE user_id=?",
            (lang, goal, user_id),
        )


def set_user_level(user_id: int, level: str):
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET level=?, onboarded=1 WHERE user_id=?",
            (level, user_id),
        )


def set_presentation_preference(user_id: int, preference: str):
    if preference not in {"brief", "detailed"}:
        raise ValueError(f"Unknown presentation preference: {preference}")
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET presentation_preference=? WHERE user_id=?",
            (preference, user_id),
        )


def set_user_lang(user_id: int, lang: str):
    """تغییر فقط زبان"""
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET target_lang=? WHERE user_id=?",
            (lang, user_id),
        )


def set_user_goal(user_id: int, goal: str):
    """تغییر فقط هدف"""
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET goal=? WHERE user_id=?",
            (goal, user_id),
        )


def touch_streak(user_id: int) -> int:
    today = _today().isoformat()
    with transaction() as conn:
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
    with transaction() as conn:
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
        return True


def release_word_query(user_id: int):
    today = _today().isoformat()
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET words_asked_today=MAX(words_asked_today - 1, 0) "
            "WHERE user_id=? AND words_asked_date=?",
            (user_id, today),
        )


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
    with transaction() as conn:
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
        return True


def release_grammar_tip(user_id: int):
    today = _today().isoformat()
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET grammar_tips_asked_today="
            "MAX(grammar_tips_asked_today - 1, 0) "
            "WHERE user_id=? AND grammar_tips_asked_date=?",
            (user_id, today),
        )


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
    with transaction() as conn:
        conn.execute("UPDATE users SET plan=? WHERE user_id=?", (plan, user_id))


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
    with transaction() as conn:
        conn.execute("UPDATE users SET bot_blocked=1 WHERE user_id=?", (user_id,))


def reset_user_blocked(user_id: int):
    with transaction() as conn:
        conn.execute("UPDATE users SET bot_blocked=0 WHERE user_id=?", (user_id,))
