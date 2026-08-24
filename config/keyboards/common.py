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
        rows.append([InlineKeyboardButton(f"{marker} {field}", callback_data=f"admin:display_toggle:{field}")])
    rows.append([InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")])
    return InlineKeyboardMarkup(rows)

