#!/usr/bin/env python3
"""Benchmark comparing JSON-long, JSON-mini, and CSV prompt formats.

Usage:
    python scripts/benchmark_format_comparison.py

Requires: openai, python-dotenv, tiktoken (optional)
Set AI_API_KEY in .env or environment.
"""
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

from openai import OpenAI

from dotenv import load_dotenv

load_dotenv()

try:
    import tiktoken
except ModuleNotFoundError:
    tiktoken = None

CLIENT = OpenAI(
    base_url=os.getenv("AI_BASE_URL", "https://api.example.com/v1"),
    api_key=os.getenv("AI_API_KEY", ""),
)
MODEL = "gemini-flash-lite-latest"

INPUT_COST_PER_1M = 0.25
OUTPUT_COST_PER_1M = 1.5

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "benchmark_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

if tiktoken is not None:
    try:
        ENCODING = tiktoken.encoding_for_model("gpt-4")
    except KeyError:
        ENCODING = tiktoken.get_encoding("cl100k_base")
else:
    ENCODING = None


def estimate_tokens(text: str) -> int:
    if ENCODING is not None:
        return len(ENCODING.encode(text))
    return max(1, len(text) // 4)


def get_system_prompt_json_long(lang="en", goal="general", level="beginner") -> str:
    return f"""تو معلم خصوصی زبان {lang} برای فارسی‌زبانان هستی.
هدف کاربر: {goal}. سطح کاربر: {level}.

هر بار یک واژهٔ مفید، کاربردی و نسبتاً رایج انتخاب کن.
خروجی را دقیقاً به صورت JSON خام با کلیدهای زیر برگردان:
{{
  "word": "واژه در زبان {lang}",
  "phonetic": "آوانگاری تلفظ یا رشته خالی",
  "fa_meaning": "معادل کوتاه فارسی",
  "fa_explanation": "توضیح ۱-۲ جمله‌ای به فارسی",
  "synonyms": ["مترادف ۱", "مترادف ۲", "مترادف ۳"],  # اختیاری
  "antonyms": ["متضاد ۱", "متضاد ۲"],  # اختیاری
  "examples": ["جمله نمونه اول به زبان {lang}.", "جمله نمونه دوم به زبان {lang}."],  # اجباری
  "example_translations": ["ترجمه فارسی جمله اول.", "ترجمه فارسی جمله دوم."],  # اجباری
  "grammar_tip": "نکته گرامری کوتاه و کاربردی"  # اختیاری
}}
فقط و فقط یک JSON خام برگردان؛ بدون توضیح اضافه.
توجه: synonyms، antonyms و grammar_tip اختیاری هستند. در صورت نبود معنی‌دار، به‌ترتیب []، [] و "" بگذار."""

def get_system_prompt_json_mini(lang="en", goal="general", level="beginner") -> str:
    return f"""تو معلم خصوصی زبان {lang} برای فارسی‌زبانان هستی.
هدف کاربر: {goal}. سطح کاربر: {level}.

هر بار یک واژهٔ مفید، کاربردی و نسبتاً رایج انتخاب کن.
خروجی را دقیقاً به صورت JSON خام با کلیدهای کوتاه زیر برگردان:
{{
  "w": "واژه در زبان {lang}",
  "ph": "آوانگاری تلفظ یا رشته خالی",
  "m": "معادل کوتاه فارسی",
  "x": "توضیح ۱-۲ جمله‌ای به فارسی",
  "s": ["مترادف ۱", "مترادف ۲", "مترادف ۳"],  # اختیاری
  "a": ["متضاد ۱", "متضاد ۲"],  # اختیاری
  "e": ["جمله نمونه اول به زبان {lang}.", "جمله نمونه دوم به زبان {lang}."],  # اجباری
  "t": ["ترجمه فارسی جمله اول.", "ترجمه فارسی جمله دوم."],  # اجباری
  "g": "نکته گرامری کوتاه و کاربردی"  # اختیاری
}}
فقط و فقط یک JSON خام برگردان؛ بدون توضیح اضافه.
توجه: s، a و g اختیاری هستند. در صورت نبود معنی‌دار، به‌ترتیب []، [] و "" بگذار."""

def get_system_prompt_csv(lang="en", goal="general", level="beginner") -> str:
    return f"""تو معلم خصوصی زبان {lang} برای فارسی‌زبانان هستی.
هدف کاربر: {goal}. سطح کاربر: {level}.

هر بار یک واژهٔ مفید، کاربردی و نسبتاً رایج انتخاب کن.
خروجی را به صورت یک جدول CSV با هدر زیر و با جداکننده '|' برگردان.
برای فیلدهای لیستی (مترادف‌ها، متضادها، مثال‌ها و ترجمه‌ها) از جداکنندهٔ داخلی ';' استفاده کن.
هدر:
word|phonetic|fa_meaning|fa_explanation|synonyms|antonyms|examples|example_translations|grammar_tip

سپس یک سطر با مقادیر متناظر بنویس. تنها یک سطر (به علاوهٔ هدر) برگردان.
فیلدهای synonyms، antonyms و grammar_tip اختیاری هستند؛ در صورت نبود، بخش مربوطه را خالی بگذار (مثلاً || برای فیلدهای خالی).
مثال:
apple|/ˈæp.əl/|سیب|میوه‌ای گرد و شیرین|fruit;snack| |I eat an apple daily.;Apples are red.|من روزانه یک سیب می‌خورم.;سیب‌ها قرمزند.|اسم قابل شمارش
"""


def extract_json(text: str) -> Any:
    import re
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                value, _ = decoder.raw_decode(text[i:])
                return value
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("No JSON found", text, 0)

def parse_csv(text: str) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    if len(lines) < 2:
        raise ValueError("CSV must have at least header and one data row")
    header = [h.strip() for h in lines[0].split('|')]
    rows = []
    for line in lines[1:]:
        values = [v.strip() for v in line.split('|')]
        if len(values) < len(header):
            values += [''] * (len(header) - len(values))
        row = dict(zip(header, values))
        for field in ['synonyms', 'antonyms', 'examples', 'example_translations']:
            if field in row and row[field]:
                row[field] = [item.strip() for item in row[field].split(';') if item.strip()]
            else:
                row[field] = []
        rows.append(row)
    return rows

def validate_card_from_dict(card_data: Dict) -> bool:
    text_fields = ['word', 'fa_meaning', 'fa_explanation']
    for f in text_fields:
        if f not in card_data or not isinstance(card_data[f], str) or not card_data[f].strip():
            return False

    list_fields = ['examples', 'example_translations']
    for f in list_fields:
        if f not in card_data or not isinstance(card_data[f], list) or len(card_data[f]) == 0:
            return False
        if not all(isinstance(item, str) for item in card_data[f]):
            return False

    if len(card_data['examples']) != len(card_data['example_translations']):
        return False

    optional_fields = {
        'synonyms': list,
        'antonyms': list,
        'grammar_tip': str,
        'phonetic': str
    }
    for field, expected_type in optional_fields.items():
        if field in card_data:
            if not isinstance(card_data[field], expected_type):
                return False
            if expected_type == list and not all(isinstance(item, str) for item in card_data[field]):
                return False
    return True

def validate_card_mini(card_data: Dict) -> bool:
    mapping = {
        'w': 'word', 'ph': 'phonetic', 'm': 'fa_meaning', 'x': 'fa_explanation',
        's': 'synonyms', 'a': 'antonyms', 'e': 'examples', 't': 'example_translations',
        'g': 'grammar_tip'
    }
    converted = {}
    for short, long in mapping.items():
        if short in card_data:
            converted[long] = card_data[short]
        elif long in card_data:
            converted[long] = card_data[long]
        else:
            if long in ['word', 'fa_meaning', 'fa_explanation', 'examples', 'example_translations']:
                return False
    return validate_card_from_dict(converted)

def validate_csv_row(row: Dict) -> bool:
    return validate_card_from_dict(row)


def send_request(system_prompt: str, format_name: str, iteration: int) -> Dict:
    user_prompt = "یک واژهٔ جدید به من آموزش بده."
    start_time = time.time()
    try:
        response = CLIENT.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=350
        )
        latency = time.time() - start_time
        content = response.choices[0].message.content or ""
        usage = response.usage if hasattr(response, 'usage') else None
        prompt_tokens = usage.prompt_tokens if usage else estimate_tokens(system_prompt + user_prompt)
        completion_tokens = usage.completion_tokens if usage else estimate_tokens(content)
        total_tokens = usage.total_tokens if usage else prompt_tokens + completion_tokens
    except Exception as e:
        return {
            "format": format_name,
            "iteration": iteration,
            "success": False,
            "error": str(e),
            "content": "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency": 0,
            "parsed": False,
            "validation_passed": False
        }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(OUTPUT_DIR, f"{format_name}_{iteration}_{timestamp}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    parsed = False
    validation_passed = False
    parse_error = None
    if format_name == "json_long":
        try:
            parsed_data = extract_json(content)
            if isinstance(parsed_data, dict):
                parsed = True
                validation_passed = validate_card_from_dict(parsed_data)
        except Exception as e:
            parse_error = str(e)
    elif format_name == "json_mini":
        try:
            parsed_data = extract_json(content)
            if isinstance(parsed_data, dict):
                parsed = True
                validation_passed = validate_card_mini(parsed_data)
        except Exception as e:
            parse_error = str(e)
    elif format_name == "csv":
        try:
            rows = parse_csv(content)
            if rows:
                parsed = True
                validation_passed = validate_csv_row(rows[0])
        except Exception as e:
            parse_error = str(e)

    return {
        "format": format_name,
        "iteration": iteration,
        "success": True,
        "error": None,
        "content": content,
        "filename": filename,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency": latency,
        "parsed": parsed,
        "validation_passed": validation_passed,
        "parse_error": parse_error
    }


def run_tests(iterations_per_format=3):
    formats = [
        ("json_long", get_system_prompt_json_long()),
        ("json_mini", get_system_prompt_json_mini()),
        ("csv", get_system_prompt_csv())
    ]

    all_results = []
    for fmt_name, sys_prompt in formats:
        print(f"\n=== Testing format: {fmt_name} ===")
        for i in range(iterations_per_format):
            print(f"  Iteration {i+1}...")
            result = send_request(sys_prompt, fmt_name, i+1)
            all_results.append(result)
            status = "OK" if result["success"] else "FAIL"
            parsed = "P" if result.get("parsed") else "F"
            valid = "V" if result.get("validation_passed") else "X"
            cost = (result['prompt_tokens']*INPUT_COST_PER_1M/1e6 + 
                    result['completion_tokens']*OUTPUT_COST_PER_1M/1e6)
            print(f"    {status} | Parse:{parsed} | Valid:{valid} | Tokens: {result['total_tokens']} | Cost: ${cost:.6f}")

    summary_file = os.path.join(OUTPUT_DIR, "summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print("\n" + "="*80)
    print("SUMMARY REPORT")
    print("="*80)
    print(f"{'Format':<12} {'Iter':<4} {'Success':<8} {'Parsed':<8} {'Valid':<8} {'InTok':<8} {'OutTok':<8} {'Cost($)':<10} {'Lat(ms)':<10}")
    for r in all_results:
        cost = (r['prompt_tokens']*INPUT_COST_PER_1M/1e6 + r['completion_tokens']*OUTPUT_COST_PER_1M/1e6)
        lat_ms = r.get('latency', 0) * 1000
        print(f"{r['format']:<12} {r['iteration']:<4} {str(r['success']):<8} {str(r.get('parsed', False)):<8} {str(r.get('validation_passed', False)):<8} {r['prompt_tokens']:<8} {r['completion_tokens']:<8} {cost:<10.6f} {lat_ms:<10.1f}")

    print(f"\nResponse files saved in: {OUTPUT_DIR}")
    print(f"Summary saved in: {summary_file}")

if __name__ == "__main__":
    run_tests(iterations_per_format=3)
