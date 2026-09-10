"""Blind 4-way S2 judge test: GLM (recorded) vs 2x Gemini Lite (direct)
vs Cohere North Mini (OpenRouter :free) on the frozen accept50 set.

Same prompt for every contender (precard_pipeline._judge_prompt), one
retry on invalid JSON only, three consecutive 429s abort the run
(owner rule: stop, never long-backoff). GLM needs no new calls:
its picks are read from the recorded pilot200glm s2.json baseline.

Keys (never logged): os.environ, then factory/.env, then
tools/egress/.env (owner layout). Network via injectable http_post
for hermetic tests. Runner owns pacing + progress resume; analysis
(Cohen's k vs GLM, JSON-valid rate) happens offline on the out file.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import card_pilot
import precard_pipeline

GOOGLE_URL = ("https://generativelanguage.googleapis.com/v1beta/"
              "models/%s:generateContent")
OR_URL = "https://openrouter.ai/api/v1/chat/completions"
BATCH = 8
RETRY_PREFIX = precard_pipeline.RETRY_PREFIX


class RateLimited(Exception):
    """Three consecutive 429 batches — stop, do not backoff."""


def _parse_env_file(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if key and val and key not in out:
                    out[key] = val
    except OSError:
        pass
    return out


def load_keys(env, factory_env_path, egress_env_path):
    """GOOGLE_AI_API_KEY / OPENROUTER_API_KEY: env > factory > egress."""
    merged = {}
    merged.update(_parse_env_file(egress_env_path))
    merged.update(_parse_env_file(factory_env_path))
    merged.update({k: v for k, v in (env or {}).items() if v})
    return {k: merged.get(k, "") for k in
            ("GOOGLE_AI_API_KEY", "OPENROUTER_API_KEY")}


def _default_post(url, payload, timeout, headers=None):
    heads = {"Content-Type": "application/json"}
    heads.update(headers or {})
    req = urllib.request.Request(url, data=payload, headers=heads)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _strip_fences(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rsplit("```", 1)[0].strip():
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _fetch_data(call_once):
    """One attempt + one retry on invalid JSON.

    Returns parsed data or None (fail-closed). HTTP 429 propagates
    (runner counts strikes); other HTTP errors propagate.
    """
    for attempt in (0, 1):
        raw = call_once(RETRY_PREFIX if attempt else "")
        try:
            return json.loads(_strip_fences(raw))
        except ValueError:
            continue
    return None


def google_judge(api_key, model, chunk, prompt, anchor_map,
                 http_post=None, timeout=90):
    """Gemini-direct judge: thinking MINIMAL, JSON mime, prompt verbatim."""
    post = http_post or _default_post
    url = (GOOGLE_URL % model) + "?key=" + api_key

    def once(prefix):
        body = {"contents": [{"parts": [{"text": prefix + prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingLevel": "MINIMAL"}}}
        raw = post(url, json.dumps(body).encode(), timeout)
        env = json.loads(raw.decode("utf-8", "replace"))
        try:
            return env["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return ""

    try:
        data = _fetch_data(once)
    except urllib.error.HTTPError:
        raise
    if data is None:
        return {}
    return precard_pipeline._judge_validate(data, chunk, anchor_map) or {}


def openrouter_judge(api_key, model, chunk, prompt, anchor_map,
                     http_post=None, timeout=90):
    """OpenRouter judge: reasoning effort none + excluded."""
    post = http_post or (
        lambda url, payload, timeout: _default_post(
            url, payload, timeout,
            {"Authorization": "Bearer " + api_key}))

    def once(prefix):
        body = {"model": model,
                "messages": [{"role": "user",
                              "content": prefix + prompt}],
                "reasoning": {"effort": "none", "exclude": True}}
        raw = post(OR_URL, json.dumps(body).encode(), timeout)
        env = json.loads(raw.decode("utf-8", "replace"))
        try:
            return env["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""

    try:
        data = _fetch_data(once)
    except urllib.error.HTTPError:
        raise
    if data is None:
        return {}
    return precard_pipeline._judge_validate(data, chunk, anchor_map) or {}


def fill_missing_windows(items, anchor_map, kaikki_index=None,
                       kaikki_raw=None, rank_fn=None):
    """Same S1 windows for every contender: compute windows missing
    from the recorded anchor windows (dropped/proper items) via the pipeline
    S1 ranker. rank_fn(item, index, read_entry) injectable (tests)."""
    missing = [it for it in items
               if precard_pipeline.item_key(it) not in anchor_map]
    if not missing:
        return dict(anchor_map)
    rank = rank_fn or precard_pipeline.anchor_rank_item
    if rank_fn is None:
        index = kaikki_index or card_pilot.load_kaikki_index(
            card_pilot.DEFAULT_KAIKKI_INDEX)
        raw = kaikki_raw or card_pilot.DEFAULT_KAIKKI_RAW

        def read_entry(row, _raw=raw):
            return card_pilot.read_kaikki_entry(
                _raw, row["offset"], row["length"])
    else:
        index, read_entry = None, None
    out = dict(anchor_map)
    for item in missing:
        try:
            out[precard_pipeline.item_key(item)] = rank(
                item, index, read_entry)
        except Exception:
            out[precard_pipeline.item_key(item)] = {"candidates": []}
    return out


def run_model(tag, items, anchor_map, progress_path, judge_fn,
              batch=BATCH, pace=4.0, sleep_fn=None):
    """Judge every item (batched S2 prompts), resume from progress.

    judge_fn(chunk, prompt) -> validated {key: {...}}. Three
    consecutive HTTP-429 batches raise RateLimited.
    """
    sleep = sleep_fn or time.sleep
    try:
        with open(progress_path, encoding="utf-8") as handle:
            progress = json.load(handle)
    except (OSError, ValueError):
        progress = {}
    done = dict(progress.get(tag, {}))
    todo = [it for it in items
            if precard_pipeline.item_key(it) not in done]
    total = len(items)
    print("[blind50 %s] start: %d items (%d todo, %d kept)" % (
        tag, total, len(todo), total - len(todo)), flush=True)
    strikes = 0
    queue = list(todo)
    n_batches = (len(queue) + batch - 1) // batch if queue else 0
    batch_no = 0
    while queue:
        chunk, queue = queue[:batch], queue[batch:]
        prompt = precard_pipeline._judge_prompt(chunk, anchor_map)
        try:
            valid = judge_fn(chunk, prompt)
        except urllib.error.HTTPError as exc:
            if getattr(exc, "code", None) != 429:
                raise
            strikes += 1
            if strikes >= 3:
                print("[blind50 %s] batch %d/%d: 429 (strike %d/3, "
                      "stopping)" % (tag, batch_no + 1, n_batches, strikes),
                      flush=True)
                raise RateLimited(
                    "3 consecutive 429 batches — stopping")
            print("[blind50 %s] batch %d/%d: 429 (strike %d/3, "
                  "re-queued)" % (tag, batch_no + 1, n_batches, strikes),
                  flush=True)
            queue.extend(chunk)  # re-queue: never silently drop
            continue
        batch_no += 1
        strikes = 0
        for item in chunk:
            key = precard_pipeline.item_key(item)
            done[key] = valid.get(key, {"sense_id": "", "gloss": ""})
        progress[tag] = done
        _atomic_write(progress_path, progress)
        print("[blind50 %s] batch %d/%d: done=%d/%d" % (
            tag, batch_no, n_batches, len(done), total), flush=True)
        sleep(pace)
    print("[blind50 %s] finished: done=%d/%d" % (
        tag, len(done), total), flush=True)
    return done


def _atomic_write(path, payload):
    """Crash-safe progress write (tmp + replace, never partial JSON)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Blind 4-way S2 test.")
    ap.add_argument("--accept", required=True)
    ap.add_argument("--s1", required=True,
                    help="recorded s1.json windows (pilot200glm/progress)")
    ap.add_argument("--glm-s2", required=True,
                    help="recorded GLM baseline (pilot200glm s2.json)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--progress", required=True)
    ap.add_argument("--models", default="g35,g31,north",
                    help="subset of g35,g31,north (glm baseline free)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pace", type=float, default=4.0)
    ap.add_argument("--kaikki-index", default=None)
    ap.add_argument("--kaikki-raw", default=None)
    args = ap.parse_args(argv)

    with open(args.accept, encoding="utf-8") as handle:
        items = json.load(handle)
    with open(args.s1, encoding="utf-8") as handle:
        anchor_map = json.load(handle)["done"]
    with open(args.glm_s2, encoding="utf-8") as handle:
        glm = json.load(handle)["done"]

    # Identical candidate windows for every contender (recorded +
    # live-filled for items the recorded run dropped).
    anchor_map = fill_missing_windows(items, anchor_map, args.kaikki_index,
                                 args.kaikki_raw)

    here = os.path.dirname(os.path.abspath(__file__))
    keys = load_keys(
        os.environ, os.path.join(here, ".env"),
        os.path.join(here, "..", "tools", "egress", ".env"))
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    specs = {"g35": ("GOOGLE_AI_API_KEY", "gemini-3.5-flash-lite",
                     google_judge),
             "g31": ("GOOGLE_AI_API_KEY", "gemini-3.1-flash-lite",
                     google_judge),
             "north": ("OPENROUTER_API_KEY",
                       "cohere/north-mini-code:free", openrouter_judge)}
    unknown = [m for m in models if m not in specs]
    if unknown:
        raise SystemExit("unknown --models: %s (choose from %s)" % (
            ",".join(unknown), ",".join(sorted(specs))))
    result = {"glm": {k: {"sense_id": (v or {}).get("sense_id", "")}
                      for k, v in glm.items()}}
    for tag in models:
        key_name, model, fn = specs[tag]
        if args.dry_run:
            print("dry-run %s %s (%d items)" % (tag, model, len(items)))
            continue
        api_key = keys[key_name]
        if not api_key:
            raise KeyError("missing key: %s" % key_name)
        result[tag] = run_model(
            tag, items, anchor_map, args.progress,
            lambda chunk, prompt, _fn=fn, _k=api_key, _m=model: _fn(
                _k, _m, chunk, prompt, anchor_map),
            pace=args.pace)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    print("wrote %s (%d models)" % (args.out, len(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
