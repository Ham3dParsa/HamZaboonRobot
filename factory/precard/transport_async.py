"""Async cloud-judge transport seam (contract R1/R2/R7, TDD green + review).

New module: the sync path (provider_transport.py / provider_lease_policy.py
/ judge.py) stays
untouched. Reuses the sync domain exceptions (KeyRing, RateLimited,
ProviderCooldown, AuthError), the shared prompt builder
(judge.arbiter_prompt — prompt parity by construction), the shared validator
(judge.arbiter_validate_multi), the F4 inflection veto, and the terminal
telemetry shape (factory.core.telemetry.record_call). Route modes read
provider_registry rows (F2). Backoff sleeps with the semaphore slot RELEASED
(head-of-line rule). Rotation is compare-and-rotate (no double-rotate under
contention). Telemetry attempt rows carry key_idx:int only — key strings
never recorded. Per-row failures fail closed; a bad row never aborts a run.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error

from factory.precard import provider_transport as sync_transport
from factory.core.llm_json import (
    ABORT,
    COOLDOWN_SWITCH,
    FAIL_CLOSED,
    RETRY_ONCE,
    ROTATE,
    classify as classify_error,
)

ROUTE_MODES = ("direct", "tunnel")
DEFAULT_CONCURRENCY = 8
MAX_CONCURRENCY = 10
ROTATE_PAUSE_S = 5.0


def clamp_concurrency(n):
    """Clamp worker count into [1, MAX_CONCURRENCY].

    Non-numeric or non-finite input falls back to DEFAULT_CONCURRENCY
    (documented).
    """
    try:
        n = int(n)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_CONCURRENCY
    return max(1, min(MAX_CONCURRENCY, n))


def resolve_route(provider):
    """direct|tunnel from the provider registry row (F2: data, not code).

    Unknown providers go direct (fail-closed to the simplest path).
    """
    from factory.precard import provider_registry as registry
    row = registry.resolve_provider(provider)
    if row is None:
        return "direct"
    return row.get("route", "direct")


def to_thread_adapter(sync_fn):
    """Wrap a sync (key, model, prompt)->(text, usage) transport for async.

    Lets the async engine reuse the production sync transports with zero
    new HTTP code. Threads are not cancellable: a wait_for timeout abandons
    (not kills) the worker thread — documented, same as sync socket
    timeouts abandoning kernel state.
    """
    async def _call(key, model, prompt):
        return await asyncio.to_thread(sync_fn, key, model, prompt)
    return _call


async def sleep_unlocked(sem, delay_s, sleep_fn):
    """Sleep without holding the semaphore slot (head-of-line rule).

    Caller must hold the slot; if it does not, the sleep still happens and
    the slot is left exactly as found. Requires a BoundedSemaphore (plain
    asyncio.Semaphore.release() never raises, so over-release would
    silently inflate the bound — all production call sites use
    BoundedSemaphore; see run_judge_async and the pipeline branch).
    """
    try:
        sem.release()
    except ValueError:
        if sleep_fn is None:
            await asyncio.sleep(delay_s)
        else:
            await sleep_fn(delay_s)
        return
    try:
        if sleep_fn is None:
            await asyncio.sleep(delay_s)
        else:
            await sleep_fn(delay_s)
    finally:
        await sem.acquire()


class _RowFailed(Exception):
    """Internal item-level failure: reason + attempts so far (never lost)."""

    def __init__(self, reason, attempts=None):
        super().__init__(reason)
        self.reason = reason
        self.attempts = list(attempts or [])

    def __str__(self):
        return str(self.reason)


def _log_attempt(ring, model, attempt, latency_s, outcome, key_idx=None):
    """Sync-shaped attempt row {model, attempt, latency_s, key_idx, outcome}.

    key_idx is captured under the ring lock by the caller (exact under
    contention); it falls back to ring.idx only for legacy single-threaded
    callers. Ring mirror stays last-writer-wins; the authoritative per-row
    copy rides on the returned attempts list.
    """
    if not isinstance(key_idx, int) or isinstance(key_idx, bool):
        key_idx = ring.idx
    entry = {"model": model, "attempt": attempt,
             "latency_s": round(latency_s, 4),
             "key_idx": key_idx, "outcome": outcome}
    log = getattr(ring, "attempt_log", None)
    if log is None:
        ring.attempt_log = log = []
    log.append(entry)
    return entry


def _read_error_body(exc):
    """Best-effort HTTPError body for classify ("" when unreadable).

    Mechanical mirror of sync _http_error_body (no taxonomy here — the
    table stays single-owned by llm_json.classify).
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


async def _call_with_backoff(*, transport, model, prompt, semaphore, ring,
                             ring_lock, timeout_s, sleep_fn, backoff_s,
                             provider="generic", key_var="",
                             file_label="factory/.env"):
    """One model-text attempt with rotation. Returns (text, attempts).

    Raw urllib HTTPError is mapped through the SHARED classify table
    (sync_transport._action_for_http_error) so production transports get
    the exact sync rotation/abort/cooldown semantics: ROTATE behaves like
    RateLimited, ABORT raises AuthError, COOLDOWN_SWITCH raises
    ProviderCooldown, RETRY_ONCE/FAIL_CLOSED fail the item closed.
    Domain RateLimited/AuthError/ProviderCooldown raised directly by a
    transport keep their meaning. Timeout (or non-positive timeout budget)
    and anything else raise _RowFailed carrying attempts (never lost).
    """
    try:
        valid_budget = float(timeout_s) > 0
    except (TypeError, ValueError):
        valid_budget = False
    if not valid_budget:
        raise _RowFailed("timeout", [])
    loop = asyncio.get_running_loop()
    attempts = []
    attempt_no = 0

    def _http_action(exc):
        try:
            code = getattr(exc, "code", None)
            if code is not None:
                code = int(code)
            else:
                code = None
        except (TypeError, ValueError):
            code = None
        try:
            return classify_error(code, _read_error_body(exc), provider)
        except Exception:
            return None

    async with semaphore:
        while True:
            attempt_no += 1
            async with ring_lock:
                current_key = ring.current
                read_idx = ring.idx
            start = loop.time()
            try:
                text, _usage = await asyncio.wait_for(
                    transport(current_key, model, prompt),
                    timeout=timeout_s)
            except asyncio.TimeoutError:
                attempts.append(_log_attempt(
                    ring, model, attempt_no, timeout_s, "error", read_idx))
                raise _RowFailed("timeout", attempts)
            except sync_transport.ProviderCooldown:
                raise
            except sync_transport.AuthError:
                raise
            except sync_transport.RateLimited:
                action = ROTATE
                exc_name = None
            except urllib.error.HTTPError as exc:
                action = _http_action(exc)
                exc_name = "HTTPError:%s" % getattr(exc, "code", "?")
                if action == ABORT:
                    hint = key_var.strip() if key_var and key_var.strip() \
                        else "keys"
                    raise sync_transport.AuthError(
                        "provider auth failed (HTTP %s): check %s in %s — "
                        "aborting with no silent fallback"
                        % (getattr(exc, "code", "?"), hint, file_label))
                if action == COOLDOWN_SWITCH:
                    raise sync_transport.ProviderCooldown(
                        "project quota for provider %s" % provider)
                if action not in (ROTATE, RETRY_ONCE, FAIL_CLOSED, None):
                    action = FAIL_CLOSED
                if action in (RETRY_ONCE, FAIL_CLOSED, None):
                    latency = loop.time() - start
                    attempts.append(_log_attempt(
                        ring, model, attempt_no, latency, "error",
                        read_idx))
                    raise _RowFailed(exc_name, attempts)
            except Exception as exc:
                latency = loop.time() - start
                attempts.append(_log_attempt(
                    ring, model, attempt_no, latency, "error", read_idx))
                raise _RowFailed("transport:%s" % type(exc).__name__,
                                 attempts)
            else:
                action = None
            latency = loop.time() - start
            if action == ROTATE:
                attempts.append(_log_attempt(
                    ring, model, attempt_no, latency, "rotated", read_idx))
                async with ring_lock:
                    if ring.idx == read_idx:
                        more = ring.rotate()
                    else:
                        more = True
                if not more:
                    raise sync_transport.RateLimited(
                        "ring exhausted for provider %s" % provider)
                await sleep_unlocked(semaphore, backoff_s, sleep_fn)
                continue
            ring.last_call = {"latency_s": round(latency, 4),
                              "key_idx": read_idx}
            attempts.append(_log_attempt(
                ring, model, attempt_no, latency, "settled", read_idx))
            return text, attempts


async def judge_row_async(row, *, prompt_fn, validate_fn, transport, model,
                          semaphore, ring, ring_lock, timeout_s, sleep_fn,
                          state, backoff_s=ROTATE_PAUSE_S,
                          provider="generic", key_var="",
                          file_label="factory/.env"):
    """One row vote. Returns the validated vote mapping (FAILED on trouble).

    Thin wrapper over _call_with_backoff + caller-supplied validator.
    """
    if not isinstance(row, dict):
        return {"key": "", "verdict": "FAILED",
                "winner_index": None, "reason": "row", "attempts": []}
    key = row.get("key", "")
    mine = []
    try:
        prompt = prompt_fn(row)
    except Exception as exc:
        return {"key": key, "verdict": "FAILED",
                "winner_index": None, "reason": "prompt:%s"
                % type(exc).__name__, "attempts": mine}
    try:
        text, mine = await _call_with_backoff(
            transport=transport, model=model, prompt=prompt,
            semaphore=semaphore, ring=ring, ring_lock=ring_lock,
            timeout_s=timeout_s, sleep_fn=sleep_fn, backoff_s=backoff_s,
            provider=provider, key_var=key_var, file_label=file_label)
    except (sync_transport.AuthError, sync_transport.ProviderCooldown,
            sync_transport.RateLimited):
        raise
    except _RowFailed as exc:
        mine = exc.attempts or mine
        return {"key": key, "verdict": "FAILED",
                "winner_index": None, "reason": str(exc), "attempts": mine}
    try:
        _status, vote = validate_fn(text)
    except Exception as exc:
        return {"key": key, "verdict": "FAILED",
                "winner_index": None,
                "reason": "validator:%s" % type(exc).__name__,
                "attempts": mine}
    if not isinstance(vote, dict):
        return {"key": key, "verdict": "FAILED",
                "winner_index": None, "reason": "envelope",
                "attempts": mine}
    vote = dict(vote)
    vote.setdefault("key", key)
    vote["attempts"] = mine
    return vote


async def judge_batch_async(batch_items, anchor_map, *, transport, model,
                            semaphore, ring, ring_lock, timeout_s, sleep_fn,
                            state, backoff_s=ROTATE_PAUSE_S, telemetry=None,
                            tele_stage="s2", tele_batch=0, tele_run_id="",
                            provider="", model_actual=None,
                            tele_attempts=False, tried=None, key_var="",
                            file_label="factory/.env"):
    """Judge one JUDGE_BATCH with the sync prompt, validator, and veto.

    Prompt parity by construction (judge.arbiter_prompt), shape parity
    (arbiter_validate_multi + apply_inflection_veto + per-vote "model"
    stamp), telemetry parity (record_call terminal ok/fallback/error +
    optional attempt rows). Total failure returns {} — the caller falls
    back per item, exactly like sync lines 879-880. AuthError /
    ProviderCooldown / exhausted RateLimited propagate like sync.
    """
    from factory.precard import judge as judge_mod
    from factory.core import telemetry as tele_mod
    if isinstance(tried, list):
        async with ring_lock:
            if model not in tried:
                tried.append(model)
    if not batch_items:
        return {}
    prompt = judge_mod.arbiter_prompt(batch_items, anchor_map)
    attempts = []
    try:
        text, attempts = await _call_with_backoff(
            transport=transport, model=model, prompt=prompt,
            semaphore=semaphore, ring=ring, ring_lock=ring_lock,
            timeout_s=timeout_s, sleep_fn=sleep_fn, backoff_s=backoff_s,
            provider=provider or "generic", key_var=key_var,
            file_label=file_label)
    except _RowFailed as exc:
        mapping = {}
        attempts = exc.attempts or []
    else:
        mapping = {}
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        try:
            mapping = judge_mod.arbiter_validate_multi(
                data, batch_items, anchor_map) or {}
        except Exception:
            mapping = {}
        for vote in mapping.values():
            if isinstance(vote, dict):
                vote["model"] = model
        judge_mod.apply_inflection_veto(mapping, batch_items, anchor_map)
    if telemetry is not None:
        last = attempts[-1] if attempts else {}
        if mapping:
            tele_mod.record_call(
                telemetry, stage=tele_stage, batch_id=tele_batch,
                key_idx=last.get("key_idx", ring.idx), model=model,
                latency_s=last.get("latency_s", 0.0), outcome="ok",
                run_id=tele_run_id, provider=provider,
                model_actual=model_actual or model,
                cost=tele_mod.resolve_cost())
        else:
            tele_mod.record_call(
                telemetry, stage=tele_stage, batch_id=tele_batch,
                key_idx=ring.idx, model="s1-fallback",
                latency_s=last.get("latency_s", 0.0) if last else 0.0,
                outcome="fallback", run_id=tele_run_id, provider=provider,
                model_actual=model_actual or "s1-fallback",
                cost=tele_mod.resolve_cost(made_call=True))
        if tele_attempts:
            tele_mod.emit_attempt_rows(
                telemetry, attempts, stage=tele_stage, batch_id=tele_batch,
                run_id=tele_run_id, provider=provider,
                model_actual=model_actual or model)
    return mapping


def _read_progress(progress_path):
    done = {}
    if not progress_path:
        raise ValueError("progress_path is required (refusing blind resume)")
    try:
        with open(progress_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and "key" in rec and "vote" in rec:
                    done[rec["key"]] = rec["vote"]
    except OSError:
        pass
    return done


_RESUMABLE_VERDICTS = ("LINK", "NONE", "FAILED")


def _is_wellformed_vote(vote):
    """Structural trust check for resumed votes (no model call).

    Malformed stored votes are re-judged; well-formed ones (including
    terminal FAILED) are trusted as-is, mirroring sync resume.
    """
    return isinstance(vote, dict) \
        and vote.get("verdict") in _RESUMABLE_VERDICTS


async def run_batches_async(units, *, transport, model, semaphore, ring,
                            ring_lock, timeout_s, sleep_fn, state,
                            backoff_s=ROTATE_PAUSE_S, telemetry=None,
                            tele_stage="s2", tele_run_id="", provider="",
                            model_actual=None, tele_attempts=False,
                            tried=None, key_var="", file_label="factory/.env",
                            progress_sink=None):
    """Judge batch units concurrently.

    Returns (maps, terminal) where maps is {index: mapping} for settled
    units and terminal is the first AuthError/ProviderCooldown/RateLimited
    (or None). Anything else already failed closed inside judge_batch_async.
    After each settled unit, progress_sink(index, mapping) runs synchronously
    (kill-safe persistence; exceptions propagate loud). The caller merges
    maps, then raises terminal exactly like the sync stage.
    """
    async def one(idx, unit):
        mapping = await judge_batch_async(
            unit["batch_items"], unit["anchor_map"],
            transport=transport, model=model, semaphore=semaphore,
            ring=ring, ring_lock=ring_lock, timeout_s=timeout_s,
            sleep_fn=sleep_fn, state=state, backoff_s=backoff_s,
            telemetry=telemetry, tele_stage=tele_stage,
            tele_batch=unit.get("tele_batch", idx), tele_run_id=tele_run_id,
            provider=provider, model_actual=model_actual,
            tele_attempts=tele_attempts, tried=tried, key_var=key_var,
            file_label=file_label)
        if progress_sink is not None:
            progress_sink(idx, mapping)
        return idx, mapping

    results = await asyncio.gather(
        *[one(i, u) for i, u in enumerate(units)], return_exceptions=True)
    out = {}
    terminal = None
    for item in results:
        if isinstance(item, BaseException):
            if isinstance(item, (KeyboardInterrupt, SystemExit,
                                 asyncio.CancelledError)):
                raise item
            if terminal is None and isinstance(
                    item, (sync_transport.AuthError,
                           sync_transport.ProviderCooldown,
                           sync_transport.RateLimited)):
                terminal = item
                continue
            raise item
        idx, mapping = item
        out[idx] = mapping
    return out, terminal


async def run_judge_async(rows, *, transport, model, prompt_fn, validate_fn,
                          ring, concurrency, timeout_s, progress_path,
                          sleep_fn=None, backoff_s=ROTATE_PAUSE_S,
                          provider="generic"):
    """Judge rows with bounded concurrency; resume skips done keys.

    Duplicate keys inside one run are judged once (first wins). Resumed
    votes are structurally re-checked; malformed ones are re-judged.
    """
    sem = asyncio.BoundedSemaphore(clamp_concurrency(concurrency))
    ring_lock = asyncio.Lock()
    file_lock = asyncio.Lock()
    stored = _read_progress(progress_path)
    seen = set()
    fresh = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get("key")
        if key in seen:
            continue
        seen.add(key)
        if key in stored:
            if _is_wellformed_vote(stored[key]):
                continue
            del stored[key]
        fresh.append(row)
    out = dict(stored)

    async def one(row):
        vote = await judge_row_async(
            row, prompt_fn=prompt_fn, validate_fn=validate_fn,
            transport=transport, model=model, semaphore=sem, ring=ring,
            ring_lock=ring_lock, timeout_s=timeout_s, sleep_fn=sleep_fn,
            state={}, backoff_s=backoff_s, provider=provider)
        rec = {"key": row.get("key"), "vote": vote}
        async with file_lock:
            with open(progress_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec["key"], vote

    results = await asyncio.gather(
        *[one(r) for r in fresh], return_exceptions=True)
    for item in results:
        # Loud: terminal (Auth/Cooldown/RateLimited), cancellation, and
        # unexpected errors all propagate — file progress already holds
        # settled rows, so nothing judged is lost.
        if isinstance(item, BaseException):
            raise item
        key, vote = item
        out[key] = vote
    return out
