from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from .constants import *  # noqa: F401,F403
from config.catalog import GOALS, LANGUAGES, LEVELS, language_label



# --- Daily Cards & Review ---

# --- SRS 4-Grade (Review: recall-based) ---

def lang_inline_keyboard(*, back_to_settings: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(option.name_fa, callback_data=f"lang:{option.code}")]
        for option in LANGUAGES.values()
    ]
    if back_to_settings:
        buttons.append([InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")])
    return InlineKeyboardMarkup(buttons)



def goal_inline_keyboard(*, back_to_settings: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(option.name_fa, callback_data=f"goal:{option.code}")]
        for option in GOALS.values()
    ]
    if back_to_settings:
        buttons.append([InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")])
    return InlineKeyboardMarkup(buttons)



def level_inline_keyboard(*, back_to_settings: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                f"{option.name_fa} ({option.cefr})",
                callback_data=f"level:{option.code}",
            )
        ]
        for option in LEVELS.values()
    ]
    if back_to_settings:
        buttons.append([InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")])
    return InlineKeyboardMarkup(buttons)



def presentation_settings_keyboard(
    current: str,
    *,
    back_to_settings: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{'✅ ' if current == 'brief' else ''}{IBTN_BRIEF}",
                callback_data="presentation:set:brief",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if current == 'detailed' else ''}{IBTN_DETAILED}",
                callback_data="presentation:set:detailed",
            ),
        ]
    ]
    if back_to_settings:
        rows.append([InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")])
    return InlineKeyboardMarkup(rows)



def settings_inline_keyboard(lang: str, goal: str, level: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🌐 زبان: {lang}", callback_data="settings:lang"),
            InlineKeyboardButton(f"🎯 هدف: {goal}", callback_data="settings:goal"),
        ],
        [
            InlineKeyboardButton(f"📚 سطح: {level}", callback_data="settings:level"),
            InlineKeyboardButton("🎛 نمایش کارت", callback_data="settings:display_toggles"),
        ],
        [
            InlineKeyboardButton("👤 وضعیت اشتراک و آمار", callback_data="settings:status"),
        ],
        [
            InlineKeyboardButton(IBTN_CLOSE, callback_data="settings:close"),
        ],
    ])



def settings_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")]
    ])

