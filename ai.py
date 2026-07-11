import json
import re

from openai import OpenAI

from config import DEFAULT_AI_BASE_URL, DEFAULT_AI_API_KEY, DEFAULT_AI_MODEL
import db


def _client() -> OpenAI:
    base_url = db.get_setting("ai_base_url", DEFAULT_AI_BASE_URL)
    api_key = db.get_setting("ai_api_key", DEFAULT_AI_API_KEY)
    return OpenAI(base_url=base_url, api_key=api_key)


def _model() -> str:
    return db.get_setting("ai_model", DEFAULT_AI_MODEL)


def _extract_json(text: str) -> dict:
    text = text.strip()
    # حذف بلاک کد
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    # پیدا کردن بزرگ‌ترین آبجکت JSON
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    return json.loads(text)


def ask_json(system_prompt: str, user_prompt: str = "بساز.") -> dict:
    """یک تماس با مدل زبانی می‌گیرد و انتظار دارد خروجی JSON خام باشد."""
    client = _client()
    resp = client.chat.completions.create(
        model=_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.9,
    )
    content = resp.choices[0].message.content or ""
    return _extract_json(content)
