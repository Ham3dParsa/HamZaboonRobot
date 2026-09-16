"""Sense judge (sense_judge stage): multi-pick validation + veto.

Moved verbatim from factory/pipeline/precard_pipeline (provenance:
precard line R1-R6/F4, 2026-09-14); only the imports changed (intra-
package) and two names went public (judge_prompt, apply_inflection_veto).
Vendored with it: LEVEL_N + validate_picks (frozen copy from
factory/archive/v14_v16/run_v14_phase3_judge) and the inflection /
superlative stub predicates (frozen copy from factory/pipeline/card_pilot).
JUDGE_MODELS is NOT vendored here: it lives in factory.precard.net
(P2 single owner) and is imported. Model attempts route through
net.call_leg (single-model + KeyRing rotation); each leg walks its
net-table chain (steps down only on ROTATE-exhausted) and free legs
switch provider on COOLDOWN_SWITCH via net.switch_plan (R6).
"""

from __future__ import annotations

import re

from factory.precard.accounting import item_key
from factory.precard import anchor as _anchor_home
from factory.precard.ids import normalize_id_part
# P2 (R5): JUDGE_MODELS lives in factory.precard.net (single owner);
# this leg holds zero model lists and reads chains through it.
from factory.precard.net import JUDGE_MODELS
from factory.precard import net as _net

# Model attempts route through net.call_leg (single-model + KeyRing
# rotation). Each leg walks its net-table chain (steps down only on
# ROTATE-exhausted) and free legs switch provider on COOLDOWN_SWITCH
# via net.switch_plan, always with that provider's own ring (R6).

MAX_FANOUT = 4

LEVEL_N = (("beginner", 2), ("intermediate", 3), ("advanced", 4))


def validate_picks(picks, input_ids):
    """Frozen copy of factory/archive/v14_v16/run_v14_phase3_judge."""
    if not isinstance(picks, dict):
        return False
    for lvl, n in LEVEL_N:
        want = min(n, len(input_ids))
        lst = picks.get(lvl)
        if not isinstance(lst, list) or len(lst) != want:
            return False
        if any(i not in input_ids for i in lst) or len(set(lst)) != len(lst):
            return False
    return True


_INFLECTION_RX = re.compile(
    r"(?i)\b(?:plural|past(?:\s+participle)?|present\s+participle"
    r"(?:\s+and\s+gerund)?|gerund|comparative(?:\s+degree)?|"
    r"superlative(?:\s+degree)?|third(?:-|\s+)person\s+singular)"
    r"\s+of\b")


def is_inflection_gloss(gloss):
    """Frozen copy from factory/pipeline/card_pilot (R36)."""
    return bool(_INFLECTION_RX.search(gloss or ""))


_SUPERLATIVE_RX = re.compile(
    r"(?i)^\s*(?:superlative|comparative)(?:\s+form)?\s+of\s+(.+?)\s*\.?\s*$")


def is_superlative_gloss(gloss):
    """Frozen copy from factory/pipeline/card_pilot (R44)."""
    return bool(_SUPERLATIVE_RX.search(gloss or ""))


def judge_fallback(item, anchor_res):
    """Fail-closed pick: anchor-top first candidate.

    The old home routed scoreless pseudo-entries through the archive
    deterministic_picks, which provably returns input order there
    (no scores, no EVP entries), so [0] is the anchor top either way
    (pinned by test_fallback_matches_archive_first_candidate).
    """
    cands = (anchor_res or {}).get("candidates", [])
    if not cands:
        return {"sense_id": "", "gloss": "", "model": "s1-fallback-empty",
                "picks": []}
    first = cands[0]["sense_id"]
    gloss = cands[0].get("gloss", "")
    return {"sense_id": first, "gloss": gloss, "model": "s1-fallback",
            "picks": [{"sense_id": first, "gloss": gloss}]}


def judge_prompt(batch, anchor_map):
    lines = ["PICK the 1-4 most useful senses per item for Persian "
             "learners of English, ordered most-useful-first (one card "
             "= one atomic sense downstream, so rank every sense worth "
             "its own card).",
             "Prioritization hierarchy:",
             "1. High-frequency tangible and conversational meaning over "
             "technical, academic, or domain-specific jargon (e.g., "
             "cooking/water boil > thermodynamic boil), UNLESS the item's "
             "pool_level is C1/C2 or all candidates are strictly "
             "abstract/technical.",
             "2. Modern living usage over archaic, obsolete, or highly "
             "regional dialectal senses.",
             "3. If candidates contain both an independent lexical meaning "
             "and a purely grammatical/inflectional reference, ALWAYS pick "
             "the independent lexical meaning.",
             "4. For modal/auxiliary verbs (would, could, should), the "
             "grammatical main sense takes absolute precedence over any "
             "nominal or philosophical sense.",
              "",
              'Output: {"results": [{"key": "<item key>", '
              '"picks": ["<sense_id>", ... up to 4]}]}.',
              "A single \"pick\": \"<sense_id>\" row is also accepted "
              "(one sense).",
              "Every pick MUST be one of that item's candidate ids "
              "(empty picks only when the item has no candidates).",
              "Input follows:"]
    for item in batch:
        key = item_key(item)
        cands = (anchor_map.get(key) or {}).get("candidates", [])
        lines.append("KEY %s (%s, pool %s):" % (
            key, item.get("kind", "?"), item.get("pool_level", "?")))
        for cand in cands:
            tags = sorted((cand.get("tags") or []))
            tag_bit = " [%s]" % ", ".join(tags) if tags else ""
            lines.append("- %s%s %s" % (cand.get("sense_id", "?"), tag_bit,
                                        (cand.get("gloss") or "")[:200]))
        if not cands:
            lines.append("- (no candidates)")
    return "\n".join(lines)


def judge_validate_multi(data, batch, anchor_map):
    """Validate ordered multi-pick {"key","picks":[...]} rows (R1).

    Each pick must be one of the item's candidate ids; unknown ids are
    dropped, duplicates collapse (first wins), the list caps at
    MAX_FANOUT. A legacy single {"key","pick"} row is accepted as a
    one-pick list (same shape _judge_validate accepts, including its
    lemma-style "picks"-dict collapse to the first pick and the empty
    pick for candidatelss items). Returns {key: {"sense_id", "gloss",
    "picks": [{sense_id, gloss}, ...]}} with sense_id/gloss = the
    primary (first) pick — downstream stages keep reading those keys
    unchanged. Invalid rows are left out (caller fails closed); None
    unless every batch item validates.
    """
    if not isinstance(data, dict) or not isinstance(
            data.get("results"), list):
        return None
    by_key = {}
    for row in data["results"]:
        if isinstance(row, dict) and "key" in row:
            by_key[row["key"]] = row
    out = {}
    for item in batch:
        key = item_key(item)
        row = by_key.get(key)
        cands = (anchor_map.get(key) or {}).get("candidates", [])
        ids = [c["sense_id"] for c in cands]
        gloss_of = {c["sense_id"]: c.get("gloss", "") for c in cands}
        if not isinstance(row, dict):
            continue
        raw_picks = row.get("picks")
        if raw_picks is None and row.get("pick") is not None:
            raw_picks = [row.get("pick")]
        if isinstance(raw_picks, dict):
            if validate_picks(raw_picks, ids):
                flat = (row["picks"].get("beginner")
                        or row["picks"].get("intermediate")
                        or row["picks"].get("advanced") or [])
                raw_picks = flat[:1] if flat else None
            else:
                continue
        if not isinstance(raw_picks, list):
            continue
        seen, seen_gloss, picks = set(), set(), []
        for sid in raw_picks:
            if not isinstance(sid, str) or sid in seen:
                continue
            if sid == "" and not ids:
                continue
            if sid in ids and len(picks) < MAX_FANOUT:
                norm_gloss = normalize_id_part(gloss_of.get(sid, ""))
                if norm_gloss in seen_gloss:
                    continue
                seen.add(sid)
                seen_gloss.add(norm_gloss)
                picks.append({"sense_id": sid,
                              "gloss": gloss_of.get(sid, "")})
        if not picks:
            if not ids and not any(
                    isinstance(s, str) and s != "" for s in raw_picks):
                out[key] = {"sense_id": "", "gloss": "", "picks": []}
            continue
        out[key] = {"sense_id": picks[0]["sense_id"],
                    "gloss": picks[0]["gloss"], "picks": picks}
    want = {item_key(i) for i in batch}
    if set(out) != want:
        return None
    return out


def _judge_validate(data, batch, anchor_map):
    """Accept single {"key","pick"} rows (plus lemma-style "picks" rows).

    Thin single-pick view over judge_validate_multi: multi-pick rows
    collapse to their primary pick. Returns {key: {"sense_id","gloss"}}
    for valid rows only; invalid rows are left out (caller fails closed).
    """
    multi = judge_validate_multi(data, batch, anchor_map)
    if multi is None:
        return None
    return {k: {"sense_id": v["sense_id"], "gloss": v["gloss"]}
            for k, v in multi.items()}


def fanout_picks(item, pick_entry):
    """Ordered [{sense_id, gloss}] for one item's precard rows (R1).

    Primary first, then judged secondaries (capped at MAX_FANOUT);
    entries without a stored picks list fan out to their single pick.
    Dedupes by sense_id AND normalized gloss: kaksi duplicate glosses
    across senses (call#2/call#0 "To reach out with one's voice") are
    the same atomic sense — emitting both would fork two identical
    cards under one pre_card_id. Covers legacy stored picks too (all
    stages read through this choke point).
    """
    try:
        picks = (pick_entry or {}).get("picks")
        if isinstance(picks, list) and picks:
            out, seen_sid, seen_gloss = [], set(), set()
            for pick in picks[:MAX_FANOUT]:
                if not isinstance(pick, dict) or not pick.get("sense_id"):
                    continue
                norm_gloss = normalize_id_part(pick.get("gloss", ""))
                if pick["sense_id"] in seen_sid or norm_gloss in seen_gloss:
                    continue
                seen_sid.add(pick["sense_id"])
                seen_gloss.add(norm_gloss)
                out.append({"sense_id": pick["sense_id"],
                            "gloss": pick.get("gloss", "")})
            if out:
                return out
        sid = (pick_entry or {}).get("sense_id", "")
        return [{"sense_id": sid,
                 "gloss": (pick_entry or {}).get("gloss", "")}]
    except Exception:
        return [{"sense_id": "", "gloss": ""}]


def _veto_inflection_pick(pick, anchor_res):
    """F4 post-judge veto: (sense_id, gloss) with stub picks corrected.

    When the picked gloss is a mechanical-inflection reference (S0b
    verdict-path predicates: is_inflection_gloss / is_superlative_gloss
    — both "of"-requiring, so a real gloss like "a comparative study"
    never vetoes), the judge crowned a stub
    (removed/forcing/wondering/better): fall back to the anchor-top
    non-stub — the first window candidate in anchor order whose gloss
    is NOT such a reference. Anything else (real pick, empty pick,
    all-stub window) returns the pick unchanged — a veto reroutes, it
    never drops, so uncertainty keeps the item. The judge model tag is
    untouched (the sense_id change is visible in s2 progress); the
    predicates live in card_pilot (single source, reused by import —
    the veto inherits their exact boundary, including whole-gloss
    superlative anchoring).
    """
    sid = (pick or {}).get("sense_id", "")
    gloss = (pick or {}).get("gloss", "")
    if not sid or not gloss or not _is_veto_stub_gloss(gloss):
        return sid, gloss
    for cand in (anchor_res or {}).get("candidates", []) or []:
        if cand.get("sense_id") \
                and not _is_veto_stub_gloss(cand.get("gloss", "")):
            return cand.get("sense_id", ""), cand.get("gloss", "")
    return sid, gloss


def _is_veto_stub_gloss(gloss):
    """F4 stub predicate: vendored S0b verdict-path predicates below."""
    return bool(is_inflection_gloss(gloss)
                or is_superlative_gloss(gloss))


def apply_inflection_veto(out, batch, anchor_map):
    """F4: veto every stub pick in a judge_batch result dict, in place."""
    for item in batch:
        key = item_key(item)
        if key in out:
            sid, gloss = _veto_inflection_pick(
                out[key], (anchor_map or {}).get(key))
            out[key]["sense_id"], out[key]["gloss"] = sid, gloss
            # v14.1: the veto reroutes every fanned-out pick, not just
            # the primary — a stub crowned second still falls back to
            # the anchor-top non-stub (veto reroutes, never drops).
            # Stub picks vetoed onto the same anchor sense collapse
            # (first wins) — one card per atomic sense, never twins.
            vetoed, veto_seen = [], set()
            for pick in (out[key].get("picks") or []):
                vsid, vgloss = _veto_inflection_pick(
                    pick, (anchor_map or {}).get(key))
                if vsid in veto_seen:
                    continue
                veto_seen.add(vsid)
                vetoed.append({"sense_id": vsid, "gloss": vgloss})
            if vetoed:
                out[key]["picks"] = vetoed
                out[key]["sense_id"] = vetoed[0]["sense_id"]
                out[key]["gloss"] = vetoed[0]["gloss"]
    return out


# ---- T4b: network loops (moved verbatim, imports rewired) ----

import urllib.error

from factory.core.telemetry import (
    emit_attempt_rows, extract_usage, last_attempt_latency, record_call,
    resolve_cost)
from factory.precard.transport import (
    AuthError, KeyRing, ProviderCooldown, RateLimited, extract_json,
    raise_for_auth, _tele_tokens, MAX_ATTEMPTS, RETRY_PREFIX)

_tele_record = record_call
_tele_usage = extract_usage
from factory.precard.prompts import INFLECTION_REVIEW_SYS


INFLECTION_REVIEW_BATCH = 16
JUDGE_BATCH = 12



def _inflection_review_prompt(batch):
    """Batch prompt: one KEY/word/gloss block per item."""
    lines = ["Judge EACH inflected form against its dictionary gloss.",
             'Output: {"results": [{"key": "<item key>", '
             '"keep": true/false, "reason": "<why>"}]}.',
             "Input follows:"]
    for entry in batch:
        lines.append("KEY %s" % entry["key"])
        lines.append("word: %s" % (entry.get("text") or ""))
        lines.append("gloss: %s" % ((entry.get("gloss") or "")[:200]))
    return "\n".join(lines)


def _review_auth_tele(telemetry, tele_stage, batch_id, tele_key_idx, model,
                      http_status=401, run_id="", provider="",
                      model_actual=None, latency_s=0.0):
    """Auth record before a loud 401/403 abort (never silent)."""
    if telemetry is None:
        return
    record_call(
        telemetry, stage=tele_stage, batch_id=batch_id,
        key_idx=tele_key_idx, model=model,
        latency_s=latency_s, outcome="auth", http_status=http_status,
        run_id=run_id, provider=provider,
        model_actual=model_actual or model,
        cost=resolve_cost(made_call=True))


def _review_tele(telemetry, tele_stage, batch_id, tele_key_idx, model,
                 usage, outcome, latency_s=0.0, run_id="", provider="",
                 model_actual=None, made_call=True):
    """One terminal review-batch record (tokens None-tolerated).

    ``latency_s`` is the winning attempt's measured perf_counter span;
    Google direct (usage always None) lands ``cost="unknown"``, never
    a silent zero.
    """
    if telemetry is None:
        return
    prompt_tokens, completion_tokens = _tele_tokens(usage)
    record_call(
        telemetry, stage=tele_stage, batch_id=batch_id,
        key_idx=tele_key_idx, model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_s=latency_s, outcome=outcome,
        run_id=run_id, provider=provider,
        model_actual=model_actual or model,
        cost=resolve_cost(prompt_tokens=prompt_tokens,
                          completion_tokens=completion_tokens,
                          made_call=made_call))


def _validate_review_results(data, want_keys, key_field="key"):
    """Shared envelope check for the R30/R31 review passes.

    Returns the {key: row} mapping when every wanted key is present,
    else None (caller fails closed / retries).
    """
    if not isinstance(data, dict) or not isinstance(
            data.get("results"), list):
        return None
    by_key = {}
    for row in data["results"]:
        if isinstance(row, dict) and isinstance(row.get(key_field), str):
            by_key[row[key_field]] = row
    if set(by_key) != set(want_keys):
        return None
    return by_key


def inflection_review(items, transport, api_key="", model_calls=None,
                       telemetry=None, tele_stage="s0b",
                       tele_key_idx=0, tele_run_id="", tele_provider="",
                       tele_model_actual=None, tele_attempts=False,
                       models=None, tried=None, sleep_fn=None, state=None,
                       ring=None, key_var="", file_label="factory/.env",
                       rings=None):
    """R36: batched inflection-form review.

    items: [{key, text, gloss}]. Returns {key: {keep:bool, reason:str,
    model:str, uncertain:bool}}. keep=False only on an explicit LLM
    drop verdict; every failure (transport error, bad JSON, envelope
    mismatch) fails closed to {keep: True, uncertain: True} flagged
    review-uncertain (never drop on uncertainty). Auth aborts loudly.
    Hermetic with an injected transport. Every attempt routes through
    net.call_leg (single-model + KeyRing rotation, so a 429 rotates
    to the next key on the same model); a ROTATE-exhausted model
    steps down to the next chain model, and a free leg cooled at
    project level continues on the next switch_plan provider's chain
    with that provider's own ring (R6). Tuple (text, usage)
    transports surface token counts into one terminal telemetry
    record per batch (None-tolerated, cost-unknown flagged, real
    perf_counter latency, real key idx, run_id-joined; per-try
    attempt rows only when ``tele_attempts`` is on).
    """
    import time as _time
    if model_calls is None:
        model_calls = {}
    if state is None:
        state = {}
    if ring is None:
        ring = KeyRing([api_key])
    # P2: default chain from the net table (zen inflection pair);
    # explicit models (e.g. avalai/google single-model legs) win.
    base_models = list(models) if models else None
    # R6 provider loop (same rule as the other legs): free legs may
    # continue on the next switch_plan provider after a cooldown
    # (that provider's own ring); providers without a ring are not
    # attempted. Explicit models only ever run on the base provider.
    base_provider = _net.norm_provider(tele_provider or "zen") or "zen"
    ordered = [p for p in _net.switch_plan(base_provider,
                                           "inflection_review")
               if p == base_provider
               or (rings is not None and p in rings)]
    # Inflection transports take (key, model, system, text) while
    # call_leg drives (key, model, text): bind the fixed review
    # system prompt once (extra leading texts pass through, so the
    # avalai/google remap transports keep working unchanged).
    def _adapted(key, model, text, _t=transport):
        return _t(key, model, INFLECTION_REVIEW_SYS, text)
    out = {}
    for batch_no, base in enumerate(
            range(0, len(items or []), INFLECTION_REVIEW_BATCH), start=1):
        batch = items[base:base + INFLECTION_REVIEW_BATCH]
        want = [e["key"] for e in batch]
        prompt = _inflection_review_prompt(batch)
        settled = False
        win_model, win_usage = "review-fallback", None
        attempt_log = []
        cool_exc = None
        cur_ring = ring
        for eff_idx, eff in enumerate(ordered):
            eff_models = (list(base_models)
                          if base_models is not None and eff == base_provider
                          else _net.leg_chain(eff, "inflection_review"))
            eff_ring = (rings or {}).get(eff) or ring
            cur_ring = eff_ring
            eff_target = _net.target_for(eff)
            eff_key_var = key_var if eff == base_provider else ""
            eff_cooled = False
            for model in eff_models:
                if isinstance(tried, list) and model not in tried:
                    tried.append(model)
                for attempt in range(MAX_ATTEMPTS):
                    text = prompt if attempt == 0 else RETRY_PREFIX + prompt
                    start = _time.perf_counter()
                    try:
                        model_calls[model] = model_calls.get(model, 0) + 1
                        raw, usage = _net.call_leg(
                            None, eff_target, text, transport=_adapted,
                            model=model, ring=eff_ring,
                            key_var=eff_key_var, sleep_fn=sleep_fn,
                            state=state,
                            label="%s/inflection#%d" % (model, attempt),
                            file_label=file_label)
                        data = extract_json(raw)
                    except AuthError:
                        attempt_log.append(
                            {"model": model, "attempt": attempt,
                             "latency_s": _time.perf_counter() - start,
                             "key_idx": eff_ring.idx, "outcome": "auth"})
                        _review_auth_tele(telemetry, tele_stage, batch_no,
                                          eff_ring.idx, model,
                                          run_id=tele_run_id,
                                          provider=eff,
                                          model_actual=tele_model_actual,
                                          latency_s=last_attempt_latency(
                                              attempt_log))
                        raise
                    except ProviderCooldown as exc:
                        attempt_log.append(
                            {"model": model, "attempt": attempt,
                             "latency_s": _time.perf_counter() - start,
                             "key_idx": eff_ring.idx,
                             "outcome": "cooldown",
                             "http_status": 429})
                        eff_cooled = True
                        cool_exc = exc
                        break
                    except RateLimited:
                        attempt_log.append(
                            {"model": model, "attempt": attempt,
                             "latency_s": _time.perf_counter() - start,
                             "key_idx": eff_ring.idx, "outcome": "retry"})
                        break  # ROTATE-exhausted: step down, as before
                    except urllib.error.HTTPError as exc:
                        if exc.code in (401, 403):
                            attempt_log.append(
                                {"model": model, "attempt": attempt,
                                 "latency_s": _time.perf_counter() - start,
                                 "key_idx": eff_ring.idx,
                                 "outcome": "auth",
                                 "http_status": exc.code})
                            _review_auth_tele(
                                telemetry, tele_stage, batch_no,
                                eff_ring.idx, model,
                                http_status=exc.code,
                                run_id=tele_run_id,
                                provider=eff,
                                model_actual=tele_model_actual,
                                latency_s=last_attempt_latency(
                                    attempt_log))
                            raise_for_auth(exc)
                        data = None
                    except Exception:
                        data = None
                    if data is None:
                        attempt_log.append(
                            {"model": model, "attempt": attempt,
                             "latency_s": _time.perf_counter() - start,
                             "key_idx": eff_ring.idx, "outcome": "retry"})
                        continue
                    by_key = _validate_review_results(data, want)
                    if by_key is None:
                        attempt_log.append(
                            {"model": model, "attempt": attempt,
                             "latency_s": _time.perf_counter() - start,
                             "key_idx": eff_ring.idx, "outcome": "retry"})
                        continue
                    rows_ok = True
                    for key in want:
                        row = by_key[key]
                        keep = row.get("keep")
                        reason = row.get("reason", "")
                        if not isinstance(keep, bool):
                            rows_ok = False
                            break
                        out[key] = {
                            "keep": keep,
                            "reason": reason if isinstance(reason, str)
                            else "",
                            "model": model, "uncertain": False}
                    if not rows_ok:
                        out = {k: v for k, v in out.items()
                               if k not in want}
                        attempt_log.append(
                            {"model": model, "attempt": attempt,
                             "latency_s": _time.perf_counter() - start,
                             "key_idx": eff_ring.idx, "outcome": "retry"})
                        continue
                    settled = True
                    win_latency = _time.perf_counter() - start
                    attempt_log.append(
                        {"model": model, "attempt": attempt,
                         "latency_s": win_latency,
                         "key_idx": eff_ring.idx, "outcome": "settled"})
                    win_model, win_usage = model, usage
                    break
                if eff_cooled:
                    break
                if settled:
                    break
            if eff_cooled:
                # R6: a free-leg cooldown moves to the next provider's
                # chain (same batch, that provider's ring); the last —
                # or any paid — provider raises loud (the caller fails
                # the batch closed to review-uncertain).
                if eff_idx + 1 < len(ordered):
                    continue
                raise cool_exc
        if not settled:
            for key in want:
                if key not in out:
                    out[key] = {"keep": True, "reason": "review-error",
                                "model": "review-fallback",
                                "uncertain": True}
        # Terminal record: the transport was attempted either way, so
        # a fallback still flags cost-unknown (calls burned, usage
        # unseen) — never cost-none (that means no call happened).
        _review_tele(telemetry, tele_stage, batch_no, cur_ring.idx,
                     win_model, win_usage,
                     "ok" if settled else "fallback",
                     latency_s=last_attempt_latency(attempt_log),
                     run_id=tele_run_id, provider=eff,
                     model_actual=tele_model_actual)
        if tele_attempts:
            emit_attempt_rows(telemetry, attempt_log, stage=tele_stage,
                              batch_id=batch_no, run_id=tele_run_id,
                              provider=eff,
                              model_actual=tele_model_actual)
    return out


def judge_batch(batch, anchor_map, api_key, transport, sleep_fn, state,
                   telemetry=None, tele_stage="s2", tele_batch=0,
                   ring=None, models=None, provider="zen", key_var="",
                   file_label="factory/.env", tele_run_id="",
                   tele_model_actual=None, tele_attempts=False,
                   tried=None, rings=None):
    """    Judge-pick one batch. Returns {key: {sense_id, gloss, model, picks}}.

    Default chain comes from the net table (zen sense-judge pair); an
    explicit `models` list (e.g. AvalAI glm-5.3-flash via
    --judge-provider avalai) replaces it. 2 attempts per model, 401/403
    loud abort, 429 rotates the KeyRing (brief pause, same-call retry;
    a ROTATE-exhausted model steps down to the next chain model and
    only a fully-exhausted chain raises RateLimited so the runner
    flushes and STOPS); a free leg cooled at project level
    (ProviderCooldown) continues on the next switch_plan provider's
    chain with that provider's own ring, while paid legs (and the
    last provider) raise for a resume (R6),
    anything else fail-closed to the S1 top pick per item. v14.1: the
    judge returns 1-4 ordered picks per item (judge_validate_multi —
    legacy single "pick" rows still validate as one pick); the ordered
    list rides on "picks" with sense_id/gloss = the primary. F4: every
    pick (judge-model AND s1-fallback, primary AND secondaries) passes
    the inflection-stub veto — a stub gloss falls back to the
    anchor-top non-stub candidate.
    R27: one
    telemetry record per batch (ok on a judge-model pick, fallback on
    s1-fallback, error on all-keys-429); tuple (text, usage) transports
    surface token counts (None-tolerated, cost-unknown flagged).
    Terminal records carry the REAL perf_counter latency and REAL
    ring.idx of the settling call, ``model`` (requested) vs
    ``model_actual`` (really hit), provider, and run_id; per-try
    attempt rows only when ``tele_attempts`` is on (default off, so
    attempt-row volume is unchanged by default).
    """
    # P2: default chain from the net table (zen sense-judge pair);
    # explicit models (e.g. avalai/google single-model legs) win.
    base_models = list(models) if models else None
    prompt = judge_prompt(batch, anchor_map)
    transport = transport  # default wired by caller to judge call_responses
    if ring is None:
        ring = KeyRing([api_key])
    attempt_rows = []
    # R6 provider loop: free legs may continue on the next
    # switch_plan provider after a cooldown (that provider's own
    # ring — never another provider's key); providers without a
    # ring are not attempted (the leg stops for a resume, as
    # before). Explicit models only ever run on the base provider.
    base_provider = _net.norm_provider(provider) or "zen"
    ordered = [p for p in _net.switch_plan(provider, "sense_judge")
               if p == base_provider
               or (rings is not None and p in rings)]
    limited_all = True  # cleared by any model that is not ROTATE-exhausted
    n_tried = 0
    cool_exc = None

    def _attempts(eff):
        if tele_attempts and telemetry is not None:
            emit_attempt_rows(telemetry, attempt_rows, stage=tele_stage,
                              batch_id=tele_batch, run_id=tele_run_id,
                              provider=eff,
                              model_actual=tele_model_actual)

    for eff_idx, eff in enumerate(ordered):
        eff_models = (list(base_models)
                      if base_models is not None and eff == base_provider
                      else _net.leg_chain(eff, "sense_judge"))
        eff_ring = (rings or {}).get(eff) or ring
        eff_target = _net.target_for(eff)
        eff_key_var = key_var if eff == base_provider else ""
        eff_cooled = False
        for model in eff_models:
            if isinstance(tried, list) and model not in tried:
                tried.append(model)
            n_tried += 1
            for attempt in range(MAX_ATTEMPTS):
                text = prompt if attempt == 0 else RETRY_PREFIX + prompt
                label = "%s/%s#%d" % (model, "+".join(
                    item_key(i) for i in batch), attempt)
                usage = None
                try:
                    # P2: every attempt routes through net.call_leg (same
                    # ring, same rotation — the leg holds no model lists).
                    raw, usage = _net.call_leg(
                        None, eff_target, text, transport=transport,
                        model=model, ring=eff_ring, key_var=eff_key_var,
                        sleep_fn=sleep_fn, state=state, label=label,
                        file_label=file_label)
                except AuthError:
                    raise
                except ProviderCooldown as exc:
                    # P2 (R6): project-level quota on a free leg with
                    # more providers continues on the next provider's
                    # chain (same batch, that provider's ring); paid
                    # legs and the last provider STOP loud for a
                    # resume.
                    attempt_rows.extend(list(
                        getattr(eff_ring, "attempt_log", []) or []))
                    if telemetry is not None:
                        _tele_record(telemetry, stage=tele_stage,
                                     batch_id=tele_batch,
                                     key_idx=eff_ring.idx,
                                     model=model,
                                     latency_s=last_attempt_latency(
                                         attempt_rows),
                                     outcome="error", http_status=429,
                                     run_id=tele_run_id, provider=eff,
                                     model_actual=tele_model_actual or model,
                                     cost=resolve_cost(made_call=True))
                    _attempts(eff)
                    eff_cooled = True
                    cool_exc = exc
                    break
                except RateLimited:
                    attempt_rows.extend(list(
                        getattr(eff_ring, "attempt_log", []) or []))
                    if telemetry is not None:
                        _tele_record(telemetry, stage=tele_stage,
                                     batch_id=tele_batch,
                                     key_idx=eff_ring.idx,
                                     model=model,
                                     latency_s=last_attempt_latency(
                                         attempt_rows),
                                     outcome="error", http_status=429,
                                     run_id=tele_run_id, provider=eff,
                                     model_actual=tele_model_actual or model,
                                     cost=resolve_cost(made_call=True))
                    _attempts(eff)
                    # P2 (R6): ROTATE-exhausted steps down to the next
                    # model in the same leg's chain (no run abort here;
                    # the caller still flushes+STOPS when the whole chain
                    # is exhausted — see the raise below).
                    break
                except urllib.error.HTTPError as exc:
                    limited_all = False
                    if getattr(exc, "code", None) in (401, 403):
                        raise_for_auth(exc)
                    raw, usage = None, None
                except Exception:
                    limited_all = False
                    raw, usage = None, None
                else:
                    limited_all = False
                attempt_rows.extend(list(
                    getattr(eff_ring, "attempt_log", []) or []))
                if raw is None:
                    continue
                try:
                    data = extract_json(raw)
                except AuthError:
                    raise
                except Exception:
                    continue
                try:
                    valid = judge_validate_multi(data, batch, anchor_map)
                except Exception:
                    valid = None
                if valid is not None:
                    out = {k: {**v, "model": model}
                           for k, v in valid.items()}
                    apply_inflection_veto(out, batch, anchor_map)  # F4
                    if telemetry is not None:
                        prompt_tokens, completion_tokens = _tele_tokens(
                            usage)
                        last = getattr(eff_ring, "last_call", None) or {}
                        _tele_record(
                            telemetry, stage=tele_stage,
                            batch_id=tele_batch,
                            key_idx=last.get("key_idx", eff_ring.idx),
                            model=model,
                            latency_s=last.get("latency_s", 0.0),
                            outcome="ok",
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            run_id=tele_run_id, provider=eff,
                            model_actual=tele_model_actual or model,
                            cost=resolve_cost(
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens))
                    _attempts(eff)
                    return out
            if eff_cooled:
                break
        if eff_cooled:
            # R6: a free-leg cooldown moves to the next provider's
            # chain (same batch, that provider's ring); the last —
            # or any paid — provider stops loud for a resume.
            if eff_idx + 1 < len(ordered):
                continue
            raise cool_exc
    if limited_all and n_tried:
        # P2 (R6): the whole chain ROTATE-exhausted — STOP loud (the
        # caller flushes progress); anything else already fell back
        # per item above. Per-model error records exist, so no extra
        # terminal row here.
        _attempts(base_provider)
        raise RateLimited(
            "all sense_judge models 429 (provider quotas exhausted) — "
            "re-run later (progress flushed, resume safe)")
    out = {item_key(i): {**judge_fallback(i, anchor_map.get(item_key(i))),
                         } for i in batch}
    apply_inflection_veto(out, batch, anchor_map)  # F4 (fallback too:
    # the anchor top itself can be a stub when inflection kept it)
    if telemetry is not None:
        _tele_record(telemetry, stage=tele_stage, batch_id=tele_batch,
                     key_idx=ring.idx, model="s1-fallback",
                     latency_s=last_attempt_latency(attempt_rows),
                     outcome="fallback", run_id=tele_run_id,
                     provider=provider,
                     model_actual=tele_model_actual or "s1-fallback",
                     cost=resolve_cost(made_call=True))
    _attempts(base_provider)
    return out


def parse_superlative_base(gloss):
    """R44: base lemma of a superlative/comparative gloss ("" if none).

    Frozen from factory/pipeline/card_pilot (provenance: precard line,
    2026-09-14). Whole-gloss anchored (^...$): prose merely mentioning
    "superlative of" mid-sentence never parses. The base must be a
    single alpha token (multi-word/qualified targets are not clean
    redirects). Target is stripped of quotes/dots. Index membership
    is checked by the CALLER (inflection gate), keeping this pure.
    """
    hit = _SUPERLATIVE_RX.search(gloss or "")
    if not hit:
        return ""
    target = (hit.group(1) or "").strip().strip(
        "'\"\u201c\u201d\u2018\u2019").strip().rstrip(".").strip()
    # Cut trailing qualifiers: "good: most good" -> "good".
    target = re.split(r"[:;,(]", target, maxsplit=1)[0].strip()
    if not re.fullmatch(r"[A-Za-z]+", target):  # F4: single alpha token
        return ""
    return target


def inflection_needs_review(item, index, read_entry):
    """R36: (needs, gloss) — True when the raw lemma head is inflection.

    Moved verbatim from factory/pipeline/precard_pipeline (provenance:
    precard line, 2026-09-14); pilot-owned helpers now resolve inside
    this package (anchor reads, judge stub predicates).
    """
    text = (item.get("text") or "").strip()
    if not text:
        return False, ""
    entries, pos = _anchor_home._entries_for(item, index)
    try:
        gloss = _anchor_home.raw_first_gloss(entries, read_entry)
    except Exception:
        return False, ""
    if gloss and is_superlative_gloss(gloss):
        base = parse_superlative_base(gloss)
        if not base or base.lower() not in (index or {}):
            return False, ""
        return True, gloss
    if gloss and is_inflection_gloss(gloss):
        return True, gloss
    return False, ""

