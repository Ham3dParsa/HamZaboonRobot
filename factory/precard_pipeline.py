"""Pre-card pipeline: sample.json -> precard.jsonl (locked R22-R25, v8 R29/R32).

Factory-only research script. No bot/DB/handler changes. Reuses the
existing pipeline scripts BY IMPORT (never a third copy of their logic):

- S1 deterministic sense rank: card_pilot.anchor_item_en (the same
  vendored-v14 scorer card_pilot already uses).
- S2 sense judge pick: run_v14_phase3_judge.call_responses transport +
  MODELS chain (Muse-only 1.3 -> 1.2 override), validate_picks /
  deterministic_picks reuse, 2 attempts, 401/403 loud abort,
  other-errors fail-closed to the S1 top pick.
- S3 topic vector: run_v15_topics USER_TMPL + lemma_block prompt,
  call_responses transport, validate_vectors / fallback_vectors.
- S4 topic label: card_pilot.assign_topic two-leg (deterministic v16 leg
  + v16b LLM top-up), run_v16b_topup.call_responses as the LLM leg.
- S5 dataset enrichment: IPA + 8-20w examples + sense_id via
  card_pilot.first_entry_ipa / sense_example_texts /
  filter_examples_by_length / tatoeba_candidates / score_senses.

Conventions (same as run_v14_phase3 / run_v15 / run_v16b / phrase_judge):
batch 8, sleep 2.5s between batches, per-model 2 attempts, resume
progress rewritten every batch. One progress JSON PER STAGE lives in
--progress-dir (s1..s5, {done, failed, backoffs}); --resume is on by
default (done items are skipped). On HTTP 429: backoff 60s, then 300s,
then continue-next fail-closed (the backoff event is recorded, done work
is never lost). Progress is flushed EVERY batch and in a finally block
(KeyboardInterrupt-safe). A resume banner prints done/remaining per
stage at startup.

Output: precard.jsonl, one line per SURVIVING item:
{key, kind, text, pool_level, sense_id, en_def, ipa, ipa_src,
 dataset_examples[], abbrev_expansion (R29), pos[]/pos_src (R32),
 topic_vector[{label, weight}], topic_method,
 drop_reason (None when kept), type_pending (only when true),
 stage_calls{..., s0}}.
Dropped items are NEVER written to precard.jsonl; their reasons live in
the s0 progress state ({done: {key: {kept, reason, type_pending}}},
failed=[dropped keys]) and on stdout. Never silent.
V7: S1 drops proper-noun anchors (anchored entry POS in {name, propn},
reason anchor-proper-noun, recorded on the s1 done entry + failed list —
the ONE anchor-drop place; card_pilot anchor helpers never drop).
V7: every batch prints ONE stdout line "S<stage> batch i/N ok=X fail=Y
model=calls" (batch_log_line, owned by card_pilot) and each run writes
a compact run.log beside --out (stage start/end + counts + timings).

S0 PREPROCESS (strict, v6 scope: junk words/phrases and rare senses leak
less): word items drop when R4 name-only (card_pilot.is_proper_noun_lemma
over card_pilot.build_pos_sets, reused by import) or R20 wordfreq zipf <
3.0 unless academic-tagged (lemma in the AWL families file
--awl-families, or an academic/evp field on the sample item); phrase
items drop when the phrase-type log (--phrase-type-log, read via
card_pilot.load_phrase_types) judges applied_keep==False, else they are
kept with the "type-pending" flag when the log is missing or the phrase
is unjudged. Missing aux files (AWL, type log, wordfreq) fail OPEN to
keep (recorded, never silent) — they only ever add keeps, never drops.

Usage (owner run, needs VPN-ready long run — NOT run by the agent):
    python factory/precard_pipeline.py
    python factory/precard_pipeline.py --dry-run --limit 8
    python factory/card_pilot.py --from-precard <precard.jsonl>
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import card_pilot  # noqa: E402  (S1/S4/S5 owner path, reused by import)
from card_pilot import item_key  # noqa: E402
from llm_json import AuthError, extract_json, raise_for_auth  # noqa: E402
from phrase_judge import write_progress  # noqa: E402  (resume plumbing)
from telemetry import record_call as _tele_record  # noqa: E402
from telemetry import write_summary as _tele_write  # noqa: E402

DEFAULT_SAMPLE = "W:/hamzaban_data_factory/pilot/sample.json"
DEFAULT_OUT = "W:/hamzaban_data_factory/pilot/precard.jsonl"
DEFAULT_PROGRESS_DIR = "W:/hamzaban_data_factory/pilot/progress_precard"
DEFAULT_AWL_FAMILIES = "W:/hamzaban_data_factory/raw/awl_families.json"

BATCH = 8
SLEEP = 2.5
BACKOFF_WAITS = [60.0, 300.0]
MAX_ATTEMPTS = 2
ZIPF_MIN = 3.0
# R35 v9 — level-aware R20 floors by item pool_level. Lower levels need
# common words (3.0); C1/C2 items may be rarer (2.5/1.5). Unknown or
# missing pool_level falls back to ZIPF_MIN (3.0, fail-closed to keep
# the old gate). Phrases keep current behavior — NO zipf gate here:
# phrase frequency lives on a different scale (multiword strings have
# no wordfreq zipf reading), so phrases stay on the phrase-type log
# path only.
ZIPF_FLOORS = {"A1": 3.0, "A2": 3.0, "B1": 3.0, "B2": 3.0,
               "C1": 2.5, "C2": 1.5}
STAGES = ("s0", "s0b", "s1", "s2", "s3", "s4", "s5")
RETRY_PREFIX = ("Your last reply was not valid JSON. "
                "Re-send ONLY the JSON object.\n")


def parse_args(argv=None):
    """CLI: sample/out/progress-dir/dry-run/limit (+ kaikki/tatoeba paths)."""
    ap = argparse.ArgumentParser(description="Pre-card pipeline (R22-R25).")
    ap.add_argument("--sample", default=DEFAULT_SAMPLE)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--progress-dir", default=DEFAULT_PROGRESS_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-resume", action="store_true",
                    help="ignore existing stage progress (default: resume on)")
    ap.add_argument("--only", default="",
                    help="run a single stage only (S0..S5 incl. S0b, "
                    "case-insensitive; "
                    "other stages are skipped, resume still honored)")
    ap.add_argument("--stages", default="",
                    help="comma-separated stage subset (e.g. --stages s1,s2; "
                    "mutually exclusive with --only)")
    ap.add_argument("--rekey", default="",
                    help="keyfile (one item key per line, # comments "
                    "allowed): force redo of the listed keys in the "
                    "SELECTED stages (resume still skips everything else)")
    ap.add_argument("--kaikki-index", default=card_pilot.DEFAULT_KAIKKI_INDEX)
    ap.add_argument("--kaikki-raw", default=card_pilot.DEFAULT_KAIKKI_RAW)
    ap.add_argument("--tatoeba-pool", default=card_pilot.DEFAULT_TATOEBA_POOL)
    ap.add_argument("--phrase-type-log", default=card_pilot.DEFAULT_PHRASE_TYPE_LOG,
                    help="phrase-type audit log (missing file = all phrases "
                    "kept with the type-pending flag, never fails)")
    ap.add_argument("--awl-families", default=DEFAULT_AWL_FAMILIES,
                    help="AWL families JSON (missing file = no academic tags "
                    "from AWL, never fails)")
    args = ap.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        ap.error("--limit must be >= 0")
    return args


def load_sample(path):
    """Load sample.json (list of {kind, text, pos?, pool_level})."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise SystemExit("cannot read sample %s: %s" % (path, exc))
    except ValueError as exc:
        raise SystemExit("corrupt sample %s: %s" % (path, exc))
    if not isinstance(data, list):
        raise SystemExit("corrupt sample %s: top-level list expected" % path)
    return data


# ------------------------------------------------------- R26 select ---

def _selected_stages(args):
    """R26: selected stage set from --only / --stages (default: all).

    --only Sx runs one stage; --stages a,b runs a subset (both
    case-insensitive). The two flags are mutually exclusive. Per-stage
    resume still applies inside the selection (skip done unless rekeyed).
    """
    only = (args.only or "").strip().lower()
    stages = (args.stages or "").strip().lower()
    if only and stages:
        raise SystemExit("--only and --stages are mutually exclusive")
    if only:
        if only not in STAGES:
            raise SystemExit("--only must be one of %s (got %r)"
                             % (", ".join(STAGES), args.only))
        return {only}
    if stages:
        picks = [s.strip() for s in stages.split(",") if s.strip()]
        bad = [s for s in picks if s not in STAGES]
        if not picks or bad:
            raise SystemExit("--stages must be a comma list from %s (got %r)"
                             % (", ".join(STAGES), args.stages))
        return set(picks)
    return set(STAGES)


def _load_rekey_keys(path):
    """R26: item keys forced to redo (one per line, # comments allowed).

    Also tolerates a JSON list file. Empty path -> []. Missing file ->
    SystemExit (explicit user input must never silently no-op).
    """
    if not (path or "").strip():
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            blob = handle.read()
    except OSError as exc:
        raise SystemExit("cannot read rekey file %s: %s" % (path, exc))
    stripped = blob.strip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except ValueError as exc:
            raise SystemExit("corrupt rekey file %s: %s" % (path, exc))
        if not isinstance(data, list):
            raise SystemExit("corrupt rekey file %s: JSON list expected"
                             % path)
        return [str(k).strip() for k in data
                if isinstance(k, str) and k.strip()]
    return [line.strip() for line in blob.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def _stage_range(selected, stage, items):
    """R26: batch base offsets ([] when the stage is not selected)."""
    if stage not in selected:
        return []
    return list(range(0, len(items), BATCH))


def _dry_run_needs(progress_dir, items, selected, rekeyed, resume):
    """R26 dry-run: per-stage todo counts from existing progress.

    Counts are upper bounds (s0/s1 drops are only known after the real
    run). Nothing is read except progress JSON; nothing is written.
    """
    keys = [item_key(i) for i in items]
    rekeyed_set = set(rekeyed or [])
    needs = {}
    for stage in STAGES:
        done = set()
        if resume:
            path = pathlib.Path(progress_dir) / ("%s.json" % stage)
            if path.exists():
                try:
                    saved = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    saved = {}
                if isinstance(saved, dict):
                    done = set((saved.get("done") or {}))
        todo = [k for k in keys if k not in done or k in rekeyed_set]
        needs[stage] = {"todo": len(todo), "done": len(done & set(keys))}
    return needs


# ---------------------------------------------------------------- S0 ---

def load_awl_members(path):
    """Lowercase AWL member set from an awl_families.json file.

    Shape: {"families": {family: [members]}} (fetch_awl.py). Missing /
    unreadable / wrong-shape file -> empty set (fail open to keep,
    recorded by the caller — aux data only ever adds keeps).
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return set()
    fams = (data.get("families") if isinstance(data, dict) else None) or {}
    out = set()
    if isinstance(fams, dict):
        for head, members in fams.items():
            if isinstance(head, str) and head.strip():
                out.add(head.strip().lower())
            for member in (members or []):
                if isinstance(member, str) and member.strip():
                    out.add(member.strip().lower())
    return out


_ZIPF_CACHE: dict = {}


def default_zipf(text):
    """wordfreq zipf_frequency (en) with per-lemma cache; None when unknown.

    None covers both "wordfreq not installed" and "wordfreq raises" —
    the caller keeps the item and records zipf-unknown (never silent).
    NOTE: wordfreq returns 0.0 for out-of-vocabulary lemmas; 0.0 is a
    real (low) score, NOT None, so junk still drops per R20.
    """
    key = (text or "").strip().lower()
    if key in _ZIPF_CACHE:
        return _ZIPF_CACHE[key]
    try:
        from wordfreq import zipf_frequency
        value = float(zipf_frequency(key, "en"))
    except Exception:
        value = None
    _ZIPF_CACHE[key] = value
    return value


def _is_academic(item, awl_set):
    """Academic tag: explicit academic/evp field on the sample item, else
    lemma membership in the AWL families set."""
    if bool(item.get("academic")):
        return True
    evp = item.get("evp")
    if isinstance(evp, dict) and bool(evp.get("academic")):
        return True
    return (item.get("text") or "").strip().lower() in (awl_set or set())


def s0_classify_item(item, pos_sets, zipf_fn, awl_set, type_map,
                     type_log_available):
    """S0 verdict for one sample item: {"kept", "reason", "type_pending"}.

    kept=False carries a drop reason (r4-name-only / r20-zipf-low:<z> /
    applied-keep-false:<type>); kept=True has reason None except the
    zipf-unknown-kept note. Phrase items kept without a type judgement
    carry type_pending=True ("type-pending" flag). R35 v9: the word zipf
    gate is level-aware (ZIPF_FLOORS by pool_level); academic bypass kept.
    """
    kind = item.get("kind") or "word"
    text = (item.get("text") or "").strip()
    if kind == "word":
        if card_pilot.is_proper_noun_lemma(
                text, (pos_sets or {}).get(text.lower(), set())):
            return {"kept": False, "reason": "r4-name-only",
                    "type_pending": False}
        try:
            zipf = zipf_fn(text)
        except Exception:
            zipf = None
        if zipf is None:
            return {"kept": True, "reason": "zipf-unknown-kept",
                    "type_pending": False}
        floor = ZIPF_FLOORS.get(
            (item.get("pool_level") or "").strip().upper(), ZIPF_MIN)
        if float(zipf) < floor and not _is_academic(item, awl_set):
            return {"kept": False,
                    "reason": "r20-zipf-low:%.2f" % float(zipf),
                    "type_pending": False}
        return {"kept": True, "reason": None, "type_pending": False}
    entry = (type_map or {}).get(text) if type_log_available else None
    if not isinstance(entry, dict):
        return {"kept": True, "reason": None, "type_pending": True}
    if not entry.get("applied_keep"):
        return {"kept": False,
                "reason": "applied-keep-false:%s" % (
                    entry.get("phrase_type") or "unknown"),
                "type_pending": False}
    return {"kept": True, "reason": None, "type_pending": False}


def _is_429(exc):
    return (isinstance(exc, urllib.error.HTTPError)
            and getattr(exc, "code", None) == 429)


def _note_backoff(state, label, waits, outcome):
    state.setdefault("backoffs", []).append(
        {"label": label, "waits": list(waits), "outcome": outcome})


def _call_with_429(call, sleep_fn, state, label):
    """One call with 60s -> 300s backoff on HTTP 429, then fail-closed.

    Returns (result-or-None, waits, exhausted). exhausted is True only on
    a 429 pile-up (caller must fail closed immediately and continue-next).
    Auth (401/403) and other errors propagate to the caller.
    """
    waits = []
    for wait in BACKOFF_WAITS:
        try:
            return call(), waits, False
        except urllib.error.HTTPError as exc:
            if getattr(exc, "code", None) == 429:
                waits.append(wait)
                _note_backoff(state, label, waits, "backing-off")
                sleep_fn(wait)
                continue
            raise
    try:
        return call(), waits, False
    except urllib.error.HTTPError as exc:
        if getattr(exc, "code", None) == 429:
            _note_backoff(state, label, waits, "exhausted-continue-next")
            return None, waits, True
        raise


# -------------------------------------------------------------- S0b ---

def s0b_needs_review(item, index, read_entry):
    """R36: (needs, gloss) — True when the raw anchor top is inflection.

    The check runs on the unresolved top scorer (no xref index): xref
    stubs never match the inflection pattern, so ordering is moot.
    Read failures fail open to (False, "") — S0b only ever adds drops
    on an explicit LLM verdict, never on lookup errors.
    """
    text = (item.get("text") or "").strip()
    if not text:
        return False, ""
    entries, pos = _entries_for(item, index)
    try:
        _, gloss, _, _ = card_pilot.pick_anchor_sense_full(
            text, entries, pos, read_entry)
    except Exception:
        return False, ""
    if gloss and (card_pilot.is_inflection_gloss(gloss)
                   or card_pilot.parse_superlative_base(gloss)):
        return True, gloss
    return False, ""


# ---------------------------------------------------------------- S1 ---

def s1_rank_item(item, index, read_entry):
    """S1 deterministic rank via the card_pilot anchor path (imported).

    Returns {"candidates": [{sense_id, gloss, score}...],
             "top": {"sense_id", "gloss"} or None,
             "en_def": gloss or "",
             "anchor_pos": entry POS of the anchored sense ("" if none)}.
    V7: anchor_pos feeds the S1 anchor-proper-noun drop in main (the ONE
    place anchors are dropped — card_pilot anchor helpers never drop).
    R39 v10: candidates are the tiered judge window (up to
    JUDGE_WINDOW_CAP, bucketed by pool_level with POS coverage) so S2
    sees the same window the pilot shortlist displays; top/en_def stay
    the S1 anchor top (window rank 1).
    """
    probe = dict(item)
    # R39 v10: judge-width window (up to JUDGE_WINDOW_CAP) built in the
    # single anchor_item_en scorer pass via candidate_k — same read
    # count as the legacy top-3 path, same xref resolution.
    card_pilot.anchor_item_en(
        probe, index, read_entry,
        candidate_k=card_pilot.JUDGE_WINDOW_CAP)
    cands = [c for c in (probe.get("sense_candidates") or [])
             if isinstance(c, dict) and c.get("sense_id")]
    top = {"sense_id": cands[0]["sense_id"], "gloss": cands[0].get("gloss", "")} \
        if cands else None
    entries, pos = _entries_for(item, index)
    anchor_pos = probe.get("anchor_pos") or \
        card_pilot.anchor_entry_pos_for_entries(
            item.get("text", ""), entries, pos, read_entry)
    return {"candidates": cands, "top": top,
            "en_def": probe.get("en_def", "") or "",
            "anchor_pos": anchor_pos,
            "anchor_tags": list(probe.get("anchor_tags") or []),
            "xref_method": probe.get("xref_method", "") or "",
            "resolved_from": probe.get("xref_resolved_from", "") or "",
            "xref_unresolvable": bool(probe.get("xref_unresolvable"))}


# ---------------------------------------------------------------- S2 ---

def _s2_prompt(batch, s1map):
    lines = ["PICK the single most useful sense per item for Persian "
             "learners of English (most concrete everyday meaning first).",
             'Output: {"results": [{"key": "<item key>", '
             '"pick": "<sense_id>"}]}.',
             "Every pick MUST be one of that item's candidate ids "
             "(empty pick only when the item has no candidates).",
             "Input follows:"]
    for item in batch:
        key = item_key(item)
        cands = (s1map.get(key) or {}).get("candidates", [])
        lines.append("KEY %s (%s, pool %s):" % (
            key, item.get("kind", "?"), item.get("pool_level", "?")))
        for cand in cands:
            lines.append("- %s %s" % (cand.get("sense_id", "?"),
                                      (cand.get("gloss") or "")[:200]))
        if not cands:
            lines.append("- (no candidates)")
    return "\n".join(lines)


def _s2_fallback(item, s1res):
    """Fail-closed pick: S1 top (via the imported deterministic_picks)."""
    from run_v14_phase3_judge import deterministic_picks
    cands = (s1res or {}).get("candidates", [])
    if not cands:
        return {"sense_id": "", "gloss": "", "model": "s1-fallback-empty"}
    pseudo = {"ranked_senses": [
        {"sense_id": c["sense_id"]} for c in cands]}
    try:
        picks = deterministic_picks(pseudo)
        first = (picks.get("beginner") or [cands[0]["sense_id"]])[0]
    except Exception:
        first = cands[0]["sense_id"]
    gloss = next((c.get("gloss", "") for c in cands
                  if c["sense_id"] == first), "")
    return {"sense_id": first, "gloss": gloss, "model": "s1-fallback"}


def _s2_validate(data, batch, s1map):
    """Accept single {"key","pick"} rows (plus lemma-style "picks" rows).

    Lemma-style rows are validated with the imported validate_picks and
    collapse to their first pick. Returns {key: {"sense_id","gloss"}}
    for valid rows only; invalid rows are left out (caller fails closed).
    """
    from run_v14_phase3_judge import validate_picks
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
        cands = (s1map.get(key) or {}).get("candidates", [])
        ids = [c["sense_id"] for c in cands]
        if not isinstance(row, dict):
            continue
        pick = row.get("pick")
        if pick is None and isinstance(row.get("picks"), dict):
            if validate_picks(row["picks"], ids):
                flat = (row["picks"].get("beginner")
                        or row["picks"].get("intermediate")
                        or row["picks"].get("advanced") or [])
                pick = flat[0] if flat else None
            else:
                continue
        if pick == "" and not ids:
            out[key] = {"sense_id": "", "gloss": ""}
        elif isinstance(pick, str) and pick in ids:
            gloss = next(c.get("gloss", "") for c in cands
                         if c["sense_id"] == pick)
            out[key] = {"sense_id": pick, "gloss": gloss}
    want = {item_key(i) for i in batch}
    if set(out) != want:
        return None
    return out


def s2_judge_batch(batch, s1map, api_key, transport, sleep_fn, state,
                   telemetry=None, tele_stage="s2", tele_batch=0):
    """Judge-pick one batch. Returns {key: {sense_id, gloss, model}}.

    Muse-only chain (judge MODELS[:2]), 2 attempts per model, 401/403
    loud abort, 429 backoff-then-continue-next, anything else fail-closed
    to the S1 top pick per item. R27: one telemetry record per batch
    (ok on a judge-model pick, fallback on s1-fallback).
    """
    from run_v14_phase3_judge import MODELS as JUDGE_MODELS
    from run_v14_phase3_judge import call_responses as _  # noqa: F401 (owner path ref)
    models = list(JUDGE_MODELS[:2])
    prompt = _s2_prompt(batch, s1map)
    transport = transport  # default wired by caller to judge call_responses
    give_up = False  # 429 pile-up: stop the chain, fail closed now
    for model in models:
        for attempt in range(MAX_ATTEMPTS):
            text = prompt if attempt == 0 else RETRY_PREFIX + prompt
            label = "%s/%s#%d" % (model, "+".join(
                item_key(i) for i in batch), attempt)
            try:
                raw, _waits, exhausted = _call_with_429(
                    lambda: transport(api_key, model, text),
                    sleep_fn, state, label)
            except AuthError:
                raise
            except urllib.error.HTTPError as exc:
                if getattr(exc, "code", None) in (401, 403):
                    raise_for_auth(exc)
                raw, exhausted = None, False
            except Exception:
                raw, exhausted = None, False
            if exhausted:
                give_up = True
                break
            if raw is None:
                continue
            try:
                data = extract_json(raw)
            except AuthError:
                raise
            except Exception:
                continue
            try:
                valid = _s2_validate(data, batch, s1map)
            except Exception:
                valid = None
            if valid is not None:
                out = {k: {**v, "model": model} for k, v in valid.items()}
                if telemetry is not None:
                    _tele_record(telemetry, stage=tele_stage,
                                 batch_id=tele_batch, key_idx=0,
                                 model=model, latency_s=0.0, outcome="ok")
                return out
        if give_up:
            break
    out = {item_key(i): {**_s2_fallback(i, s1map.get(item_key(i))),
                         } for i in batch}
    if telemetry is not None:
        _tele_record(telemetry, stage=tele_stage, batch_id=tele_batch,
                     key_idx=0, model="s1-fallback", latency_s=0.0,
                     outcome="fallback")
    return out


# ---------------------------------------------------------------- S3 ---

def _s3_pseudo_records(batch, s2map, s1map):
    """Group batch picks into run_v15 pseudo lemma records."""
    groups = {}
    for item in batch:
        key = item_key(item)
        pick = (s2map.get(key) or {})
        sid = pick.get("sense_id", "")
        if not sid:
            continue
        lemma = (item.get("text") or "").strip()
        rec = groups.setdefault(
            lemma, {"lemma": lemma, "ranked_senses": []})
        if all(s["sense_id"] != sid for s in rec["ranked_senses"]):
            gloss = pick.get("gloss", "") or (
                s1map.get(key) or {}).get("en_def", "")
            rec["ranked_senses"].append(
                {"sense_id": sid, "gloss": gloss,
                 "topic_label": "Other / Abstract"})
    return list(groups.values())


def s3_vector_batch(batch, s2map, s1map, api_key, transport, sleep_fn, state,
                    telemetry=None, tele_stage="s3", tele_batch=0):
    """Topic vectors for one batch via the run_v15 path (imported).

    Returns {sense_id: {"vector": [{label, weight}...], "model": ...}}.
    Empty-pick items are absent (caller maps them to the single Other
    fallback). Total failure fails closed per lemma to fallback_vectors.
    R27: one telemetry record per batch (ok / fallback).
    """
    from run_v15_topics import MODELS as V15_MODELS
    from run_v15_topics import USER_TMPL, fallback_vectors, lemma_block
    from run_v15_topics import validate_vectors
    from run_v15_topics import call_responses as _  # noqa: F401 (owner path ref)
    pseudos = _s3_pseudo_records(batch, s2map, s1map)
    out = {}
    if not pseudos:
        return out
    prompt = USER_TMPL + "\n\n".join(lemma_block(r) for r in pseudos)
    give_up = False
    for model in V15_MODELS:
        for attempt in range(MAX_ATTEMPTS):
            text = prompt if attempt == 0 else RETRY_PREFIX + prompt
            label = "%s/v15#%d" % (model, attempt)
            try:
                raw, _waits, exhausted = _call_with_429(
                    lambda: transport(api_key, model, text),
                    sleep_fn, state, label)
            except AuthError:
                raise
            except urllib.error.HTTPError as exc:
                if getattr(exc, "code", None) in (401, 403):
                    raise_for_auth(exc)
                raw, exhausted = None, False
            except Exception:
                raw, exhausted = None, False
            if exhausted:
                give_up = True
                break
            if raw is None:
                continue
            try:
                data = extract_json(raw)
            except AuthError:
                raise
            except Exception:
                continue
            by_lemma = {x.get("lemma"): x for x in
                        (data.get("results") or [])
                        if isinstance(x, dict)} \
                if isinstance(data, dict) else {}
            ok_all, merged = True, {}
            for pseudo in pseudos:
                vecs = (by_lemma.get(pseudo["lemma"]) or {}).get("vectors")
                try:
                    good, normed = validate_vectors(vecs, pseudo)
                except Exception:
                    good, normed = False, None
                if not good or normed is None:
                    ok_all = False
                    break
                for entry in normed:
                    merged[entry["sense_id"]] = {
                        "vector": [{"label": e["topic_label"],
                                    "weight": round(float(e["weight"]), 4)}
                                   for e in entry["vector"]],
                        "model": model}
            if ok_all:
                if telemetry is not None:
                    _tele_record(telemetry, stage=tele_stage,
                                 batch_id=tele_batch, key_idx=0,
                                 model=model, latency_s=0.0, outcome="ok")
                return merged
        if give_up:
            break
    for pseudo in pseudos:
        try:
            legs = fallback_vectors(pseudo)
        except Exception:
            legs = []
        for entry in legs:
            out[entry["sense_id"]] = {
                "vector": [{"label": e["topic_label"],
                            "weight": round(float(e["weight"]), 4)}
                           for e in entry["vector"]],
                "model": "deterministic"}
    if telemetry is not None:
        _tele_record(telemetry, stage=tele_stage, batch_id=tele_batch,
                     key_idx=0, model="deterministic", latency_s=0.0,
                     outcome="fallback")
    return out


# ---------------------------------------------------------------- S4 ---

def _backoff_llm_transport(transport, sleep_fn, state):
    """Wrap an (api_key, model, user_text) transport with 60s->300s 429
    backoff (recorded); third 429 re-raises so assign_topic fails closed."""
    def wrap(api_key, model, user_text):
        waits = []
        for wait in BACKOFF_WAITS:
            try:
                return transport(api_key, model, user_text)
            except urllib.error.HTTPError as exc:
                if getattr(exc, "code", None) == 429:
                    waits.append(wait)
                    _note_backoff(state, "%s/s4" % model, waits,
                                  "backing-off")
                    sleep_fn(wait)
                    continue
                raise
        try:
            return transport(api_key, model, user_text)
        except urllib.error.HTTPError as exc:
            if getattr(exc, "code", None) == 429:
                _note_backoff(state, "%s/s4" % model, waits,
                              "exhausted-continue-next")
            raise
    return wrap


def s4_label_item(item, gloss, sense_id, vector_lookup, api_key, transport,
                  sleep_fn, state, progress_path, model_calls,
                  telemetry=None, tele_stage="s4", tele_batch=0):
    """S4 topic label via card_pilot.assign_topic (imported two-leg)."""
    llm_leg = (_backoff_llm_transport(transport, sleep_fn, state)
               if transport is not None else None)
    try:
        assigned = card_pilot.assign_topic(
            item.get("text", ""), gloss or "",
            sense_id=sense_id or None, llm_transport=llm_leg,
            progress_path=progress_path, api_key=api_key,
            model_calls=model_calls, vector_lookup=vector_lookup)
    except AuthError:
        if telemetry is not None:
            _tele_record(telemetry, stage=tele_stage, batch_id=tele_batch,
                         key_idx=0, model="", latency_s=0.0,
                         outcome="auth")
        raise
    except Exception:
        assigned = {"label": "Other / Abstract",
                    "method": card_pilot.TOPIC_METHOD_TAG,
                    "vector": card_pilot.single_topic_vector(
                        "Other / Abstract")}
        if telemetry is not None:
            _tele_record(telemetry, stage=tele_stage, batch_id=tele_batch,
                         key_idx=0, model="", latency_s=0.0,
                         outcome="fallback")
    else:
        if telemetry is not None:
            _tele_record(telemetry, stage=tele_stage, batch_id=tele_batch,
                         key_idx=0, model="", latency_s=0.0, outcome="ok")
    return assigned


# ---------------------------------------------------------------- S5 ---

def _entries_for(item, index):
    """Candidate entry rows for an item (same selection as anchor_item_en)."""
    text = (item.get("text") or "").strip()
    key = text.lower()
    if (item.get("kind") or "word") == "word":
        return list((index or {}).get(key, [])), item.get("pos", "")
    if key in (index or {}):
        return list(index[key]), ""
    for token in sorted(set(key.split()), key=lambda t: (-len(t), t)):
        rows = (index or {}).get(token, [])
        if rows:
            return list(rows), ""
    return [], ""


def s5_enrich_item(item, s2pick, index, read_entry, tatoeba_pool,
                   zipf_fn=None):
    """S5 enrichment from the S2-chosen sense (card_pilot helpers only).

    R29/R32 v8: also returns abbrev_expansion (dataset-first parse of the
    chosen gloss) and pos/pos_src (anchored entry POS first, 1-3 tags).
    R42 v11: the example pool (anchored-sense kaikki examples, then the
    tatoeba pool — both through the existing length filter, reused)
    additionally passes the four cloze gates via
    card_pilot.prefer_cloze_passing (reused by import): cloze-passing
    examples fill the N_EXAMPLES slots first; cloze failures backfill
    only when no passing alternative exists, so the downstream release
    machinery (split_frozen_by_containment) still records them with
    their cloze-<gate> reason instead of silently keeping weak slots.
    """
    sid = (s2pick or {}).get("sense_id", "")
    gloss = (s2pick or {}).get("gloss", "")
    if not sid:
        return {"sense_id": "", "en_def": gloss or "",
                "ipa": "", "ipa_src": card_pilot.IPA_SRC_MODEL,
                "dataset_examples": [], "abbrev_expansion": "",
                "pos": [], "pos_src": "none"}
    try:
        want_idx = int(sid.split("#")[-1])
    except (TypeError, ValueError):
        want_idx = None
    entries, pos = _entries_for(item, index)
    # R34 v9: an xref-resolved pick carries the TARGET lemma in its
    # sense_id ("colour#2" for item "color") — enrich from the target
    # rows, not the item rows.
    sid_lemma = sid.rpartition("#")[0].strip().lower() if "#" in sid \
        else ""
    if sid_lemma and sid_lemma != (item.get("text") or "").strip().lower():
        target_rows = (index or {}).get(sid_lemma)
        if target_rows:
            entries, pos = list(target_rows), ""
    entry = sense = None
    if want_idx is not None:
        try:
            scored = card_pilot.score_senses(
                sid_lemma or item.get("text", ""), entries, pos,
                read_entry)
        except Exception:
            scored = []
        for _score, idx, cand_entry, cand_sense, _gloss in scored:
            if idx == want_idx:
                entry, sense = cand_entry, cand_sense
                break
    ipa = card_pilot.first_entry_ipa(entry) if entry else ""
    pool = card_pilot.filter_examples_by_length(
        card_pilot.sense_example_texts(sense)) if sense else []
    extra = card_pilot.filter_examples_by_length(
        card_pilot.tatoeba_candidates(
            tatoeba_pool, item.get("text", ""),
            item.get("kind") or "word"),
        loose_cap=True)
    seen = set(pool)
    for cand in extra:
        if cand not in seen:
            pool.append(cand)
            seen.add(cand)
    picked = card_pilot.prefer_cloze_passing(
        pool, item.get("text", ""), item.get("kind") or "word",
        item.get("pool_level", ""), card_pilot.N_EXAMPLES, zipf_fn)
    pos_tags = card_pilot.anchor_pos_tags(
        item.get("text", ""), entries, pos, read_entry)
    return {"sense_id": sid, "en_def": gloss or "",
            "ipa": ipa,
            "ipa_src": card_pilot.IPA_SRC_DATASET if ipa
            else card_pilot.IPA_SRC_MODEL,
            "dataset_examples": picked[:card_pilot.N_EXAMPLES],
            "abbrev_expansion": card_pilot.parse_abbrev_expansion(
                gloss or ""),
            "pos": pos_tags,
            "pos_src": "dataset" if pos_tags else "none"}


# ------------------------------------------------------------- main ---

def _default_judge_transport(api_key, model, user_text):
    from run_v14_phase3_judge import call_responses
    return call_responses(api_key, model, user_text)


def _default_topic_transport(api_key, model, user_text):
    from run_v15_topics import call_responses
    return call_responses(api_key, model, user_text)


def _default_assign_transport(api_key, model, user_text):
    from run_v16b_topup import call_responses
    return call_responses(api_key, model, user_text)


def _default_inflect_transport(api_key, model, sys_text, user_text):
    return card_pilot.call_responses(api_key, model, sys_text, user_text)


def _flush(progress_dir, states):
    for stage in STAGES:
        write_progress(str(pathlib.Path(progress_dir) / ("%s.json" % stage)),
                       states[stage])


# Sentinel: None means "no LLM leg" (deterministic only), _USE_DEFAULT
# means the real pipeline-script transport. (Plain `or` would conflate
# the two and leak network calls into hermetic tests.)
_USE_DEFAULT = object()


def main(argv=None, _judge_transport=_USE_DEFAULT,
         _topic_transport=_USE_DEFAULT, _assign_transport=_USE_DEFAULT,
         _inflect_transport=_USE_DEFAULT,
         _sleep_fn=None, _index=None, _read_entry=None, _tatoeba=None,
         _zipf_fn=None, _awl_set=None, _type_map=None,
         _type_log_available=None):
    """Run the pre-card pipeline. Returns 0 on success (exit code)."""
    args = parse_args(argv)
    sleep_fn = _sleep_fn or time.sleep
    items = load_sample(args.sample)
    if args.limit:
        items = items[:args.limit]

    if args.dry_run:
        selected = _selected_stages(args)
        rekeyed = _load_rekey_keys(args.rekey)
        needs = _dry_run_needs(args.progress_dir, items, selected,
                               rekeyed, resume=not args.no_resume)
        print("dry-run plan (nothing written, no network):")
        print("  sample:   %s (%d items)" % (args.sample, len(items)))
        print("  out:      %s (not written)" % args.out)
        print("  progress: %s (not written)" % args.progress_dir)
        print("  batches:  %d x %d (S0..S5 incl. S0b, resume %s)" % (
            (len(items) + BATCH - 1) // BATCH if items else 0, BATCH,
            "off" if args.no_resume else "on"))
        print("  stages:   S0 preprocess[R4-name/R20-zipf-level/phrase-type] / "
              "S0b inflection-review / S1 rank / S2 judge[1.3->1.2] / "
              "S3 vectors / S4 label / S5 enrich")
        print("  selected: %s" % ", ".join(s for s in STAGES
                                           if s in selected))
        if rekeyed:
            print("  rekey:    %d key(s) forced to redo" % len(rekeyed))
        for stage in STAGES:
            if stage in selected:
                print("  need %s: %d todo (%d done kept, upper bound "
                      "pre-drop)" % (stage, needs[stage]["todo"],
                                     needs[stage]["done"]))
            else:
                print("  stage %s: skipped (not selected)" % stage)
        return 0

    progress_dir = pathlib.Path(args.progress_dir)
    progress_dir.mkdir(parents=True, exist_ok=True)
    resume = not args.no_resume
    states = {}
    for stage in STAGES:
        path = progress_dir / ("%s.json" % stage)
        loaded = {}
        if resume and path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise SystemExit("corrupt progress %s: %s" % (path, exc))
        states[stage] = {"done": loaded.get("done", {}),
                         "failed": loaded.get("failed", []),
                         "backoffs": loaded.get("backoffs", [])}
    total = len(items)
    banner = []
    for stage in STAGES:
        done_n = len(states[stage]["done"])
        banner.append("%s done=%d remaining=%d" % (
            stage, done_n, max(0, total - done_n)))
    print("resume: %s" % " | ".join(banner))
    # R26: stage selection + rekey eviction (resume still skips the rest).
    # Stage dependency: S1/S2 feed S3/S4/S5 (anchor -> judge -> vector ->
    # label -> enrich), so rekeying an upstream stage auto-invalidates the
    # same keys downstream — otherwise assembly mixes new anchors with
    # stale enrichment (kiss#5-style staleness).
    _DOWNSTREAM = {"s1": ("s2", "s3", "s4", "s5"), "s2": ("s3", "s4", "s5"),
                   "s3": ("s4", "s5"), "s4": ("s5",)}
    selected = _selected_stages(args)
    rekeyed = _load_rekey_keys(args.rekey)
    if rekeyed:
        rekeyed_set = set(rekeyed)
        for stage in selected:
            for key in rekeyed:
                states[stage]["done"].pop(key, None)
            states[stage]["failed"] = [
                k for k in states[stage]["failed"]
                if k not in rekeyed_set]
        for stage in selected:
            for down in _DOWNSTREAM.get(stage, ()):
                for key in rekeyed:
                    states[down]["done"].pop(key, None)
                states[down]["failed"] = [
                    k for k in states[down]["failed"]
                    if k not in rekeyed_set]
        print("rekey: %d key(s) forced to redo in %s" % (
            len(rekeyed),
            ", ".join(s for s in STAGES if s in selected)))

    # V7: compact run.log in the out dir (stage start/end + counts +
    # timings); batch_log_line (owned by card_pilot, reused by import)
    # prints ONE stdout line per batch. ok/fail per stage: s0 kept vs
    # dropped; s1 ranked vs anchor-proper-noun/error; s2 judge model vs
    # s1-fallback; s3 model vector vs deterministic fallback; s4/s5 have
    # no fail-closed signal, so fail is always 0 there.
    from card_pilot import RunLogger, batch_log_line  # noqa: E402
    run_logger = RunLogger(
        str(pathlib.Path(args.out).parent / "run.log"))
    for stage in STAGES:
        if stage not in selected:
            run_logger.log("stage %s skipped (not selected)" % stage)
    tele_store = []  # R27: per-batch records (key_idx only, never values)

    if _index is not None:
        index = _index
    else:
        try:
            index = card_pilot.load_kaikki_index(args.kaikki_index)
        except OSError as exc:
            raise SystemExit("cannot load kaikki index %s: %s" % (
                args.kaikki_index, exc))
    if _read_entry is not None:
        read_entry = _read_entry
    else:
        def read_entry(row, _raw=args.kaikki_raw):
            return card_pilot.read_kaikki_entry(_raw, row["offset"],
                                                row["length"])
    tatoeba_pool = _tatoeba if _tatoeba is not None else \
        card_pilot.load_tatoeba_pool(args.tatoeba_pool)

    # S0 (strict preprocess, deterministic, batch-flushed). Aux files fail
    # open to keep: a missing AWL/type-log only ever adds keeps.
    zipf_fn = _zipf_fn or default_zipf
    awl_set = (_awl_set if _awl_set is not None
               else load_awl_members(args.awl_families))
    if _type_map is not None:
        type_map = _type_map
    else:
        try:
            type_map = card_pilot.load_phrase_types(args.phrase_type_log)
        except Exception:
            type_map = {}
    type_log_available = (bool(type_map) if _type_log_available is None
                          else bool(_type_log_available))
    pos_sets = card_pilot.build_pos_sets(index)
    s0_info: dict = {}
    run_logger.stage_start("s0")
    n_s0_batches = (len(items) + BATCH - 1) // BATCH or 1
    for batch_no, base in enumerate(
            _stage_range(selected, "s0", items), start=1):
        batch = items[base:base + BATCH]
        for item in batch:
            key = item_key(item)
            if key not in states["s0"]["done"]:
                verdict = s0_classify_item(
                    item, pos_sets, zipf_fn, awl_set, type_map,
                    type_log_available)
                states["s0"]["done"][key] = verdict
                if not verdict["kept"] \
                        and key not in states["s0"]["failed"]:
                    states["s0"]["failed"].append(key)
        _flush(progress_dir, states)
        ok = sum(1 for i in batch
                 if (states["s0"]["done"].get(item_key(i)) or {}).get("kept"))
        print(batch_log_line("s0", batch_no, n_s0_batches, ok,
                             len(batch) - ok, {}))
    run_logger.stage_end(
        "s0",
        ok=sum(1 for v in states["s0"]["done"].values() if v.get("kept")),
        fail=len(states["s0"].get("failed", [])))
    for key, verdict in states["s0"]["done"].items():
        s0_info[key] = verdict
    dropped = {k for k, v in s0_info.items() if not v.get("kept")}
    items = [i for i in items if item_key(i) not in dropped]
    if dropped:
        print("s0 preprocess: kept=%d dropped=%d (%s)" % (
            len(items), len(dropped),
            ", ".join(sorted("%s:%s" % (k, s0_info[k].get("reason"))
                             for k in dropped))))

    need_llm = (_judge_transport is _USE_DEFAULT
                or _topic_transport is _USE_DEFAULT
                or _assign_transport is _USE_DEFAULT
                or _inflect_transport is _USE_DEFAULT)
    api_key = "injected"
    if need_llm:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from env_loader import load_factory_env
        env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
        api_key = env["OPENCODE_ZEN_API_KEY"]
        if not api_key:
            raise SystemExit("no OPENCODE_ZEN_API_KEY in factory/.env")
    judge_transport = (_default_judge_transport
                       if _judge_transport is _USE_DEFAULT
                       else _judge_transport)
    topic_transport = (_default_topic_transport
                       if _topic_transport is _USE_DEFAULT
                       else _topic_transport)
    assign_transport = (_default_assign_transport
                        if _assign_transport is _USE_DEFAULT
                        else _assign_transport)
    inflect_transport = (_default_inflect_transport
                         if _inflect_transport is _USE_DEFAULT
                         else _inflect_transport)

    s4_cache = progress_dir / "s4_topup_cache.json"
    s4_calls: dict = {}
    precards: dict = {}
    s0b_dropped: set = set()
    try:
        # S0b R36: inflection micro-stage (own progress key s0b.json).
        # Items whose raw anchor top is an inflection stub go to the
        # batched inflection_review (card_pilot, Muse chain, imported);
        # explicit keep-false drops with reason inflection-drop:<reason>;
        # review errors keep the item flagged review-uncertain (fail
        # closed, never drop on uncertainty). transport=None skips the
        # LLM leg (all kept, stated). Drops never reach precard.jsonl.
        # R44 v12: superlative/comparative-pattern glosses redirect to
        # the BASE lemma (kept, reason superlative-redirect, redirect_to
        # the base) on an explicit keep-false verdict; an explicit keep
        # (established nominal/idiomatic sense) stays inflection-keep.
        # Verdict variant inside S0b — no new stage.
        run_logger.stage_start("s0b")
        n_s0b_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s0b", items), start=1):
            batch = items[base:base + BATCH]
            todo = [i for i in batch
                    if item_key(i) not in states["s0b"]["done"]]
            review = []
            for item in todo:
                key = item_key(item)
                try:
                    needs, gloss = s0b_needs_review(
                        item, index, read_entry)
                except Exception:
                    needs, gloss = False, ""
                if not needs:
                    states["s0b"]["done"][key] = {
                        "kept": True, "reason": "not-inflection",
                        "uncertain": False}
                else:
                    review.append({"key": key,
                                   "text": item.get("text", ""),
                                   "gloss": gloss})
            if review and inflect_transport is not None:
                try:
                    verdicts = card_pilot.inflection_review(
                        review, inflect_transport, api_key)
                except AuthError:
                    raise
                except Exception:
                    verdicts = {}
                for entry in review:
                    key = entry["key"]
                    verdict = verdicts.get(key)
                    base = card_pilot.parse_superlative_base(
                        entry.get("gloss") or "")
                    if verdict is None:
                        states["s0b"]["done"][key] = {
                            "kept": True, "reason": "review-uncertain",
                            "uncertain": True}
                    elif not verdict.get("keep") and base:
                        states["s0b"]["done"][key] = {
                            "kept": True,
                            "reason": "superlative-redirect",
                            "redirect_to": base,
                            "uncertain": False}
                    elif not verdict.get("keep"):
                        states["s0b"]["done"][key] = {
                            "kept": False,
                            "reason": "inflection-drop:%s" % (
                                verdict.get("reason") or "base-lemma"),
                            "uncertain": False}
                        if key not in states["s0b"]["failed"]:
                            states["s0b"]["failed"].append(key)
                    else:
                        states["s0b"]["done"][key] = {
                            "kept": True,
                            "reason": ("review-uncertain"
                                       if verdict.get("uncertain")
                                       else "inflection-keep"),
                            "uncertain": bool(
                                verdict.get("uncertain"))}
                sleep_fn(SLEEP)
            elif review:
                for entry in review:
                    states["s0b"]["done"][entry["key"]] = {
                        "kept": True, "reason": "s0b-no-transport",
                        "uncertain": False}
            _flush(progress_dir, states)
            failed_here = sum(
                1 for i in batch
                if not (states["s0b"]["done"].get(item_key(i)) or {}).get(
                    "kept", True))
            print(batch_log_line("s0b", batch_no, n_s0b_batches,
                                 len(batch) - failed_here, failed_here,
                                 {}))
        run_logger.stage_end(
            "s0b",
            ok=sum(1 for v in states["s0b"]["done"].values()
                   if v.get("kept")),
            fail=len(states["s0b"].get("failed", [])))
        s0b_dropped = {k for k, v in states["s0b"]["done"].items()
                       if isinstance(v, dict) and not v.get("kept")}
        items = [i for i in items if item_key(i) not in s0b_dropped]
        # R44 v12: propagate superlative redirects onto the in-memory
        # items AND merge into the base lemma (Gemini: avoid FSRS
        # fragmentation across best/good). The item becomes the base form
        # (redirected_from recorded); downstream stages key off the new
        # text, so fresh keys are resume-safe by construction.
        for item in items:
            s0b = states["s0b"]["done"].get(item_key(item)) or {}
            if s0b.get("redirect_to"):
                item["redirect_to"] = s0b["redirect_to"]
                item["s0b_reason"] = s0b.get("reason", "")
                base = str(s0b["redirect_to"]).strip().lower()
                if base and base != (item.get("text") or "").strip().lower():
                    item["redirected_from"] = item.get("text", "")
                    item["text"] = base
        if s0b_dropped:
            print("s0b inflection: kept=%d dropped=%d (%s)" % (
                len(items), len(s0b_dropped),
                ", ".join(sorted(
                    "%s:%s" % (k, states["s0b"]["done"][k].get("reason"))
                    for k in s0b_dropped
                    if k in states["s0b"]["done"]))))
        # S1 (deterministic, batch-flushed). V7 anchor-POS drop lives ONLY
        # here: when the anchored sense's entry POS is in {name, propn}
        # (card_pilot.PROPER_NOUN_POS, reused by import — deterministic,
        # no name lists) the item drops with reason anchor-proper-noun.
        # R34 v9: unresolvable bare-xref anchors drop here too (reason
        # no-real-def: no target entry, or the target is also a bare
        # xref — 1 hop max, no chains).
        # The reason rides on the s1 done entry + failed list (drops never
        # reach precard.jsonl); s1_dropped is rebuilt from state, so the
        # drop is resume-safe with no re-run needed.
        run_logger.stage_start("s1")
        n_s1_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s1", items), start=1):
            batch = items[base:base + BATCH]
            for item in batch:
                key = item_key(item)
                # V7 resume-compat: v6-era s1 entries lack anchor_pos, so
                # they are re-ranked deterministically (same scores plus
                # anchor_pos/drop verdict) instead of skipped. R34 v9
                # extends the compat to the xref fields.
                done_entry = states["s1"]["done"].get(key)
                if not isinstance(done_entry, dict) \
                        or "anchor_pos" not in done_entry \
                        or "anchor_tags" not in done_entry \
                        or "xref_unresolvable" not in done_entry:
                    try:
                        ranked = s1_rank_item(item, index, read_entry)
                        if (ranked.get("anchor_pos") or "") in \
                                card_pilot.PROPER_NOUN_POS:
                            ranked["dropped"] = "anchor-proper-noun"
                            if key not in states["s1"]["failed"]:
                                states["s1"]["failed"].append(key)
                        elif set(ranked.get("anchor_tags") or {}) & \
                                card_pilot.VULGAR_TAGS:
                            ranked["dropped"] = "vulgar-anchor"
                            if key not in states["s1"]["failed"]:
                                states["s1"]["failed"].append(key)
                        elif ranked.get("xref_unresolvable"):
                            ranked["dropped"] = "no-real-def"
                            if key not in states["s1"]["failed"]:
                                states["s1"]["failed"].append(key)
                        states["s1"]["done"][key] = ranked
                    except Exception as exc:
                        states["s1"]["done"][key] = {
                            "candidates": [], "top": None, "en_def": "",
                            "anchor_pos": "", "xref_method": "",
                            "resolved_from": "",
                            "xref_unresolvable": False}
                        if key not in states["s1"]["failed"]:
                            states["s1"]["failed"].append(key)
                        _note_backoff(states["s1"], key, [],
                                      "s1-error: %s" % type(exc).__name__)
            _flush(progress_dir, states)
            failed_here = sum(
                1 for i in batch
                if (states["s1"]["done"].get(item_key(i)) or {}).get(
                    "dropped")
                or item_key(i) in states["s1"]["failed"])
            print(batch_log_line("s1", batch_no, n_s1_batches,
                                 len(batch) - failed_here, failed_here,
                                 {}))
        s1_dropped = {k for k, v in states["s1"]["done"].items()
                      if isinstance(v, dict) and v.get("dropped")}
        run_logger.stage_end("s1", ok=len(states["s1"]["done"]) - len(
            s1_dropped), fail=len(s1_dropped))
        if s1_dropped:
            print("s1 anchor-pos: kept=%d dropped=%d (%s)" % (
                len(items) - len(s1_dropped & {item_key(i) for i in items}),
                len(s1_dropped & {item_key(i) for i in items}),
                ", ".join(sorted(
                    "%s:%s" % (k, states["s1"]["done"][k].get("dropped"))
                    for k in s1_dropped
                    if k in states["s1"]["done"]))))
        items = [i for i in items if item_key(i) not in s1_dropped]
        # S2 (judge batches). ok = judge-model picks in the batch,
        # fail = s1-fallback (fail-closed) picks in the batch.
        run_logger.stage_start("s2")
        n_s2_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s2", items), start=1):
            batch = items[base:base + BATCH]
            todo = [i for i in batch
                    if item_key(i) not in states["s2"]["done"]]
            if todo:
                try:
                    verdicts = s2_judge_batch(
                        todo, states["s1"]["done"], api_key,
                        judge_transport, sleep_fn, states["s2"],
                        telemetry=tele_store, tele_batch=batch_no)
                except AuthError:
                    raise
                for item in todo:
                    key = item_key(item)
                    verdict = verdicts.get(key)
                    if verdict is None:
                        verdict = _s2_fallback(
                            item, states["s1"]["done"].get(key))
                    states["s2"]["done"][key] = verdict
                    if (verdict.get("model") or "").startswith("s1-") \
                            and key not in states["s2"]["failed"]:
                        states["s2"]["failed"].append(key)
                sleep_fn(SLEEP)
            _flush(progress_dir, states)
            fail = sum(
                1 for i in batch
                if ((states["s2"]["done"].get(item_key(i)) or {}).get(
                    "model", "") or "").startswith("s1-"))
            print(batch_log_line("s2", batch_no, n_s2_batches,
                                 len(batch) - fail, fail, {}))
        run_logger.stage_end(
            "s2",
            ok=sum(1 for v in states["s2"]["done"].values()
                   if not (v.get("model", "") or "").startswith("s1-")),
            fail=sum(1 for v in states["s2"]["done"].values()
                     if (v.get("model", "") or "").startswith("s1-")))
        # S3 (vector batches). ok = model vectors, fail = deterministic
        # (fail-closed) fallbacks.
        run_logger.stage_start("s3")
        n_s3_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s3", items), start=1):
            batch = items[base:base + BATCH]
            todo = [i for i in batch
                    if item_key(i) not in states["s3"]["done"]]
            if todo:
                try:
                    vecs = s3_vector_batch(
                        todo, states["s2"]["done"],
                        states["s1"]["done"], api_key,
                        topic_transport, sleep_fn, states["s3"],
                        telemetry=tele_store, tele_batch=batch_no)
                except AuthError:
                    raise
                for item in todo:
                    key = item_key(item)
                    sid = (states["s2"]["done"].get(key) or {}).get(
                        "sense_id", "")
                    hit = vecs.get(sid) if sid else None
                    if hit is None:
                        hit = {"vector": [{"label": "Other / Abstract",
                                           "weight": 1.0}],
                               "model": "deterministic"}
                        if key not in states["s3"]["failed"]:
                            states["s3"]["failed"].append(key)
                    states["s3"]["done"][key] = hit
                sleep_fn(SLEEP)
            _flush(progress_dir, states)
            fail = sum(
                1 for i in batch
                if (states["s3"]["done"].get(item_key(i)) or {}).get(
                    "model") == "deterministic")
            print(batch_log_line("s3", batch_no, n_s3_batches,
                                 len(batch) - fail, fail, {}))
        run_logger.stage_end(
            "s3",
            ok=sum(1 for v in states["s3"]["done"].values()
                   if v.get("model") != "deterministic"),
            fail=sum(1 for v in states["s3"]["done"].values()
                     if v.get("model") == "deterministic"))
        # S4 (label per item, batch-flushed). No fail-closed signal on
        # this stage (exceptions propagate, except auth which aborts),
        # so fail is always 0.
        run_logger.stage_start("s4")
        vec_lookup = {}
        for key, hit in states["s3"]["done"].items():
            for entry in (hit.get("vector") or []):
                if isinstance(entry, dict) and entry.get("label"):
                    vec_lookup.setdefault(
                        (states["s2"]["done"].get(key) or {}).get(
                            "sense_id", ""),
                        []).append(entry)
        n_s4_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s4", items), start=1):
            batch = items[base:base + BATCH]
            did_work = False
            for item in batch:
                key = item_key(item)
                if key not in states["s4"]["done"]:
                    did_work = True
                    pick = states["s2"]["done"].get(key) or {}
                    lookup = {}
                    if pick.get("sense_id") in vec_lookup:
                        lookup[pick["sense_id"]] = vec_lookup[
                            pick["sense_id"]]
                    try:
                        assigned = s4_label_item(
                            item, pick.get("gloss", ""),
                            pick.get("sense_id", ""), lookup or None,
                            api_key, assign_transport, sleep_fn,
                            states["s4"], str(s4_cache), s4_calls,
                            telemetry=tele_store, tele_batch=batch_no)
                    except AuthError:
                        raise
                    states["s4"]["done"][key] = assigned
            if did_work:
                sleep_fn(SLEEP)
            _flush(progress_dir, states)
            print(batch_log_line("s4", batch_no, n_s4_batches,
                                 len(batch), 0, s4_calls))
        run_logger.stage_end("s4", ok=len(states["s4"]["done"]), fail=0)
        # S5 (deterministic enrichment, batch-flushed). Same as S4: no
        # fail-closed signal, fail is always 0.
        run_logger.stage_start("s5")
        n_s5_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s5", items), start=1):
            batch = items[base:base + BATCH]
            for item in batch:
                key = item_key(item)
                if key not in states["s5"]["done"]:
                    states["s5"]["done"][key] = s5_enrich_item(
                        item, states["s2"]["done"].get(key) or {},
                        index, read_entry, tatoeba_pool)
            _flush(progress_dir, states)
            print(batch_log_line("s5", batch_no, n_s5_batches,
                                 len(batch), 0, {}))
        run_logger.stage_end("s5", ok=len(states["s5"]["done"]), fail=0)
        # Assemble output (survivors only; drops live in s0/s1 progress).
        for item in items:
            key = item_key(item)
            enrich = states["s5"]["done"].get(key) or {}
            label = states["s4"]["done"].get(key) or {}
            vec3 = states["s3"]["done"].get(key) or {}
            pick = states["s2"]["done"].get(key) or {}
            s0v = s0_info.get(key) or {}
            s0b = states["s0b"]["done"].get(key) or {}
            topic_vector = (label.get("vector")
                            or vec3.get("vector")
                            or [{"label": "Other / Abstract",
                                 "weight": 1.0}])
            rec = {
                "key": key, "kind": item.get("kind") or "word",
                "text": item.get("text", ""),
                "pool_level": item.get("pool_level", ""),
                "redirect_to": item.get("redirect_to", "") or "",
                "redirected_from": item.get("redirected_from", "") or "",
                "sense_id": enrich.get("sense_id", ""),
                "en_def": enrich.get("en_def", ""),
                "ipa": enrich.get("ipa", ""),
                "ipa_src": enrich.get("ipa_src",
                                      card_pilot.IPA_SRC_MODEL),
                "dataset_examples": enrich.get("dataset_examples", []),
                "abbrev_expansion": enrich.get("abbrev_expansion", ""),
                "pos": enrich.get("pos", []),
                "pos_src": enrich.get("pos_src", "none"),
                "topic_vector": topic_vector,
                "topic_method": label.get("method")
                or card_pilot.TOPIC_METHOD_TAG,
                "drop_reason": None,
                "stage_calls": {
                    "s0": ("kept:type-pending" if s0v.get("type_pending")
                           else "kept"),
                    "s0b": (s0b.get("reason", "") or "kept"),
                    "s2": pick.get("model", ""),
                    "s3": vec3.get("model", ""),
                    "s4": label.get("method", ""),
                    "s4_models": dict(s4_calls)},
            }
            if s0v.get("type_pending"):
                rec["type_pending"] = True
            precards[key] = rec
    except KeyboardInterrupt:
        print("interrupted — flushing stage progress")
        raise SystemExit(130)
    finally:
        if not args.dry_run:
            _flush(progress_dir, states)
        try:
            run_logger.close()
        except Exception:
            pass
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Redirect merges can map two lemmas onto one base key (best+better
    # -> good): emit the first, record later ones as duplicate-redirect
    # drops so FSRS never fragments and no silent overwrites happen.
    seen_keys: set = set()
    dup_redirect: list = []
    with open(out_path, "w", encoding="utf-8") as handle:
        for item in items:
            key = item_key(item)
            if key in seen_keys:
                dup_redirect.append("%s(redirected_from=%s)" % (
                    key, item.get("redirected_from", "?")))
                continue
            seen_keys.add(key)
            handle.write(json.dumps(
                precards[key], ensure_ascii=False) + "\n")
    if dup_redirect:
        print("duplicate-redirect drops (merged into base, FSRS-safe): %s"
              % ", ".join(sorted(set(dup_redirect))))
    _tele_write(str(out_path.parent / "telemetry_summary.json"), tele_store)
    n_failed = sum(len(states[s].get("failed", [])) for s in STAGES)
    print("precard done: %d items -> %s (s0 dropped=%d, s0b dropped=%d, "
          "s1 dropped=%d, failed flags=%d)"
          % (len(items), out_path, len(states["s0"].get("failed", [])),
             len(s0b_dropped), len(s1_dropped), n_failed))
    run_logger.log("precard done: %d items s0_dropped=%d s0b_dropped=%d "
                   "s1_dropped=%d failed=%d" % (
                       len(items), len(states["s0"].get("failed", [])),
                       len(s0b_dropped), len(s1_dropped), n_failed))
    run_logger.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
