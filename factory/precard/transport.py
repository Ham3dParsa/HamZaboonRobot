"""Network plumbing for the precard line (sole owner in new home).

Vendored frozen with provenance (precard line R1-R6, 2026-09-14):
KeyRing/RateLimited/write_progress from factory/lexicon/phrase_judge;
telemetry recorders from factory/core/telemetry; RunLogger +
_unwrap_transport_result from factory/pipeline/card_pilot; rotation,
consts, and AvalAI/Google transports from factory/pipeline/
precard_pipeline; the three Zen leg transports (+ their SYS texts, one
shared ZEN_BASE) from the v14/v15/v16b archive scripts.
AuthError/extract_json/raise_for_auth are IMPORTED from
factory/core/llm_json (single class shared with phrase_judge and
card_pilot, so a transport-raised auth abort is caught by every
``except AuthError`` in the line). RateLimited stays defined here:
phrase_judge imports KeyRing from this module, so importing its
RateLimited back would cycle; every precard handler catches this
module's RateLimited, which is the class ProviderCooldown extends.
The classify error-taxonomy stays single-sourced in llm_json.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from factory.core.llm_json import (
    ABORT, COOLDOWN_SWITCH, ROTATE, AuthError, classify,
    extract_json, raise_for_auth)
# AuthError/extract_json/raise_for_auth are re-exported here so the
# existing ``from factory.precard.transport import ...`` seams in
# topics/judge/pipeline/net keep working on the single llm_json class.
from factory.precard.prompts import JUDGE_SYS


GOOGLE_PRECARD_MODEL = "gemini-3.5-flash-lite"


GOOGLE_MODELS_URL = ("https://generativelanguage.googleapis.com/v1beta/"
                     "models/%s:generateContent")


AVALAI_PRECARD_MODEL = "glm-5.3-flash"


AVALAI_CHAT_URL = "https://api.avalai.ir/v1/chat/completions"


RETRY_PREFIX = ("Your last reply was not valid JSON. "
                "Re-send ONLY the JSON object.\n")


ROTATE_PAUSE = 5.0


MAX_ATTEMPTS = 2


OUTCOMES = ("ok", "invalid", "fallback", "error", "auth")


def _read_egress_env_key(path, key):
    """Single key from a dotenv file (owner layout fallback); "" when
    absent. Never logs values — the caller only checks emptiness."""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip().strip("'\"")
    except OSError:
        pass
    return ""


def _google_payload(user_text):
    """Pure Gemini REST payload (H5: temperature 0.0 locks determinism)."""
    return {
        "contents": [{"parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingLevel": "MINIMAL"}},
    }


def _google_remap_transport(default_model):
    """Adapter letting Zen-model loops run unchanged on Google direct.

    Same shape as the AvalAI remap: substitutes the leg model for any
    requested name; extra leading texts are prepended. Telemetry keeps
    the requested (Zen) name — runs are told apart by progress dirs.
    """
    def wrap(api_key, model, *texts):
        text = "\n\n".join(t for t in texts if t)
        return _google_chat_transport(api_key, default_model, text)
    return wrap


def _google_chat_transport(api_key, model, user_text):
    """Google-direct transport (Gemini REST): (text, None).

    thinkingLevel MINIMAL (closest to off on 3.x Lites) +
    responseMimeType JSON. HTTP errors propagate untouched (429 is
    rotation fuel; the shared classify table owns meaning). No usage
    counters on this API shape -> None (telemetry records latency).
    """
    payload = json.dumps(_google_payload(user_text)).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_MODELS_URL % model, data=payload,
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        text = ""
    return text or "", None


def _avalai_remap_transport(default_model):
    """Adapter letting Zen-model loops run unchanged on AvalAI.

    S0b/S3/S4 loops live in card_pilot (shared with card-gen — untouched
    by design) and request Zen model names. This wraps
    _avalai_chat_transport, substituting the precard model for any
    requested name; extra leading texts (the inflect sys prompt) are
    prepended. Telemetry keeps the requested (Zen) name — runs are told
    apart by their progress dirs, not by these labels.
    Cost bound (#4 review): a fully-failing item repeats the SAME paid
    model through the loop (S4 up to 5 models x 2 attempts, S0b 2 x 2);
    worst case ~$0.001/item at GLM rates, only on total failure. PENDING
    owner cost sign-off; single-model collapse is follow-up.
    """
    def wrap(api_key, model, *texts):
        text = "\n\n".join(t for t in texts if t)
        return _avalai_chat_transport(api_key, default_model, text)
    return wrap


def _avalai_chat_transport(api_key, model, user_text):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": user_text}],
        "temperature": 0,
        # reasoning_effort low in BOTH places (verified 2026-09-06:
        # nested-only, top-only, and both all return reasoning_tokens=0;
        # either alone works, both together is belt-and-suspenders).
        "reasoning_effort": "low",
        "extra_body": {"reasoning_effort": "low"},
    }).encode("utf-8")
    req = urllib.request.Request(
        AVALAI_CHAT_URL, data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    msg = ((data.get("choices") or [{}])[0].get("message", {})
           if isinstance(data, dict) else {})
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    return (msg.get("content") or ""), (usage if isinstance(usage, dict)
                                        else None)


def _unwrap_transport_result(res):
    """Split a transport reply into (raw_text, usage-dict-or-None)."""
    if isinstance(res, tuple) and len(res) == 2:
        usage = res[1] if isinstance(res[1], dict) else None
        return res[0], usage
    return res, None


class RunLogger:
    """V7 compact run.log writer (stage start/end + counts + timings)."""

    def __init__(self, path, namer=None):
        import atexit as _atexit
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "w", encoding="utf-8")
        self._starts = {}
        # Human voice: namer(stage)->display name. run.log is read by
        # humans, so callers pass stage labels; ids stay in data files.
        self._namer = namer
        # Exception-safe close: every exit path (raise/sys.exit) still
        # releases the handle at interpreter shutdown; close() is
        # idempotent so the explicit happy-path close stays as-is.
        _atexit.register(self.close)

    def log(self, line):
        if self._handle.closed:
            # Reopen in append mode: close() may already have run in a
            # finally block while the caller still has summary lines.
            self._handle = open(self.path, "a", encoding="utf-8")
        self._handle.write(line + "\n")
        self._handle.flush()

    def _shown(self, stage):
        try:
            return self._namer(stage) if self._namer else stage
        except (TypeError, LookupError):
            return stage

    def stage_start(self, stage):
        self._starts[stage] = time.perf_counter()
        self.log("stage %s start" % self._shown(stage))

    def stage_end(self, stage, ok=0, fail=0):
        start = self._starts.get(stage, time.perf_counter())
        secs = time.perf_counter() - start
        self.log("stage %s end ok=%d fail=%d secs=%.2f"
                 % (self._shown(stage), ok, fail, secs))

    def close(self):
        try:
            self._handle.close()
        except Exception:
            pass


def _rotating_llm_transport(transport, sleep_fn, state, ring,
                             provider="zen", key_var="",
                             file_label="factory/.env"):
    """Wrap an (api_key, model, user_text) transport with KeyRing rotation.

    Error meaning comes from the shared classify table
    (factory.core.llm_json owns it): ROTATE (429/quota) pauses briefly,
    rotates to the next key, and retries the SAME call. COOLDOWN_SWITCH
    (project-level quota, e.g. Google RESOURCE_EXHAUSTED) raises
    ProviderCooldown after exactly one attempt with NO rotation —
    same-project key rotation is forbidden by the taxonomy (provider
    switching is the caller's job, arriving with P2 LEG_FALLBACKS).
    ABORT
    (401/403) raises AuthError naming the key variable and file with
    no further attempts. Transient 5xx/timeout (the taxonomy's single
    retry row) is intentionally NOT retried in this wrapper: it
    propagates to the caller, which fails the item closed, and the
    next run retries it via resume. Anything else propagates untouched.
    When EVERY key fails consecutively, raises RateLimited —
    the S4 caller converts it to SystemExit AFTER flushing progress
    (OC must-fix: raising SystemExit here bypassed the flush and lost
    in-memory s4.done entries). card_pilot.assign_topic re-raises
    RateLimited through its fail-closed handler for the same reason.
    """
    def wrap(_api_key, model, user_text):
        while True:
            try:
                out = transport(ring.current, model, user_text)
                ring.used = 0
                return out
            except urllib.error.HTTPError as exc:
                action = _action_for_http_error(exc, provider)
                if action == COOLDOWN_SWITCH:
                    _note_backoff(state, "%s/s4" % model, [],
                                  COOLDOWN_SWITCH)
                    raise ProviderCooldown(
                        "provider-level quota on %s (project blocked) — "
                        "same-project key rotation forbidden, switch "
                        "provider or server and re-run" % provider)
                if action != ROTATE:
                    if action == ABORT:
                        _abort_auth(exc, key_var, file_label)
                    raise
                _note_backoff(state, "%s/s4" % model, [ROTATE_PAUSE],
                              "rotating")
                sleep_fn(ROTATE_PAUSE)
                if ring.rotate():
                    continue
                _note_backoff(state, "%s/s4" % model, [],
                              "all-keys-429-stop")
                raise RateLimited(
                    "all keys 429 (provider quotas exhausted) — re-run "
                    "later (progress flushed, resume safe)")
    return wrap


def _http_error_body(exc):
    """Best-effort HTTPError body for classify ("" when unreadable).

    Never raises: fake transports and exhausted streams surface as an
    empty body, and the status-code rules still decide correctly.
    """
    try:
        raw = exc.read()
    except Exception:
        return ""
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8", "replace")
        except Exception:
            return ""
    return str(raw or "")


def _action_for_http_error(exc, provider="zen"):
    """classify() action for one HTTPError (table lives in llm_json)."""
    try:
        code = getattr(exc, "code", None)
    except Exception:
        code = None
    try:
        return classify(code, _http_error_body(exc), provider)
    except Exception:
        return None


def _abort_auth(exc, key_var="", file_label="factory/.env"):
    """Loud auth stop: AuthError naming the key variable and file.

    No values, no retries, no fallback — the caller aborts and the
    operator re-checks the named credential. file_label names the env
    file actually searched (threaded from the wrapper); it defaults to
    the standard factory env file for direct callers.
    """
    code = getattr(exc, "code", None)
    hint = key_var.strip() if key_var and key_var.strip() else "keys"
    raise AuthError(
        "provider auth failed (HTTP %s): check %s in %s — "
        "aborting with no silent fallback" % (code, hint, file_label))


def _note_backoff(state, label, waits, outcome):
    state.setdefault("backoffs", []).append(
        {"label": label, "waits": list(waits), "outcome": outcome})


def _tele_tokens(usage):
    """Token pair from a surfaced usage dict (None-tolerated)."""
    if isinstance(usage, dict):
        return extract_usage(usage)
    return None, None


def _call_with_rotation(transport, ring, model, text, sleep_fn, state,
                        label, provider="zen", key_var="",
                        file_label="factory/.env"):
    """One LLM call with phrase_judge KeyRing rotation on HTTP 429.

    Error meaning comes from the shared classify table
    (factory.core.llm_json owns it): ROTATE (429/quota) pauses briefly,
    rotates to the next key, and retries the SAME call. COOLDOWN_SWITCH
    (project-level quota, e.g. Google RESOURCE_EXHAUSTED) raises
    ProviderCooldown after exactly one attempt with NO rotation.
    ABORT (401/403) raises AuthError naming the
    key variable and file with no further attempts. Transient 5xx/
    timeout (the taxonomy's single retry row) is intentionally NOT
    retried in this wrapper: it propagates to the caller, which fails
    the item closed, and the next run retries it via resume.
    Anything else propagates to the caller.
    Success resets the ring streak (same F1 rule as
    phrase_judge.call_with_backoff). When EVERY key fails
    consecutively, records the stop event and raises RateLimited — the
    caller flushes progress and STOPS for a VPN-server switch. Auth
    (401/403) and other errors propagate to the caller.
    Returns (raw_text, usage-dict-or-None): tuple (text, usage)
    transports surface token counts (None-tolerated); plain-text
    transports yield None.
    """
    while True:
        try:
            out = transport(ring.current, model, text)
            ring.used = 0
            if isinstance(out, tuple) and len(out) == 2:
                return out[0], (out[1] if isinstance(out[1], dict)
                                 else None)
            return out, None
        except urllib.error.HTTPError as exc:
            action = _action_for_http_error(exc, provider)
            if action == COOLDOWN_SWITCH:
                _note_backoff(state, label, [], COOLDOWN_SWITCH)
                raise ProviderCooldown(
                    "provider-level quota on %s (project blocked) — "
                    "same-project key rotation forbidden, switch "
                    "provider or server and re-run" % provider)
            if action != ROTATE:
                if action == ABORT:
                    _abort_auth(exc, key_var, file_label)
                raise
            _note_backoff(state, label, [ROTATE_PAUSE], "rotating")
            sleep_fn(ROTATE_PAUSE)
            if ring.rotate():
                continue
            _note_backoff(state, label, [], "all-keys-429-stop")
            raise RateLimited(
                "all keys 429 (provider quotas exhausted) — re-run later")


def write_summary(path, calls):
    """Write telemetry_summary.json (summary + record count)."""
    summary = summarize(calls)
    dest = pathlib.Path(str(path))
    if str(dest.parent) not in ("", "."):
        dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False))
    return summary


def summarize(calls):
    """Aggregate {by_stage, by_model, by_key_idx} (None tokens count 0)."""
    summary = {"by_stage": {}, "by_model": {}, "by_key_idx": {}}
    for call in calls or []:
        for dim, raw in (("by_stage", call.get("stage")),
                         ("by_model", call.get("model")),
                         ("by_key_idx", call.get("key_idx"))):
            key = str(raw)
            bucket = summary[dim].setdefault(key, _bucket())
            bucket["calls"] += 1
            for token_key in ("prompt_tokens", "completion_tokens"):
                try:
                    number = call.get(token_key)
                    bucket[token_key] += int(number) if number is not None \
                        else 0
                except (TypeError, ValueError):
                    pass
    summary["records"] = len(list(calls or []))
    return summary


def _bucket():
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def record_call(store, *, stage, batch_id, key_idx, model,
                prompt_tokens=None, completion_tokens=None,
                latency_s=0.0, outcome="ok", http_status=None):
    """Append one call record. ``key_idx`` MUST be an int (never a key).

    Raises ``TypeError`` when ``key_idx`` is not an int — a literal key
    string must never reach the persisted file.
    """
    if not isinstance(key_idx, int) or isinstance(key_idx, bool):
        raise TypeError("key_idx must be an int (key values never persist)")
    try:
        batch_id = int(batch_id)
    except (TypeError, ValueError):
        batch_id = 0
    try:
        latency = float(latency_s or 0.0)
    except (TypeError, ValueError):
        latency = 0.0
    entry = {
        "ts": now_ts(),
        "stage": str(stage or ""),
        "batch_id": batch_id,
        "key_idx": key_idx,
        "model": str(model or ""),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_s": round(latency, 3),
        "outcome": outcome if outcome in OUTCOMES else "error",
        "http_status": http_status,
    }
    store.append(entry)
    return entry


def now_ts() -> str:
    """UTC ISO timestamp for one record."""
    return datetime.now(timezone.utc).isoformat()


def extract_usage(data) -> tuple:
    """Probe a Zen responses payload for token usage.

    Accepts the full response JSON (``{"usage": {...}}``) or a bare
    usage dict. Probes ``input_tokens``/``output_tokens`` first, then
    ``prompt_tokens``/``completion_tokens``. Anything missing or
    non-numeric -> ``None`` (tolerated, never raises).
    """
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict) and isinstance(data, dict):
        usage = data
    if not isinstance(usage, dict):
        return None, None

    def _num(*names):
        for name in names:
            try:
                value = usage.get(name)
            except AttributeError:
                continue
            if isinstance(value, bool):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            return int(number)
        return None

    return (_num("input_tokens", "prompt_tokens"),
            _num("output_tokens", "completion_tokens"))


def write_progress(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
    os.replace(tmp, path)


class RateLimited(Exception):
    """All keys 429 — caller flushes progress and exits for a server switch."""


class ProviderCooldown(RateLimited):
    """Project-level quota (cool-down-and-switch, e.g. Google RESOURCE_EXHAUSTED).

    The llm_json taxonomy forbids same-project key rotation here: rotating
    would burn every key on the same blocked project. Raised after exactly
    one attempt with no rotation. A RateLimited subclass, so every existing
    ``except RateLimited`` caller flushes progress and stops safely;
    the message + cool-down backoff outcome tell the operator to
    switch provider (or server) instead of re-running the same leg.
    True automatic provider-switching arrives with P2 LEG_FALLBACKS.
    """


class KeyRing:
    """Round-robin keys. rotate() on 429; exhausted after a full circle.

    Single owner for the precard line (P0 net core):
    factory.lexicon.phrase_judge imports this class instead of keeping
    its own copy; factory.precard.net builds its leg rings from it."""

    def __init__(self, keys):
        self.keys = [k for k in keys if k]
        if not self.keys:
            raise ValueError(
                "KeyRing needs at least one non-empty key "
                "(set OPENCODE_ZEN_API_KEY in factory/.env)")
        self.idx = 0
        self.used = 0

    @property
    def current(self):
        return self.keys[self.idx]

    def rotate(self):
        """Move to next key. Returns False when every key just 429'd."""
        if not self.keys:
            return False
        self.used += 1
        self.idx = (self.idx + 1) % len(self.keys)
        if self.used >= len(self.keys):
            self.used = 0
            return False
        return True


CALL_TIMEOUT = 180

# Shared Zen base (identical in all three archive leg scripts; verified).
ZEN_BASE = "https://opencode.ai/zen/v1"


## Generic Zen direct transport (frozen from factory/pipeline/card_pilot.call_responses; S0b default leg).
def zen_direct_transport(api_key, model, system, user, timeout=CALL_TIMEOUT):
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


# Frozen from factory/archive/v14_v16/run_v14_phase3_judge.call_responses
# (provenance: precard line, 2026-09-15): the default Zen sense-judge
# transport on the shared 3-arg (api_key, model, user_text) seam.
# pipeline.main falls back to it when no judge transport is injected.
def zen_judge_transport(api_key, model, user_text, timeout=180):
    body = json.dumps({"model": model, "input": [
        {"role": "system", "content": JUDGE_SYS},
        {"role": "user", "content": user_text}],
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": 4000}).encode()
    req = urllib.request.Request(
        ZEN_BASE + "/responses", data=body,
        headers={"Authorization": "Bearer %s" % api_key,
                 "Content-Type": "application/json",
                 "User-Agent": "HamZaban-factory/1.0 (research lexicon judge)",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    parts = []
    for item in data.get("output", []):
        for chunk in item.get("content", []):
            if chunk.get("type") == "output_text":
                parts.append(chunk.get("text", ""))
    return "".join(parts)


TELEMETRY_HISTORY_TAIL = 20000


def append_telemetry_history(out_dir, tele_store):
    """Append this run's telemetry records to the cumulative jsonl.

    Frozen from factory/pipeline/card_pilot (provenance: precard line,
    2026-09-14). Returns (all_records, corrupt_lines). Corrupt prior-run
    lines are counted (never silently skipped); an unreadable history
    file falls back to this run's records with a warning (history is
    unrecoverable, the current run is never discarded). The reread is
    capped at TELEMETRY_HISTORY_TAIL lines so the file stays bounded.
    """
    out_dir = pathlib.Path(out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print("warning: telemetry history append failed (%s); "
              "summary covers this run only" % exc)
        return list(tele_store), 0
    hist = out_dir / "telemetry_records.jsonl"
    try:
        with open(hist, "a", encoding="utf-8") as handle:
            for rec in tele_store:
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except (OSError, ValueError):
                pass
    except OSError as exc:
        print("warning: telemetry history append failed (%s); "
              "summary covers this run only" % exc)
        return list(tele_store), 0
    all_tele, corrupt = [], 0
    try:
        with open(hist, encoding="utf-8") as handle:
            lines = handle.readlines()
        for line in lines[-TELEMETRY_HISTORY_TAIL:]:
            line = line.strip()
            if not line:
                continue
            try:
                all_tele.append(json.loads(line))
            except ValueError:
                corrupt += 1
    except OSError as exc:
        print("warning: telemetry history reread failed (%s); "
              "summary covers this run only" % exc)
        return list(tele_store), corrupt
    if corrupt:
        print("warning: telemetry history skipped %d corrupt line(s)"
              % corrupt)
    return all_tele, corrupt

