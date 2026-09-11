"""Pre-card pipeline: sample.json -> precard.jsonl (locked R22-R25, v8 R29/R32).

Factory-only research script. No bot/DB/handler changes. Reuses the
existing pipeline scripts BY IMPORT (never a third copy of their logic):

- S1 deterministic sense rank: card_pilot.anchor_item_en (the same
  vendored-v14 scorer card_pilot already uses).
- S2 sense judge pick: run_v14_phase3_judge.call_responses transport +
  MODELS chain (Muse-only 1.3 -> 1.2 override), validate_picks /
  deterministic_picks reuse, 2 attempts, 401/403 loud abort,
  other-errors fail-closed to the S1 top pick. S2 today = single-pick
  per item; beginner-2/intermediate-3/advanced-4 picks + x1.5 EVP boost
  belong to v14c (run_v14_phase3_judge), not this pipeline.
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
default (done items are skipped). On HTTP 429: rotate the phrase_judge
KeyRing to the next key (brief 5s pause) and retry the SAME call; when
EVERY key 429s consecutively, flush progress and STOP with a SystemExit
telling the operator to switch VPN server (no long backoff — owner
rule). Progress is flushed EVERY batch and in a finally block
(KeyboardInterrupt-safe). A resume banner prints done/remaining per
stage at startup.

Output: precard.jsonl, one line per SURVIVING item:
{key, kind, text, pool_level, sense_id, en_def, ipa, ipa_src,
 dataset_examples[], abbrev_expansion (R29), pos[]/pos_src (R32),
 lexical_type/register/pre_card_id (C3, dataset-only, zero LLM),
 topic_vector[{label, weight}], topic_method,
 drop_reason (None when kept), type_pending (only when true),
 proper_route (only when the S2 pick routed to the proper-pool track),
 stage_calls{..., s0}}.
Dropped items are NEVER written to precard.jsonl; their reasons live in
the s0 progress state ({done: {key: {kept, reason, type_pending}}},
failed=[dropped keys]) and on stdout. Never silent.
V7: S1 drops proper-noun anchors (anchored entry POS in {name, propn},
reason anchor-proper-noun, recorded on the s1 done entry + failed list —
the ONE anchor-drop place; card_pilot anchor helpers never drop).
Post-S2 proper-noun routing: a JUDGED pick whose entry POS is proper
while the S1 anchor was not is either routed to the proper-pool track
(proper_route=<class> on the s2 done entry + the precard row, item
continues to S3+) or dropped with reason pick-proper-noun/<suffix>
(org-guard / person-name / no-class / zipf-low — recorded on the s2
done entry + failed list, never in precard.jsonl).
V7: console shows a live one-line progress per batch (_batch_progress)
plus an English [STAGE] summary box; multilingual drop details go to
dropped.log. Each run writes a compact run.log beside --out (stage
start/end + counts + timings).

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
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import card_pilot  # noqa: E402  (anchor/label/enrich owner path, reused by import)
from card_pilot import append_telemetry_history  # noqa: E402  (F7 history seam)
from card_pilot import item_key  # noqa: E402
from llm_json import AuthError, extract_json, raise_for_auth  # noqa: E402
from phrase_judge import KeyRing, RateLimited, write_progress  # noqa: E402  (resume + rotation seam)
from telemetry import extract_usage as _tele_usage  # noqa: E402
from telemetry import record_call as _tele_record  # noqa: E402
from telemetry import write_summary as _tele_write  # noqa: E402

DEFAULT_SAMPLE = "W:/hamzaban_data_factory/pilot/sample.json"
DEFAULT_OUT = "W:/hamzaban_data_factory/pilot/precard.jsonl"
DEFAULT_PROGRESS_DIR = "W:/hamzaban_data_factory/pilot/progress_precard"
DEFAULT_AWL_FAMILIES = "W:/hamzaban_data_factory/raw/awl_families.json"

BATCH = 8
SLEEP = 2.5
ROTATE_PAUSE = 5.0
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
# R4 country backstop (#606): hardcoded ISO 3166-1 English short names,
# matched casefolded BEFORE every other gate so a lowercase leak like
# "bolivia" drops even with no kaikki POS data. "turkey" is deliberately
# the ISO/UN "türkiye" spelling — the bare bird/food noun stays keepable.
COUNTRY_NAMES = frozenset({
    "afghanistan", "albania", "algeria", "andorra", "angola",
    "antigua and barbuda", "argentina", "armenia", "australia",
    "austria", "azerbaijan", "bahamas", "bahrain", "bangladesh",
    "barbados", "belarus", "belgium", "belize", "benin", "bhutan",
    "bolivia", "bosnia and herzegovina", "botswana", "brazil",
    "brunei", "bulgaria", "burkina faso", "burundi", "cabo verde",
    "cambodia", "cameroon", "canada", "central african republic",
    "chad", "chile", "china", "colombia", "comoros", "congo",
    "costa rica", "croatia", "cuba", "cyprus", "czechia",
    "côte d'ivoire", "denmark", "djibouti", "dominica",
    "dominican republic", "ecuador", "egypt", "el salvador",
    "equatorial guinea", "eritrea", "estonia", "eswatini", "ethiopia",
    "fiji", "finland", "france", "gabon", "gambia", "georgia",
    "germany", "ghana", "greece", "grenada", "guatemala", "guinea",
    "guinea bissau", "guyana", "haiti", "honduras", "hungary",
    "iceland", "india", "indonesia", "iran", "iraq", "ireland",
    "israel", "italy", "jamaica", "japan", "jordan", "kazakhstan",
    "kenya", "kiribati", "kuwait", "kyrgyzstan", "laos", "latvia",
    "lebanon", "lesotho", "liberia", "libya", "liechtenstein",
    "lithuania", "luxembourg", "madagascar", "malawi", "malaysia",
    "maldives", "mali", "malta", "marshall islands", "mauritania",
    "mauritius", "mexico", "micronesia", "moldova", "monaco",
    "mongolia", "montenegro", "morocco", "mozambique", "myanmar",
    "namibia", "nauru", "nepal", "netherlands", "new zealand",
    "nicaragua", "niger", "nigeria", "north korea", "north macedonia",
    "norway", "oman", "pakistan", "palau", "palestine", "panama",
    "papua new guinea", "paraguay", "peru", "philippines", "poland",
    "portugal", "qatar", "romania", "russia", "rwanda",
    "saint kitts and nevis", "saint lucia",
    "saint vincent and the grenadines", "samoa", "san marino",
    "sao tome and principe", "saudi arabia", "senegal", "serbia",
    "seychelles", "sierra leone", "singapore", "slovakia",
    "slovenia", "solomon islands", "somalia", "south africa",
    "south korea", "south sudan", "spain", "sri lanka", "sudan",
    "suriname", "sweden", "switzerland", "syria", "taiwan",
    "tajikistan", "tanzania", "thailand", "timor leste", "togo",
    "tonga", "trinidad and tobago", "tunisia", "türkiye",
    "turkmenistan", "tuvalu", "uganda", "ukraine",
    "united arab emirates", "united kingdom",
    "united states of america", "uruguay", "uzbekistan", "vanuatu",
    "venezuela", "viet nam", "yemen", "zambia", "zimbabwe",
    "american samoa", "anguilla", "antarctica", "aruba", "bermuda",
    "british virgin islands", "cayman islands", "christmas island",
    "cocos islands", "cook islands", "curaçao", "faroe islands",
    "french guiana", "french polynesia", "gibraltar", "greenland",
    "guam", "guernsey", "hong kong", "isle of man", "jersey",
    "macao", "martinique", "mayotte", "montserrat", "new caledonia",
    "niue", "norfolk island", "northern mariana islands", "pitcairn",
    "puerto rico", "réunion", "saint helena",
    "saint pierre and miquelon", "sint maarten",
    "svalbard and jan mayen", "tokelau", "turks and caicos islands",
    "us virgin islands", "vatican city", "wallis and futuna",
    "western sahara", "åland islands",
    # ASCII/diacritic aliases (#606 review): spellings owners actually
    # type — turkiye, vietnam, cote d'ivoire, curacao, reunion,
    # aland islands, são tomé and príncipe. Same leak class as the lowercase fix; without these
    # the empty-POS path misses both the blocklist and the R4 gate.
    # Lookup also folds separators (hyphen to space, curly quotes to
    # ASCII) so guinea-bissau/guinea bissau, timor-leste/timor leste,
    # and curly-apostrophe côte d’ivoire all hit one entry.
    "turkiye", "vietnam", "cote d'ivoire", "curacao", "reunion",
    "aland islands", "são tomé and príncipe",
})
STAGES = ("s0", "s0b", "s1", "s2", "s3", "s4", "s5")
# Human-readable stage names for logs (ids stay stable in files/progress).
STAGE_NAMES = {
    "s0": "preprocess", "s0b": "inflection", "s1": "anchor",
    "s2": "judge", "s3": "vectors", "s4": "label", "s5": "enrich",
}
# Finglish stage tags for the console (plain ASCII — Windows terminal
# safe). run.log keeps bare ids (greppable, stable); the console shows
# "name (finglish)" so a non-developer owner can follow the run.
STAGE_FINGLESH = {
    "s0": "pishpardazesh", "s0b": "sarf", "s1": "langar",
    "s2": "davari", "s3": "bordar", "s4": "barchasb",
    "s5": "ghanasazi",
}


def stage_name(stage):
    """Bare display name (no Finglish tag). Kept: tests pin it and
    parallel sessions may reference it; console uses stage_label()."""
    return STAGE_NAMES.get(stage, stage)


def stage_label(stage):
    """Console label: English name + Finglish tag, ASCII-only."""
    name = STAGE_NAMES.get(stage)
    if name is None:
        return stage
    return "%s (%s)" % (name, STAGE_FINGLESH.get(stage, stage))


# Reverse map: --only/--stages accept ids or names ("judge" == "s2").
_NAME_TO_STAGE = {name: sid for sid, name in STAGE_NAMES.items()}


def _normalize_stage(pick):
    """Stage id from an id or a display name (case-insensitive)."""
    key = (pick or "").strip().lower()
    if key in STAGES:
        return key
    return _NAME_TO_STAGE.get(key, key)
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
                    help="run a single stage only (id or name, e.g. "
                    "--only judge; case-insensitive; "
                    "other stages are skipped, resume still honored)")
    ap.add_argument("--stages", default="",
                    help="comma-separated stage subset (ids or names, e.g. "
                    "--stages anchor,judge; "
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
    ap.add_argument("--judge-provider", default="zen",
                    choices=("zen", "avalai"),
                    help="S2 judge transport: zen (default, free chain) or "
                    "avalai (paid chain — locked 2026-09-06; "
                    "requires AVALAI_API_KEY). DEPRECATED alias: use "
                    "--llm-provider avalai (covers all precard LLM legs).")
    ap.add_argument("--llm-provider", default="zen",
                    choices=("zen", "avalai"),
                    help="ALL precard LLM legs (S0b/S2/S3/S4): zen (default) "
                    "or avalai (paid chain, no Persian needed — locked "
                    "2026-09-06; requires AVALAI_API_KEY)")
    ap.add_argument("--precard-model", default="",
                    help="AvalAI model for all precard legs (default "
                    "glm-5.3-flash; e.g. deepseek-v4-flash for the "
                    "comparison run). Ignored on the zen path.")
    ap.add_argument("--judge-model", default="",
                    help="S2 judge model id (default: provider default — "
                    "Zen chain models for zen, glm-5.3-flash for avalai)")
    ap.add_argument("--stage-provider", action="append", default=[],
                    metavar="STAGE=PROVIDER",
                    help="per-leg provider override, repeatable "
                    "(e.g. --stage-provider s2=avalai --stage-provider "
                    "s4=zen). Legs: s0b, s2, s3, s4. Wins over "
                    "--llm-provider for that leg.")
    ap.add_argument("--stage-model", action="append", default=[],
                    metavar="STAGE=MODEL",
                    help="per-leg model override, repeatable "
                    "(e.g. --stage-model s2=deepseek-v4-flash). "
                    "Wins over --precard-model/--judge-model for that leg.")
    args = ap.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        ap.error("--limit must be >= 0")
    return args


# LLM legs of the precard line (preprocess/anchor/enrich are deterministic).
LLM_LEGS = ("s0b", "s2", "s3", "s4")


def _parse_stage_map(values, allowed_values=None):
    """Parse ["s2=avalai"] into {s2: avalai}. Bad entries raise SystemExit
    (fail-fast: a typo must not silently burn paid calls on the wrong leg).
    """
    out = {}
    for raw in values or []:
        if "=" not in raw:
            raise SystemExit("bad --stage-* value %r (want STAGE=value)"
                             % raw)
        stage, _, value = raw.partition("=")
        stage, value = stage.strip().lower(), value.strip()
        if stage not in LLM_LEGS:
            raise SystemExit("bad --stage-* leg %r (legs: %s)" % (
                stage, ", ".join(LLM_LEGS)))
        if allowed_values is not None and value not in allowed_values:
            raise SystemExit("bad --stage-* value %r (want one of: %s)" % (
                value, ", ".join(allowed_values)))
        if not value:
            raise SystemExit("bad --stage-* value %r (empty)" % raw)
        out[stage] = value
    return out


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
        only = _normalize_stage(only)
        if only not in STAGES:
            raise SystemExit("--only must be one of %s (got %r)"
                             % (", ".join(STAGES), args.only))
        return {only}
    if stages:
        picks = [_normalize_stage(s)
                 for s in stages.split(",") if s.strip()]
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


def preprocess_classify_item(item, pos_sets, zipf_fn, awl_set, type_map,
                     type_log_available, entry_fn=None):
    """Preprocess verdict for one sample item (s0): {"kept", "reason", "type_pending"}.

    kept=False carries a drop reason (r4-name-only / r4-country-blocklist /
    r20-zipf-low:<z> / applied-keep-false:<type> / g2..g6 input gates,
    locked 2026-09-07).
    Order for words: R4 country blocklist (casefolded, ABSOLUTE for
    single tokens since F1 — no POS-aware exemption, china drops too),
    R4 proper-noun, G-gates (no zipf bypass — entry
    lookup is fail-open), then the R20 zipf floor. A computed quarantine
    flag rides along on unknown zipf (kept, review value survives) but a
    low-zipf suspect drops on frequency, never quarantines. kept=True has reason None except the
    zipf-unknown-kept note. A kept item may carry quarantine=<gate> (G4
    single-sense suspect — surfaced in the stage summary + dropped.log
    for owner review, item is NOT dropped).
    Phrase items kept without a type judgement
    carry type_pending=True ("type-pending" flag). R35 v9: the word zipf
    gate is level-aware (ZIPF_FLOORS by pool_level); academic bypass kept.
    entry_fn(text) -> {"senses": [{"gloss", "tags"}], "poss": set()}
    or None; without entry data the G-gates are skipped (keep).
    """
    kind = item.get("kind") or "word"
    text = (item.get("text") or "").strip()
    if kind == "word":
        country_key = text.casefold().replace("-", " ").replace(
            "’", "'").replace("‘", "'")
        if country_key in COUNTRY_NAMES:
            # F1: ABSOLUTE for single tokens — the old #606 POS-aware
            # exemption (china porcelain, jersey shirt) is gone: a
            # country-named lemma never becomes a card, whatever kaikki
            # knows it as. The rare china-porcelain loss is accepted
            # (owner lock); the turkey bird stays keepable because the
            # list carries the ISO/UN "türkiye" spelling, not "turkey".
            return {"kept": False, "reason": "r4-country-blocklist",
                    "type_pending": False}
        if card_pilot.is_proper_noun_lemma(
                text, (pos_sets or {}).get(text.lower(), set())):
            return {"kept": False, "reason": "r4-name-only",
                    "type_pending": False}
        # G-gates evaluate even on unknown zipf (review: no bypass —
        # entry lookup itself is fail-open, so uncertainty keeps).
        quarantine = None
        if entry_fn is not None:
            try:
                view = entry_fn(text)
            except Exception:
                view = None
            if view and view.get("senses"):
                reason, quarantine = _preprocess_input_gates(text, view)
                if reason:
                    return {"kept": False, "reason": reason,
                            "type_pending": False}
        try:
            zipf = zipf_fn(text)
        except Exception:
            zipf = None
        if zipf is None:
            # Unknown frequency keeps, but a computed quarantine flag
            # still rides along (review value survives the unknown).
            if quarantine:
                return {"kept": True, "reason": "zipf-unknown-kept",
                        "type_pending": False, "quarantine": quarantine}
            return {"kept": True, "reason": "zipf-unknown-kept",
                    "type_pending": False}
        floor = ZIPF_FLOORS.get(
            (item.get("pool_level") or "").strip().upper(), ZIPF_MIN)
        if float(zipf) < floor and not _is_academic(item, awl_set):
            return {"kept": False,
                    "reason": "r20-zipf-low:%.2f" % float(zipf),
                    "type_pending": False}
        # Quarantine is reserved for frequency-passing items (Q1): a
        # low-zipf suspect drops on frequency above, never quarantines.
        if quarantine:
            return {"kept": True, "reason": None,
                    "type_pending": False,
                    "quarantine": quarantine}
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


# G-gate patterns (locked 2026-09-07, calibrated on the 284 dry run).
# G2: every sense gloss is a mechanical inflection reference. Includes
# bare variants ("past of go", hyphenated "third-person singular").
_G2_FORM_RX = re.compile(
    r"\b(third[ -]?person singular|simple past|past of|past tense|"
    r"past participle|present participle|present of|gerund|plural of|"
    r"comparative|superlative)\b",
    re.IGNORECASE)
# G5: demonym / geo glosses on adjective entries. Canonical phrasings
# (calibrated 2026-09-07; intentionally narrow — see tests for the
# positive/negative boundary).
# G5: demonym / geo glosses. "of or pertaining to X" counts only with a
# capitalized object (Italy, not words) — proper names signal places, so
# this branch is case-SENSITIVE on purpose (no IGNORECASE here).
_G5_DEMONYM_RX = re.compile(
    r"\b(nationality|demonym|capital of|city in|native of|"
    r"inhabitant of|person from|"
    r"countr(y|ies)\b[^.]{0,20}?\b(language|nation|nationality)\b|"
    r"language spoken)\b", re.IGNORECASE)
# Case-sensitive on purpose (no IGNORECASE): the place guard [A-Z]
# must not match lowercase. Connector words are spelled case-explicitly.
_G5_PERTAIN_RX = re.compile(
    r"\b[Oo][Ff] [Oo][Rr] "
    r"([Pp][Ee][Rr][Tt][Aa][Ii][Nn][Ii][Nn][Gg]|"
    r"[Rr][Ee][Ll][Aa][Tt][Ii][Nn][Gg]) "
    r"[Tt][Oo] ([Tt][Hh][Ee] [A-Z]|[A-Z])")


def _preprocess_entry_view(item, index, read_entry):
    """Collect {senses:[{gloss,tags}], poss:set} across all rows of a lemma.

    Fail-open to None on any lookup error (caller keeps the item — G-gates
    never drop on uncertainty).
    """
    try:
        rows, _pos = _entries_for(item, index)
    except Exception:
        return None
    senses, poss = [], set()
    try:
        for row in rows or []:
            entry = read_entry(row) or {}
            if isinstance(entry, dict):
                pos = str(entry.get("pos") or "").strip().casefold()
                if pos:
                    poss.add(pos)
                for sense in entry.get("senses") or []:
                    if not isinstance(sense, dict):
                        continue
                    glosses = sense.get("glosses") or []
                    tags = [str(t or "").strip().casefold()
                            for t in sense.get("tags") or []]
                    senses.append({
                        "gloss": glosses[0] if glosses else "",
                        "tags": [t for t in tags if t],
                    })
    except Exception:
        return None
    if not senses:
        return None
    return {"senses": senses, "poss": poss}


def _preprocess_input_gates(text, view):
    """G2..G6 input gates. Returns (drop_reason|None, quarantine|None).

    G1 (case-fold) lives in the sample builder, not here. Order: G3/G4/G6
    metadata checks, then G2/G5 gloss scans. Quarantine (G4 single-sense
    suspect like "led") keeps the item with a review flag.
    Normalization is enforced HERE (not trusted from the caller): poss
    and per-sense tags are casefolded up front, so any entry_fn casing
    (Abbreviation, Interj) still matches.
    """
    poss = {str(p or "").strip().casefold() for p in view.get("poss", set())}
    senses = []
    for s in view.get("senses") or []:
        if not isinstance(s, dict):
            continue
        senses.append({
            "gloss": s.get("gloss") or "",
            "tags": [str(t or "").strip().casefold()
                     for t in s.get("tags", [])],
        })
    glosses = [s.get("gloss") or "" for s in senses]
    # G3: interjection-only entries have no flashcard value (all POS
    # spellings: interj/intj/interjection). A word with other POS rows
    # (by/would/when) is NOT dropped here — proper channels own those.
    _interj = {"interj", "intj", "interjection"}
    if poss and poss <= _interj:
        return "g3-interjection", None
    # G4: abbreviations. All-caps fires on case-preserving samples
    # (live: FEB/WHO/NSW dropped in pilot200g); the tag leg covers
    # lowercased inputs. A lone lowercase single-abbrev sense is
    # quarantined, not dropped (led).
    n_abbr = sum(1 for s in senses if "abbreviation" in s.get("tags", []))
    # Caps alone never drops (BOOK/PLAY stay); caps + at least one abbrev
    # tag, or every-sense-abbrev (multi-sense), drops.
    if (re.fullmatch(r"[A-Z]{2,6}", text or "") and n_abbr > 0) or \
            (senses and n_abbr == len(senses) and len(senses) > 1):
        return "g4-abbrev", None
    if senses and len(senses) == 1 and n_abbr == 1:
        return None, "g4-abbrev"
    # G6: every sense obsolete.
    if senses and all("obsolete" in s.get("tags", []) for s in senses):
        return "g6-obsolete", None
    # G2: every gloss a mechanical inflection reference (kept when at
    # least one sense is independent, e.g. accusing#1 adjective).
    if glosses and all(_G2_FORM_RX.search(g) for g in glosses):
        return "g2-inflection-form", None
    # G5: demonym/geo glosses (phase-1 learner pool; travel phase brings
    # them back from a dedicated dataset).
    if glosses and any(_G5_DEMONYM_RX.search(g or "")
                        or _G5_PERTAIN_RX.search(g or "")
                        for g in glosses):
        return "g5-demonym", None
    return None, None


def _tele_tokens(usage):
    """Token pair from a surfaced usage dict (None-tolerated)."""
    if isinstance(usage, dict):
        return _tele_usage(usage)
    return None, None


def _note_backoff(state, label, waits, outcome):
    state.setdefault("backoffs", []).append(
        {"label": label, "waits": list(waits), "outcome": outcome})


def _call_with_rotation(transport, ring, model, text, sleep_fn, state,
                        label):
    """One LLM call with phrase_judge KeyRing rotation on HTTP 429.

    On 429: brief ROTATE_PAUSE pause, rotate to the next key, retry the
    SAME call. Success resets the ring streak (same F1 rule as
    phrase_judge.call_with_backoff). When EVERY key 429s consecutively,
    records the stop event and raises RateLimited — the caller flushes
    progress and STOPS for a VPN-server switch. Auth (401/403) and
    other errors propagate to the caller.
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
            if getattr(exc, "code", None) != 429:
                raise
            _note_backoff(state, label, [ROTATE_PAUSE], "rotating")
            sleep_fn(ROTATE_PAUSE)
            if ring.rotate():
                continue
            _note_backoff(state, label, [], "all-keys-429-stop")
            raise RateLimited(
                "all keys 429 (provider quotas exhausted) — re-run later")


# -------------------------------------------------------------- S0b ---

def inflection_needs_review(item, index, read_entry):
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
    if gloss and card_pilot.is_superlative_gloss(gloss):
        # F4: superlative-pattern stubs redirect only onto a real base —
        # single-alpha base AND present in the index, else not-inflection
        # (parse stays pure; the index check lives here at the call site).
        base = card_pilot.parse_superlative_base(gloss)
        if not base or base.lower() not in (index or {}):
            return False, ""
        return True, gloss
    if gloss and card_pilot.is_inflection_gloss(gloss):
        return True, gloss
    return False, ""


# ---------------------------------------------------------------- S1 ---

def _reroute_proper_anchor(item, ranked, index, read_entry):
    """Best non-proper candidate when the anchor is proper (act-fix).

    File-order decay can crown an initialism (act#0 ACT-territory) while
    common senses (act#6 deed) sit lower in the same window. Dropping the
    item loses a base word; re-anchoring to the first candidate whose
    entry POS is not proper keeps it. Returns (top, en_def, anchor_pos)
    or None when every candidate is proper (true propers still drop).
    Lookup errors fail open to None (caller keeps the drop).
    """
    try:
        for cand in ranked.get("candidates") or []:
            sid = cand.get("sense_id", "")
            if not sid:
                continue
            pos = _picked_entry_pos(item, sid, index, read_entry)
            if pos and pos not in card_pilot.PROPER_NOUN_POS:
                # Re-rank: the re-anchored sense becomes window rank 1 so
                # the judge sees the same best-first order as the
                # anchor (otherwise the judge would still pick the proper top).
                rest = [c for c in ranked["candidates"]
                        if c.get("sense_id") != sid]
                ranked["candidates"] = [cand] + rest
                return ({"sense_id": sid,
                         "gloss": cand.get("gloss", "")},
                        cand.get("gloss", ""), pos)
    except (KeyError, TypeError, AttributeError, ValueError):
        return None
    return None


# F2: name-gloss heads (given/surname/place-name + first/last/maiden/
# nickname). Anchored on purpose: a gloss merely MENTIONING a surname
# ("a dictionary of surnames") is a real sense, while kaikki name senses
# open with the head ("A female given name.", "A surname."). Mirrors the
# person-guard vocabulary in judge_proper_route, plus place names (same
# leak class). Boundary (review): bare "diminutive" is NOT a head — it
# would collide with the real "diminutive suffix" linguistics sense.
_NAME_GLOSS_RX = re.compile(
    r"^\s*(?:a|an|the)\s+"
    r"(?:(?:male|female|unisex|masculine|feminine)\s+)?"
    r"(?:given\s+name|surname|family\s+name|place\s+name|first\s+name|"
    r"last\s+name|maiden\s+name|nickname)\b",
    re.IGNORECASE)


def _is_name_gloss(gloss):
    """F2: True when the gloss is a name head (given/surname/place-name)."""
    return bool(_NAME_GLOSS_RX.match(gloss or ""))


def _reroute_name_gloss_anchor(item, ranked, index, read_entry):
    """Best non-name candidate when the anchor top is a name gloss (F2).

    Single-POS name entries (gillian#0 "A female given name." under a
    noun entry) crown the name the same way file-order decay crowned
    ACT — dropping the item loses a base word, so re-anchor to the
    first candidate whose gloss is not a name gloss and whose entry POS
    is not proper (act-fix re-rank pattern: the target becomes window
    rank 1 so the judge sees the same best-first order). An
    unresolvable target POS ("") is uncertainty, not disqualification —
    the gloss signal already picked the target, so it reroutes with
    anchor_pos "" (downstream treats "" as non-proper) instead of
    dropping. Returns (top, en_def, anchor_pos) or None when the top is
    not a name gloss or every candidate is a name (true names still
    drop). Lookup errors fail open to None (caller keeps the drop).
    """
    try:
        if not _is_name_gloss((ranked.get("top") or {}).get("gloss", "")):
            return None
        for cand in ranked.get("candidates") or []:
            sid = cand.get("sense_id", "")
            if not sid or _is_name_gloss(cand.get("gloss", "")):
                continue
            pos = _picked_entry_pos(item, sid, index, read_entry)
            if pos not in card_pilot.PROPER_NOUN_POS:
                rest = [c for c in ranked["candidates"]
                        if c.get("sense_id") != sid]
                ranked["candidates"] = [cand] + rest
                return ({"sense_id": sid,
                         "gloss": cand.get("gloss", "")},
                        cand.get("gloss", ""), pos)
    except (KeyError, TypeError, AttributeError, ValueError):
        return None
    return None


def anchor_rank_item(item, index, read_entry):
    """Anchor deterministic rank (s1) via the card_pilot anchor path.

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

def _judge_prompt(batch, anchor_map):
    lines = ["PICK the single most useful sense per item for Persian "
             "learners of English (most concrete everyday meaning first).",
             'Output: {"results": [{"key": "<item key>", '
             '"pick": "<sense_id>"}]}.',
             "Every pick MUST be one of that item's candidate ids "
             "(empty pick only when the item has no candidates).",
             "Input follows:"]
    for item in batch:
        key = item_key(item)
        cands = (anchor_map.get(key) or {}).get("candidates", [])
        lines.append("KEY %s (%s, pool %s):" % (
            key, item.get("kind", "?"), item.get("pool_level", "?")))
        for cand in cands:
            lines.append("- %s %s" % (cand.get("sense_id", "?"),
                                      (cand.get("gloss") or "")[:200]))
        if not cands:
            lines.append("- (no candidates)")
    return "\n".join(lines)


def _judge_fallback(item, anchor_res):
    """Fail-closed pick: anchor top (via the imported deterministic_picks)."""
    from run_v14_phase3_judge import deterministic_picks
    cands = (anchor_res or {}).get("candidates", [])
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


def _judge_validate(data, batch, anchor_map):
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
        cands = (anchor_map.get(key) or {}).get("candidates", [])
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
    """F4 stub predicate: S0b verdict-path predicates, reused by import."""
    return bool(card_pilot.is_inflection_gloss(gloss)
                or card_pilot.is_superlative_gloss(gloss))


def _apply_inflection_veto(out, batch, anchor_map):
    """F4: veto every stub pick in a judge_batch result dict, in place."""
    for item in batch:
        key = item_key(item)
        if key in out:
            sid, gloss = _veto_inflection_pick(
                out[key], (anchor_map or {}).get(key))
            out[key]["sense_id"], out[key]["gloss"] = sid, gloss
    return out


def judge_batch(batch, anchor_map, api_key, transport, sleep_fn, state,
                   telemetry=None, tele_stage="s2", tele_batch=0,
                   ring=None, models=None):
    """    Judge-pick one batch. Returns {key: {sense_id, gloss, model}}.

    Default chain is Muse-only (judge MODELS[:2]); an explicit `models`
    list (e.g. AvalAI glm-5.3-flash via --judge-provider avalai) replaces
    it. 2 attempts per model, 401/403
    loud abort, 429 rotates the KeyRing (brief pause, same-call retry;
    all-keys-429 raises RateLimited so the runner flushes and STOPS),
    anything else fail-closed to the S1 top pick per item. F4: every
    pick (judge-model AND s1-fallback) passes the inflection-stub veto
    — a stub gloss falls back to the anchor-top non-stub candidate.
    R27: one
    telemetry record per batch (ok on a judge-model pick, fallback on
    s1-fallback, error on all-keys-429); tuple (text, usage) transports
    surface token counts (None-tolerated).
    """
    from run_v14_phase3_judge import MODELS as JUDGE_MODELS
    from run_v14_phase3_judge import call_responses as _  # noqa: F401 (owner path ref)
    models = list(models) if models else list(JUDGE_MODELS[:2])
    prompt = _judge_prompt(batch, anchor_map)
    transport = transport  # default wired by caller to judge call_responses
    if ring is None:
        ring = KeyRing([api_key])
    for model in models:
        for attempt in range(MAX_ATTEMPTS):
            text = prompt if attempt == 0 else RETRY_PREFIX + prompt
            label = "%s/%s#%d" % (model, "+".join(
                item_key(i) for i in batch), attempt)
            usage = None
            try:
                raw, usage = _call_with_rotation(
                    transport, ring, model, text, sleep_fn, state, label)
            except AuthError:
                raise
            except RateLimited:
                if telemetry is not None:
                    _tele_record(telemetry, stage=tele_stage,
                                 batch_id=tele_batch, key_idx=0,
                                 model=model, latency_s=0.0,
                                 outcome="error", http_status=429)
                raise
            except urllib.error.HTTPError as exc:
                if getattr(exc, "code", None) in (401, 403):
                    raise_for_auth(exc)
                raw, usage = None, None
            except Exception:
                raw, usage = None, None
            if raw is None:
                continue
            try:
                data = extract_json(raw)
            except AuthError:
                raise
            except Exception:
                continue
            try:
                valid = _judge_validate(data, batch, anchor_map)
            except Exception:
                valid = None
            if valid is not None:
                out = {k: {**v, "model": model} for k, v in valid.items()}
                _apply_inflection_veto(out, batch, anchor_map)  # F4
                if telemetry is not None:
                    prompt_tokens, completion_tokens = _tele_tokens(usage)
                    _tele_record(telemetry, stage=tele_stage,
                                 batch_id=tele_batch, key_idx=0,
                                 model=model, latency_s=0.0, outcome="ok",
                                 prompt_tokens=prompt_tokens,
                                 completion_tokens=completion_tokens)
                return out
    out = {item_key(i): {**_judge_fallback(i, anchor_map.get(item_key(i))),
                         } for i in batch}
    _apply_inflection_veto(out, batch, anchor_map)  # F4 (fallback too:
    # the S1 anchor top itself can be a stub when S0b kept it)
    if telemetry is not None:
        _tele_record(telemetry, stage=tele_stage, batch_id=tele_batch,
                     key_idx=0, model="s1-fallback", latency_s=0.0,
                     outcome="fallback")
    return out


# ------------------------------ post-judge proper-noun routing ---

# Post-judge proper-noun routing: a picked sense whose entry POS is proper
# (card_pilot.PROPER_NOUN_POS, reused by import — deterministic, no name
# lists) while the anchor was NOT proper is either routed to the
# proper-pool track (proper_route=<class>, item continues to vectors+) or
# dropped with reason pick-proper-noun/<suffix>. Classes come from
# GENERAL gloss regexes only (no lists of specific names); the lemma
# zipf floor (2.5, injectable via zipf_fn) keeps rare proper nouns out;
# the org-guard (club|team|band|company|companies) and the person-guard
# (given name|surname|family name) NEVER route — organisations and
# person names are not learner cards. Seam: an idempotent pass over the
# judge done entries (s2.json) immediately after the judge stage (NOT a
# new stage — STAGES and every stage signature are untouched). Verdicts
# ride as additive proper_route/proper_drop markers on the judge done
# entries, so resume only evaluates keys missing both markers, and
# rekeying anchor/judge (which evicts judge done downstream) re-runs the
# pass by construction.
# Precard rows gain ONLY the optional proper_route field (additive —
# the parallel fork session reads it).
PROPER_ROUTE_ZIPF_MIN = 2.5

_PROPER_ROUTE_CLASSES = (
    ("geo", re.compile(
        r"\bcountry\b|\bcapital of\b|\bocean\b|\briver\b|\bmountain\b",
        re.IGNORECASE)),
    ("language", re.compile(r"\blanguage\b", re.IGNORECASE)),
    ("money", re.compile(r"\bcurrency\b", re.IGNORECASE)),
    ("time", re.compile(r"\bday of the week\b|\bmonth of\b",
                        re.IGNORECASE)),
    ("holiday", re.compile(r"\bfestival\b|\bholiday\b", re.IGNORECASE)),
)
_PROPER_ROUTE_ORG_RX = re.compile(
    r"\bclub\b|\bteam\b|\bband\b|\bcompan(?:y|ies)\b", re.IGNORECASE)
_PROPER_ROUTE_PERSON_RX = re.compile(
    r"\bgiven name\b|\bsurname\b|\bfamily name\b", re.IGNORECASE)


def _picked_entry_pos(item, sense_id, index, read_entry):
    """Entry POS of the S2-picked sense ("" when unresolvable).

    Mirrors the S5 xref-target switch (imported helpers only): an
    xref-resolved pick carries the TARGET lemma in its sense_id, so the
    POS is read from the target rows, not the item rows. Lookup errors
    fail open to "" (the caller keeps the item on the normal track).
    """
    try:
        want_idx = int((sense_id or "").split("#")[-1])
    except (TypeError, ValueError, AttributeError):
        return ""
    try:
        entries, pos = _entries_for(item, index)
        sid_lemma = (sense_id or "").rpartition("#")[0].strip().lower()
        if sid_lemma and sid_lemma != (
                item.get("text") or "").strip().lower():
            target_rows = (index or {}).get(sid_lemma)
            if target_rows:
                entries, pos = list(target_rows), ""
        scored = card_pilot.score_senses(
            sid_lemma or item.get("text", ""), entries, pos, read_entry)
    except Exception:
        return ""
    for _score, idx, entry, _sense, _gloss in scored:
        if idx == want_idx:
            try:
                return str((entry or {}).get("pos") or "").strip().casefold()
            except Exception:
                return ""
    return ""


def judge_proper_route(item, pick, anchor_res, index, read_entry, zipf_fn=None):
    """Post-judge proper-noun verdict for one item.

    Returns {"routed", "proper_route", "reason"}: routed=True carries
    proper_route=<class> (item continues to S3+ on the proper-pool
    track); routed=False with reason None means "not a proper pick —
    continue normally"; routed=False with reason
    "pick-proper-noun/<suffix>" means drop. The org/person guards run
    before class/zipf so they always win. zipf_fn=None uses the live
    default_zipf (tests inject a stub).
    """
    anchored = str((anchor_res or {}).get("anchor_pos") or "").strip().casefold()
    picked_pos = _picked_entry_pos(
        item, (pick or {}).get("sense_id", ""), index, read_entry)
    if picked_pos not in card_pilot.PROPER_NOUN_POS \
            or anchored in card_pilot.PROPER_NOUN_POS:
        return {"routed": False, "proper_route": "", "reason": None}
    gloss = (pick or {}).get("gloss", "") or ""
    if _PROPER_ROUTE_ORG_RX.search(gloss):
        return {"routed": False, "proper_route": "",
                "reason": "pick-proper-noun/org-guard"}
    if _PROPER_ROUTE_PERSON_RX.search(gloss):
        return {"routed": False, "proper_route": "",
                "reason": "pick-proper-noun/person-name"}
    route = ""
    for cls, rx in _PROPER_ROUTE_CLASSES:
        if rx.search(gloss):
            route = cls
            break
    if not route:
        return {"routed": False, "proper_route": "",
                "reason": "pick-proper-noun/no-class"}
    fn = zipf_fn or default_zipf
    try:
        zipf = fn((item.get("text") or "").strip())
    except Exception:
        zipf = None
    if zipf is None:
        return {"routed": False, "proper_route": "",
                "reason": "pick-proper-noun/zipf-unknown"}
    if float(zipf) < PROPER_ROUTE_ZIPF_MIN:
        return {"routed": False, "proper_route": "",
                "reason": "pick-proper-noun/zipf-low:%.2f" % float(zipf)}
    return {"routed": True, "proper_route": route, "reason": None}


# ---------------------------------------------------------------- S3 ---

def _vectors_pseudo_records(batch, judge_map, anchor_map):
    """Group batch picks into run_v15 pseudo lemma records."""
    groups = {}
    for item in batch:
        key = item_key(item)
        pick = (judge_map.get(key) or {})
        sid = pick.get("sense_id", "")
        if not sid:
            continue
        lemma = (item.get("text") or "").strip()
        rec = groups.setdefault(
            lemma, {"lemma": lemma, "ranked_senses": []})
        if all(s["sense_id"] != sid for s in rec["ranked_senses"]):
            gloss = pick.get("gloss", "") or (
                anchor_map.get(key) or {}).get("en_def", "")
            rec["ranked_senses"].append(
                {"sense_id": sid, "gloss": gloss,
                 "topic_label": "Other / Abstract"})
    return list(groups.values())


def vectors_batch(batch, judge_map, anchor_map, api_key, transport, sleep_fn,
                    state, telemetry=None, tele_stage="s3", tele_batch=0,
                    ring=None, models=None):
    """Topic vectors for one batch via the run_v15 path (imported).

    Returns {sense_id: {"vector": [{label, weight}...], "model": ...}}.
    Empty-pick items are absent (caller maps them to the single Other
    fallback). Total failure fails closed per lemma to fallback_vectors.
    429 rotates the KeyRing (brief pause, same-call retry; all-keys-429
    raises RateLimited so the runner flushes and STOPS).
    R27: one telemetry record per batch (ok / fallback / error); tuple
    (text, usage) transports surface token counts (None-tolerated).
    """
    from run_v15_topics import MODELS as V15_MODELS
    from run_v15_topics import USER_TMPL, fallback_vectors, lemma_block
    from run_v15_topics import validate_vectors
    from run_v15_topics import call_responses as _  # noqa: F401 (owner path ref)
    v15_models = list(models) if models else list(V15_MODELS)
    pseudos = _vectors_pseudo_records(batch, judge_map, anchor_map)
    out = {}
    if not pseudos:
        return out
    prompt = USER_TMPL + "\n\n".join(lemma_block(r) for r in pseudos)
    if ring is None:
        ring = KeyRing([api_key])
    for model in v15_models:
        for attempt in range(MAX_ATTEMPTS):
            text = prompt if attempt == 0 else RETRY_PREFIX + prompt
            label = "%s/v15#%d" % (model, attempt)
            usage = None
            try:
                raw, usage = _call_with_rotation(
                    transport, ring, model, text, sleep_fn, state, label)
            except AuthError:
                raise
            except RateLimited:
                if telemetry is not None:
                    _tele_record(telemetry, stage=tele_stage,
                                 batch_id=tele_batch, key_idx=0,
                                 model=model, latency_s=0.0,
                                 outcome="error", http_status=429)
                raise
            except urllib.error.HTTPError as exc:
                if getattr(exc, "code", None) in (401, 403):
                    raise_for_auth(exc)
                raw, usage = None, None
            except Exception:
                raw, usage = None, None
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
                    prompt_tokens, completion_tokens = _tele_tokens(usage)
                    _tele_record(telemetry, stage=tele_stage,
                                 batch_id=tele_batch, key_idx=0,
                                 model=model, latency_s=0.0, outcome="ok",
                                 prompt_tokens=prompt_tokens,
                                 completion_tokens=completion_tokens)
                return merged
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

def _rotating_llm_transport(transport, sleep_fn, state, ring):
    """Wrap an (api_key, model, user_text) transport with KeyRing rotation.

    On 429: brief ROTATE_PAUSE pause, rotate to the next key, retry the
    SAME call. When EVERY key 429s consecutively, raises RateLimited —
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
                if getattr(exc, "code", None) != 429:
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


def label_item(item, gloss, sense_id, vector_lookup, api_key, transport,
                  sleep_fn, state, progress_path, model_calls,
                  telemetry=None, tele_stage="s4", tele_batch=0,
                  ring=None):
    """Label topic (s4) via card_pilot.assign_topic (imported two-leg).

    Telemetry (model + surfaced tokens, fallback on deterministic miss)
    is owned by assign_topic — this wrapper only maps auth/stop signals
    and stays fail-closed to Other / Abstract. RateLimited from the
    rotating transport propagates untouched (re-raised below) so the S4
    caller flushes progress and stops for a server switch.
    """
    if ring is None:
        ring = KeyRing([api_key])
    llm_leg = (_rotating_llm_transport(transport, sleep_fn, state, ring)
               if transport is not None else None)
    try:
        return card_pilot.assign_topic(
            item.get("text", ""), gloss or "",
            sense_id=sense_id or None, llm_transport=llm_leg,
            progress_path=progress_path, api_key=api_key,
            model_calls=model_calls, vector_lookup=vector_lookup,
            telemetry=telemetry, tele_stage=tele_stage,
            tele_batch=tele_batch)
    except AuthError:
        raise
    except RateLimited:
        raise
    except Exception:
        return {"label": "Other / Abstract",
                "method": card_pilot.TOPIC_METHOD_TAG,
                "vector": card_pilot.single_topic_vector(
                    "Other / Abstract"),
                "topic_path": "fallback"}


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


# --------------------------------- C3 pack wirings (locked 2026-09-10) ---
# Additive precard row fields from dataset sources only (zero LLM calls):
# lexical_type (word default; slang/colloquial/idiomatic from the picked
# kaikki sense tags; phrases from the phrase-type log verbatim), register
# (neutral default; informal tag; slang_vulgar from vulgar/offensive tags),
# pre_card_id (sha1-hex16 of lemma.lower|pos|en_def normalized — EN only,
# never Persian). Destination-side pack filters read these; gates/scoring
# never do (no behavior change there).
LEXICAL_TYPE_DEFAULT = "word"
REGISTER_DEFAULT = "neutral"
REGISTER_INFORMAL = "informal"
REGISTER_SLANG_VULGAR = "slang_vulgar"
_LEXICAL_SLANG_TAGS = {"slang"}
_LEXICAL_COLLOQUIAL_TAGS = {"colloquial"}
_LEXICAL_IDIOMATIC_TAGS = {"idiomatic"}
_REGISTER_INFORMAL_TAGS = {"informal"}
_REGISTER_SLANG_VULGAR_TAGS = {"vulgar", "offensive"}
# F3 register floor: slang/colloquial sense tags imply at least informal
# (kush/recon land informal, not neutral). Reuses the lexical-type tag
# sets above (single source — no second copy of the vocabulary).


def _normalize_tags(tags):
    """Lowercased tag set from any caller shape (None/str/list of str).

    Normalization lives HERE (not trusted from the caller) so the public
    C3 helpers stay safe for any caller — a raw "Slang"/" Vulgar " tag
    still maps instead of silently falling through to the default.
    """
    if isinstance(tags, str):
        tags = [tags]
    try:
        items = list(tags or [])
    except TypeError:
        return set()
    return {str(t or "").strip().casefold()
            for t in items if str(t or "").strip()}


def _sense_tag_set(sense):
    """Lowercased kaikki tag set of one sense dict ({} on bad shape)."""
    try:
        tags = (sense or {}).get("tags") or []
    except AttributeError:
        return set()
    return _normalize_tags(tags)


def lexical_type_for(kind, sense_tags, phrase_entry=None):
    """Lexical type for one precard row (pure, dataset-only).

    Phrases with a phrase-type log entry use its phrase_type, casefolded
    (log values are the lowercase PHRASE_TYPES vocabulary; the fold only
    guards a stray capital from forking downstream pack filters).
    Everything else maps the picked-sense kaikki tags (slang >
    colloquial > idiomatic) with a "word" default.
    """
    if (kind or "word") == "phrase" and isinstance(phrase_entry, dict):
        phrase_type = str(phrase_entry.get("phrase_type") or "").strip()
        if phrase_type:
            return phrase_type.casefold()
    tags = _normalize_tags(sense_tags)
    if tags & _LEXICAL_SLANG_TAGS:
        return "slang"
    if tags & _LEXICAL_COLLOQUIAL_TAGS:
        return "colloquial"
    if tags & _LEXICAL_IDIOMATIC_TAGS:
        return "idiomatic"
    return LEXICAL_TYPE_DEFAULT


def register_for(sense_tags):
    """Register for one precard row (pure, dataset-only).

    slang_vulgar (vulgar/offensive tags) wins over informal; slang or
    colloquial tags imply at least informal (F3 floor); default is
    neutral. The vulgar/offensive set is the locked ticket scope — the
    broader S1 VULGAR_TAGS drop is a separate gate, untouched here.
    """
    tags = _normalize_tags(sense_tags)
    if tags & _REGISTER_SLANG_VULGAR_TAGS:
        return REGISTER_SLANG_VULGAR
    if tags & (_REGISTER_INFORMAL_TAGS | _LEXICAL_SLANG_TAGS
               | _LEXICAL_COLLOQUIAL_TAGS):
        return REGISTER_INFORMAL
    return REGISTER_DEFAULT


def _normalize_id_part(text):
    """One pre_card_id component: stripped, lowered, whitespace-collapsed."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def compute_pre_card_id(lemma, pos, en_def):
    """Stable precard id: sha1-hex16("lemma|pos|en_def") over normalized
    EN content only (Persian phase-2 edits can never move it). The 64-bit
    truncation is fine at precard volume; if this id ever becomes a
    cross-run dedup key, revisit the birthday bound first."""
    key = "%s|%s|%s" % (_normalize_id_part(lemma),
                        _normalize_id_part(pos),
                        _normalize_id_part(en_def))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def enrich_item(item, judge_pick, index, read_entry, tatoeba_pool,
                   zipf_fn=None, phrase_entry=None):
    """Enrichment (s5) from the judge-chosen sense (card_pilot helpers).

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
    "enrich_path" is "full" when the dataset carriers cover IPA + all
    N_EXAMPLES slots, else "partial" (the model fills gaps downstream)
    so the fallback is counted in stage_calls, not silent.
    C3: also returns lexical_type + register (picked-sense kaikki tags /
    phrase-type log entry) and pre_card_id (stable EN-content id) —
    dataset sources only, zero LLM calls.
    """
    sid = (judge_pick or {}).get("sense_id", "")
    gloss = (judge_pick or {}).get("gloss", "")
    kind = item.get("kind") or "word"
    lemma = (item.get("text") or "").strip()
    if not sid:
        return {"sense_id": "", "en_def": gloss or "",
                "ipa": "", "ipa_src": card_pilot.IPA_SRC_MODEL,
                "dataset_examples": [], "abbrev_expansion": "",
                "pos": [], "pos_src": "none", "enrich_path": "partial",
                "lexical_type": lexical_type_for(kind, set(),
                                                 phrase_entry),
                "register": REGISTER_DEFAULT,
                "pre_card_id": compute_pre_card_id(
                    lemma, item.get("pos", ""), gloss or "")}
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
    picked_examples = picked[:card_pilot.N_EXAMPLES]
    enrich_path = ("full" if ipa and len(picked_examples) >=
                   card_pilot.N_EXAMPLES else "partial")
    sense_tags = _sense_tag_set(sense)
    id_pos = (pos_tags[0] if pos_tags else (item.get("pos") or ""))
    return {"sense_id": sid, "en_def": gloss or "",
            "ipa": ipa,
            "ipa_src": card_pilot.IPA_SRC_DATASET if ipa
            else card_pilot.IPA_SRC_MODEL,
            "dataset_examples": picked_examples,
            "abbrev_expansion": card_pilot.parse_abbrev_expansion(
                gloss or ""),
            "pos": pos_tags,
            "pos_src": "dataset" if pos_tags else "none",
            "enrich_path": enrich_path,
            "lexical_type": lexical_type_for(kind, sense_tags,
                                             phrase_entry),
            "register": register_for(sense_tags),
            "pre_card_id": compute_pre_card_id(lemma, id_pos,
                                               gloss or "")}


# ------------------------------------------------------------- main ---

def _default_judge_transport(api_key, model, user_text):
    from run_v14_phase3_judge import call_responses
    return call_responses(api_key, model, user_text)


# AvalAI (OpenAI-compatible) chat transport for the paid model chain
# (locked 2026-09-06: S2 glm-5.3-flash wired here; S3 gemini-3.5-flash-lite
# and repair gemini-3.8-flash are a planned follow-up, not yet wired).
# shape as the Zen transports, so KeyRing rotation (429) and the
# 401/403 auth mapping apply unchanged. reasoning_effort low is
# mandatory: without it thinking tokens eat the budget and the answer
# comes back empty (verified 2026-09-06: 300 thinking tokens, "").
AVALAI_CHAT_URL = "https://api.avalai.ir/v1/chat/completions"
AVALAI_PRECARD_MODEL = "glm-5.3-flash"


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


def _default_topic_transport(api_key, model, user_text):
    from run_v15_topics import call_responses
    return call_responses(api_key, model, user_text)


def _default_assign_transport(api_key, model, user_text):
    from run_v16b_topup import call_responses
    return call_responses(api_key, model, user_text)


def _default_inflect_transport(api_key, model, sys_text, user_text):
    return card_pilot.call_responses(api_key, model, sys_text, user_text)


def _color(text, name):
    """ANSI color for consoles; plain text when piped/NO_COLOR/Windows-legacy.

    Console-only helper (stored reasons/logs stay uncolored for files).
    """
    import os as _os
    codes = {"green": "32", "red": "31", "yellow": "33", "cyan": "36",
             "bold": "1"}
    try:
        use = sys.stdout.isatty() and not _os.environ.get("NO_COLOR") \
            and name in codes
    except Exception:
        use = False
    if not use:
        return text
    return "\x1b[%sm%s\x1b[0m" % (codes[name], text)


def _batch_progress(stage, batch_no, n_batches, ok, fail):
    """Live one-line progress (carriage return, English-only console).

    Replaces per-batch line spam: the line rewrites in place. run.log
    keeps full history (unchanged); a stage summary box follows at each
    stage end. Persian drop details go to dropped.log, never the console
    (Windows terminal mojibake).
    """
    width = 20
    total = n_batches or 1
    done = min(batch_no, total)
    filled = int(width * done / total)
    print("\r%s" % _color(
        "[%s] [%s%s] %d/%d | ok=%d fail=%d" % (
            stage_label(stage), "=" * filled, " " * (width - filled),
            done, total, ok, fail), "cyan"), end="", flush=True)


def _reason_slug(reason):
    """English slug of a drop reason (text before the first colon)."""
    return str(reason or "").split(":")[0].strip() or "unknown"


def _stage_summary(stage, states, out_path):
    """English stage box on stdout + full multilingual details to file."""
    from collections import Counter
    done = states.get(stage, {}).get("done", {}) or {}
    failed = states.get(stage, {}).get("failed", []) or []
    # Same kept rule as run_logger.stage_end callers: an entry counts as
    # kept unless explicitly not-kept or dropped (a verdict carrying both
    # kept=True and dropped=<reason> is dropped — fail-closed).
    kept = sum(1 for v in done.values()
               if isinstance(v, dict) and v.get("kept", True) is not False
               and not v.get("dropped"))
    slugs = Counter()
    details = []
    quarantined = []
    for key, verdict in done.items():
        if not isinstance(verdict, dict):
            continue
        reason = verdict.get("reason") or verdict.get("dropped") or ""
        if verdict.get("quarantine"):
            quarantined.append("%s: quarantine-%s" % (
                key, verdict.get("quarantine")))
        if verdict.get("kept", True) and not verdict.get("dropped"):
            # S2 judge fallbacks stay live but are notable: the judge
            # failed and the S1 anchor survived instead.
            if str(verdict.get("model", "")).startswith("s1-"):
                slugs["s1-fallback"] += 1
                details.append("%s: s1-fallback" % key)
            continue
        slugs[_reason_slug(reason)] += 1
        details.append("%s: %s" % (key, reason))
    for key in failed:
        if key not in done:
            slugs["failed-no-entry"] += 1
            details.append("%s: failed-no-entry" % key)
    print("")
    print(_color("[STAGE %s] kept=%d dropped=%d%s%s" % (
        stage_label(stage), kept, len(failed),
        " | " + ", ".join("%s=%d" % kv for kv in slugs.most_common(4))
        if slugs else "",
        " | quarantined=%d" % len(quarantined) if quarantined else ""),
        "green" if not failed else "yellow"))
    if details or quarantined:
        drop_log = pathlib.Path(str(out_path)).parent / "dropped.log"
        try:
            with open(drop_log, "a", encoding="utf-8") as handle:
                handle.write("=== %s drops ===\n" % stage)
                for line in details:
                    handle.write(line + "\n")
                if quarantined:
                    handle.write("=== %s quarantine (kept, review) ===\n"
                                 % stage)
                    for line in quarantined:
                        handle.write(line + "\n")
        except OSError as exc:
            print("warning: dropped.log append failed (%s)" % exc)


def _flush(progress_dir, states):
    for stage in STAGES:
        write_progress(str(pathlib.Path(progress_dir) / ("%s.json" % stage)),
                       states[stage])



def _flush_telemetry(tele_dir, tele_store, flushed):
    """Append unflushed telemetry records + rewrite the summary.

    Kill-safe incremental persistence: a killed run keeps every record up
    to the last completed stage (and every STOP path flushes before
    exiting). Returns the new flushed count. Summary covers the current
    run; the end-of-run history append stays cumulative.
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
                    list(tele_store))
    return len(tele_store)
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
        print("  batches:  %d x %d (preprocess..enrich incl. inflection, "
              "resume %s)" % (
            (len(items) + BATCH - 1) // BATCH if items else 0, BATCH,
            "off" if args.no_resume else "on"))
        print("  stages:   preprocess[name/zipf/phrase gates] / "
              "inflection-review / anchor-rank / judge / "
              "vectors / label / enrich")
        print("  selected: %s" % ", ".join(
            stage_label(s) for s in STAGES if s in selected))
        if rekeyed:
            print("  rekey:    %d key(s) forced to redo" % len(rekeyed))
        for stage in STAGES:
            if stage in selected:
                print("  need %s: %d todo (%d done kept, upper bound "
                      "pre-drop)" % (stage_label(stage),
                                     needs[stage]["todo"],
                                     needs[stage]["done"]))
            else:
                print("  stage %s: skipped (not selected)"
                      % stage_label(stage))
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
            stage_label(stage), done_n, max(0, total - done_n)))
    print("resume: %s" % " | ".join(banner))
    # R26: stage selection + rekey eviction (resume still skips the rest).
    # Stage dependency: anchor -> judge -> vectors -> label -> enrich,
    # so rekeying an upstream stage auto-invalidates the same keys downstream — otherwise assembly mixes
    # new anchors with stale enrichment (kiss#5-style staleness).
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
            ", ".join(stage_label(s) for s in STAGES if s in selected)))

    # V7: compact run.log in the out dir (stage start/end + counts +
    # timings). Console shows a live one-line progress per batch
    # (_batch_progress) plus an English [STAGE] box; multilingual drop
    # details go to dropped.log. ok/fail per stage: s0 kept vs
    # dropped; s1 ranked vs anchor-proper-noun/error; s2 judge model vs
    # s1-fallback; s3 model vector vs deterministic fallback; s4/s5 have
    # no fail-closed signal, so fail is always 0 there.
    from card_pilot import RunLogger  # noqa: E402
    run_logger = RunLogger(
        str(pathlib.Path(args.out).parent / "run.log"))
    for stage in STAGES:
        if stage not in selected:
            run_logger.log("stage %s skipped (not selected)" % stage)
    tele_store = []  # R27: per-batch records (key_idx only, never values)
    tele_dir = pathlib.Path(args.out).parent
    tele_flushed = 0

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
    preprocess_info: dict = {}
    # Memoized entry views: one Kaikki read pass per lemma per run (S0
    # was previously in-memory; without this each item pays open+seek).
    preprocess_view_cache: dict = {}

    def _cached_view(text):
        key = (text or "").strip().casefold()
        if key not in preprocess_view_cache:
            preprocess_view_cache[key] = _preprocess_entry_view(
                {"kind": "word", "text": text}, index, read_entry)
        return preprocess_view_cache[key]
    run_logger.stage_start("s0")
    n_preprocess_batches = (len(items) + BATCH - 1) // BATCH or 1
    for batch_no, base in enumerate(
            _stage_range(selected, "s0", items), start=1):
        batch = items[base:base + BATCH]
        for item in batch:
            key = item_key(item)
            if key not in states["s0"]["done"]:
                verdict = preprocess_classify_item(
                    item, pos_sets, zipf_fn, awl_set, type_map,
                    type_log_available, entry_fn=_cached_view)
                states["s0"]["done"][key] = verdict
                if not verdict["kept"] \
                        and key not in states["s0"]["failed"]:
                    states["s0"]["failed"].append(key)
        _flush(progress_dir, states)
        ok = sum(1 for i in batch
                 if (states["s0"]["done"].get(item_key(i)) or {}).get("kept"))
        _batch_progress("s0", batch_no, n_preprocess_batches, ok,
                          len(batch) - ok)
    run_logger.stage_end(
        "s0",
        ok=sum(1 for v in states["s0"]["done"].values() if v.get("kept")),
        fail=len(states["s0"].get("failed", [])))
    tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed)
    _stage_summary("s0", states, args.out)
    for key, verdict in states["s0"]["done"].items():
        preprocess_info[key] = verdict
    dropped = {k for k, v in preprocess_info.items() if not v.get("kept")}
    items = [i for i in items if item_key(i) not in dropped]
    if dropped:
        # Details live in dropped.log (written by _stage_summary);
        # console stays a single short line (no 80-item spam).
        print(_color("s0 preprocess: kept=%d dropped=%d "
                     "(see dropped.log)" % (len(items), len(dropped)),
                     "cyan"))

    need_llm = (_judge_transport is _USE_DEFAULT
                or _topic_transport is _USE_DEFAULT
                or _assign_transport is _USE_DEFAULT
                or _inflect_transport is _USE_DEFAULT)
    # Provider intent before any key loading (review: full-AvalAI runs
    # must not demand an unused Zen key). None = caller-owned/skipped leg
    # (no Zen), _USE_DEFAULT = pipeline default (Zen unless AvalAI mode).
    # Per-leg overrides (--stage-provider/--stage-model) participate in
    # every decision below, so a mixed line (e.g. s2 zen + rest avalai)
    # wires correctly. Precedence per leg: --stage-* win, then S2-only
    # --judge-*, then master --llm-provider/--precard-model, then Zen.
    stage_prov = _parse_stage_map(args.stage_provider, ("zen", "avalai"))
    stage_model = _parse_stage_map(args.stage_model)

    def _leg_provider(leg):
        if leg in stage_prov:
            return stage_prov[leg]
        if leg == "s2" and args.judge_provider == "avalai":
            return "avalai"
        return args.llm_provider

    def _leg_model(leg):
        if leg in stage_model:
            return stage_model[leg]
        if leg == "s2" and args.judge_model:
            return args.judge_model
        if args.precard_model:
            return args.precard_model
        return AVALAI_PRECARD_MODEL

    _injected = {"s0b": _inflect_transport, "s2": _judge_transport,
                 "s3": _topic_transport, "s4": _assign_transport}
    providers = {leg: _leg_provider(leg) for leg in LLM_LEGS}
    models = {leg: _leg_model(leg) for leg in LLM_LEGS}

    def _leg_avalai(leg):
        return providers[leg] == "avalai" \
            and _injected[leg] in (_USE_DEFAULT, None)

    full_avalai = all(_leg_avalai(leg) for leg in LLM_LEGS) and any(
        _injected[leg] is _USE_DEFAULT for leg in LLM_LEGS)
    judge_avalai = _judge_transport is _USE_DEFAULT \
        and providers["s2"] == "avalai"
    # Exact provider manifest: stage -> provider + actual model (telemetry
    # loops record requested Zen names on remap legs, so this file is the
    # disambiguator for cost attribution).
    provider_map = {
        leg: {"provider": providers[leg],
              "model": (models[leg] if providers[leg] == "avalai"
                        else "zen-chain")}
        for leg in LLM_LEGS}
    api_key = "injected"
    api_key_2 = ""
    zen_needed = any(providers[leg] == "zen"
                     and _injected[leg] is _USE_DEFAULT for leg in LLM_LEGS)
    avalai_needed = any(_leg_avalai(leg) for leg in LLM_LEGS)
    if need_llm and zen_needed and not full_avalai:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from env_loader import load_factory_env
        env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
        api_key = env["OPENCODE_ZEN_API_KEY"]
        api_key_2 = env.get("OPENCODE_ZEN_API_KEY_2", "")
        if not api_key:
            raise SystemExit("no OPENCODE_ZEN_API_KEY in factory/.env")
    if full_avalai or not zen_needed:
        # No Zen anywhere (or Zen unused): skip the Zen ring.
        ring = None
    else:
        try:
            ring = KeyRing([api_key, api_key_2])
        except ValueError as exc:
            raise SystemExit("no Zen keys: %s" % exc)
    judge_transport = (_default_judge_transport
                       if _judge_transport is _USE_DEFAULT
                       else _judge_transport)
    judge_models = None
    # AvalAI wiring per leg. S2 gets its own key/ring pair (F1 scoping);
    # S0b/S3/S4 share the leg-keyed pairs below.
    leg_api_key, leg_ring = {}, {}
    judge_api_key, judge_ring = None, None
    # full_avalai/judge_avalai computed above (before key loading).
    precard_model = args.precard_model or AVALAI_PRECARD_MODEL
    if avalai_needed:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from env_loader import load_factory_env
        try:
            env_av = load_factory_env(required=("AVALAI_API_KEY",))
            avalai_key = env_av["AVALAI_API_KEY"]
        except KeyError:
            raise SystemExit("no AVALAI_API_KEY in factory/.env "
                             "(avalai provider needs it)")
        if not avalai_key:
            raise SystemExit("no AVALAI_API_KEY in factory/.env "
                             "(avalai provider needs it)")
        try:
            avalai_ring = KeyRing([avalai_key])
        except ValueError as exc:
            raise SystemExit("no AvalAI keys: %s" % exc)
        for leg in LLM_LEGS:
            if not _leg_avalai(leg):
                continue
            leg_api_key[leg] = avalai_key
            leg_ring[leg] = avalai_ring
        if judge_avalai:
            judge_api_key = avalai_key
            judge_ring = avalai_ring
            judge_transport = _avalai_chat_transport
            judge_models = [models["s2"]]
    if full_avalai:
        api_key, ring = avalai_key, KeyRing([avalai_key])
    topic_transport = assign_transport = inflect_transport = None
    vectors_models_override = [models["s3"]] if _leg_avalai("s3") else None
    # Per-leg remaps (uniform for full and mixed modes, per-leg models).
    # A leg keeps its remap when avalai, else falls back to Zen below.
    for leg in ("s0b", "s3", "s4"):
        if not _leg_avalai(leg):
            continue
        _remap_leg = _avalai_remap_transport(models[leg])
        if leg == "s0b" and _inflect_transport is _USE_DEFAULT:
            inflect_transport = _remap_leg
        elif leg == "s3" and _topic_transport is _USE_DEFAULT:
            topic_transport = _remap_leg
        elif leg == "s4" and _assign_transport is _USE_DEFAULT:
            assign_transport = _remap_leg
    _any_avalai_leg = any(_leg_avalai(leg) for leg in LLM_LEGS)
    if (args.judge_model or args.precard_model or args.stage_model) \
            and _judge_transport is _USE_DEFAULT \
            and not _any_avalai_leg:
        print("warning: model flags apply only with "
              "an avalai provider; ignored on the zen path",
              file=sys.stderr)
    # Defaults for legs the remap loop above did not claim: a leg keeps
    # its remap when avalai, else falls back to the Zen default.
    if _topic_transport is _USE_DEFAULT and topic_transport is None:
        topic_transport = _default_topic_transport
    elif _topic_transport is not _USE_DEFAULT:
        topic_transport = _topic_transport
    if _assign_transport is _USE_DEFAULT and assign_transport is None:
        assign_transport = _default_assign_transport
    elif _assign_transport is not _USE_DEFAULT:
        assign_transport = _assign_transport
    if _inflect_transport is _USE_DEFAULT and inflect_transport is None:
        inflect_transport = _default_inflect_transport
    elif _inflect_transport is not _USE_DEFAULT:
        inflect_transport = _inflect_transport

    label_topup_cache = progress_dir / "s4_topup_cache.json"
    label_calls: dict = {}
    precards: dict = {}
    inflection_dropped: set = set()
    # Provider manifest: exact stage -> provider + actual model for cost
    # attribution (console + run.log + provider_map.json beside --out).
    _prov_line = ", ".join(
        "%s=%s/%s" % (leg, provider_map[leg]["provider"],
                      provider_map[leg]["model"]) for leg in LLM_LEGS)
    print(_color("providers: %s" % _prov_line, "cyan"))
    run_logger.log("providers: %s" % _prov_line)
    try:
        with open(pathlib.Path(args.out).parent / "provider_map.json",
                  "w", encoding="utf-8") as handle:
            handle.write(json.dumps(provider_map, ensure_ascii=False))
    except OSError as exc:
        print("warning: provider_map.json write failed (%s)" % exc)
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
        n_inflection_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s0b", items), start=1):
            batch = items[base:base + BATCH]
            todo = [i for i in batch
                    if item_key(i) not in states["s0b"]["done"]]
            review = []
            for item in todo:
                key = item_key(item)
                try:
                    needs, gloss = inflection_needs_review(
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
                        review, inflect_transport,
                        leg_api_key.get("s0b", api_key),
                        telemetry=tele_store, tele_stage="s0b")
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
                    elif not verdict.get("keep") and base and not verdict.get(
                            "uncertain"):
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
            _batch_progress("s0b", batch_no, n_inflection_batches,
                              len(batch) - failed_here, failed_here)
        run_logger.stage_end(
            "s0b",
            ok=sum(1 for v in states["s0b"]["done"].values()
                   if v.get("kept")),
            fail=len(states["s0b"].get("failed", [])))
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed)
        _stage_summary("s0b", states, args.out)
        inflection_dropped = {k for k, v in states["s0b"]["done"].items()
                       if isinstance(v, dict) and not v.get("kept")}
        items = [i for i in items if item_key(i) not in inflection_dropped]
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
        if inflection_dropped:
            # Details live in dropped.log; console stays one short line.
            print(_color("s0b inflection: kept=%d dropped=%d "
                         "(see dropped.log)" % (len(items),
                                                len(inflection_dropped)),
                         "cyan"))
        # S1 (deterministic, batch-flushed). V7 anchor-POS drop lives ONLY
        # here: when the anchored sense's entry POS is in {name, propn}
        # (card_pilot.PROPER_NOUN_POS, reused by import — deterministic,
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
        run_logger.stage_start("s1")
        n_anchor_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s1", items), start=1):
            batch = items[base:base + BATCH]
            for item in batch:
                key = item_key(item)
                # V7 resume-compat: v6-era s1 entries lack anchor_pos, so
                # they are re-ranked deterministically (same scores plus
                # anchor_pos/drop verdict) instead of skipped. R34 v9
                # extends the compat to the xref fields. F2 extends it to
                # kept name-topped entries (pre-F2 progress never ran the
                # name-gloss verdict); dropped entries are never re-run.
                done_entry = states["s1"]["done"].get(key)
                done_top = ((done_entry.get("top") or {}).get("gloss", "")
                            if isinstance(done_entry, dict) else "")
                needs_name_eval = (
                    isinstance(done_entry, dict)
                    and "dropped" not in done_entry
                    and not done_entry.get("rerouted_from_name")
                    and _is_name_gloss(done_top))
                if not isinstance(done_entry, dict) \
                        or "anchor_pos" not in done_entry \
                        or "anchor_tags" not in done_entry \
                        or "xref_unresolvable" not in done_entry \
                        or needs_name_eval:
                    try:
                        ranked = anchor_rank_item(item, index, read_entry)
                        if (ranked.get("anchor_pos") or "") in \
                                card_pilot.PROPER_NOUN_POS:
                            rerouted = _reroute_proper_anchor(
                                item, ranked, index, read_entry)
                            if rerouted is not None:
                                ranked["top"], ranked["en_def"], \
                                    ranked["anchor_pos"] = rerouted
                                ranked["rerouted_from_proper"] = True
                                print(_color(
                                    "warning: %s re-anchored off proper "
                                    "top -> %s" % (
                                        key,
                                        rerouted[0].get("sense_id", "")),
                                    "yellow"))
                            else:
                                ranked["dropped"] = "anchor-proper-noun"
                                if key not in states["s1"]["failed"]:
                                    states["s1"]["failed"].append(key)
                        elif _is_name_gloss(
                                (ranked.get("top") or {}).get("gloss", "")):
                            # F2: name-gloss top (given/surname/place-name)
                            # with a non-proper entry POS — the gloss-based
                            # sibling of the proper branch above. Reroutes
                            # to the first non-name sense (act-fix
                            # pattern), else drops as anchor-name-gloss.
                            rerouted = _reroute_name_gloss_anchor(
                                item, ranked, index, read_entry)
                            if rerouted is not None:
                                ranked["top"], ranked["en_def"], \
                                    ranked["anchor_pos"] = rerouted
                                ranked["rerouted_from_name"] = True
                                print(_color(
                                    "warning: %s re-anchored off name "
                                    "top -> %s" % (
                                        key,
                                        rerouted[0].get("sense_id", "")),
                                    "yellow"))
                            else:
                                ranked["dropped"] = "anchor-name-gloss"
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
            _batch_progress("s1", batch_no, n_anchor_batches,
                              len(batch) - failed_here, failed_here)
        anchor_dropped = {k for k, v in states["s1"]["done"].items()
                      if isinstance(v, dict) and v.get("dropped")}
        run_logger.stage_end("s1", ok=len(states["s1"]["done"]) - len(
            anchor_dropped), fail=len(anchor_dropped))
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed)
        _stage_summary("s1", states, args.out)
        if anchor_dropped:
            # Details live in dropped.log; console stays one short line.
            print(_color("s1 anchor-pos: kept=%d dropped=%d "
                         "(see dropped.log)" % (
                             len(items) - len(anchor_dropped & {item_key(i)
                                                            for i in items}),
                             len(anchor_dropped & {item_key(i)
                                               for i in items})),
                         "cyan"))
        items = [i for i in items if item_key(i) not in anchor_dropped]
        # S2 (judge batches). ok = judge-model picks in the batch,
        # fail = s1-fallback (fail-closed) picks in the batch.
        run_logger.stage_start("s2")
        n_judge_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s2", items), start=1):
            batch = items[base:base + BATCH]
            todo = [i for i in batch
                    if item_key(i) not in states["s2"]["done"]]
            if todo:
                try:
                    verdicts = judge_batch(
                        todo, states["s1"]["done"],
                        judge_api_key or api_key,
                        judge_transport, sleep_fn, states["s2"],
                        telemetry=tele_store, tele_batch=batch_no,
                        ring=judge_ring or ring, models=judge_models)
                except AuthError:
                    raise
                except RateLimited as exc:
                    _flush(progress_dir, states)
                    tele_flushed = _flush_telemetry(tele_dir, tele_store,
                                                    tele_flushed)
                    hint = ("wait for quota reset then re-run"
                            if (full_avalai or judge_avalai)
                            else "switch VPN server then re-run")
                    raise SystemExit(
                        "STOP s2 at batch %d: %s — progress flushed, "
                        "%s" % (batch_no, exc, hint))
                for item in todo:
                    key = item_key(item)
                    verdict = verdicts.get(key)
                    if verdict is None:
                        verdict = _judge_fallback(
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
            _batch_progress("s2", batch_no, n_judge_batches,
                              len(batch) - fail, fail)
        run_logger.stage_end(
            "s2",
            ok=sum(1 for v in states["s2"]["done"].values()
                   if not (v.get("model", "") or "").startswith("s1-")),
            fail=sum(1 for v in states["s2"]["done"].values()
                     if (v.get("model", "") or "").startswith("s1-")))
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed)
        _stage_summary("s2", states, args.out)
        # Post-S2 proper-noun routing (idempotent pass over the s2 done
        # state — evaluated here, right after S2, so S3+ only ever see
        # routed/kept items; resume-safe via the proper_route/proper_drop
        # markers, flushed when the pass evaluates anything).
        evaluated = 0
        for item in items:
            key = item_key(item)
            entry = states["s2"]["done"].get(key)
            if not isinstance(entry, dict):
                continue
            if "proper_route" in entry and "proper_drop" in entry:
                continue
            verdict = judge_proper_route(
                item, entry, states["s1"]["done"].get(key),
                index, read_entry, zipf_fn)
            entry["proper_route"] = verdict["proper_route"]
            entry["proper_drop"] = verdict["reason"] or ""
            if verdict["reason"] and key not in states["s2"]["failed"]:
                states["s2"]["failed"].append(key)
            evaluated += 1
        if evaluated:
            _flush(progress_dir, states)
        judge_proper_dropped = {
            k for k, v in states["s2"]["done"].items()
            if isinstance(v, dict) and v.get("proper_drop")}
        judge_proper_here = judge_proper_dropped & {item_key(i) for i in items}
        if evaluated or judge_proper_here:
            print("s2 proper-route: routed=%d dropped=%d%s" % (
                sum(1 for i in items
                    if (states["s2"]["done"].get(item_key(i)) or {}).get(
                        "proper_route")),
                len(judge_proper_here),
                " (%s)" % ", ".join(sorted(
                    "%s:%s" % (k, states["s2"]["done"][k].get("proper_drop"))
                    for k in judge_proper_here)) if judge_proper_here else ""))
        items = [i for i in items if item_key(i) not in judge_proper_dropped]
        # S3 (vector batches). ok = model vectors, fail = deterministic
        # (fail-closed) fallbacks.
        run_logger.stage_start("s3")
        n_vectors_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s3", items), start=1):
            batch = items[base:base + BATCH]
            todo = [i for i in batch
                    if item_key(i) not in states["s3"]["done"]]
            if todo:
                try:
                    vecs = vectors_batch(
                        todo, states["s2"]["done"],
                        states["s1"]["done"],
                        leg_api_key.get("s3", api_key),
                        topic_transport, sleep_fn, states["s3"],
                        telemetry=tele_store, tele_batch=batch_no,
                        ring=leg_ring.get("s3", ring),
                        models=vectors_models_override)
                except AuthError:
                    raise
                except RateLimited as exc:
                    _flush(progress_dir, states)
                    tele_flushed = _flush_telemetry(tele_dir, tele_store,
                                                    tele_flushed)
                    raise SystemExit(
                        "STOP s3 at batch %d: %s — progress flushed, "
                        "%s" % (batch_no, exc,
                                "wait for quota reset then re-run"
                                if full_avalai else
                                "switch VPN server then re-run"))
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
            _batch_progress("s3", batch_no, n_vectors_batches,
                              len(batch) - fail, fail)
        run_logger.stage_end(
            "s3",
            ok=sum(1 for v in states["s3"]["done"].values()
                   if v.get("model") != "deterministic"),
            fail=sum(1 for v in states["s3"]["done"].values()
                     if v.get("model") == "deterministic"))
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed)
        _stage_summary("s3", states, args.out)
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
        n_label_batches = (len(items) + BATCH - 1) // BATCH or 1
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
                        assigned = label_item(
                            item, pick.get("gloss", ""),
                            pick.get("sense_id", ""), lookup or None,
                            leg_api_key.get("s4", api_key),
                            assign_transport, sleep_fn,
                            states["s4"], str(label_topup_cache), label_calls,
                            telemetry=tele_store, tele_batch=batch_no,
                            ring=leg_ring.get("s4", ring))
                    except AuthError:
                        raise
                    except RateLimited as exc:
                        _flush(progress_dir, states)
                        tele_flushed = _flush_telemetry(
                            tele_dir, tele_store, tele_flushed)
                        raise SystemExit(
                            "STOP s4 at batch %d: %s — progress flushed, "
                            "%s"
                            % (batch_no, exc,
                               "wait for quota reset then re-run"
                               if full_avalai else
                               "switch VPN server then re-run"))
                    states["s4"]["done"][key] = assigned
            if did_work:
                sleep_fn(SLEEP)
            _flush(progress_dir, states)
            _batch_progress("s4", batch_no, n_label_batches,
                              len(batch), 0)
        run_logger.stage_end("s4", ok=len(states["s4"]["done"]), fail=0)
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed)
        _stage_summary("s4", states, args.out)
        # S5 (deterministic enrichment, batch-flushed). Same as S4: no
        # fail-closed signal, fail is always 0.
        run_logger.stage_start("s5")
        n_enrich_batches = (len(items) + BATCH - 1) // BATCH or 1
        for batch_no, base in enumerate(
                _stage_range(selected, "s5", items), start=1):
            batch = items[base:base + BATCH]
            for item in batch:
                key = item_key(item)
                done = states["s5"]["done"].get(key)
                # C3 resume-compat: pre-C3 s5 entries lack pre_card_id —
                # re-enrich deterministically (no LLM) instead of skipping.
                if not isinstance(done, dict) \
                        or "pre_card_id" not in done:
                    phrase_entry = None
                    if (item.get("kind") or "word") == "phrase" \
                            and type_log_available:
                        phrase_entry = (type_map or {}).get(
                            (item.get("text") or "").strip())
                    states["s5"]["done"][key] = enrich_item(
                        item, states["s2"]["done"].get(key) or {},
                        index, read_entry, tatoeba_pool,
                        phrase_entry=phrase_entry)
            _flush(progress_dir, states)
            _batch_progress("s5", batch_no, n_enrich_batches,
                              len(batch), 0)
        run_logger.stage_end("s5", ok=len(states["s5"]["done"]), fail=0)
        tele_flushed = _flush_telemetry(tele_dir, tele_store, tele_flushed)
        _stage_summary("s5", states, args.out)
        # Assemble output (survivors only; drops live in s0/s1 progress).
        for item in items:
            key = item_key(item)
            enrich = states["s5"]["done"].get(key) or {}
            label = states["s4"]["done"].get(key) or {}
            vec3 = states["s3"]["done"].get(key) or {}
            pick = states["s2"]["done"].get(key) or {}
            preprocess_view = preprocess_info.get(key) or {}
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
                "lexical_type": enrich.get("lexical_type",
                                           LEXICAL_TYPE_DEFAULT),
                "register": enrich.get("register", REGISTER_DEFAULT),
                "pre_card_id": enrich.get("pre_card_id", ""),
                "topic_vector": topic_vector,
                "topic_method": label.get("method")
                or card_pilot.TOPIC_METHOD_TAG,
                "drop_reason": None,
                "stage_calls": {
                    "s0": ("kept:type-pending" if preprocess_view.get("type_pending")
                            else "kept:quarantine-%s" % preprocess_view.get("quarantine")
                            if preprocess_view.get("quarantine") else "kept"),
                    "s0b": (s0b.get("reason", "") or "kept"),
                    "s2": pick.get("model", ""),
                    "s3": vec3.get("model", ""),
                    "s4": label.get("method", ""),
                    "s4_path": label.get("topic_path", ""),
                    "s4_models": dict(label_calls),
                    "s5": enrich.get("enrich_path", "")},
            }
            if preprocess_view.get("type_pending"):
                rec["type_pending"] = True
            if preprocess_view.get("quarantine"):
                # Advisory review flag flows downstream (card stays live;
                # owner filters quarantine=* for the review list).
                rec["quarantine"] = preprocess_view["quarantine"]
            if (pick.get("proper_route") or ""):
                rec["proper_route"] = pick["proper_route"]
            if key not in precards:
                precards[key] = rec
            # else F2: duplicate-redirect loser — first item wins the
            # merged key (last-writer content is silently wrong); the
            # loser is recorded as a duplicate-redirect drop at
            # emission (seen_keys below), never overwriting.
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
    # Atomic write (tmp+os.replace, OC must-fix): a crash mid-write must
    # never truncate precard.jsonl and force a full re-run.
    seen_keys: set = set()
    dup_redirect: list = []
    _tmp = str(out_path) + ".tmp"
    with open(_tmp, "w", encoding="utf-8") as handle:
        for item in items:
            key = item_key(item)
            if key in seen_keys:
                dup_redirect.append("%s(redirected_from=%s)" % (
                    key, item.get("redirected_from", "?")))
                continue
            seen_keys.add(key)
            handle.write(json.dumps(
                precards[key], ensure_ascii=False) + "\n")
    os.replace(_tmp, out_path)
    if dup_redirect:
        print("duplicate-redirect drops (merged into base, FSRS-safe): %s"
              % ", ".join(sorted(set(dup_redirect))))
    # F7 telemetry history: same cumulative seam as card_pilot (imported,
    # never a second copy) so resume runs never erase history — the
    # summary covers ALL runs, not just this one.
    _all_tele, _tele_corrupt = append_telemetry_history(
        out_path.parent, tele_store[tele_flushed:])
    _tele_summary = _tele_write(
        str(out_path.parent / "telemetry_summary.json"), _all_tele)
    if _tele_corrupt:
        _tele_summary["history_corrupt_lines"] = _tele_corrupt
    n_failed = sum(len(states[s].get("failed", [])) for s in STAGES)
    print("precard done: %d items -> %s (s0 dropped=%d, s0b dropped=%d, "
          "s1 dropped=%d, failed flags=%d)"
          % (len(items), out_path, len(states["s0"].get("failed", [])),
             len(inflection_dropped), len(anchor_dropped), n_failed))
    run_logger.log("precard done: %d items s0_dropped=%d s0b_dropped=%d "
                   "s1_dropped=%d failed=%d" % (
                       len(items), len(states["s0"].get("failed", [])),
                       len(inflection_dropped), len(anchor_dropped), n_failed))
    run_logger.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
