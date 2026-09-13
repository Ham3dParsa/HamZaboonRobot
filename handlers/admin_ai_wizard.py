"""Admin AI wizard helpers leaf (REF2-T4, first).

Verbatim home of wizard constants and pure helpers split out of
``handlers/admin_ai.py``. The facade keeps re-exports so every existing
caller via ``handlers/admin_ai`` works unchanged.
"""

import hashlib
import logging
import re
from urllib.parse import quote, unquote

from services import db
from services.ai import preset_fields
from services.utils.confirm_summary import FieldDiff


MAX_GROUP_LABEL_LEN = 40

_FIELD_HELP = {
    "name": preset_fields.PRESET_NAME_HINT_FA,
    "api_key": "کلید API سرویس‌دهنده (مثلاً sk-...). این کلید به‌صورت رمزنگاری‌شده در پایگاه داده ذخیره می‌شود.",
    "base_url": "آدرس سرور سازگار با OpenAI. نمونه: https://api.example.com/v1",
    "model": "نام دقیق مدل. نمونه: gpt-4o-mini یا gemini-2.0-flash-lite",
    "max_concurrency": "تعداد درخواست‌هایی که هم‌زمان به این سرویس‌دهنده فرستاده می‌شود. عدد ۲ یا ۳ معمول است.",
    "max_rpm": "بیشترین تعداد درخواست در هر دقیقه. صفر = بدون محدودیت.",
    "max_tpm": "بیشترین تعداد توکن ورودی و خروجی در هر دقیقه. صفر = بدون محدودیت.",
    "daily_batch_size": "تعداد کارت واژگان در هر دسته که یک‌جا از AI درخواست می‌شود. بین ۳ تا ۱۲.",
    "max_daily_req": "سقف تعداد درخواست به این پریست در هر روز. صفر = بدون محدودیت.",
    "timeout_seconds": "مدت زمان انتظار برای پاسخ از سرویس‌دهنده (به ثانیه). عدد اعشاری مجاز است.",
    "temperature": "میزان خلاقیت مدل. بین ۰.۰ (دقیق) تا ۲.۰ (خلاق). پیش‌فرض: ۰.۶",
    "max_output_tokens": "حداکثر تعداد توکن در هر پاسخ. پیش‌فرض: ۴۰۹۶",
    "priority": "اولویت در زنجیره فال‌بک. عدد کمتر = اولویت بیشتر. پریست با priority=۰ اولین نفری است که امتحان می‌شود.",
    "is_emergency": "آیا این پریست فقط برای مواقع اضطراری است؟ پریست‌های اضطراری همیشه بعد از پریست‌های عادی امتحان می‌شوند.",
    "in_fallback_chain": "آیا این پریست به‌صورت خودکار در زنجیره فال‌بک شرکت کند؟ اگر خاموش شود، فقط با انتخاب دستی قابل استفاده است.",
    "input_cost_per_million": "هزینه هر یک میلیون توکن ورودی (درخواست) به دلار. خالی = استفاده از مقدار سراسری تنظیم شده در داشبورد هزینه.",
    "output_cost_per_million": "هزینه هر یک میلیون توکن خروجی (پاسخ) به دلار. خالی = استفاده از مقدار سراسری.",
    "group_label": "برچسب دلخواه برای گروه‌بندی پریست‌هایی که کلید API مشترک دارند. نمونه: «سرویس‌دهنده اصلی» یا «پشتیبان رایگان»",
    "reasoning_effort": "میزان تلاش استدلال: none (حذف از درخواست؛ برای مدل‌های بدون تفکر)، minimal (کمترین توکن، پیشنهادی برای Spark)، low، medium، high، xhigh. فقط وقتی none نیست ارسال می‌شود. Spark 1.3 همیشه فکر می‌کند و none با 400 خطا می‌دهد؛ از minimal یا low استفاده کنید.",
}

FIELD_LABELS = {
    "base_url": "Base URL",
    "model": "Model",
    "api_key": "API Key",
    "daily_batch_size": "Batch Size",
    "max_concurrency": "Concurrency",
    "max_rpm": "RPM Limit",
    "max_tpm": "Max TPM",
    "max_daily_req": "Max Daily Requests",
    "timeout_seconds": "Timeout (s)",
    "temperature": "Temperature",
    "max_output_tokens": "Max Output Tokens",
    "is_emergency": "Is Emergency",
    "name": "Preset Name",
    "priority": "Priority",
    "input_cost_per_million": "Input Cost $/1M",
    "output_cost_per_million": "Output Cost $/1M",
    "in_fallback_chain": "In Fallback Chain",
    "group_label": "Group Label",
    "reasoning_effort": "Reasoning Effort",
}

WIZARD_FIELDS = [
    "name", "api_key", "base_url", "model",
    "max_concurrency", "max_rpm", "max_tpm", "daily_batch_size",
    "max_daily_req", "timeout_seconds", "temperature", "max_output_tokens",
    "priority", "is_emergency", "in_fallback_chain",
    "input_cost_per_million", "output_cost_per_million", "group_label",
    "reasoning_effort",
]

WIZARD_GROUP_HEADERS = {
    0: "🆔 — گروه هویت (Identity):",
    4: "🔒 — گروه محدودیت‌ها (Limits):",
    12: "⛓️ — گروه فال‌بک (Fallback):",
    15: "💰 — گروه هزینه و برچسب (Cost & Label):",
}

TOTAL_WIZARD_FIELDS = len(WIZARD_FIELDS)

def _preset_edit_diffs(preset: dict, edits: dict) -> list[FieldDiff]:
    """Build dirty-field diffs in WIZARD_FIELDS order (single-field preset_edits flow).

    Old/new display strings come from the canonical
    ``preset_fields.display_value`` owner (D1): stored ``api_key`` resolved +
    masked (never plaintext), staged drafts override and are masked too.
    Empty values render as "—". Labels use the canonical
    FIELD_LABELS map. The per-field table block renders through the shared
    ``render_diffs`` seam (same bold label + vertical قبلی/جدید table as
    ``build_confirm_message``); the edit
    menu keeps its own chrome (title + picker prompt + pending header), so it
    consumes the shared FieldDiff list instead of the confirm-dialog message.
    """
    diffs: list[FieldDiff] = []
    ordered = [f for f in WIZARD_FIELDS if f in edits]
    ordered += [f for f in edits if f not in WIZARD_FIELDS and f in preset_fields.PRESET_FIELDS]
    for field_name in ordered:
        old_str = preset_fields.display_value(preset, field_name)
        new_str = preset_fields.display_value(preset, field_name, edits[field_name])
        diffs.append(
            FieldDiff(
                label=FIELD_LABELS.get(field_name, field_name),
                old=old_str,
                new=new_str,
                field=field_name,
            )
        )
    return diffs

def _validate_wizard_value(field_name: str, raw: str, preset_name: str) -> tuple | None:
    """Validate a wizard field value. Returns (value,) or None on invalid."""
    try:
        if field_name in ("daily_batch_size", "max_concurrency", "max_rpm", "max_tpm", "max_daily_req", "max_output_tokens"):
            v = int(raw)
            if v < 0:
                return None
            return (v,)
        elif field_name in ("timeout_seconds", "temperature"):
            return (float(raw),)
        elif field_name == "is_emergency":
            v = int(raw)
            if v not in (0, 1):
                return None
            return (v,)
        elif field_name == "name":
            v = preset_fields.validate_preset_name(raw)
            if v is None:
                return None
            if v != preset_name and db.get_preset(v):
                return None
            return (v,)
        elif field_name in ("input_cost_per_million", "output_cost_per_million"):
            if raw == "":
                return (None,)
            v = float(raw)
            if v < 0:
                return None
            return (v,)
        elif field_name == "in_fallback_chain":
            v = int(raw)
            if v not in (0, 1):
                return None
            return (v,)
        elif field_name == "priority":
            v = int(raw)
            if v < 0:
                return None
            return (v,)
        elif field_name == "group_label":
            if not raw or len(raw) > MAX_GROUP_LABEL_LEN:
                return None
            return (raw,)
        elif field_name == "reasoning_effort":
            v = raw.strip().lower()
            if v not in ("none", "minimal", "low", "medium", "high", "xhigh"):
                return None
            return (v,)
        else:
            return (raw,)
    except (ValueError, TypeError):
        return None

