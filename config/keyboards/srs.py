from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import KeyboardButtonStyle

from .constants import *  # noqa: F401,F403
from config.catalog import language_label




# --- SRS 4-Grade (First-Exposure: familiarity-based) ---

# --- Query / Word Lookup ---

# --- Pronunciation ---

# --- Admin – General ---


# --- Session Summary Report ---

def study_start_keyboard() -> InlineKeyboardMarkup:
    """Single '📚 شروع مطالعه' inline button for the nudge / menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(BTN_STUDY_SESSION, callback_data="study:start")],
    ])



def study_inactive_keyboard() -> InlineKeyboardMarkup:
    """Keyboard that replaces a stale study card's grade buttons.

    Pressing it triggers a 'this message is no longer active' popup, after
    which the stale message is deleted. Prevents grading an outdated card.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(IBTN_STUDY_INACTIVE, callback_data="study:inactive")],
    ])



def query_result_keyboard(
    token: str,
    lang: str | None = None,
    *,
    saved: bool = False,
) -> InlineKeyboardMarkup:
    label = IBTN_REMOVE_FROM_REVIEW if saved else IBTN_ADD_TO_REVIEW
    if lang:
        label = f"{label} ({language_label(lang)})"
    buttons = [
        InlineKeyboardButton(
            label,
            callback_data=f"query:add:{token}",
        )
    ]
    rows = [
        buttons,
        [
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:q:{token}",
            )
        ],
    ]
    return InlineKeyboardMarkup(rows)



def query_duplicate_keyboard(token: str) -> InlineKeyboardMarkup:
    """Retrieve-vs-new choice with an exit, when a repeated word is asked (R7b).

    ``query:dup:new`` re-runs the ask (quota + AI); ``query:dup:reuse`` re-renders
    the stored prior card for free; ``query:dup:cancel`` returns to the menu so the
    learner always has an exit.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                IBTN_QUERY_DUP_NEW,
                callback_data=f"query:dup:new:{token}",
            ),
            InlineKeyboardButton(
                IBTN_QUERY_DUP_REUSE,
                callback_data=f"query:dup:reuse:{token}",
            ),
        ],
        [
            InlineKeyboardButton(
                IBTN_QUERY_DUP_CANCEL,
                callback_data="query:dup:cancel",
            ),
        ],
    ])



def get_review_keyboard(
    user_id: int,
    word_id: int,
) -> InlineKeyboardMarkup:
    """Returns 4-grade review keyboard (recall-based labels).

    Layout (2×2 grid + delete/pronounce row):
    [ به سختی یادم اومد 🟡 ] [ یادم نیامد ⭕ ]
    [ خیلی راحت بود 🟣 ] [ خوب بود 🟢 ]
    [ 🗑 حذف از مطالعه ] [ 🔊 تلفظ ]
    """
    rows = [
        [
            InlineKeyboardButton(
                IBTN_SRS_HARD_REVIEW,
                callback_data=f"srs:2:{user_id}:{word_id}",
                style=KeyboardButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                IBTN_SRS_AGAIN_REVIEW,
                callback_data=f"srs:1:{user_id}:{word_id}",
                style=KeyboardButtonStyle.DANGER,
            ),
        ],
        [
            InlineKeyboardButton(
                IBTN_SRS_EASY_REVIEW,
                callback_data=f"srs:4:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_SRS_GOOD_REVIEW,
                callback_data=f"srs:3:{user_id}:{word_id}",
                style=KeyboardButtonStyle.SUCCESS,
            ),
        ],
        [
            InlineKeyboardButton(
                IBTN_SRS_DELETE,
                callback_data=f"srs:delete:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:s:{user_id}:{word_id}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(rows)



def get_srs_front_keyboard(
    user_id: int,
    word_id: int,
) -> InlineKeyboardMarkup:
    """Returns the staged-reveal front keyboard for a regular review card.

    The learner first reads the hidden front-stage prompt, then taps the reveal
    action to open the back stage + grade buttons (#338 §2B). The delete row is
    deferred to Phase 3 (#338 P3-T2).
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                IBTN_SRS_REVEAL,
                callback_data=f"srs:reveal:{user_id}:{word_id}",
            )
        ],
    ])



def get_srs_delete_confirm_keyboard(
    user_id: int,
    word_id: int,
) -> InlineKeyboardMarkup:
    """Returns the two-step delete confirm keyboard (Rule 3).

    [ ✅ بله، حذف شود ] [ ❌ انصراف ]
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                IBTN_SRS_DELETE_CONFIRM,
                callback_data=f"srs:delete:yes:{user_id}:{word_id}",
                style=KeyboardButtonStyle.DANGER,
            ),
            InlineKeyboardButton(
                IBTN_SRS_DELETE_CANCEL,
                callback_data=f"srs:delete:no:{user_id}:{word_id}",
            ),
        ],
    ])



def get_first_exposure_keyboard(
    user_id: int,
    word_id: int,
) -> InlineKeyboardMarkup:
    """Returns 4-grade first-exposure keyboard (familiarity-based labels).

    Layout (2×2 grid + delete/pronounce row):
    [ کمی آشناام 🟨 ] [ کاملاً ناآشناام 🟥 ]
    [ کاملاً بلدمش 🟪 ] [ آشنایی خوب 🟩 ]
    [ 🗑 حذف از مطالعه ] [ 🔊 تلفظ ]
    """
    rows = [
        [
            InlineKeyboardButton(
                IBTN_SRS_HARD_FE,
                callback_data=f"srs:fe:2:{user_id}:{word_id}",
                style=KeyboardButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                IBTN_SRS_AGAIN_FE,
                callback_data=f"srs:fe:1:{user_id}:{word_id}",
                style=KeyboardButtonStyle.DANGER,
            ),
        ],
        [
            InlineKeyboardButton(
                IBTN_SRS_EASY_FE,
                callback_data=f"srs:fe:4:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_SRS_GOOD_FE,
                callback_data=f"srs:fe:3:{user_id}:{word_id}",
                style=KeyboardButtonStyle.SUCCESS,
            ),
        ],
        [
            InlineKeyboardButton(
                IBTN_SRS_DELETE,
                callback_data=f"srs:delete:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:s:{user_id}:{word_id}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(rows)

