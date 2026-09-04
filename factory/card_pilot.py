"""Card-generation pilot: 20 learner cards through the REAL card flow.

Scope: factory research only. No bot/DB/handler changes.

- Sample: 14 words stratified over the lemmas pool CEFR mix (seed 7) +
  6 phrases spread over judged phrase levels. The sample is persisted to
  ``sample.json`` so re-runs render the same cards.
- Generate: one complete learner card per item via the REAL existing
  prompt builder (``services.ai.prompts.custom_word_system_prompt``) and
  the REAL validator (``services.ai.ai.validate_card``). The prompt is
  reused by import, never forked.
- Transport: Zen responses API with the factory key
  (``factory/env_loader`` ``OPENCODE_ZEN_API_KEY``), free model chain,
  per-call timeout 180s, 2.5s sleep between calls, bounded retry (2
  attempts per model), 401/403 aborts loudly, every failure is recorded
  with its error (no silent skip). Progress JSON supports resume.
- Cost: free chain, $0 expected; per-model call counts are recorded.
- Render: Persian RTL gallery HTML with per-card sections.

Usage (owner run, real generation — takes time, ~20 model calls):
    python factory/card_pilot.py --n-words 14 --n-phrases 6
Dry run (no network, no files written):
    python factory/card_pilot.py --dry-run
"""

import argparse
import csv
import html
import json
import pathlib
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

FACTORY_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = FACTORY_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(FACTORY_DIR))

from llm_json import AuthError, extract_json, raise_for_auth  # noqa: E402
from services.ai import prompts as card_prompts  # noqa: E402  (real prompt builder)
from services.ai.ai import CardValidationError, validate_card  # noqa: E402  (real validator)

LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
# Quota order for remainder seats: pool-size order (B-heavy pool).
QUOTA_EXTRAS_ORDER = ["B1", "B2", "A2", "C1", "A1", "C2"]
CEFR_TO_BOT_LEVEL = {
    "A1": "beginner", "A2": "beginner",
    "B1": "intermediate", "B2": "intermediate",
    "C1": "advanced", "C2": "advanced",
}
SEED = 7

ZEN_BASE = "https://opencode.ai/zen/v1"
MODELS = ["muse-spark-1.3-contributor-free", "muse-spark-1.2-contributor-free",
          "ling-3.0-flash-fin-free", "mimo-v2.5-free",
          "nemotron-3.5-lightning-free"]
CALL_TIMEOUT = 180
CALL_SLEEP = 2.5
MAX_ATTEMPTS = 2

DEFAULT_OUT_DIR = "W:/hamzaban_data_factory/pilot/"
DEFAULT_REPORT = "W:/hamzaban_data_factory/reports/card-pilot-2026-09-04.html"
REPAIR_PREFIX = ("Your last reply was not valid JSON. "
                 "Re-send ONLY the JSON object.\n")


def compute_quotas(n, levels=LEVEL_ORDER, extras=QUOTA_EXTRAS_ORDER):
    """Split n seats over CEFR levels: even base + remainder to extras order."""
    base, rem = divmod(n, len(levels))
    quotas = {lv: base for lv in levels}
    for lv in extras[:rem]:
        quotas[lv] += 1
    return quotas


def load_word_pool(path):
    with open(path, encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_phrase_judgements(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sample_words(pool, n_words=14, seed=SEED):
    """Stratified sample of unique lemmas across the pool CEFR mix."""
    by_level = {lv: [] for lv in LEVEL_ORDER}
    seen = set()
    for row in pool:
        lemma = (row.get("lemma") or "").strip()
        cefr = (row.get("cefr") or "").strip()
        if not lemma or lemma in seen or cefr not in by_level:
            continue
        seen.add(lemma)
        by_level[cefr].append(row)
    for lv in by_level:
        by_level[lv].sort(key=lambda r: r["lemma"])
    quotas = compute_quotas(n_words)
    rng = random.Random(seed)
    sample = []
    for lv in LEVEL_ORDER:
        group = by_level[lv]
        want = min(quotas[lv], len(group))
        sample.extend(rng.sample(group, want) if want else [])
    return [{"kind": "word", "text": r["lemma"], "pos": r.get("pos", ""),
             "pool_level": r["cefr"]} for r in sample]


def sample_phrases(judged, n_phrases=6, seed=SEED):
    """Spread sample across judged phrase levels."""
    by_level = {lv: [] for lv in LEVEL_ORDER}
    seen = set()
    for row in judged:
        phrase = (row.get("phrase") or "").strip()
        level = (row.get("verdict_level") or "").strip()
        if not phrase or phrase in seen or level not in by_level:
            continue
        if row.get("failed_flag"):
            continue
        seen.add(phrase)
        by_level[level].append(row)
    for lv in by_level:
        by_level[lv].sort(key=lambda r: r["phrase"])
    quotas = compute_quotas(n_phrases)
    rng = random.Random(seed)
    sample = []
    for lv in LEVEL_ORDER:
        group = by_level[lv]
        want = min(quotas[lv], len(group))
        sample.extend(rng.sample(group, want) if want else [])
    return [{"kind": "phrase", "text": r["phrase"],
             "freq": r.get("freq"), "pool_level": r["verdict_level"]}
            for r in sample]


def item_key(item):
    return ("w:" if item["kind"] == "word" else "p:") + item["text"]


def build_prompts(item):
    """System/user prompts via the REAL learner-card prompt builder."""
    bot_level = CEFR_TO_BOT_LEVEL[item["pool_level"]]
    system = card_prompts.custom_word_system_prompt(
        "en", bot_level, compact=card_prompts.card_output_is_compact())
    return system, item["text"], bot_level


def validate_card_obj(obj):
    """Validate with the REAL card validator. Returns (ok, card, reason)."""
    try:
        return True, validate_card(obj), ""
    except CardValidationError as exc:
        return False, None, str(exc)
    except Exception as exc:  # defensive: never crash the pilot on a card
        return False, None, "%s: %s" % (type(exc).__name__, str(exc)[:200])


def call_responses(api_key, model, system, user, timeout=CALL_TIMEOUT):
    body = json.dumps({"model": model, "input": [
        {"role": "system", "content": system}, {"role": "user", "content": user}],
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": 2000}).encode()
    req = urllib.request.Request(
        ZEN_BASE + "/responses", data=body,
        headers={"Authorization": "Bearer %s" % api_key,
                 "Content-Type": "application/json",
                 "User-Agent": "HamZaban-factory/1.0 (card pilot)",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    parts = []
    for out_item in data.get("output", []):
        for chunk in out_item.get("content", []):
            if chunk.get("type") == "output_text":
                parts.append(chunk.get("text", ""))
    return "".join(parts)


def generate_card(item, api_key, transport=None, model_calls=None):
    """Generate + validate one card. Failures recorded, never raised.

    Only auth failures (401/403 via AuthError) propagate to abort loudly.
    """
    transport = transport or call_responses
    if model_calls is None:
        model_calls = {}
    system, user, bot_level = build_prompts(item)
    record = {"key": item_key(item), "kind": item["kind"], "text": item["text"],
              "pool_level": item["pool_level"], "bot_level": bot_level,
              "model_used": "", "card": None, "valid": False,
              "reason": "", "error": ""}
    last_error = ""
    for model in MODELS:
        for attempt in range(MAX_ATTEMPTS):
            prompt = user if attempt == 0 else REPAIR_PREFIX + user
            try:
                model_calls[model] = model_calls.get(model, 0) + 1
                raw = transport(api_key, model, system, prompt)
                obj = extract_json(raw)
            except AuthError:
                raise
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise_for_auth(exc)  # maps to AuthError, aborts loud
                last_error = "HTTPError %s: %s" % (exc.code, str(exc)[:200])
                continue
            except Exception as exc:
                last_error = "%s: %s" % (type(exc).__name__, str(exc)[:200])
                continue
            ok, card, reason = validate_card_obj(obj)
            if ok:
                record.update(model_used=model, card=card, valid=True)
                return record
            last_error = "validation: %s" % reason
        # next model after exhausting attempts
    record["error"] = last_error
    record["reason"] = last_error
    return record


def git_commit():
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()[:12] or "unknown"
    except Exception:
        return "unknown"


def tehran_now_str():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Tehran")
    except Exception:
        tz = timezone(timedelta(hours=3, minutes=30))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z")


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def render_gallery(cards, meta):
    """Render the Persian RTL gallery HTML for card records."""
    total = len(cards)
    passed = sum(1 for c in cards if c.get("valid"))
    rate = (100.0 * passed / total) if total else 0.0
    calls = meta.get("model_calls", {})
    calls_str = ", ".join("<span class=\"en\">%s: %d</span>" % (esc(m), n)
                          for m, n in calls.items()) or "—"
    sections = []
    for idx, rec in enumerate(cards, 1):
        card = rec.get("card") or {}
        if rec.get("valid"):
            badge = "<span class=\"badge ok\">تأیید شد</span>"
        elif rec.get("card") is not None:
            badge = "<span class=\"badge bad\">نامعتبر: %s</span>" % esc(rec.get("reason"))
        else:
            badge = "<span class=\"badge bad\">خطا: %s</span>" % esc(rec.get("error") or rec.get("reason"))
        kind_fa = "واژه" if rec.get("kind") == "word" else "عبارت"
        examples = "".join(
            "<li><span class=\"en\">%s</span><br>%s</li>"
            % (esc(e), esc(t))
            for e, t in zip(card.get("examples", []),
                            card.get("example_translations", [])))
        syns = ", ".join("<span class=\"en\">%s</span>" % esc(s)
                         for s in card.get("synonyms", [])) or "—"
        ants = ", ".join("<span class=\"en\">%s</span>" % esc(a)
                         for a in card.get("antonyms", [])) or "—"
        phon = card.get("phonetic", {})
        ipa = esc(phon.get("ipa", "") if isinstance(phon, dict) else phon)
        raw_json = esc(json.dumps(card, ensure_ascii=False) if card else "")
        sections.append(
            "<section class=\"card\" id=\"card-%d\">\n"
            "<h2><span class=\"en\">%s</span> <span class=\"kind\">(%s)</span> %s</h2>\n"
            "<p>سطح برچسب: <b>%s</b> ـ سطح کارت: <b>%s</b> ـ مدل: "
            "<span class=\"en\">%s</span></p>\n"
            "<p><b>معنی:</b> %s</p>\n"
            "<p><b>توضیح:</b> %s</p>\n"
            "<p><b>تلفظ:</b> <span class=\"en\">%s</span></p>\n"
            "<p><b>مثال‌ها:</b></p>\n<ol>%s</ol>\n"
            "<p><b>مترادف:</b> %s</p>\n<p><b>متضاد:</b> %s</p>\n"
            "<p><b>نکته گرامری:</b> %s</p>\n"
            "<details><summary>JSON خام</summary>"
            "<pre class=\"en\">%s</pre></details>\n"
            "</section>"
            % (idx, esc(rec.get("text")), kind_fa, badge,
               esc(rec.get("pool_level")), esc(rec.get("bot_level")),
               esc(rec.get("model_used") or "—"),
               esc(card.get("fa_meaning", "—")), esc(card.get("fa_explanation", "—")),
               ipa, examples or "<li>—</li>", syns, ants,
               esc(card.get("grammar_tip", "—") or "—"), raw_json))
    return (
        "<!DOCTYPE html>\n<html lang=\"fa\" dir=\"rtl\">\n<head>\n"
        "<meta charset=\"utf-8\">\n<title>گذرنامه کارت‌ها</title>\n"
        "<link rel=\"stylesheet\" "
        "href=\"https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css\">\n"
        "<style>\n"
        "body{font-family:Vazirmatn,Tahoma,sans-serif;max-width:900px;margin:auto;padding:1em;}\n"
        ".en{font-family:Georgia,serif;direction:ltr;unicode-bidi:embed;}\n"
        ".card{border:1px solid #ccc;border-radius:8px;padding:1em;margin:1em 0;}\n"
        ".badge{border-radius:4px;padding:0.1em 0.5em;font-size:0.85em;}\n"
        ".ok{background:#d9f2d9;} .bad{background:#f7d9d9;}\n"
        "pre{white-space:pre-wrap;}\n"
        "</style>\n</head>\n<body>\n"
        "<h1>گذرنامه کارت‌ها (آزمایشی)</h1>\n"
        "<p>تاریخ تهران: %s ـ commit: <span class=\"en\">%s</span></p>\n"
        "<p>کارت‌ها: %d ـ تأییدشده: %d ـ نرخ قبولی: %.1f%%</p>\n"
        "<p>فراخوانی مدل‌ها: %s ـ هزینه مورد انتظار: $0 (زنجیره رایگان)</p>\n"
        "%s\n</body>\n</html>"
        % (esc(meta.get("date_tehran", "")), esc(meta.get("commit", "")),
           total, passed, rate, calls_str, "\n".join(sections)))


def load_cards_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Card-gen pilot (factory research)")
    ap.add_argument("--n-words", type=int, default=14)
    ap.add_argument("--n-phrases", type=int, default=6)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--report", default=DEFAULT_REPORT)
    ap.add_argument("--word-pool", default=str(
        REPO_ROOT / "factory" / "packs" / "en" / "lemmas_10k.csv"))
    ap.add_argument("--phrase-log", default=(
        "W:/hamzaban_data_factory/fixtures/phrase_judge_log.jsonl"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    pool = load_word_pool(args.word_pool)
    judged = load_phrase_judgements(args.phrase_log)
    sample = sample_words(pool, args.n_words, args.seed)
    sample += sample_phrases(judged, args.n_phrases, args.seed)
    if len(sample) != args.n_words + args.n_phrases:
        print("warning: short sample %d (pool gaps)" % len(sample))

    out_dir = pathlib.Path(args.out_dir)
    if args.dry_run:
        print("dry-run: %d words + %d phrases sampled, no files written, "
              "no network calls" % (args.n_words, args.n_phrases))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    sample_path = out_dir / "sample.json"
    if sample_path.exists():
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        print("reusing persisted sample (%d items)" % len(sample))
    else:
        sample_path.write_text(json.dumps(sample, ensure_ascii=False),
                               encoding="utf-8")

    sys.path.insert(0, str(FACTORY_DIR))
    from env_loader import load_factory_env
    env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
    api_key = env["OPENCODE_ZEN_API_KEY"]
    if not api_key:
        sys.exit("no OPENCODE_ZEN_API_KEY in factory/.env")

    prog_path = out_dir / "progress.json"
    prog = json.loads(prog_path.read_text(encoding="utf-8")) if prog_path.exists() else {}
    done = prog.get("done", {})
    model_calls = prog.get("model_calls", {})
    for item in sample:
        key = item_key(item)
        if key in done:
            continue
        rec = generate_card(item, api_key, model_calls=model_calls)
        done[key] = rec
        prog_path.write_text(json.dumps(
            {"done": done, "failed": [k for k, v in done.items() if not v.get("valid")],
             "model_calls": model_calls}, ensure_ascii=False), encoding="utf-8")
        print("%s %s valid=%s model=%s" % (
            rec["kind"], rec["text"], rec["valid"], rec["model_used"] or "none"))
        time.sleep(CALL_SLEEP)

    records = [done[item_key(item)] for item in sample]
    (out_dir / "cards.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8")
    meta = {"date_tehran": tehran_now_str(), "commit": git_commit(),
            "model_calls": model_calls}
    report_path = pathlib.Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_gallery(records, meta), encoding="utf-8")
    passed = sum(1 for r in records if r.get("valid"))
    print("pilot done: %d/%d valid, calls=%s, report=%s"
          % (passed, len(records), model_calls, report_path))
    return 0


if __name__ == "__main__":
    main()
