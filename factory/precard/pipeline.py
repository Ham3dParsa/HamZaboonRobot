"""Precard pipeline: sample.json -> precard.jsonl (v1.4.1).

Self-contained runner: stage order preprocess/inflection_review/
anchor_rank/sense_judge/topic_vectors/topic_label/enrich, fan-out
assembly, atomic emission. Moved verbatim from
factory/pipeline/precard_pipeline (provenance: precard line R1-R6,
2026-09-14); stage vocabulary is real words throughout (progress.py),
state keys are new ids, stage_calls payload keys stay s-shaped for
downstream readers.

Usage:
    python -m factory.precard --sample <sample.json> --out <precard.jsonl>
    python -m factory.precard --dry-run --limit 8
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

FACTORY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(FACTORY_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from factory.core.env_loader import load_factory_env
from factory.core.telemetry import new_run_id
from factory.precard import progress
from factory.precard import transport
from factory.precard.accounting import audit_sample_accounting
from factory.precard.accounting import item_key
from factory.precard.net import (
    AVALAI_PRECARD_MODEL, GOOGLE_PRECARD_MODEL, LEG_FALLBACKS,
    PROVIDER_KEY_VARS)
from factory.precard.anchor import (
    PROPER_NOUN_POS, VULGAR_TAGS, anchor_rank_item, build_pos_sets,
    default_zipf, judge_proper_route, kaikki_pos_set,
    preprocess_classify_item, _backfill_candidate_tags, _is_name_gloss,
    _mother_for_top, _needs_tag_backfill, _reroute_name_gloss_anchor,
    _reroute_proper_anchor, _target_sense_tags, _preprocess_entry_view)
from factory.precard.enrich import (
    LEXICAL_TYPE_DEFAULT, REGISTER_DEFAULT, enrich_item)
from factory.precard.judge import (
    JUDGE_BATCH, fanout_picks, inflection_needs_review,
    inflection_review, judge_batch, judge_fallback,
    parse_superlative_base)
from factory.precard.anchor import IPA_SRC_MODEL
from factory.precard.topics import (
    LABEL_BATCH, TOPIC_METHOD, _needs_fanout_relabel, label_batch,
    vectors_batch)
from factory.core.telemetry import write_summary as _tele_write
from factory.precard.transport import (
    AuthError, KeyRing, RateLimited, append_telemetry_history,
    extract_json, raise_for_auth,
    _note_backoff, _tele_tokens, RunLogger, write_progress,
    _avalai_chat_transport, _google_chat_transport,
    _avalai_remap_transport, _google_remap_transport,
    _read_egress_env_key)


LLM_LEGS = ("inflection_review", "sense_judge", "topic_vectors",
            "topic_label")

# R9: --only/--stages refusal map — a selected judging/labeling/
# enrich stage runs on its required upstream's done state. Deterministic
# stages (preprocess/inflection_review/anchor_rank) read the index and
# datasets, never upstream progress, so they carry no requirement
# (--only anchor_rank on a fresh dir keeps working). A tuple value
# means ALL listed upstreams are required (topic_label reads both
# sense progress and topic_vectors via vec_lookup).
_REQUIRES_UPSTREAM = {
    "sense_judge": "anchor_rank",
    "topic_vectors": "sense_judge",
    "topic_label": ("sense_judge", "topic_vectors"),
    "enrich": "sense_judge",
}

_USE_DEFAULT = object()


BATCH = 8


SLEEP = 2.5


DEFAULT_SAMPLE = "W:/hamzaban_data_factory/pilot/sample.json"


DEFAULT_OUT = "W:/hamzaban_data_factory/pilot/precard.jsonl"


DEFAULT_PROGRESS_DIR = "W:/hamzaban_data_factory/pilot/progress_precard"


DEFAULT_AWL_FAMILIES = "W:/hamzaban_data_factory/raw/awl_families.json"


DEFAULT_KAIKKI_INDEX = "W:/hamzaban_data_factory/raw/kaikki-en-index.jsonl"


DEFAULT_KAIKKI_RAW = "W:/hamzaban_data_factory/raw/kaikki-en-words.jsonl"


DEFAULT_TATOEBA_POOL = ("W:/hamzaban_data_factory/fixtures/"
                        "tatoeba_pool_v13a.json")


DEFAULT_PHRASE_TYPE_LOG = ("W:/hamzaban_data_factory/fixtures/"
                           "phrase_type_log.jsonl")


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
        only = progress.normalize_stage(only)
        if only not in progress.STAGES:
            raise SystemExit("--only must be one of %s (got %r)"
                             % (", ".join(progress.STAGES), args.only))
        return {only}
    if stages:
        picks = [progress.normalize_stage(s)
                 for s in stages.split(",") if s.strip()]
        bad = [s for s in picks if s not in progress.STAGES]
        if not picks or bad:
            raise SystemExit("--stages must be a comma list from %s (got %r)"
                             % (", ".join(progress.STAGES), args.stages))
        return set(picks)
    return set(progress.STAGES)


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


def _refuse_empty_upstream(selected, states, flag):
    """R9: --only/--stages with empty upstream refuses (names the stage).

    A selected stage in _REQUIRES_UPSTREAM runs on its upstream's done
    state — with neither progress-file entries nor the upstream selected
    in this same run it would silently emit fallbacks, so refuse instead.
    Full runs and deterministic-only selections never trip this. Returns
    the refusal message, or None when the selection is runnable.
    """
    for stage in progress.STAGES:
        if stage not in selected or stage not in _REQUIRES_UPSTREAM:
            continue
        required = _REQUIRES_UPSTREAM[stage]
        if isinstance(required, str):
            required = (required,)
        for upstream in required:
            if upstream in selected:
                continue
            if len(states.get(upstream, {}).get("done", {}) or {}) == 0:
                return ("%s %s with empty upstream %s (no %s progress, and "
                        "%s is not selected) — run the full pipeline first "
                        "(drop %s), or re-run without --no-resume"
                        % (flag, progress.display(stage),
                           progress.display(upstream),
                           progress.display(upstream),
                           progress.display(upstream), flag))
    return None


def _stage_range(selected, stage, items, width=BATCH):
    """R26: batch base offsets ([] when the stage is not selected)."""
    if stage not in selected:
        return []
    return list(range(0, len(items), width))


def _dry_run_needs(progress_dir, items, selected, rekeyed, resume):
    """R26 dry-run: per-stage todo counts from existing progress.

    Counts are upper bounds (s0/s1 drops are only known after the real
    run). Nothing is read except progress JSON; nothing is written.
    """
    keys = [item_key(i) for i in items]
    rekeyed_set = set(rekeyed or [])
    needs = {}
    for stage in progress.STAGES:
        done = set()
        if resume:
            path = progress.find_stage_file(progress_dir, stage)
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


def _color(text, name, stream=None):
    """ANSI color for consoles; plain text when piped/NO_COLOR/Windows-legacy.

    Console-only helper (stored reasons/logs stay uncolored for files).
    ``stream`` is the target stream for the tty check (stdout progress
    vs stderr aborts); NO_COLOR is honored on both (R11).
    """
    import os as _os
    codes = {"green": "32", "red": "31", "yellow": "33", "cyan": "36",
             "bold": "1"}
    target = stream if stream is not None else sys.stdout
    try:
        use = target.isatty() and not _os.environ.get("NO_COLOR") \
            and name in codes
    except Exception:
        use = False
    if not use:
        return text
    return "\x1b[%sm%s\x1b[0m" % (codes[name], text)


def _bar_eta(durations, remaining):
    """Rolling-mean ETA for the bar v2 (R11).

    ``durations`` are completed per-batch seconds; ``remaining`` is the
    batch count left. ``"?"`` until 3 batches are observed (no mean
    worth showing before that).
    """
    if len(durations) < 3:
        return "?"
    window = durations[-5:]
    mean = sum(window) / len(window)
    secs = max(0.0, mean * max(0, remaining))
    if secs < 90:
        return "%ds" % int(round(secs))
    mins, secs = divmod(int(round(secs)), 60)
    if mins < 90:
        return "%dm%02ds" % (mins, secs)
    hrs, mins = divmod(mins, 60)
    return "%dh%02dm" % (hrs, mins)


_BAR_WIDTH = 100


def _batch_progress(stage, batch_no, n_batches, ok, fail, *, eta="?",
                    hits=0, misses=0, quiet=False):
    """Live one-line progress v2 (carriage return, English-only console).

    Bar v2 (R11): done/todo, ok/fail, ETA (rolling mean, ``?`` until 3
    batches), HIT/MISS (HIT = resolved with no LLM call: resume-skip,
    leg-1, file cache; MISS = LLM consulted). Replaces per-batch line
    spam: the line rewrites in place, padded so stale characters never
    linger. run.log keeps full history; a stage summary box follows at
    each stage end. Persian drop details go to dropped.log, never the
    console (Windows terminal mojibake). Silent under --quiet.
    """
    if quiet:
        return
    width = 20
    total = n_batches or 1
    done = min(batch_no, total)
    filled = int(width * done / total)
    line = ("[%s] [%s%s] %d/%d | ok=%d fail=%d | ETA %s | HIT=%d MISS=%d"
            % (progress.display(stage), "=" * filled,
               " " * (width - filled), done, total, ok, fail, eta,
               hits, misses))
    print("\r%s" % _color(line.ljust(_BAR_WIDTH), "cyan"),
          end="", flush=True)


class _JsonLog:
    """--json-log machine event stream (R11): run_events.jsonl.

    Human progress stays on stdout; this file carries one JSON object
    per run/stage/batch/warning event, every event run_id-joined.
    Best-effort: an unwritable path disables silently (files are
    secondary to the run itself). Always closed by the caller.
    """

    def __init__(self, out_path, run_id, enabled):
        from datetime import datetime, timezone
        self._now = lambda: datetime.now(timezone.utc).isoformat()
        self._run_id = str(run_id or "")
        self._handle = None
        if enabled:
            try:
                dest = pathlib.Path(str(out_path)).parent \
                    / "run_events.jsonl"
                dest.parent.mkdir(parents=True, exist_ok=True)
                self._handle = open(dest, "w", encoding="utf-8")
            except OSError:
                self._handle = None

    def event(self, kind, **fields):
        if self._handle is None:
            return
        try:
            rec = {"ts": self._now(), "run_id": self._run_id,
                   "event": kind}
            rec.update(fields)
            self._handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._handle.flush()
        except (OSError, ValueError, TypeError):
            pass

    def close(self):
        try:
            if self._handle is not None:
                self._handle.close()
        except OSError:
            pass
        finally:
            self._handle = None


def _reason_slug(reason):
    """English slug of a drop reason (text before the first colon)."""
    return str(reason or "").split(":")[0].strip() or "unknown"


# Issue #730: the entry band is the lemma's pool_level at sampling time
# (the sample item's pool_level, uppercased). Kept rows already carry it
# (precard.jsonl pool_level); dropped lemmas carry no senses, so the band
# is persisted per dropped key as a dropped.log suffix instead — a new
# sample file beside the proof would duplicate the input and force the
# viewer to join two files, while the suffix keeps key+reason+band on one
# greppable line. Backward compatible: old lines without the suffix keep
# parsing exactly as before (key = text before the second colon); the
# reader below returns None for them.
ENTRY_BAND_UNKNOWN = "?"


def _sanitize_entry_band(raw):
    """Round-trip-safe band: no []/CR/LF (line forgery), uppercased."""
    cleaned = re.sub(r"[\[\]\r\n]+", "", str(raw or "")).strip().upper()
    return cleaned or ENTRY_BAND_UNKNOWN


def entry_band(item):
    """Entry band of one sample item: pool_level at sampling time."""
    try:
        raw = (item or {}).get("pool_level", "")
    except AttributeError:
        raw = ""
    return _sanitize_entry_band(raw)


def build_entry_bands(items):
    """Snapshot {item_key: entry band} at sampling time (call before any
    stage filters the item list, so dropped keys keep their band)."""
    bands = {}
    for item in items or []:
        try:
            bands[item_key(item)] = entry_band(item)
        except Exception:
            continue
    return bands


def format_drop_line(key, reason, entry_bands=None):
    """One dropped.log detail line: legacy "key: reason" plus the
    " [entry=BAND]" suffix when the key's entry band is known. A None
    (or key-missing) map emits the legacy line unchanged. The band is
    sanitized (no []/CR/LF) so a hostile pool_level cannot break the
    round-trip or forge lines."""
    line = "%s: %s" % (key, reason)
    band = None
    if isinstance(entry_bands, dict):
        band = entry_bands.get(key)
    if band:
        line += " [entry=%s]" % _sanitize_entry_band(band)
    return line


def parse_drop_entry_band(reason_or_line):
    """Entry band from an enriched drop line/reason; None when the line
    predates the suffix (old proofs still read — forward/backward
    compatible)."""
    match = re.search(r"\[entry=([^\]]+)\]\s*$",
                      str(reason_or_line or ""))
    if not match:
        return None
    return match.group(1).strip() or None


def survival_per_band(entry_bands, kept_keys):
    """Per-band survival from sampling-time entry bands: {band: {"entered",
    "kept", "dropped", "survival"}} (survival None when entered == 0).

    Dropped is entered - kept (fail-closed accounting semantics: a key
    with >=1 precard row counts as kept even if it also appears in
    dropped.log as an s1-fallback detail). Pure function, stdlib only.

    v141 backfill verdict (#730): RECOMPUTABLE — sample200.frozen.json
    carries pool_level for all 284 input keys and joins prog/
    preprocess.json done keys exactly (284<->284); the kept set comes
    from precard.jsonl (185 distinct keys). v141 artifacts themselves
    are frozen (never rewritten); recompute via this helper.
    """
    kept = set(kept_keys or [])
    per_band = {}
    try:
        pairs = list((entry_bands or {}).items())
    except AttributeError:
        pairs = []
    for key, band in pairs:
        slot = per_band.setdefault(str(band or ENTRY_BAND_UNKNOWN),
                                   {"entered": 0, "kept": 0})
        slot["entered"] += 1
        if key in kept:
            slot["kept"] += 1
    out = {}
    for band in sorted(per_band):
        entered = per_band[band]["entered"]
        kept_n = per_band[band]["kept"]
        out[band] = {"entered": entered, "kept": kept_n,
                     "dropped": entered - kept_n,
                     "survival": (kept_n / entered if entered else None)}
    return out


def _stage_summary(stage, states, out_path, quiet=False, counts=None,
                   entry_bands=None):
    """English stage box on stdout + full multilingual details to file.

    R11 split: the box is human/stdout (silent under --quiet); the
    multilingual drop details always land in dropped.log. ``counts``
    (optional {"hits","misses","cache"}) appends the bar v2 HIT/MISS
    segment to the box plus a CACHE line for file-cache hits.
    ``entry_bands`` (optional {key: band} from build_entry_bands) appends
    the " [entry=BAND]" suffix to drop lines (#730); None keeps the
    legacy "key: reason" lines (old proofs stay readable).
    """
    from collections import Counter
    done = states.get(stage, {}).get("done", {}) or {}
    failed = states.get(stage, {}).get("failed", []) or []
    # Kept rule for the summary box: an entry counts as kept unless
    # explicitly not-kept or dropped (a verdict carrying both kept=True
    # and dropped=<reason> is dropped — fail-closed). run_logger callers
    # may use simpler counters (len(done)); the box is the strict one.
    kept = sum(1 for v in done.values()
               if isinstance(v, dict) and v.get("kept", True) is not False
               and not v.get("dropped"))
    # Human voice: input = distinct keys attempted (done + failed-not-in-
    # done). Fallback verdicts (s2 judge) are kept AND listed in failed,
    # so kept + dropped may exceed input there — the s1-fallback slug
    # names the overlap.
    input_n = len(done) + len([k for k in failed if k not in done])
    slugs = Counter()
    details = []
    quarantined = []
    for key, verdict in done.items():
        if not isinstance(verdict, dict):
            continue
        reason = verdict.get("reason") or verdict.get("dropped") or ""
        if verdict.get("quarantine"):
            # Kept-key note (review list, not a drop): no entry suffix —
            # the lemma survives with its precard rows carrying pool_level.
            quarantined.append("%s: quarantine-%s" % (
                key, verdict.get("quarantine")))
        if verdict.get("kept", True) and not verdict.get("dropped"):
            # judge fallbacks stay live but are notable: the judge
            # failed and the anchor survived instead.
            # Kept-key note (same as quarantine above): no entry suffix.
            if str(verdict.get("model", "")).startswith("s1-"):
                slugs["s1-fallback"] += 1
                details.append("%s: s1-fallback" % key)
            continue
        slugs[_reason_slug(reason)] += 1
        details.append(format_drop_line(key, reason, entry_bands))
    for key in failed:
        if key not in done:
            slugs["failed-no-entry"] += 1
            details.append(
                format_drop_line(key, "failed-no-entry", entry_bands))
    hits = misses = cache = 0
    if isinstance(counts, dict):
        try:
            hits = int(counts.get("hits", 0) or 0)
            misses = int(counts.get("misses", 0) or 0)
            cache = int(counts.get("cache", 0) or 0)
        except (TypeError, ValueError):
            hits = misses = cache = 0
    hit_seg = (" | HIT=%d MISS=%d" % (hits, misses)
               if counts is not None else "")
    if not quiet:
        print("")
        # Human pipeline log: domain voice + Finglish, no s0-style ids.
        print(_color("%s: input %d \u2192 kept %d, dropped %d" % (
            progress.display(stage), input_n, kept, len(failed)),
            "green" if not failed else "yellow"))
        print(_color("[STAGE %s] kept=%d dropped=%d%s%s%s" % (
            progress.display(stage), kept, len(failed),
            " | " + ", ".join("%s=%d" % kv for kv in slugs.most_common(4))
            if slugs else "",
            " | quarantined=%d" % len(quarantined) if quarantined else "",
            hit_seg),
            "green" if not failed else "yellow"))
        if cache:
            print(_color("CACHE file hits=%d" % cache, "cyan"))
    if details or quarantined:
        drop_log = pathlib.Path(str(out_path)).parent / "dropped.log"
        try:
            with open(drop_log, "a", encoding="utf-8") as handle:
                handle.write("=== %s drops ===\n" % progress.display(stage))
                for line in details:
                    handle.write(line + "\n")
                if quarantined:
                    handle.write("=== %s quarantine (kept, review) ===\n"
                                 % progress.display(stage))
                    for line in quarantined:
                        handle.write(line + "\n")
        except OSError as exc:
            # R11: warnings/errors go to stderr, never stdout.
            print("warning: dropped.log append failed (%s)" % exc,
                  file=sys.stderr)


def _flush(progress_dir, states):
    for stage in progress.STAGES:
        write_progress(str(progress.stage_file(progress_dir, stage)),
                       states[stage])


def _flush_telemetry(tele_dir, tele_store, flushed, run_id=""):
    """Append unflushed telemetry records + rewrite the summary.

    Kill-safe incremental persistence: a killed run keeps every record up
    to the last completed stage (and every STOP path flushes before
    exiting). Returns the new flushed count. Summary covers the current
    run and carries its run_id; the end-of-run history append stays
    cumulative.
    """
    pending = tele_store[flushed:]
    if pending:
        tele_dir = pathlib.Path(tele_dir)
        tele_dir.mkdir(parents=True, exist_ok=True)
        hist = tele_dir / "telemetry_records.jsonl"
        with open(hist, "a", encoding="utf-8") as handle:
            for rec in pending:
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _tele_write(str(tele_dir / "telemetry_summary.json"),
                    list(tele_store), run_id=run_id)
    return len(tele_store)


def _parse_stage_map(values, allowed_values=None):
    """Parse ["sense_judge=avalai"] into {sense_judge: avalai}. Bad entries raise SystemExit
    (fail-fast: a typo must not silently burn paid calls on the wrong leg).
    Legs accept new ids (legacy s-ids still work).
    """
    out = {}
    for raw in values or []:
        if "=" not in raw:
            raise SystemExit("bad --stage-* value %r (want STAGE=value)"
                             % raw)
        stage, _, value = raw.partition("=")
        raw_stage = stage.strip().lower()
        stage, value = progress.normalize_stage(raw_stage), value.strip()
        if stage not in LLM_LEGS:
            raise SystemExit("bad --stage-* leg %r (legs: %s)" % (
                raw_stage, ", ".join(
                    "%s/%s" % (s, progress.display(s)) for s in LLM_LEGS)))
        if allowed_values is not None and value not in allowed_values:
            raise SystemExit("bad --stage-* value %r (want one of: %s)" % (
                value, ", ".join(allowed_values)))
        if not value:
            raise SystemExit("bad --stage-* value %r (empty)" % raw)
        out[stage] = value
    return out


def main(argv=None, _judge_transport=_USE_DEFAULT,
         _topic_transport=_USE_DEFAULT, _assign_transport=_USE_DEFAULT,
         _inflect_transport=_USE_DEFAULT,
         _sleep_fn=None, _index=None, _read_entry=None, _tatoeba=None,
         _zipf_fn=None, _awl_set=None, _type_map=None,
         _type_log_available=None):
    """Run the pre-card pipeline. Returns 0 on success (exit code)."""
    args = parse_args(argv)
    if args.resume and args.no_resume:
        raise SystemExit("--resume and --no-resume are mutually exclusive "
                         "(--resume prints the RESUME PLAN then runs, "
                         "--no-resume starts fresh)")
    # R10: one run_id (start-ts + pid) joins provider_map.json, the
    # run.log header, every telemetry record, and every --json-log
    # event of this run.
    run_id = new_run_id()
    # R11 split: stdout is human progress (silent under --quiet);
    # warnings/errors go to stderr; files are machine-readable.
    quiet = bool(args.quiet)

    def _say(*parts, **kwargs):
        if not quiet:
            print(*parts, **kwargs)

    sleep_fn = _sleep_fn or time.sleep
    # Owner-ordered pacing (2026-09-14): --sleep-secs scales ONLY the
    # inter-batch pacing pauses; the 429-rotation backoff (ROTATE_PAUSE)
    # always stays on, so rate errors still back off instead of
    # spinning. Default keeps the historic 2.5s pacing.
    pace_secs = max(0.0, args.sleep_secs)
    pace_fn = (lambda s: None) if pace_secs == 0 else (
        lambda s: sleep_fn(pace_secs))
    items = load_sample(args.sample)
    if args.limit:
        items = items[:args.limit]
    # #730: entry-band snapshot at sampling time (before any stage
    # filters the list, so dropped keys keep their pool_level band).
    entry_bands = build_entry_bands(items)

    if args.dry_run:
        selected = _selected_stages(args)
        rekeyed = _load_rekey_keys(args.rekey)
        needs = _dry_run_needs(args.progress_dir, items, selected,
                               rekeyed, resume=not args.no_resume)
        print("dry-run plan (nothing written, no network):")
        print("  sample:   %s (%d items)" % (args.sample, len(items)))
        print("  out:      %s (not written)" % args.out)
        print("  progress: %s (not written)" % args.progress_dir)
        print("  batches:  %d x %d (preprocess..enrich incl. inflection, "
              "resume %s)" % (
            (len(items) + BATCH - 1) // BATCH if items else 0, BATCH,
            "off" if args.no_resume else "on"))
        print("  stages:   preprocess[name/zipf/phrase gates] / "
              "inflection_review / anchor_rank / sense_judge / "
              "topic_vectors / topic_label / enrich")
        print("  selected: %s" % ", ".join(
            progress.display(s) for s in progress.STAGES if s in selected))
        if rekeyed:
            print("  rekey:    %d key(s) forced to redo" % len(rekeyed))
        for stage in progress.STAGES:
            if stage in selected:
                print("  need %s: %d todo (%d done kept, upper bound "
                      "pre-drop)" % (progress.display(stage),
                                     needs[stage]["todo"],
                                     needs[stage]["done"]))
            else:
                print("  stage %s: skipped (not selected)"
                      % progress.display(stage))
        return 0

    # Machine event stream starts with the real run (dry-run above
    # returns before any file is written).
    jlog = _JsonLog(args.out, run_id, bool(args.json_log))
    # Created later (after progress load); _preflight_exit closes it
    # when set so a stillborn run never leaves run.log locked (Windows
    # tmp cleanup) — pre-existing key-error exits leaked it too.
    run_logger = None

    def _warn(message):
        print(message, file=sys.stderr)
        jlog.event("warning", message=message)

    def _report_egress_cooldown(exc):
        # Best-effort: tell the egress supervisor this server is dead
        # for the provider (location-block / project-quota class), so
        # the next leased run walks to the next server instead of
        # retrying the same egress. Only ProviderCooldown (never
        # key-level rate limits, never auth). Never fails the run;
        # never logs secrets (lease id only, same as the lease line).
        try:
            from factory.precard.transport import ProviderCooldown
        except Exception:
            return
        if not isinstance(exc, ProviderCooldown):
            return
        lease_id = os.environ.get("EGRESS_LEASE_ID", "")
        if not lease_id:
            return
        tok = os.environ.get("EGRESS_SUP_TOKEN", "")
        if not tok:
            # No supervisor token: the supervisor would 401 the report
            # anyway (and "Bearer " with an empty token is a malformed
            # header) — skip the doomed loopback call silently.
            return
        try:
            import json as _json
            import urllib.request as _url
            sup = os.environ.get("EGRESS_SUP_URL",
                                 "http://127.0.0.1:18789")
            req = _url.Request(
                sup + "/v1/report",
                data=_json.dumps({"lease_id": lease_id,
                                  "outcome": "http429"}).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + tok})
            with _url.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception:
            pass

    def _abort(stage, exc):
        # Red aborts (R11): auth stops print red on stderr, then raise.
        print(_color("auth abort (%s): %s"
                     % (progress.display(stage), exc),
                     "red", stream=sys.stderr), file=sys.stderr)
        # Like the quota-STOP paths: flush stage telemetry first so the
        # abort doesn't lose in-memory records (no later flush runs —
        # the bare raise below skips the post-try summary).
        _flush_telemetry(tele_dir, tele_store, tele_flushed,
                         run_id=run_id)
        jlog.event("abort", stage=stage, error=str(exc))
        # The bare raise below skips everything after the try/finally
        # (telemetry-history append, summary, run_done): the json-log
        # stream ends here, closed, with the abort as its last event.
        jlog.close()

    def _preflight_exit(message):
        # Stillborn run (corrupt progress, kaikki index, missing keys):
        # record the abort as the stream's last event, close it, then
        # exit — never a dangling run_events.jsonl. A None message
        # (plain `raise SystemExit`) must never become exit 0.
        if message is None:
            message = "preflight abort"
        jlog.event("abort", stage="preflight", error=message)
        jlog.close()
        try:
            if run_logger is not None:
                run_logger.close()
        except Exception:
            pass
        raise SystemExit(message)

    progress_dir = pathlib.Path(args.progress_dir)
    progress_dir.mkdir(parents=True, exist_ok=True)
    resume = not args.no_resume
    states = {}
    for stage in progress.STAGES:
        path = progress.find_stage_file(progress_dir, stage)
        loaded = {}
        if resume and path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                _preflight_exit("corrupt progress %s: %s (re-run with "
                                "--no-resume to start fresh; the file is "
                                "kept, never auto-discarded)" % (path, exc))
        states[stage] = {"done": loaded.get("done", {}),
                         "failed": loaded.get("failed", []),
                         "backoffs": loaded.get("backoffs", [])}
    total = len(items)
    banner = []
    for stage in progress.STAGES:
        done_n = len(states[stage]["done"])
        banner.append("%s done=%d remaining=%d" % (
            progress.display(stage), done_n, max(0, total - done_n)))
    _say("resume: %s" % " | ".join(banner))
    # R26: stage selection + rekey eviction (resume still skips the rest).
    # Stage dependency: anchor -> judge -> vectors -> label -> enrich,
    # so rekeying an upstream stage auto-invalidates the same keys downstream — otherwise assembly mixes
    # new anchors with stale enrichment (kiss#5-style staleness).
    _DOWNSTREAM = {"anchor_rank": ("sense_judge", "topic_vectors", "topic_label", "enrich"), "sense_judge": ("topic_vectors", "topic_label", "enrich"),
                   "topic_vectors": ("topic_label", "enrich"), "topic_label": ("enrich",)}
    try:
        selected = _selected_stages(args)
    except SystemExit as exc:
        _preflight_exit(exc.code)
    try:
        rekeyed = _load_rekey_keys(args.rekey)
    except SystemExit as exc:
        _preflight_exit(exc.code)
    sample_order = [item_key(i) for i in items]
    if rekeyed:
        sample_keys = set(sample_order)
        unknown = [k for k in rekeyed if k not in sample_keys]
        if unknown:
            shown = ", ".join(unknown[:10])
            if len(unknown) > 10:
                shown += " (+%d more)" % (len(unknown) - 10)
            _preflight_exit("rekey key(s) not in sample %s: %s "
                            "(--rekey keys must match sample item keys)"
                            % (args.sample, shown))
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
        _say("rekey: %d key(s) forced to redo in %s" % (
            len(rekeyed),
            ", ".join(progress.display(s) for s in progress.STAGES if s in selected)))
    if (args.only or "").strip() or (args.stages or "").strip():
        _sel_flag = "--only" if (args.only or "").strip() else "--stages"
        _refusal = _refuse_empty_upstream(selected, states, _sel_flag)
        if _refusal is not None:
            _preflight_exit(_refusal)
    if args.resume:
        _say("RESUME PLAN (progress %s, sample %s, %d items):" % (
            progress_dir, args.sample, len(items)))
        for stage in progress.STAGES:
            if stage not in selected:
                _say("  %s: skipped (not selected)"
                     % progress.display(stage))
                continue
            _done_here = (set(states[stage]["done"] or {})
                          & set(sample_order))
            _say("  %s: done=%d todo=%d" % (
                progress.display(stage), len(_done_here),
                len(sample_order) - len(_done_here)))

    # V7: compact run.log in the out dir (stage start/end + counts +
    # timings). Console shows a live one-line progress per batch
    # (_batch_progress) plus an English [STAGE] box; multilingual drop
    # details go to dropped.log. ok/fail per stage: s0 kept vs
    # dropped; s1 ranked vs anchor-proper-noun/error; s2 judge model vs
    # s1-fallback; s3 model vector vs deterministic fallback; s4/s5 have
    # no fail-closed signal, so fail is always 0 there.
    run_logger = RunLogger(
        str(pathlib.Path(args.out).parent / "run.log"),
        namer=progress.display, run_id=run_id)
    jlog.event("run_start", run_id=run_id)
    for stage in progress.STAGES:
        if stage not in selected:
            run_logger.log("stage %s skipped (not selected)"
                           % progress.display(stage))
    tele_store = []  # R27: per-batch records (key_idx only, never values)
    tele_dir = pathlib.Path(args.out).parent
    tele_flushed = 0

    if _index is not None:
        index = _index
    else:
        try:
            index = load_kaikki_index(args.kaikki_index)
        except OSError as exc:
            _preflight_exit("cannot load kaikki index %s: %s" % (
                args.kaikki_index, exc))
    if _read_entry is not None:
        read_entry = _read_entry
    else:
        def read_entry(row, _raw=args.kaikki_raw):
            return read_kaikki_entry(_raw, row["offset"],
                                                row["length"])
    tatoeba_pool = _tatoeba if _tatoeba is not None else \
        load_tatoeba_pool(args.tatoeba_pool)

    # preprocess (strict preprocess, deterministic, batch-flushed). Aux files fail
    # open to keep: a missing AWL/type-log only ever adds keeps.
    zipf_fn = _zipf_fn or default_zipf
    awl_set = (_awl_set if _awl_set is not None
               else load_awl_members(args.awl_families))
    if _type_map is not None:
        type_map = _type_map
    else:
        try:
            type_map = load_phrase_types(args.phrase_type_log)
        except Exception:
            type_map = {}
    type_log_available = (bool(type_map) if _type_log_available is None
                          else bool(_type_log_available))
    # RAM: lazy per-lemma pos_sets (500-sample touches ~500 lemmas, not
    # the full index — avoids building a 10k+ entry dict + per-sense sets;
    # measured ~5% process-memory drop via psutil before/after on 500).
    class _LazyPosSets(dict):
        def __missing__(self, key):
            rows = index.get(key, []) if isinstance(index, dict) else []
            val = kaikki_pos_set(rows)
            self[key] = val
            return val

        def get(self, key, default=None):
            try:
                return self[key]
            except KeyError:
                return default
    pos_sets = _LazyPosSets()
    preprocess_info: dict = {}
    # Memoized entry views: one Kaikki read pass per lemma per run (preprocess
    # was previously in-memory; without this each item pays open+seek).
    # Lazy per-lemma — avoids per-sense duplication.
    preprocess_view_cache: dict = {}

    def _cached_view(text):
        key = (text or "").strip().casefold()
        if key not in preprocess_view_cache:
            preprocess_view_cache[key] = _preprocess_entry_view(
                {"kind": "word", "text": text}, index, read_entry)
        return preprocess_view_cache[key]
    run_logger.stage_start("preprocess")
    jlog.event("stage_start", stage="preprocess")
    for batch_no, base in enumerate(
            _stage_range(selected, "preprocess", items), start=1):
        batch = items[base:base + BATCH]
        for item in batch:
            key = item_key(item)
            if key not in states["preprocess"]["done"]:
                verdict = preprocess_classify_item(
                    item, pos_sets, zipf_fn, awl_set, type_map,
                    type_log_available, entry_fn=_cached_view)
                states["preprocess"]["done"][key] = verdict
                if not verdict["kept"] \
                        and key not in states["preprocess"]["failed"]:
                    states["preprocess"]["failed"].append(key)
        _flush(progress_dir, states)
        # Deterministic stage: <1s per batch, no progress bar by design
        # (LLM stages use _batch_progress for live per-batch feedback).
    _pre_ok = sum(1 for v in states["preprocess"]["done"].values()
                  if v.get("kept"))
    _pre_fail = len(states["preprocess"].get("failed", []))
    run_logger.stage_end("preprocess", ok=_pre_ok, fail=_pre_fail)
    jlog.event("stage_end", stage="preprocess", ok=_pre_ok, fail=_pre_fail)
    tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed,
                                     run_id=run_id)
    _stage_summary("preprocess", states, args.out, quiet=quiet,
                   entry_bands=entry_bands)
    for key, verdict in states["preprocess"]["done"].items():
        preprocess_info[key] = verdict
    dropped = {k for k, v in preprocess_info.items() if not v.get("kept")}
    items = [i for i in items if item_key(i) not in dropped]
    if dropped:
        # Details live in dropped.log (written by _stage_summary);
        # console stays a single short line (no 80-item spam).
        _say(_color("%s: kept=%d dropped=%d "
                    "(see dropped.log)" % (progress.display("preprocess"),
                                           len(items), len(dropped)),
                    "cyan"))

    # Provider intent before any key loading (paid-only legs each need
    # their own key; a caller-owned/skipped leg needs none). None =
    # caller-owned/skipped leg (transport injected or None: no key,
    # no provider needed), _USE_DEFAULT = resolved from the flags
    # below (fail-closed when uncovered). Per-leg overrides
    # (--stage-provider/--stage-model) participate in every decision
    # below. Precedence per leg: --stage-* win, then --judge-*, then
    # master --llm-provider/--precard-model. There is no default
    # provider: every _USE_DEFAULT leg must resolve to avalai|google.
    try:
        stage_prov = _parse_stage_map(args.stage_provider,
                                      ("avalai", "google"))
        stage_model = _parse_stage_map(args.stage_model)
    except SystemExit as exc:
        _preflight_exit(exc.code)

    def _leg_provider(leg):
        if leg in stage_prov:
            return stage_prov[leg]
        if leg == "sense_judge" and args.judge_provider in ("avalai", "google"):
            return args.judge_provider
        return args.llm_provider

    def _provider_key_var(provider):
        """Primary key variable for a provider (auth errors name it).

        Single pairing lives in net.PROVIDER_KEY_VARS; "" falls back
        to the wrapper's generic "keys" hint.
        """
        vars_ = PROVIDER_KEY_VARS.get(provider or "", ("",))
        return vars_[0] if vars_ else ""

    def _leg_file_label(provider):
        """Env-file label for a leg's auth errors (never a value).

        AvalAI keys load from factory/.env; a Google key that came
        from the owner-layout egress fallback names tools/egress/.env
        so the operator re-checks the file actually searched.
        """
        if provider == "google" and google_key_from_egress:
            return "tools/egress/.env"
        return "factory/.env"

    def _leg_model(leg):
        if leg in stage_model:
            return stage_model[leg]
        if leg == "sense_judge" and args.judge_model:
            return args.judge_model
        if args.precard_model:
            return args.precard_model
        if providers.get(leg) == "google":
            return GOOGLE_PRECARD_MODEL
        return AVALAI_PRECARD_MODEL

    _injected = {"inflection_review": _inflect_transport, "sense_judge": _judge_transport,
                 "topic_vectors": _topic_transport, "topic_label": _assign_transport}
    providers = {leg: _leg_provider(leg) for leg in LLM_LEGS}
    models = {leg: _leg_model(leg) for leg in LLM_LEGS}
    # Fail-closed provider gate (no default provider): every leg the
    # caller left on the pipeline default must resolve to avalai|google
    # via --llm-provider (or --judge-provider for sense_judge, or
    # per-leg --stage-provider). Caller-owned legs (injected transport
    # or None) are exempt — they run no provider transport.
    for _leg in LLM_LEGS:
        if _injected[_leg] is _USE_DEFAULT \
                and providers[_leg] not in ("avalai", "google"):
            _extra = (" (or --judge-provider avalai|google)"
                      if _leg == "sense_judge" else "")
            _preflight_exit(
                "no provider for %s: pass --llm-provider avalai|google%s "
                "(or per-leg --stage-provider %s=avalai|google) — "
                "the run line has no default provider" % (
                    _leg, _extra, _leg))

    def _leg_avalai(leg):
        # None = caller-skipped leg (fallback path, transport never
        # called): needs no key. Only _USE_DEFAULT legs run on the
        # provider and need its key.
        return providers[leg] == "avalai" \
            and _injected[leg] is _USE_DEFAULT

    def _leg_google(leg):
        # Same skipped-leg rule as above (a None leg never calls its
        # transport, so it must not demand the provider key).
        return providers[leg] == "google" \
            and _injected[leg] is _USE_DEFAULT

    judge_avalai = _judge_transport is _USE_DEFAULT \
        and providers["sense_judge"] == "avalai"
    judge_google = _judge_transport is _USE_DEFAULT \
        and providers["sense_judge"] == "google"
    # Exact provider manifest: stage -> provider + actual model (remap
    # legs record the requested name on telemetry rows, so this file
    # stays the disambiguator for cost attribution). The run_id joins
    # every sink (R10); legs stay top-level (existing readers).
    # P2: every step also carries its full fallback chain (model +
    # cost per entry, from the net table) and "tried" (every model the
    # leg actually attempted this run — filled post-stage, [] before).
    provider_map = {"run_id": run_id}
    for leg in LLM_LEGS:
        provider_map[leg] = {
            "provider": providers[leg],
            "model": models[leg],
            "chain": [{"model": item_model, "cost": item_cost}
                      for item_model, item_cost in
                      LEG_FALLBACKS.get((providers[leg], leg), ())],
            "tried": []}
    api_key = "injected"
    avalai_needed = any(_leg_avalai(leg) for leg in LLM_LEGS)
    google_needed = any(_leg_google(leg) for leg in LLM_LEGS)
    # No shared default ring: every default leg carries its own
    # provider ring (leg_ring / judge_ring below); injected legs run
    # on caller-owned transports.
    ring = None
    if _judge_transport is _USE_DEFAULT:
        # Post-gate the default judge leg is always avalai|google, so
        # one of the branches below wires it; anything else is a bug.
        judge_transport = None
    else:
        judge_transport = _judge_transport
    judge_models = None
    # AvalAI wiring per leg. judge gets its own key/ring pair (F1 scoping);
    # inflection/vectors/label share the leg-keyed pairs below.
    leg_api_key, leg_ring = {}, {}
    judge_api_key, judge_ring = None, None
    google_key_from_egress = False
    # judge_avalai/judge_google computed above.
    if avalai_needed:
        try:
            env_av = load_factory_env(required=("AVALAI_API_KEY",))
            avalai_key = env_av["AVALAI_API_KEY"]
        except KeyError:
            _preflight_exit("no AVALAI_API_KEY in factory/.env "
                            "(avalai provider needs it)")
        if not avalai_key:
            _preflight_exit("no AVALAI_API_KEY in factory/.env "
                            "(avalai provider needs it)")
        try:
            avalai_ring = KeyRing([avalai_key])
        except ValueError as exc:
            _preflight_exit("no AvalAI keys: %s" % exc)
        for leg in LLM_LEGS:
            if not _leg_avalai(leg):
                continue
            leg_api_key[leg] = avalai_key
            leg_ring[leg] = avalai_ring
        if judge_avalai:
            judge_api_key = avalai_key
            judge_ring = avalai_ring
            judge_transport = _avalai_chat_transport
            judge_models = [models["sense_judge"]]
    if google_needed:
        try:
            env_go = load_factory_env(required=("GOOGLE_AI_API_KEY",))
            google_key = env_go["GOOGLE_AI_API_KEY"]
        except KeyError:
            google_key = ""
        if not google_key:
            # Owner layout fallback: spare LLM keys live beside the
            # egress SUBs (same disk, never committed, never logged).
            import pathlib as _pl
            here = _pl.Path(__file__).resolve().parent.parent.parent
            google_key = _read_egress_env_key(
                str(here / "tools" / "egress" / ".env"),
                "GOOGLE_AI_API_KEY")
            google_key_from_egress = bool(google_key)
        if not google_key:
            _preflight_exit("no GOOGLE_AI_API_KEY in factory/.env "
                            "(google provider needs it)")
        try:
            google_ring = KeyRing([google_key])
        except ValueError as exc:
            _preflight_exit("no Google keys: %s" % exc)
        for leg in LLM_LEGS:
            if not _leg_google(leg):
                continue
            leg_api_key[leg] = google_key
            leg_ring[leg] = google_ring
        if judge_google:
            judge_api_key = google_key
            judge_ring = google_ring
            judge_transport = _google_chat_transport
            judge_models = [models["sense_judge"]]
    if _judge_transport is _USE_DEFAULT and judge_transport is None:
        # Unreachable post-gate (default judge is always avalai|google
        # and wired above); fail closed instead of running unconfigured.
        _preflight_exit("no transport for sense_judge: pass "
                        "--llm-provider avalai|google (or --judge-provider "
                        "avalai|google, or --stage-provider "
                        "sense_judge=avalai|google)")
    # R6 switch rings: every loaded provider ring by provider name.
    # Every run provider is paid, so a cooled leg stops for a resume;
    # providers without a loaded ring are simply not attempted.
    provider_rings = {}
    for _leg in LLM_LEGS:
        _rg = leg_ring.get(_leg, ring)
        if _rg is not None:
            provider_rings.setdefault(providers[_leg], _rg)
    _judge_rg = judge_ring or ring
    if _judge_rg is not None:
        provider_rings.setdefault(providers["sense_judge"], _judge_rg)
    topic_transport = assign_transport = inflect_transport = None
    vectors_models_override = [models["topic_vectors"]] if _leg_avalai("topic_vectors") or \
        _leg_google("topic_vectors") else None
    # Per-leg remaps (uniform for full and mixed modes, per-leg models).
    # Post-gate every default leg is avalai|google, so the loop below
    # always claims it; caller-injected legs keep their transport.
    for leg in ("inflection_review", "topic_vectors", "topic_label"):
        if _leg_avalai(leg):
            _remap_leg = _avalai_remap_transport(models[leg])
        elif _leg_google(leg):
            _remap_leg = _google_remap_transport(models[leg])
        else:
            continue
        if leg == "inflection_review" and _inflect_transport is _USE_DEFAULT:
            inflect_transport = _remap_leg
        elif leg == "topic_vectors" and _topic_transport is _USE_DEFAULT:
            topic_transport = _remap_leg
        elif leg == "topic_label" and _assign_transport is _USE_DEFAULT:
            assign_transport = _remap_leg
    _any_avalai_leg = any(_leg_avalai(leg) for leg in LLM_LEGS)
    _any_google_leg = any(_leg_google(leg) for leg in LLM_LEGS)
    if (args.judge_model or args.precard_model or args.stage_model) \
            and _judge_transport is _USE_DEFAULT \
            and not _any_avalai_leg and not _any_google_leg:
        _warn("warning: model flags apply only to flag-resolved legs; "
              "ignored for caller-injected transports")
    # Defaults for legs the remap loop above did not claim: post-gate
    # that is only caller-injected legs (kept as-is); a default leg
    # left unwired is a bug — fail closed.
    if _topic_transport is _USE_DEFAULT and topic_transport is None:
        _preflight_exit("no transport for topic_vectors: pass "
                        "--llm-provider avalai|google (or --stage-provider "
                        "topic_vectors=avalai|google)")
    elif _topic_transport is not _USE_DEFAULT:
        topic_transport = _topic_transport
    if _assign_transport is _USE_DEFAULT and assign_transport is None:
        _preflight_exit("no transport for topic_label: pass "
                        "--llm-provider avalai|google (or --stage-provider "
                        "topic_label=avalai|google)")
    elif _assign_transport is not _USE_DEFAULT:
        assign_transport = _assign_transport
    if _inflect_transport is _USE_DEFAULT and inflect_transport is None:
        _preflight_exit("no transport for inflection_review: pass "
                        "--llm-provider avalai|google (or --stage-provider "
                        "inflection_review=avalai|google)")
    elif _inflect_transport is not _USE_DEFAULT:
        inflect_transport = _inflect_transport

    label_topup_cache = _resolve_label_topup_cache(progress_dir)
    label_calls: dict = {}
    # P2: every model each LLM leg actually attempts (provider_map
    # "tried", rewritten post-stage).
    s0b_tried: list = []
    s2_tried: list = []
    s3_tried: list = []
    s4_tried: list = []
    precards: dict = {}
    inflection_dropped: set = set()
    # Provider manifest: exact stage -> provider + actual model for cost
    # attribution (console + run.log + provider_map.json beside --out).
    def _leg_actual(leg):
        """Really-hit model for a leg (always the resolved leg model)."""
        return models[leg]

    def _leg_ring_idx(leg):
        """Real keyring index for a leg's key (0 when ringless)."""
        leg_ring_obj = leg_ring.get(leg, ring)
        try:
            return int(leg_ring_obj.idx)
        except (AttributeError, TypeError, ValueError):
            return 0

    def _write_provider_map():
        # P2: rewritten after every LLM stage so "tried" stays exact
        # (kill-safe like telemetry: a killed run keeps every step up
        # to the last completed stage).
        try:
            with open(pathlib.Path(args.out).parent / "provider_map.json",
                      "w", encoding="utf-8") as handle:
                handle.write(json.dumps(provider_map, ensure_ascii=False))
        except OSError as exc:
            _warn("warning: provider_map.json write failed (%s)" % exc)

    _prov_line = ", ".join(
        "%s=%s/%s" % (progress.display(leg), provider_map[leg]["provider"],
                      provider_map[leg]["model"]) for leg in LLM_LEGS)
    _say(_color("providers: %s" % _prov_line, "cyan"))
    run_logger.log("providers: %s" % _prov_line)
    _write_provider_map()
    jlog.event("providers", providers={
        leg: provider_map[leg] for leg in LLM_LEGS})
    try:
        # S0b R36: inflection micro-stage (own progress key inflection.json).
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
        # Verdict variant inside inflection — no new stage.
        run_logger.stage_start("inflection_review")
        jlog.event("stage_start", stage="inflection_review")
        n_inflection_batches = (len(items) + BATCH - 1) // BATCH or 1
        s0b_bar = {"durs": [], "hits": 0, "misses": 0}
        for batch_no, base in enumerate(
                _stage_range(selected, "inflection_review", items), start=1):
            _t0 = time.perf_counter()
            batch = items[base:base + BATCH]
            todo = [i for i in batch
                    if item_key(i) not in states["inflection_review"]["done"]]
            s0b_bar["hits"] += len(batch) - len(todo)
            review = []
            # R8 wiring: every-gloss pre-check needs the sense list.
            # Reuses the memoized s0 entry views (no second Kaikki pass);
            # candidates carry gloss+pos (the R2 view threads entry POS
            # per sense, so the name-row POS leg is live); fail-open —
            # lemmas without a view review via LLM unchanged.
            s0b_anchor_map = {}
            for item in todo:
                key = item_key(item)
                try:
                    view = _cached_view(item.get("text", ""))
                except Exception:
                    view = None
                if isinstance(view, dict):
                    s0b_anchor_map[key] = {
                        "candidates": [
                            {"gloss": (s or {}).get("gloss", ""),
                             "pos": (s or {}).get("pos", "")}
                            for s in (view.get("senses") or [])
                            if isinstance(s, dict)]}
            for item in todo:
                key = item_key(item)
                try:
                    needs, gloss = inflection_needs_review(
                        item, index, read_entry)
                except Exception:
                    needs, gloss = False, ""
                if not needs:
                    states["inflection_review"]["done"][key] = {
                        "kept": True, "reason": "not-inflection",
                        "uncertain": False}
                else:
                    review.append({"key": key,
                                   "text": item.get("text", ""),
                                   "gloss": gloss})
            if review and inflect_transport is not None:
                s0b_bar["misses"] += len(review)
                s0b_bar["hits"] += len(todo) - len(review)
                try:
                    verdicts = inflection_review(
                        review, inflect_transport,
                        leg_api_key.get("inflection_review", api_key),
                        telemetry=tele_store, tele_stage="inflection_review",
                        tele_key_idx=_leg_ring_idx("inflection_review"),
                        tele_run_id=run_id,
                        tele_provider=(providers["inflection_review"]
                                       or "avalai"),
                        tele_model_actual=_leg_actual("inflection_review"),
                        tele_attempts=args.tele_attempts,
                        tried=s0b_tried,
                        sleep_fn=sleep_fn,
                        state=states["inflection_review"],
                        ring=leg_ring.get("inflection_review", ring),
                        key_var=_provider_key_var(
                            providers["inflection_review"]),
                        file_label=_leg_file_label(
                            providers["inflection_review"]),
                        rings=provider_rings,
                        anchor_map=s0b_anchor_map)
                except AuthError as exc:
                    _abort("inflection_review", exc)
                    raise
                except RateLimited as exc:
                    # R9 (S4 pattern): flush then STOP for a resume —
                    _report_egress_cooldown(exc)
                    # ProviderCooldown rides along (RateLimited
                    # subclass), same as the s2/s3/s4 callers.
                    _flush(progress_dir, states)
                    tele_flushed = _flush_telemetry(tele_dir, tele_store,
                                                    tele_flushed,
                                                    run_id=run_id)
                    jlog.event("abort", stage="inflection_review",
                               batch=batch_no, error=str(exc))
                    jlog.close()
                    hint = ("wait for quota reset then re-run"
                            if (_leg_avalai("inflection_review")
                                or _leg_google("inflection_review"))
                            else "switch VPN server then re-run")
                    raise SystemExit(_color(
                        "STOP s0b at batch %d: %s — progress flushed, "
                        "%s" % (batch_no, exc, hint),
                        "red", stream=sys.stderr))
                except Exception:
                    verdicts = {}
                for entry in review:
                    key = entry["key"]
                    verdict = verdicts.get(key)
                    base = parse_superlative_base(
                        entry.get("gloss") or "")
                    if verdict is None:
                        states["inflection_review"]["done"][key] = {
                            "kept": True, "reason": "review-uncertain",
                            "uncertain": True}
                    elif not verdict.get("keep") and base and not verdict.get(
                            "uncertain"):
                        states["inflection_review"]["done"][key] = {
                            "kept": True,
                            "reason": "superlative-redirect",
                            "redirect_to": base,
                            "uncertain": False}
                    elif not verdict.get("keep"):
                        states["inflection_review"]["done"][key] = {
                            "kept": False,
                            "reason": "inflection-drop:%s" % (
                                verdict.get("reason") or "base-lemma"),
                            "uncertain": False}
                        if key not in states["inflection_review"]["failed"]:
                            states["inflection_review"]["failed"].append(key)
                    else:
                        # R8: the precheck verdict carries its own slug
                        # (review-has-independent-sense) — preserve it so
                        # progress/dropped.log show WHY the item skipped
                        # review instead of the generic inflection-keep.
                        _reason = verdict.get("reason") or ""
                        states["inflection_review"]["done"][key] = {
                            "kept": True,
                            "reason": (
                                _reason
                                if _reason ==
                                "review-has-independent-sense"
                                else ("review-uncertain"
                                      if verdict.get("uncertain")
                                      else "inflection-keep")),
                            "uncertain": bool(
                                verdict.get("uncertain"))}
                pace_fn(SLEEP)
            elif review:
                s0b_bar["hits"] += len(todo)
                for entry in review:
                    states["inflection_review"]["done"][entry["key"]] = {
                        "kept": True, "reason": "s0b-no-transport",
                        "uncertain": False}
            _flush(progress_dir, states)
            failed_here = sum(
                1 for i in batch
                if not (states["inflection_review"]["done"].get(item_key(i)) or {}).get(
                    "kept", True))
            s0b_bar["durs"].append(time.perf_counter() - _t0)
            _batch_progress("inflection_review", batch_no, n_inflection_batches,
                              len(batch) - failed_here, failed_here,
                              eta=_bar_eta(s0b_bar["durs"],
                                           n_inflection_batches - batch_no),
                              hits=s0b_bar["hits"],
                              misses=s0b_bar["misses"], quiet=quiet)
            jlog.event("batch", stage="inflection_review", batch=batch_no,
                       batches=n_inflection_batches,
                       ok=len(batch) - failed_here, fail=failed_here,
                       hits=s0b_bar["hits"], misses=s0b_bar["misses"])
        _s0b_ok = sum(1 for v in states["inflection_review"]["done"].values()
                      if v.get("kept"))
        _s0b_fail = len(states["inflection_review"].get("failed", []))
        provider_map["inflection_review"]["tried"] = list(s0b_tried)
        _write_provider_map()
        run_logger.stage_end("inflection_review", ok=_s0b_ok, fail=_s0b_fail)
        jlog.event("stage_end", stage="inflection_review",
                   ok=_s0b_ok, fail=_s0b_fail)
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed,
                                     run_id=run_id)
        _stage_summary("inflection_review", states, args.out, quiet=quiet,
                       counts={"hits": s0b_bar["hits"],
                               "misses": s0b_bar["misses"]},
                       entry_bands=entry_bands)
        inflection_dropped = {k for k, v in states["inflection_review"]["done"].items()
                       if isinstance(v, dict) and not v.get("kept")}
        items = [i for i in items if item_key(i) not in inflection_dropped]
        # R44 v12: propagate superlative redirects onto the in-memory
        # items AND merge into the base lemma (Gemini: avoid FSRS
        # fragmentation across best/good). The item becomes the base form
        # (redirected_from recorded); downstream stages key off the new
        # text, so fresh keys are resume-safe by construction.
        for item in items:
            s0b = states["inflection_review"]["done"].get(item_key(item)) or {}
            if s0b.get("redirect_to"):
                item["redirect_to"] = s0b["redirect_to"]
                item["s0b_reason"] = s0b.get("reason", "")
                base = str(s0b["redirect_to"]).strip().lower()
                if base and base != (item.get("text") or "").strip().lower():
                    item["redirected_from"] = item.get("text", "")
                    item["text"] = base
        if inflection_dropped:
            # Details live in dropped.log; console stays one short line.
            _say(_color("%s: kept=%d dropped=%d "
                        "(see dropped.log)" % (progress.display("inflection_review"),
                                               len(items),
                                               len(inflection_dropped)),
                        "cyan"))
        # anchor (deterministic, batch-flushed). V7 anchor-POS drop lives ONLY
        # here: when the anchored sense's entry POS is in {name, propn}
        # (PROPER_NOUN_POS, reused by import — deterministic,
        # no name lists) the item drops with reason anchor-proper-noun.
        # R34 v9: unresolvable bare-xref anchors drop here too (reason
        # no-real-def: no target entry, or the target is also a bare
        # xref — 1 hop max, no chains).
        # F2: name-gloss anchor tops (given/surname/place-name) with a
        # non-proper entry POS reroute to the first non-name sense here
        # (act-fix pattern, flagged rerouted_from_name) or drop as
        # anchor-name-gloss when every candidate is a name.
        # The reason rides on the s1 done entry + failed list (drops never
        # reach precard.jsonl); anchor_dropped is rebuilt from state, so the
        # drop is resume-safe with no re-run needed.
        run_logger.stage_start("anchor_rank")
        jlog.event("stage_start", stage="anchor_rank")
        for batch_no, base in enumerate(
                _stage_range(selected, "anchor_rank", items), start=1):
            batch = items[base:base + BATCH]
            for item in batch:
                key = item_key(item)
                # V7 resume-compat: v6-era s1 entries lack anchor_pos, so
                # they are re-ranked deterministically (same scores plus
                # anchor_pos/drop verdict) instead of skipped. R34 v9
                # extends the compat to the xref fields. F2 extends it to
                # kept name-topped entries (pre-F2 progress never ran the
                # name-gloss verdict); dropped entries are never re-run.
                done_entry = states["anchor_rank"]["done"].get(key)
                done_top = ((done_entry.get("top") or {}).get("gloss", "")
                            if isinstance(done_entry, dict) else "")
                needs_name_eval = (
                    isinstance(done_entry, dict)
                    and "dropped" not in done_entry
                    and not done_entry.get("rerouted_from_name")
                    and _is_name_gloss(done_top))
                # Tags backfill: pre-tags s1 entries carry candidates
                # without the "tags" key — re-rank so the sense-judge
                # prompt renders [tags] identically on fresh and resumed
                # runs (same deterministic scores, tags added).
                needs_tag_backfill = _needs_tag_backfill(done_entry)
                if not isinstance(done_entry, dict) \
                        or "anchor_pos" not in done_entry \
                        or "anchor_tags" not in done_entry \
                        or "xref_unresolvable" not in done_entry \
                        or needs_name_eval \
                        or needs_tag_backfill:
                    try:
                        ranked = anchor_rank_item(item, index, read_entry)
                        if (ranked.get("anchor_pos") or "") in \
                                PROPER_NOUN_POS:
                            rerouted = _reroute_proper_anchor(
                                item, ranked, index, read_entry)
                            if rerouted is not None:
                                ranked["top"], ranked["en_def"], \
                                    ranked["anchor_pos"] = rerouted
                                ranked["rerouted_from_proper"] = True
                                # Mirror the name branch: refresh the tag
                                # carrier from the TARGET sense and re-run
                                # the vulgar verdict (review: stale
                                # anchor_tags would leak a vulgar target
                                # past the gate); empty lookups keep the
                                # anchor's tags (uncertainty keeps).
                                fresh = _target_sense_tags(
                                    item,
                                    rerouted[0].get("sense_id", ""),
                                    index, read_entry)
                                if fresh:
                                    ranked["anchor_tags"] = sorted(fresh)
                                fresh_mother = _mother_for_top(
                                    item,
                                    rerouted[0].get("sense_id", ""),
                                    index, read_entry)
                                if fresh_mother is not None:
                                    ranked["mother_lemma"], \
                                        ranked["mother_lemmas"], \
                                        ranked["mother_multi"] = fresh_mother
                                if set(ranked.get("anchor_tags")
                                       or {}) & VULGAR_TAGS:
                                    ranked.pop("rerouted_from_proper",
                                               None)
                                    ranked["dropped"] = "vulgar-anchor"
                                    if key not in states["anchor_rank"][
                                            "failed"]:
                                        states["anchor_rank"]["failed"].append(key)
                                # R11: warnings go to stderr (stdout is
                                # human progress).
                                print(_color(
                                    "warning: %s re-anchored off proper "
                                    "top -> %s" % (
                                        key,
                                        rerouted[0].get("sense_id", "")),
                                    "yellow"), file=sys.stderr)
                            else:
                                ranked["dropped"] = "anchor-proper-noun"
                                if key not in states["anchor_rank"]["failed"]:
                                    states["anchor_rank"]["failed"].append(key)
                        elif _is_name_gloss(
                                (ranked.get("top") or {}).get("gloss", "")):
                            # F2: name-gloss top (given/surname/place-name)
                            # with a non-proper entry POS — the gloss-based
                            # sibling of the proper branch above. Reroutes
                            # to the first non-name sense (act-fix
                            # pattern, flagged rerouted_from_name by the
                            # helper), keeps the anchor top on helper
                            # errors (marked name_eval_error — uncertainty
                            # keeps, re-armed on resume), else drops as
                            # anchor-name-gloss. A true reroute refreshes
                            # the tag carrier from the TARGET sense and
                            # re-runs the vulgar verdict (review: stale
                            # anchor_tags would leak a vulgar target past
                            # the gate below); empty lookups keep the
                            # anchor's tags (uncertainty keeps).
                            rerouted = _reroute_name_gloss_anchor(
                                item, ranked, index, read_entry)
                            if rerouted is not None:
                                ranked["top"], ranked["en_def"], \
                                    ranked["anchor_pos"] = rerouted
                                if ranked.get("rerouted_from_name"):
                                    fresh = _target_sense_tags(
                                        item,
                                        rerouted[0].get("sense_id", ""),
                                        index, read_entry)
                                    if fresh:
                                        ranked["anchor_tags"] = sorted(
                                            fresh)
                                    fresh_mother = _mother_for_top(
                                        item,
                                        rerouted[0].get("sense_id", ""),
                                        index, read_entry)
                                    if fresh_mother is not None:
                                        ranked["mother_lemma"], \
                                            ranked["mother_lemmas"], \
                                            ranked["mother_multi"] = \
                                            fresh_mother
                                    if set(ranked.get("anchor_tags")
                                           or {}) & VULGAR_TAGS:
                                        ranked.pop("rerouted_from_name",
                                                   None)
                                        ranked["dropped"] = "vulgar-anchor"
                                        if key not in states["anchor_rank"][
                                                "failed"]:
                                            states["anchor_rank"]["failed"].append(
                                                key)
                                    else:
                                        print(_color(
                                            "warning: %s re-anchored off "
                                            "name top -> %s" % (
                                                key,
                                                rerouted[0].get(
                                                    "sense_id", "")),
                                            "yellow"), file=sys.stderr)
                                elif ranked.get("name_eval_error"):
                                    print(_color(
                                        "warning: %s name-eval error, "
                                        "keeping anchor top" % key,
                                        "yellow"), file=sys.stderr)
                            else:
                                ranked["dropped"] = "anchor-name-gloss"
                                if key not in states["anchor_rank"]["failed"]:
                                    states["anchor_rank"]["failed"].append(key)
                        elif set(ranked.get("anchor_tags") or {}) & \
                                VULGAR_TAGS:
                            ranked["dropped"] = "vulgar-anchor"
                            if key not in states["anchor_rank"]["failed"]:
                                states["anchor_rank"]["failed"].append(key)
                        elif ranked.get("xref_unresolvable"):
                            ranked["dropped"] = "no-real-def"
                            if key not in states["anchor_rank"]["failed"]:
                                states["anchor_rank"]["failed"].append(key)
                        states["anchor_rank"]["done"][key] = ranked
                    except Exception as exc:
                        states["anchor_rank"]["done"][key] = {
                            "candidates": [], "top": None, "en_def": "",
                            "anchor_pos": "", "xref_method": "",
                            "resolved_from": "",
                            "xref_unresolvable": False}
                        if key not in states["anchor_rank"]["failed"]:
                            states["anchor_rank"]["failed"].append(key)
                        _note_backoff(states["anchor_rank"], key, [],
                                      "s1-error: %s" % type(exc).__name__)
            _flush(progress_dir, states)
            # Deterministic stage: <1s per batch, no progress bar by design
            # (LLM stages use _batch_progress for live per-batch feedback).
        anchor_dropped = {k for k, v in states["anchor_rank"]["done"].items()
                      if isinstance(v, dict) and v.get("dropped")}
        _s1_ok = len(states["anchor_rank"]["done"]) - len(anchor_dropped)
        _s1_fail = len(anchor_dropped)
        run_logger.stage_end("anchor_rank", ok=_s1_ok, fail=_s1_fail)
        jlog.event("stage_end", stage="anchor_rank",
                   ok=_s1_ok, fail=_s1_fail)
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed,
                                     run_id=run_id)
        _stage_summary("anchor_rank", states, args.out, quiet=quiet,
                       entry_bands=entry_bands)
        if anchor_dropped:
            # Details live in dropped.log; console stays one short line.
            _say(_color("%s: kept=%d dropped=%d "
                        "(see dropped.log)" % (progress.display("anchor_rank"),
                            len(items) - len(anchor_dropped & {item_key(i)
                                                           for i in items}),
                            len(anchor_dropped & {item_key(i)
                                              for i in items})),
                        "cyan"))
        items = [i for i in items if item_key(i) not in anchor_dropped]
        # judge (judge batches). ok = judge-model picks in the batch,
        # fail = s1-fallback (fail-closed) picks in the batch.
        run_logger.stage_start("sense_judge")
        jlog.event("stage_start", stage="sense_judge")
        n_judge_batches = (len(items) + JUDGE_BATCH - 1) // JUDGE_BATCH or 1
        s2_bar = {"durs": [], "hits": 0, "misses": 0}
        for batch_no, base in enumerate(
                _stage_range(selected, "sense_judge", items, JUDGE_BATCH), start=1):
            _t0 = time.perf_counter()
            batch = items[base:base + JUDGE_BATCH]
            todo = [i for i in batch
                    if item_key(i) not in states["sense_judge"]["done"]]
            s2_bar["hits"] += len(batch) - len(todo)
            if todo:
                s2_bar["misses"] += len(todo)
                # Selective-stage resume (--only/--stages without s1)
                # skips the anchor guard: attach missing tags in memory so
                # the judge prompt is identical to a full run. Persists via
                # the regular per-batch flush below.
                _backfill_candidate_tags(
                    todo, states["anchor_rank"]["done"], index, read_entry)
                try:
                    verdicts = judge_batch(
                        todo, states["anchor_rank"]["done"],
                        judge_api_key or api_key,
                        judge_transport, sleep_fn, states["sense_judge"],
                        telemetry=tele_store, tele_batch=batch_no,
                        ring=judge_ring or ring, models=judge_models,
                        provider=(providers["sense_judge"] or "avalai"),
                        key_var=_provider_key_var(
                            providers["sense_judge"]),
                        file_label=_leg_file_label(
                            providers["sense_judge"]),
                        tele_run_id=run_id,
                        tele_model_actual=_leg_actual("sense_judge"),
                        tele_attempts=args.tele_attempts,
                        tried=s2_tried, rings=provider_rings)
                except AuthError as exc:
                    _abort("sense_judge", exc)
                    raise
                except RateLimited as exc:
                    _report_egress_cooldown(exc)
                    _flush(progress_dir, states)
                    tele_flushed = _flush_telemetry(tele_dir, tele_store,
                                                    tele_flushed,
                                                    run_id=run_id)
                    jlog.event("abort", stage="sense_judge",
                               batch=batch_no, error=str(exc))
                    # The SystemExit below skips the post-try summary and
                    # run_done: end the json-log stream here, closed.
                    jlog.close()
                    hint = ("wait for quota reset then re-run"
                            if (judge_avalai or judge_google)
                            else "switch VPN server then re-run")
                    raise SystemExit(_color(
                        "STOP s2 at batch %d: %s — progress flushed, "
                        "%s" % (batch_no, exc, hint),
                        "red", stream=sys.stderr))
                for item in todo:
                    key = item_key(item)
                    verdict = verdicts.get(key)
                    if verdict is None:
                        verdict = judge_fallback(
                            item, states["anchor_rank"]["done"].get(key))
                    states["sense_judge"]["done"][key] = verdict
                    if (verdict.get("model") or "").startswith("s1-") \
                            and key not in states["sense_judge"]["failed"]:
                        states["sense_judge"]["failed"].append(key)
                pace_fn(SLEEP)
            _flush(progress_dir, states)
            fail = sum(
                1 for i in batch
                if ((states["sense_judge"]["done"].get(item_key(i)) or {}).get(
                    "model", "") or "").startswith("s1-"))
            s2_bar["durs"].append(time.perf_counter() - _t0)
            _batch_progress("sense_judge", batch_no, n_judge_batches,
                              len(batch) - fail, fail,
                              eta=_bar_eta(s2_bar["durs"],
                                           n_judge_batches - batch_no),
                              hits=s2_bar["hits"],
                              misses=s2_bar["misses"], quiet=quiet)
            jlog.event("batch", stage="sense_judge", batch=batch_no,
                       batches=n_judge_batches,
                       ok=len(batch) - fail, fail=fail,
                       hits=s2_bar["hits"], misses=s2_bar["misses"])
        _s2_ok = sum(1 for v in states["sense_judge"]["done"].values()
                     if not (v.get("model", "") or "").startswith("s1-"))
        _s2_fail = sum(1 for v in states["sense_judge"]["done"].values()
                       if (v.get("model", "") or "").startswith("s1-"))
        provider_map["sense_judge"]["tried"] = list(s2_tried)
        _write_provider_map()
        run_logger.stage_end("sense_judge", ok=_s2_ok, fail=_s2_fail)
        jlog.event("stage_end", stage="sense_judge",
                   ok=_s2_ok, fail=_s2_fail)
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed,
                                     run_id=run_id)
        _stage_summary("sense_judge", states, args.out, quiet=quiet,
                       counts={"hits": s2_bar["hits"],
                               "misses": s2_bar["misses"]},
                       entry_bands=entry_bands)
        # Post-judge proper-noun routing (idempotent pass over the s2 done
        # state — evaluated here, right after judge, so vectors+ only ever see
        # routed/kept items; resume-safe via the proper_route/proper_drop
        # markers, flushed when the pass evaluates anything).
        evaluated = 0
        for item in items:
            key = item_key(item)
            entry = states["sense_judge"]["done"].get(key)
            if not isinstance(entry, dict):
                continue
            if "proper_route" in entry and "proper_drop" in entry:
                continue
            verdict = judge_proper_route(
                item, entry, states["anchor_rank"]["done"].get(key),
                index, read_entry, zipf_fn)
            entry["proper_route"] = verdict["proper_route"]
            entry["proper_drop"] = verdict["reason"] or ""
            if verdict["reason"] and key not in states["sense_judge"]["failed"]:
                states["sense_judge"]["failed"].append(key)
            evaluated += 1
        if evaluated:
            _flush(progress_dir, states)
        judge_proper_dropped = {
            k for k, v in states["sense_judge"]["done"].items()
            if isinstance(v, dict) and v.get("proper_drop")}
        judge_proper_here = judge_proper_dropped & {item_key(i) for i in items}
        if evaluated or judge_proper_here:
            _say("%s proper-route: routed=%d dropped=%d%s" % (
                progress.display("sense_judge"),
                sum(1 for i in items
                    if (states["sense_judge"]["done"].get(item_key(i)) or {}).get(
                        "proper_route")),
                len(judge_proper_here),
                " (%s)" % ", ".join(sorted(
                    "%s:%s" % (k, states["sense_judge"]["done"][k].get("proper_drop"))
                    for k in judge_proper_here)) if judge_proper_here else ""))
        items = [i for i in items if item_key(i) not in judge_proper_dropped]
        # vectors (vector batches). ok = model vectors, fail = deterministic
        # (fail-closed) fallbacks.
        run_logger.stage_start("topic_vectors")
        jlog.event("stage_start", stage="topic_vectors")
        n_vectors_batches = (len(items) + BATCH - 1) // BATCH or 1
        s3_bar = {"durs": [], "hits": 0, "misses": 0}
        for batch_no, base in enumerate(
                _stage_range(selected, "topic_vectors", items), start=1):
            _t0 = time.perf_counter()
            batch = items[base:base + BATCH]
            todo = [i for i in batch
                    if item_key(i) not in states["topic_vectors"]["done"]]
            s3_bar["hits"] += len(batch) - len(todo)
            if todo:
                s3_bar["misses"] += len(todo)
                try:
                    vecs = vectors_batch(
                        todo, states["sense_judge"]["done"],
                        states["anchor_rank"]["done"],
                        leg_api_key.get("topic_vectors", api_key),
                        topic_transport, sleep_fn, states["topic_vectors"],
                        telemetry=tele_store, tele_batch=batch_no,
                        ring=leg_ring.get("topic_vectors", ring),
                        models=vectors_models_override,
                        provider=(providers["topic_vectors"] or "avalai"),
                        key_var=_provider_key_var(
                            providers["topic_vectors"]),
                        file_label=_leg_file_label(
                            providers["topic_vectors"]),
                        tele_run_id=run_id,
                        tele_model_actual=_leg_actual("topic_vectors"),
                        tele_attempts=args.tele_attempts,
                        tried=s3_tried, rings=provider_rings)
                except AuthError as exc:
                    _abort("topic_vectors", exc)
                    raise
                except RateLimited as exc:
                    _report_egress_cooldown(exc)
                    _flush(progress_dir, states)
                    tele_flushed = _flush_telemetry(tele_dir, tele_store,
                                                    tele_flushed,
                                                    run_id=run_id)
                    jlog.event("abort", stage="topic_vectors",
                               batch=batch_no, error=str(exc))
                    jlog.close()
                    raise SystemExit(_color(
                        "STOP s3 at batch %d: %s — progress flushed, "
                        "%s" % (batch_no, exc,
                                "wait for quota reset then re-run"
                                if (_leg_avalai("topic_vectors")
                                    or _leg_google("topic_vectors")) else
                                "switch VPN server then re-run"),
                        "red", stream=sys.stderr))
                for item in todo:
                    key = item_key(item)
                    picks = fanout_picks(
                        item, states["sense_judge"]["done"].get(key) or {})
                    sid = picks[0].get("sense_id", "") if picks else ""
                    hit = vecs.get(sid) if sid else None
                    if hit is None:
                        hit = {"vector": [{"label": "Other / Abstract",
                                           "weight": 1.0}],
                               "model": "deterministic"}
                        if key not in states["topic_vectors"]["failed"]:
                            states["topic_vectors"]["failed"].append(key)
                    # v14.1: secondary vectors ride on the primary s3
                    # entry (additive "extra_vec") so the S4 label leg
                    # and assembly resolve per-sense vectors without a
                    # second LLM pass; resume-safe (plain JSON).
                    if len(picks) > 1:
                        extra_vec = {}
                        for sub in picks[1:]:
                            sub_sid = sub.get("sense_id", "")
                            if sub_sid and sub_sid in vecs:
                                extra_vec[sub_sid] = vecs[sub_sid]
                        if extra_vec:
                            hit = {**hit, "extra_vec": extra_vec}
                    states["topic_vectors"]["done"][key] = hit
                pace_fn(SLEEP)
            _flush(progress_dir, states)
            fail = sum(
                1 for i in batch
                if (states["topic_vectors"]["done"].get(item_key(i)) or {}).get(
                    "model") == "deterministic")
            s3_bar["durs"].append(time.perf_counter() - _t0)
            _batch_progress("topic_vectors", batch_no, n_vectors_batches,
                              len(batch) - fail, fail,
                              eta=_bar_eta(s3_bar["durs"],
                                           n_vectors_batches - batch_no),
                              hits=s3_bar["hits"],
                              misses=s3_bar["misses"], quiet=quiet)
            jlog.event("batch", stage="topic_vectors", batch=batch_no,
                       batches=n_vectors_batches,
                       ok=len(batch) - fail, fail=fail,
                       hits=s3_bar["hits"], misses=s3_bar["misses"])
        _s3_ok = sum(1 for v in states["topic_vectors"]["done"].values()
                     if v.get("model") != "deterministic")
        _s3_fail = sum(1 for v in states["topic_vectors"]["done"].values()
                       if v.get("model") == "deterministic")
        provider_map["topic_vectors"]["tried"] = list(s3_tried)
        _write_provider_map()
        run_logger.stage_end("topic_vectors", ok=_s3_ok, fail=_s3_fail)
        jlog.event("stage_end", stage="topic_vectors",
                   ok=_s3_ok, fail=_s3_fail)
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed,
                                     run_id=run_id)
        _stage_summary("topic_vectors", states, args.out, quiet=quiet,
                       counts={"hits": s3_bar["hits"],
                               "misses": s3_bar["misses"]},
                       entry_bands=entry_bands)
        # label (label batched, B1: up to LABEL_BATCH items share one LLM
        # call). No fail-closed signal on this stage (exceptions
        # propagate, except auth which aborts), so fail is always 0.
        # Stride is LABEL_BATCH (pacing sleep per worked chunk, same
        # SLEEP as before — pacing, not backoff).
        run_logger.stage_start("topic_label")
        jlog.event("stage_start", stage="topic_label")
        s4_bar = {"durs": [], "hits": 0, "misses": 0, "cache": 0}
        vec_lookup = {}
        for key, hit in states["topic_vectors"]["done"].items():
            for entry in (hit.get("vector") or []):
                if isinstance(entry, dict) and entry.get("label"):
                    vec_lookup.setdefault(
                        (states["sense_judge"]["done"].get(key) or {}).get(
                            "sense_id", ""),
                        []).append(entry)
            # v14.1: secondary vectors stashed on the s3 entry join the
            # lookup so label extras resolve per-sense vectors.
            for sub_sid, sub_hit in (
                    hit.get("extra_vec") or {}).items():
                for entry in ((sub_hit or {}).get("vector") or []):
                    if isinstance(entry, dict) and entry.get("label"):
                        vec_lookup.setdefault(sub_sid, []).append(entry)
        n_label_batches = (len(items) + LABEL_BATCH - 1) // LABEL_BATCH or 1
        _s4_offsets = (list(range(0, len(items), LABEL_BATCH))
                       if "topic_label" in selected else [])
        for batch_no, base in enumerate(_s4_offsets, start=1):
            _t0 = time.perf_counter()
            batch = items[base:base + LABEL_BATCH]
            todo = [i for i in batch
                    if item_key(i) not in states["topic_label"]["done"]
                    or _needs_fanout_relabel(
                        states["topic_label"]["done"].get(item_key(i)),
                        states["sense_judge"]["done"].get(item_key(i)))]
            s4_bar["hits"] += len(batch) - len(todo)
            if todo:
                picks = {}
                for i in todo:
                    key = item_key(i)
                    s2entry = states["sense_judge"]["done"].get(key) or {}
                    picks[key] = {
                        "sense_id": s2entry.get("sense_id", ""),
                        "gloss": s2entry.get("gloss", ""),
                        "picks": fanout_picks(i, s2entry)}
                lookups = {}
                for i in todo:
                    key = item_key(i)
                    per_sid = {}
                    for sub in fanout_picks(
                            i, states["sense_judge"]["done"].get(key) or {}):
                        sid = sub.get("sense_id", "")
                        if sid and sid in vec_lookup:
                            per_sid[sid] = vec_lookup[sid]
                    if per_sid:
                        lookups[key] = per_sid
                try:
                    s4_counts = {"hit": 0, "miss": 0, "cache": 0}
                    assigned_map = label_batch(
                        todo, picks, lookups or None,
                        leg_api_key.get("topic_label", api_key),
                        assign_transport, sleep_fn,
                        states["topic_label"], str(label_topup_cache), label_calls,
                        telemetry=tele_store, tele_batch=batch_no,
                        ring=leg_ring.get("topic_label", ring),
                        provider=(providers["topic_label"] or "avalai"),
                        key_var=_provider_key_var(
                            providers["topic_label"]),
                        file_label=_leg_file_label(
                            providers["topic_label"]),
                        tele_run_id=run_id,
                        tele_model_actual=_leg_actual("topic_label"),
                        tele_attempts=args.tele_attempts,
                        counters=s4_counts, tried=s4_tried,
                        rings=provider_rings)
                    s4_bar["hits"] += s4_counts.get("hit", 0)
                    s4_bar["misses"] += s4_counts.get("miss", 0)
                    s4_bar["cache"] += s4_counts.get("cache", 0)
                except AuthError as exc:
                    _abort("topic_label", exc)
                    raise
                except RateLimited as exc:
                    _report_egress_cooldown(exc)
                    _flush(progress_dir, states)
                    tele_flushed = _flush_telemetry(
                        tele_dir, tele_store, tele_flushed, run_id=run_id)
                    jlog.event("abort", stage="topic_label",
                               batch=batch_no, error=str(exc))
                    jlog.close()
                    raise SystemExit(_color(
                        "STOP s4 at batch %d: %s — progress flushed, "
                        "%s"
                        % (batch_no, exc,
                           "wait for quota reset then re-run"
                            if (_leg_avalai("topic_label")
                                or _leg_google("topic_label")) else
                            "switch VPN server then re-run"),
                        "red", stream=sys.stderr))
                for item in todo:
                    states["topic_label"]["done"][item_key(item)] = assigned_map[
                        item_key(item)]
                pace_fn(SLEEP)
            _flush(progress_dir, states)
            s4_bar["durs"].append(time.perf_counter() - _t0)
            _batch_progress("topic_label", batch_no, n_label_batches,
                              len(batch), 0,
                              eta=_bar_eta(s4_bar["durs"],
                                           n_label_batches - batch_no),
                              hits=s4_bar["hits"],
                              misses=s4_bar["misses"], quiet=quiet)
            jlog.event("batch", stage="topic_label", batch=batch_no,
                       batches=n_label_batches, ok=len(batch), fail=0,
                       hits=s4_bar["hits"], misses=s4_bar["misses"])
        _s4_ok = len(states["topic_label"]["done"])
        provider_map["topic_label"]["tried"] = list(s4_tried)
        _write_provider_map()
        run_logger.stage_end("topic_label", ok=_s4_ok, fail=0)
        jlog.event("stage_end", stage="topic_label", ok=_s4_ok, fail=0)
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed,
                                     run_id=run_id)
        _stage_summary("topic_label", states, args.out, quiet=quiet,
                       counts={"hits": s4_bar["hits"],
                               "misses": s4_bar["misses"],
                               "cache": s4_bar["cache"]},
                       entry_bands=entry_bands)
        # enrich (deterministic enrichment, batch-flushed). Same as label: no
        # fail-closed signal, fail is always 0.
        run_logger.stage_start("enrich")
        jlog.event("stage_start", stage="enrich")
        for batch_no, base in enumerate(
                _stage_range(selected, "enrich", items), start=1):
            batch = items[base:base + BATCH]
            for item in batch:
                key = item_key(item)
                done = states["enrich"]["done"].get(key)
                # C3 resume-compat: pre-C3 s5 entries lack pre_card_id —
                # re-enrich deterministically (no LLM) instead of skipping.
                # Same for pre-bridge entries (no sense_cefr_method) and
                # pre-fan-out entries (judged secondaries, no "extra").
                if not isinstance(done, dict) \
                        or "pre_card_id" not in done \
                        or "sense_cefr_method" not in done \
                        or "example_fallback" not in done \
                        or _needs_fanout_reenrich(
                            done, states["sense_judge"]["done"].get(key)):
                    phrase_entry = None
                    if (item.get("kind") or "word") == "phrase" \
                            and type_log_available:
                        phrase_entry = (type_map or {}).get(
                            (item.get("text") or "").strip())
                    primary = enrich_item(
                        item, states["sense_judge"]["done"].get(key) or {},
                        index, read_entry, tatoeba_pool,
                        phrase_entry=phrase_entry)
                    # v14.1: every fanned-out pick enriches independently
                    # (own IPA/examples/CEFR/pre_card_id, dataset-only).
                    extras = []
                    for sub in fanout_picks(
                            item, states["sense_judge"]["done"].get(key) or {})[1:]:
                        if not sub.get("sense_id"):
                            continue
                        extras.append(enrich_item(
                            item, sub, index, read_entry, tatoeba_pool,
                            phrase_entry=phrase_entry))
                    if extras:
                        primary["extra"] = extras
                    states["enrich"]["done"][key] = primary
            _flush(progress_dir, states)
            # Deterministic stage: <1s per batch, no progress bar by design
            # (LLM stages use _batch_progress for live per-batch feedback).
        _s5_ok = len(states["enrich"]["done"])
        run_logger.stage_end("enrich", ok=_s5_ok, fail=0)
        jlog.event("stage_end", stage="enrich", ok=_s5_ok, fail=0)
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed,
                                     run_id=run_id)
        _stage_summary("enrich", states, args.out, quiet=quiet,
                       entry_bands=entry_bands)
        # Assemble output (survivors only; drops live in s0/s1 progress).
        # v14.1 (R1): one row per judged pick — the lemma fans out into
        # N independent precard records (own pre_card_id, topic vector,
        # CEFR, IPA, examples each).
        for item in items:
            key = item_key(item)
            enrich = states["enrich"]["done"].get(key) or {}
            label = states["topic_label"]["done"].get(key) or {}
            vec3 = states["topic_vectors"]["done"].get(key) or {}
            pick = states["sense_judge"]["done"].get(key) or {}
            preprocess_view = preprocess_info.get(key) or {}
            s0b = states["inflection_review"]["done"].get(key) or {}
            s1r = states["anchor_rank"]["done"].get(key) or {}
            label_extras = label.get("extra") or []
            enrich_extras = enrich.get("extra") or []
            extra_vec = (vec3.get("extra_vec") or {}) \
                if isinstance(vec3.get("extra_vec"), dict) else {}
            label_by_sid = {}
            for extra_row in label_extras:
                if isinstance(extra_row, dict) and extra_row.get("sense_id"):
                    label_by_sid[extra_row["sense_id"]] = extra_row
            enrich_by_sid = {}
            for extra_row in enrich_extras:
                if isinstance(extra_row, dict) and extra_row.get("sense_id"):
                    enrich_by_sid[extra_row["sense_id"]] = extra_row
            subs = fanout_picks(item, pick) or [
                {"sense_id": "", "gloss": ""}]
            rows = []
            for pos, sub in enumerate(subs):
                sub_enrich = enrich if pos == 0 else enrich_by_sid.get(
                    sub.get("sense_id", ""), {})
                sub_label = label if pos == 0 else label_by_sid.get(
                    sub.get("sense_id", ""), {})
                sub_vec = (sub_label.get("vector")
                           if isinstance(sub_label, dict) else None) \
                    or (extra_vec.get(sub.get("sense_id", ""), {}) or {}
                        ).get("vector") \
                    or (vec3.get("vector") if pos == 0 else None) \
                    or [{"label": "Other / Abstract", "weight": 1.0}]
                rec = _build_precard_row(
                    item, key, sub, sub_enrich, sub_label, sub_vec,
                    vec3, pick, preprocess_view, s0b, s1r,
                    pos, len(subs), label_calls)
                rows.append(rec)
            if key not in precards:
                precards[key] = rows
            # else F2: duplicate-redirect loser — first item wins the
            # merged key (last-writer content is silently wrong); the
            # loser is recorded as a duplicate-redirect drop at
            # emission (seen_keys below), never overwriting.
    except KeyboardInterrupt:
        # R11: aborts go to stderr (stdout is human progress).
        print("interrupted — flushing stage progress", file=sys.stderr)
        _flush_telemetry(tele_dir, tele_store, tele_flushed,
                         run_id=run_id)
        jlog.event("abort", stage="run", error="KeyboardInterrupt")
        jlog.close()
        raise SystemExit(130)
    finally:
        if not args.dry_run:
            _flush(progress_dir, states)
        try:
            run_logger.close()
        except Exception:
            pass
        if sys.exc_info()[0] is not None:
            # Safety net for exception paths with no explicit close
            # (e.g. OSError from _flush above or a stage-teardown bug):
            # never leak the handle. Guarded, NOT unconditional — this
            # finally also runs before the post-try summary on the
            # success path, where jlog must stay open for run_done
            # (test_json_log_events_run_id_joined pins this: an
            # unconditional close here drops run_done).
            try:
                jlog.close()
            except Exception:
                pass
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Redirect merges can map two lemmas onto one base key (best+better
    # -> good): emit the first, record later ones as duplicate-redirect
    # drops so FSRS never fragments and no silent overwrites happen.
    # Atomic write (tmp+os.replace, OC must-fix): a crash mid-write must
    # never truncate precard.jsonl and force a full re-run.
    seen_keys: set = set()
    dup_redirect: list = []
    # v14.1 (R2) fail-closed accounting: no sample key may vanish
    # without a precard row or a structured drop verdict — unaccounted
    # keys are logged loudly (console + dropped.log), never silent.
    unaccounted = audit_sample_accounting(items, precards, states)
    if unaccounted:
        # Fail-closed accounting is an error: red on stderr, always
        # shown (even under --quiet), details in dropped.log.
        print(_color("accounting-no-verdict: %d key(s) with no precard "
                     "row and no drop verdict: %s (see dropped.log)"
                     % (len(unaccounted), ", ".join(unaccounted)),
                     "red", stream=sys.stderr), file=sys.stderr)
        jlog.event("accounting-no-verdict", keys=list(unaccounted))
        try:
            drop_log = out_path.parent / "dropped.log"
            with open(drop_log, "a", encoding="utf-8") as handle:
                handle.write("=== accounting-no-verdict ===\n")
                for key in unaccounted:
                    handle.write(format_drop_line(
                        key, "accounting-no-verdict", entry_bands) + "\n")
        except OSError as exc:
            print("warning: dropped.log append failed (%s)" % exc,
                  file=sys.stderr)
    _tmp = str(out_path) + ".tmp"
    with open(_tmp, "w", encoding="utf-8") as handle:
        for item in items:
            key = item_key(item)
            if key in seen_keys:
                dup_redirect.append("%s(redirected_from=%s)" % (
                    key, item.get("redirected_from", "?")))
                continue
            seen_keys.add(key)
            for rec in precards.get(key) or []:
                handle.write(json.dumps(
                    rec, ensure_ascii=False) + "\n")
    os.replace(_tmp, out_path)
    if dup_redirect:
        _say("duplicate-redirect drops (merged into base, FSRS-safe): %s"
             % ", ".join(sorted(set(dup_redirect))))
    # F7 telemetry history: same cumulative seam as card_pilot (imported,
    # never a second copy) so resume runs never erase history — the
    # summary covers ALL runs, not just this one.
    _all_tele, _tele_corrupt = append_telemetry_history(
        out_path.parent, tele_store[tele_flushed:])
    _tele_summary = _tele_write(
        str(out_path.parent / "telemetry_summary.json"), _all_tele,
        run_id=run_id)
    if _tele_corrupt:
        _tele_summary["history_corrupt_lines"] = _tele_corrupt
    n_failed = sum(len(states[s].get("failed", [])) for s in progress.STAGES)
    _say("precard done: %d items -> %s (%s dropped=%d, %s dropped=%d, "
         "%s dropped=%d, failed flags=%d)"
         % (len(items), out_path, progress.display("preprocess"),
            len(states["preprocess"].get("failed", [])), progress.display("inflection_review"),
            len(inflection_dropped), progress.display("anchor_rank"),
            len(anchor_dropped), n_failed))
    run_logger.log("precard done: %d items %s_dropped=%d %s_dropped=%d "
                   "%s_dropped=%d failed=%d" % (
                       len(items), progress.display("preprocess"),
                       len(states["preprocess"].get("failed", [])), progress.display("inflection_review"),
                       len(inflection_dropped), progress.display("anchor_rank"),
                       len(anchor_dropped), n_failed))
    jlog.event("run_done", items=len(items), failed=n_failed,
               records=len(tele_store))
    jlog.close()
    run_logger.close()
    return 0


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
    ap.add_argument("--resume", action="store_true",
                    help="print the RESUME PLAN (per-stage done/todo from "
                    "progress) then run with resume on; mutually "
                    "exclusive with --no-resume")
    ap.add_argument("--only", default="",
                    help="run a single stage only (id or name, e.g. "
                     "--only sense_judge; case-insensitive; "
                    "other stages are skipped, resume still honored)")
    ap.add_argument("--stages", default="",
                    help="comma-separated stage subset (ids or names, e.g. "
                     "--stages anchor_rank,sense_judge; "
                    "mutually exclusive with --only)")
    ap.add_argument("--rekey", default="",
                    help="keyfile (one item key per line, # comments "
                    "allowed): force redo of the listed keys in the "
                    "SELECTED stages (resume still skips everything else)")
    ap.add_argument("--kaikki-index", default=DEFAULT_KAIKKI_INDEX)
    ap.add_argument("--kaikki-raw", default=DEFAULT_KAIKKI_RAW)
    ap.add_argument("--tatoeba-pool", default=DEFAULT_TATOEBA_POOL)
    ap.add_argument("--phrase-type-log", default=DEFAULT_PHRASE_TYPE_LOG,
                    help="phrase-type audit log (missing file = all phrases "
                    "kept with the type-pending flag, never fails)")
    ap.add_argument("--awl-families", default=DEFAULT_AWL_FAMILIES,
                    help="AWL families JSON (missing file = no academic tags "
                    "from AWL, never fails)")
    ap.add_argument("--judge-provider", default=None,
                    choices=("avalai", "google"),
                    help="judge transport: avalai (paid chain — locked "
                    "2026-09-06; requires AVALAI_API_KEY) or google "
                    "(Gemini direct, free tier; requires "
                    "GOOGLE_AI_API_KEY). DEPRECATED "
                    "alias: use --llm-provider (covers all precard legs).")
    ap.add_argument("--llm-provider", default=None,
                    choices=("avalai", "google"),
                    help="ALL precard LLM legs "
                    "(inflection/judge/vectors/label) — REQUIRED, no "
                    "default: avalai (paid chain, no Persian needed — "
                    "locked 2026-09-06; requires AVALAI_API_KEY) or "
                    "google (Gemini direct free tier; requires "
                    "GOOGLE_AI_API_KEY). A run without --llm-provider "
                    "(or per-leg --stage-provider cover) stops "
                    "fail-closed.")
    ap.add_argument("--precard-model", default="",
                    help="Model for all precard legs (default "
                    "glm-5.3-flash on avalai, gemini-3.5-flash-lite on "
                    "google; e.g. deepseek-v4-flash for the "
                    "comparison run).")
    ap.add_argument("--judge-model", default="",
                    help="judge model id (default: provider default — "
                    "glm-5.3-flash for avalai, "
                    "gemini-3.5-flash-lite for google)")
    ap.add_argument("--stage-provider", action="append", default=[],
                    metavar="STAGE=PROVIDER",
                    help="per-leg provider override, repeatable "
                     "(e.g. --stage-provider sense_judge=avalai --stage-provider "
                     "topic_label=google). Legs: inflection_review, sense_judge, topic_vectors, topic_label "
                     "(s-ids and legacy names also work). Wins over "
                    "--llm-provider for that leg.")
    ap.add_argument("--stage-model", action="append", default=[],
                    metavar="STAGE=MODEL",
                    help="per-leg model override, repeatable "
                     "(e.g. --stage-model sense_judge=deepseek-v4-flash). "
                    "Wins over --precard-model/--judge-model for that leg.")
    ap.add_argument("--sleep-secs", type=float, default=SLEEP,
                    help="pause between LLM batches (default %.1f; 0 = no "
                    "pacing sleep — faster but easier to hit 429s; the "
                    "429-rotation backoff always stays on)" % SLEEP)
    ap.add_argument("--quiet", action="store_true",
                    help="suppress human stdout progress (bars/boxes); "
                    "warnings/errors still go to stderr, files still "
                    "written")
    ap.add_argument("--json-log", action="store_true",
                    help="write machine-readable run_events.jsonl beside "
                    "--out (run/stage/batch/warning events, every event "
                    "run_id-joined)")
    ap.add_argument("--tele-attempts", action="store_true",
                    help="emit per-try telemetry attempt rows (default off: "
                    "one terminal record per batch, attempt volume "
                    "unchanged)")
    args = ap.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        ap.error("--limit must be >= 0")
    if args.sleep_secs < 0:
        ap.error("--sleep-secs must be >= 0")
    return args


def _resolve_label_topup_cache(progress_dir):
    """Top-up cache path: the new name wins; old-only dirs seed it once.

    card_pilot.assign_topic reads/writes whatever path it is given, so the
    fallback lives here: when only the old cache exists, copy it to the new
    name (best-effort), then hand out the new path. The old file is never
    written. The seed is atomic (tmp + rename) and JSON-validated, with a
    warning on failure — a failed seed only costs bounded LLM rework, since
    assign_topic treats a missing cache as empty.
    """
    new_path = pathlib.Path(progress_dir) / progress.TOPUP_NEW_NAME
    old_path = pathlib.Path(progress_dir) / progress.TOPUP_OLD_NAME
    if not new_path.exists() and old_path.exists():
        try:
            blob = old_path.read_text(encoding="utf-8")
            json.loads(blob)
            tmp_path = new_path.with_name(new_path.name + ".tmp")
            tmp_path.write_text(blob, encoding="utf-8")
            os.replace(tmp_path, new_path)
        except (OSError, ValueError) as exc:
            print("warning: topup cache seed skipped (%s)" % exc,
                  file=sys.stderr)
    return new_path


def _needs_fanout_reenrich(s5_entry, s2_entry):
    """True when an s5 row predates the v14.1 fan-out (R1 resume-compat).

    Same shape as _needs_fanout_relabel: no "extra" list while the s2
    entry holds judged secondaries. Re-enrichment is deterministic
    (dataset-only, zero LLM).
    """
    try:
        if not isinstance(s5_entry, dict) or not isinstance(s2_entry, dict):
            return False
        if "extra" in s5_entry:
            return False
        return len(fanout_picks({}, s2_entry)) > 1
    except Exception:
        return False


def _build_precard_row(item, key, sub, sub_enrich, sub_label, sub_vec,
                       vec3, pick, preprocess_view, s0b, s1r,
                       pos, n, label_calls=None):
    """One precard row for one fanned-out pick (R1 assembly helper).

    sub_enrich/sub_label carry the per-sense S5/S4 payloads (primary
    payloads for pos 0); sub_vec is the resolved per-sense topic
    vector. Row shape matches the pre-fan-out single row plus
    pick_index/fanout_n and the R3 example flags.
    """
    sub_enrich = sub_enrich if isinstance(sub_enrich, dict) else {}
    sub_label = sub_label if isinstance(sub_label, dict) else {}
    rec = {
        "key": key, "kind": item.get("kind") or "word",
        "text": item.get("text", ""),
        "pool_level": item.get("pool_level", ""),
        "redirect_to": item.get("redirect_to", "") or "",
        "redirected_from": item.get("redirected_from", "") or "",
        "sense_id": sub_enrich.get("sense_id", ""),
        "en_def": sub_enrich.get("en_def", ""),
        "circular_def": bool(sub_enrich.get("circular_def", False)),
        "ipa": sub_enrich.get("ipa", ""),
        "ipa_src": sub_enrich.get("ipa_src",
                                  IPA_SRC_MODEL),
        "dataset_examples": sub_enrich.get("dataset_examples", []),
        "example_fallback": sub_enrich.get("example_fallback",
                                           "synthetic-needed"),
        "example_synthetic_needed": bool(
            sub_enrich.get("example_synthetic_needed",
                           not sub_enrich.get("dataset_examples"))),
        "abbrev_expansion": sub_enrich.get("abbrev_expansion", ""),
        "pos": sub_enrich.get("pos", []),
        "pos_src": sub_enrich.get("pos_src", "none"),
        "lexical_type": sub_enrich.get("lexical_type",
                                       LEXICAL_TYPE_DEFAULT),
        "register": sub_enrich.get("register", REGISTER_DEFAULT),
        "sense_cefr": sub_enrich.get("sense_cefr"),
        "sense_cefr_method": sub_enrich.get("sense_cefr_method",
                                            "unmapped"),
        "pre_card_id": sub_enrich.get("pre_card_id", ""),
        "pick_index": pos, "fanout_n": n,
        "mother_lemma": (s1r.get("mother_lemma", "") or ""),
        "mother_lemmas": list(s1r.get("mother_lemmas") or []),
        "mother_multi": bool(s1r.get("mother_multi", False)),
        "topic_vector": sub_vec,
        "topic_method": sub_label.get("method")
        or TOPIC_METHOD,
        "topic_path": sub_label.get("topic_path") or "",
        "topic_guarded": bool(sub_label.get("topic_guarded", False)),
        "drop_reason": None,
        "stage_calls": {
            "s0": ("kept:type-pending" if preprocess_view.get("type_pending")
                    else "kept:quarantine-%s" % preprocess_view.get("quarantine")
                    if preprocess_view.get("quarantine") else "kept"),
            "s0b": (s0b.get("reason", "") or "kept"),
            "s2": pick.get("model", ""),
            "s3": vec3.get("model", ""),
            "s4": sub_label.get("method", ""),
            "s4_path": sub_label.get("topic_path") or "",
            "s4_models": dict(label_calls or {}),
            "s5": sub_enrich.get("enrich_path", "")},
    }
    if preprocess_view.get("type_pending"):
        rec["type_pending"] = True
    if preprocess_view.get("quarantine"):
        # Advisory review flag flows downstream (card stays live;
        # owner filters quarantine=* for the review list).
        rec["quarantine"] = preprocess_view["quarantine"]
    if (pick.get("proper_route") or ""):
        rec["proper_route"] = pick["proper_route"]
    return rec


## File loaders (frozen from factory/pipeline/card_pilot; pinned data paths below).
def load_kaikki_index(path):
    """Load the offset index: word.lower() -> [{pos, offset, length}] (file order)."""
    index = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            word = str(row.get("word") or "").lower()
            if not word:
                continue
            try:
                offset = int(row.get("offset", 0))
                length = int(row.get("length", 0))
            except (TypeError, ValueError):
                continue
            index.setdefault(word, []).append(
                {"pos": str(row.get("pos") or ""),
                 "offset": offset, "length": length})
    return index


def read_kaikki_entry(raw_path, offset, length):
    """Seek-read one raw kaikki entry (frozen from card_pilot; the raw
    file is GBs — never loaded fully)."""
    with open(raw_path, "rb") as handle:
        handle.seek(offset)
        blob = handle.read(length)
    return json.loads(blob.decode("utf-8"))


## File loaders (frozen from factory/pipeline/card_pilot; pinned data paths below).
def _fold_separators(value):
    """Fold both slash styles to "/" so normpath compares equal on POSIX
    and Windows alike (frozen from card_pilot)."""
    return str(value or "").replace("\\", "/")


def _is_pinned_default(path, default):
    """True when path names the pinned default (frozen from card_pilot;
    guards the loud-missing teeth against caller spelling)."""
    try:
        return os.path.normcase(
            os.path.normpath(_fold_separators(path))) == os.path.normcase(
            os.path.normpath(_fold_separators(default)))
    except (TypeError, ValueError):
        return False


def load_tatoeba_pool(path):
    """lemma.lower() -> [example, ...]; missing/unreadable file -> {}.

    A missing DEFAULT pool warns LOUD (stderr): silent {} would
    disable examples invisibly if someone deletes the "old-looking"
    v13a file (namespace rule — pinned live set, see factory/README).
    Explicit custom paths stay silent (tests, experiments).
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        if _is_pinned_default(path, DEFAULT_TATOEBA_POOL):
            print("WARNING: default Tatoeba pool missing: %s "
                  "(examples disabled; pinned live file, do not "
                  "delete/rename — see factory/README namespace rule)"
                  % DEFAULT_TATOEBA_POOL, file=sys.stderr)
        return {}
    return {str(k).lower(): [s for s in v if isinstance(s, str) and s.strip()]
            for k, v in data.items() if isinstance(v, list)}


## File loaders (frozen from factory/pipeline/card_pilot; pinned data paths below).
def load_phrase_types(path):
    """phrase -> {phrase_type, applied_keep}; any error -> {} (never fail)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle) if str(path).endswith(".json") \
                else [json.loads(line) for line in handle if line.strip()]
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict):
        data = data.get("phrases", [])
    out = {}
    try:
        for row in data or []:
            if not isinstance(row, dict):
                continue
            phrase = (row.get("phrase") or "").strip()
            phrase_type = (row.get("phrase_type") or "").strip()
            if phrase and phrase_type:
                out[phrase] = {"phrase_type": phrase_type,
                               "applied_keep": bool(
                                   row.get("applied_keep"))}
    except Exception:
        return {}
    return out

