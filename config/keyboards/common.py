from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from .constants import *  # noqa: F401,F403
from config.catalog import GOALS, LANGUAGES, LEVELS, language_label


from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from config.catalog import GOALS, LANGUAGES, LEVELS, language_label





# =============================================================================
# Inline Button Labels (IBTN_*)
# -----------------------------------------------------------------------------
# Central registry for all inline keyboard label strings.  Change a label
# once here and every key that uses it stays in sync automatically.
# Organised by functional area; prefix is IBTN_ (Inline ButtoN).
# =============================================================================

# --- Navigation / Generic ---

# --- Presentation ---



# --- Admin – LLM Kind / Status Values ---

# --- Admin – LLM Pricing ---

# --- Admin – AI Settings ---



# --- Admin – AI Fallback ---

# --- Admin – Custom Test Wizard ---

# --- Admin – Pending Changes ---

# --- Admin – Preset Edit Fields ---


# --- Admin – Full Edit Wizard ---

# --- Study – stale-card notice ---

# R10: /reports reopen flow — back to the recent-reports list.

# --- Admin – Preset Group / Pagination ---

# --- Admin – Fallback Chain ---

# --- Admin – Help ---

def main_menu(is_owner: bool) -> ReplyKeyboardMarkup:
    rows = [
        [BTN_STUDY_SESSION],
        [BTN_ASK_WORD],
        [BTN_SETTINGS],
        [BTN_HELP],
    ]
    if is_owner:
        rows.append([BTN_ADMIN])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)



def awaiting_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[BTN_BACK, BTN_CANCEL]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )



def _awaiting_row(
    *,
    back_cb: str,
    back_label: str,
    cancel_cb: str,
    cancel_label: str,
) -> list[list[InlineKeyboardButton]]:
    """One shared back/cancel row for awaiting text-input prompts.

    Keyword-only so a label and a callback can never be silently transposed
    (they are distinct kinds of ``str`` payloads).
    """
    return [
        [
            InlineKeyboardButton(back_label, callback_data=back_cb),
            InlineKeyboardButton(cancel_label, callback_data=cancel_cb),
        ]
    ]



def awaiting_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        _awaiting_row(
            back_cb="flow:back", back_label=BTN_BACK,
            cancel_cb="flow:cancel", cancel_label=BTN_CANCEL,
        )
    )



def admin_awaiting_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        _awaiting_row(
            back_cb="admin:back", back_label="↩️ بازگشت",
            cancel_cb="admin:cancel", cancel_label="❌ لغو",
        )
    )



DISPLAY_TOGGLE_FA_LABELS: dict[str, str] = {
    "explanation": "توضیح",
    "synonyms": "مترادف‌ها",
    "antonyms": "متضادها",
    "examples": "مثال‌ها",
    "example_translations": "ترجمه مثال‌ها",
    "grammar_tip": "نکته گرامری",
}


def display_toggles_keyboard(current: dict) -> InlineKeyboardMarkup:
    """Admin display-toggles panel — one row per DISPLAY_TOGGLE_FIELDS entry.

    Single source is config.catalog.DISPLAY_TOGGLE_FIELDS; adding a field there
    auto-adds its toggle button here (R23 / O-display-toggles).
    """
    from config.catalog import DISPLAY_TOGGLE_FIELDS

    rows = []
    for field in DISPLAY_TOGGLE_FIELDS:
        enabled = bool(current.get(field, True))
        marker = "✅" if enabled else "⭕"
        label = DISPLAY_TOGGLE_FA_LABELS.get(field, field)
        rows.append([InlineKeyboardButton(f"{marker} {label}", callback_data=f"admin:display_toggle:{field}")])
    rows.append([InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")])
    return InlineKeyboardMarkup(rows)


def display_toggle_confirm_keyboard(field: str, *, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Two-step confirm for disabling a HIGH_VALUE toggle (R9 warning)."""
    prefix = "admin:display_toggle" if is_admin else "settings:display_toggle"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ بله، خاموش کن", callback_data=f"{prefix}:confirm:{field}"),
            InlineKeyboardButton("❌ انصراف", callback_data=f"{prefix}:cancel"),
        ],
    ])


def user_display_toggles_keyboard(current: dict, forced: dict | None = None) -> InlineKeyboardMarkup:
    """User per-field toggle panel — shows effective values + forced lock hint."""
    from config.catalog import DISPLAY_TOGGLE_FIELDS

    forced = forced or {}
    rows = []
    for field in DISPLAY_TOGGLE_FIELDS:
        enabled = bool(current.get(field, True))
        marker = "✅" if enabled else "⭕"
        label = DISPLAY_TOGGLE_FA_LABELS.get(field, field)
        if field in forced:
            label = f"🔒 {label}"
        rows.append([InlineKeyboardButton(f"{marker} {label}", callback_data=f"settings:display_toggle:{field}")])
    rows.append([InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")])
    return InlineKeyboardMarkup(rows)

