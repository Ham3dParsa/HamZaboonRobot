"""Topics (topic_vectors + topic_label stages): vectors, labels, guard.

SOLE owner of the label set inside factory/precard: the live 16 heads,
frozen copy from factory/archive/v14_v16/run_v16b_topup (provenance:
LABELS16, 2026-09-14). The v14-era 13-head names (Society & Culture,
Work & Education) are NOT valid here — the guard below rewired to live
names fixes the invalid-label bug the old home carried.
"""

from __future__ import annotations

import re

from factory.precard.judge import fanout_picks
# P2 (R5): model chains live in factory.precard.net (single owner);
# this leg holds zero model lists and reads chains through it.
from factory.precard import net as _net

LABELS = ["Daily Life & Home", "Food & Drink", "Health & Body",
          "Work & Careers", "Education & Exams", "Travel & Transportation",
          "Society", "Arts & Culture", "Animals & Living Beings",
          "Nature & Environment", "Science & Technology",
          "Business & Economy", "Law & Politics", "Sports & Leisure",
          "Emotions & Relationships", "Other / Abstract"]

# Method tag frozen from factory/pipeline/card_pilot TOPIC_METHOD_TAG
# (provenance: precard line, 2026-09-14).
TOPIC_METHOD = "v16b-exact"

_OTHER_ABSTRACT = "Other / Abstract"
_ANIMALS_LABEL = "Animals & Living Beings"

# (lemma -> [(gloss keyword, concrete live label)]). Fires ONLY when the
# incoming label is Other / Abstract, so a real leg-1/LLM label is never
# overridden.
_ABSTRACT_REANCHOR = {
    "call": [(("telephone", "phone"), "Science & Technology"),
             ((), "Society")],
    "working": [(("employ", "job", "work"), "Work & Careers")],
    "spectacle": [(("perform", "show", "event", "display"), "Society")],
    "accrue": [(("accumulat", "money", "interest", "financ"),
                "Business & Economy")],
    "elevate": [(("lift", "raise"), "Daily Life & Home")],
}

_GENDER_BIO_RX = None
_GENDER_BIO_SRC = (r"\b(biological sex|reproduct|anatom|hormon|"
                   r"menstruat|pregnan)\b")
_GENDER_SIGNAL_RX = None
_GENDER_SIGNAL_SRC = (r"\b(gender|sex|male|female|masculine|feminine|"
                      r"man|men|woman|women)\b")


def _gender_bio_rx():
    """Compiled biological-sex gloss signal (lazy, import-safe)."""
    global _GENDER_BIO_RX
    if _GENDER_BIO_RX is None:
        _GENDER_BIO_RX = re.compile(_GENDER_BIO_SRC, re.IGNORECASE)
    return _GENDER_BIO_RX


def _gender_signal_rx():
    """Compiled sex/gender mention signal (word-boundaried — "manage"
    and "performance" must not match "man")."""
    global _GENDER_SIGNAL_RX
    if _GENDER_SIGNAL_RX is None:
        _GENDER_SIGNAL_RX = re.compile(_GENDER_SIGNAL_SRC, re.IGNORECASE)
    return _GENDER_SIGNAL_RX


def single_topic_vector(label):
    """Single-label fallback: [{label, 1.0}]."""
    return [{"label": label or "Other / Abstract", "weight": 1.0}]


# NOTE (identity-141 R5, deferred to T6): card_pilot.py carries its own
# copy serving the pilot line; this module is canonical for the precard
# line. Unify at T6 pilot versioning.
def topic_post_guard(text, gloss, label):
    """Deterministic topic post-guard (single owner for the precard line).

    Narrow by design — it only ever remaps two failure modes, never a
    real label:
    - gender leak: an Animals & Living Beings label on a sex/gender
      gloss moves to Health & Body (biological cue) or Society
      (social-role default).
    - abstract dumping: an Other / Abstract label on a re-anchored
      (lemma, gloss-keyword) concept moves to its concrete domain.
    Everything else passes through unchanged (fail-closed to the
    incoming label on any hostile input).
    """
    try:
        lab = (label or "").strip()
        lemma = (text or "").strip().lower()
        gloss_l = (gloss or "").lower()
    except Exception:
        return label
    if lab == _ANIMALS_LABEL:
        blob = lemma + " " + gloss_l
        if _gender_signal_rx().search(blob):
            if _gender_bio_rx().search(gloss or ""):
                return "Health & Body"
            return "Society"
        return lab
    if lab == _OTHER_ABSTRACT:
        for keywords, concrete in _ABSTRACT_REANCHOR.get(lemma, []):
            if not keywords or any(k in gloss_l for k in keywords):
                return concrete
    return lab


def apply_topic_guard(row, text, gloss):
    """Remap a label row through topic_post_guard.

    When the guard changes the label, the vector is replaced with the
    single-label fallback (the old vector described the old label).
    Returns the same dict object (mutated); hostile rows pass through.
    """
    try:
        if not isinstance(row, dict):
            return row
        new_label = topic_post_guard(text, gloss, row.get("label"))
        if new_label and new_label != row.get("label"):
            row["label"] = new_label
            row["vector"] = single_topic_vector(new_label)
            row["topic_guarded"] = True
    except Exception:
        pass
    return row


def vectors_pseudo_records(batch, judge_map, anchor_map):
    """Group batch picks into run_v15 pseudo lemma records.

    Every fanned-out pick (primary + judged secondaries) joins the
    pseudo record, so the vectors leg returns a vector per picked sense
    (deduped by sense_id).
    """
    groups = {}
    for item in batch:
        key = (("w:" if item.get("kind") == "word" else "p:")
               + item.get("text", ""))
        pick = (judge_map.get(key) or {})
        lemma = (item.get("text") or "").strip()
        rec = groups.setdefault(
            lemma, {"lemma": lemma, "ranked_senses": []})
        for sub in fanout_picks(item, pick):
            sid = sub.get("sense_id", "")
            if not sid:
                continue
            if all(s["sense_id"] != sid for s in rec["ranked_senses"]):
                gloss = sub.get("gloss", "") or (
                    anchor_map.get(key) or {}).get("en_def", "")
                rec["ranked_senses"].append(
                    {"sense_id": sid, "gloss": gloss,
                     "topic_label": "Other / Abstract"})
    return list(groups.values())


def label_fallback_result(vector_lookup, sense_id):
    """Fail-closed label row (Other / Abstract, dataset vector known)."""
    vec = (vector_lookup or {}).get(sense_id)
    return {"label": "Other / Abstract",
            "method": TOPIC_METHOD,
            "vector": list(vec) if vec
            else single_topic_vector("Other / Abstract"),
            "topic_path": "fallback"}


# ---- T4b: batched legs (moved verbatim, imports rewired) ----

import json
import os
import pathlib
import urllib.error

from factory.core.telemetry import (
    emit_attempt_rows, extract_usage, last_attempt_latency, record_call,
    resolve_cost)
from factory.precard.accounting import item_key
from factory.precard.prompts import TOPIC_TIEBREAK
from factory.precard.transport import (
    AuthError, KeyRing, ProviderCooldown, RateLimited, extract_json,
    raise_for_auth, _tele_tokens, MAX_ATTEMPTS, RETRY_PREFIX)

_tele_record = record_call
_tele_usage = extract_usage



## v15 validation set (frozen from run_v15_topics; validation-internal v13 vocabulary, never emitted).


_V15_PROTO = json.loads((pathlib.Path(__file__).resolve().parent.parent / "packs" / "en" / "topic_prototypes.json").read_text(encoding="utf-8"))


V15_LABELS = _V15_PROTO["labels"]


V15_ID2LABEL = {i + 1: lab for i, lab in enumerate(V15_LABELS)}


V15_LABEL2ID = {lab: i + 1 for i, lab in enumerate(V15_LABELS)}


V15_TOL = 0.01





V15_USER_TMPL = (
    "For EACH sense below, assign 1 to 3 topic labels with weights (numbers 0..1) summing to 1.0. "
    "The CURRENT label is usually the primary topic — keep it first with the largest weight UNLESS "
    "the gloss genuinely spans another topic (e.g. rock music = Society & Culture + Emotions & Relationships; "
    "a flat tire on a trip = Travel & Transportation + Daily Life & Home). "
    "Use 2+ topics only where genuinely mixed; single-topic senses get one entry with weight 1.0. "
    f"Allowed labels with ids (use EXACT strings): {json.dumps(V15_ID2LABEL)}. "
    'Output: {"results": [{"lemma": "...", "vectors": [{"sense_id": "<exact sense id>", '
    '"vector": [{"topic_id": N, "topic_label": "<exact allowed label>", "weight": w}]}]}]}. '
    "Cover EVERY sense id from the input exactly once. Weights must sum to 1.0 (±0.01). "
    "Input follows:\n")


def validate_vectors(vecs, r):
    """Returns (ok, normalized_vecs). Renormalizes weights within tolerance."""
    if not isinstance(vecs, list):
        return False, None
    input_ids = [s["sense_id"] for s in r["ranked_senses"]]
    if sorted(v.get("sense_id") for v in vecs if isinstance(v, dict)) != sorted(input_ids):
        return False, None
    if len(vecs) != len(input_ids):
        return False, None
    normed = []
    for v in vecs:
        entries = v.get("vector")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 3:
            return False, None
        total = 0.0
        for e in entries:
            if not isinstance(e, dict):
                return False, None
            tid = e.get("topic_id")
            lab = e.get("topic_label")
            if not isinstance(tid, int) or tid not in V15_ID2LABEL or V15_ID2LABEL[tid] != lab:
                return False, None
            try:
                w = float(e.get("weight"))
            except (TypeError, ValueError):
                return False, None
            if not 0.0 < w <= 1.0:
                return False, None
            total += w
        if abs(total - 1.0) > V15_TOL:
            return False, None
        fixed = [{"topic_id": e["topic_id"], "topic_label": e["topic_label"],
                  "weight": round(float(e["weight"]) / total, 4)} for e in entries]
        normed.append({"sense_id": v["sense_id"], "vector": fixed, "source": "judge"})
    return True, normed


def fallback_vectors(r):
    vecs = []
    for s in r["ranked_senses"]:
        lab = s.get("topic_label", "Other / Abstract")
        vecs.append({"sense_id": s["sense_id"],
                     "vector": [{"topic_id": V15_LABEL2ID[lab], "topic_label": lab, "weight": 1.0}],
                     "source": "deterministic"})
    return vecs


def v15_lemma_block(r):
    lines = [f"LEMMA {r['lemma']}:"]
    for s in r["ranked_senses"]:
        lab = s.get("topic_label", "Other / Abstract")
        lines.append(f"- {s['sense_id']} [current: {lab}] {s.get('gloss', '')[:200]}")
    return "\n".join(lines)


## v16b validation set (frozen from run_v16b_topup; LABELS16 rewired to the live registry).


V16B_ID2LABEL = {i + 1: lab for i, lab in enumerate(LABELS)}


V16B_LABEL2ID = {lab: i + 1 for i, lab in enumerate(LABELS)}


V16B_TOL = 0.01


V16B_DEFS = ("1 Daily Life & Home: everyday routines, household, clothing, time. "
        "2 Food & Drink: eating, cooking, food/drink items and the act of eating. "
        "3 Health & Body: body parts, illness, medicine, hygiene. "
        "4 Work & Careers: jobs, offices, meetings, professional life. "
        "5 Education & Exams: school, study, exams, learning. "
        "6 Travel & Transportation: trips, vehicles, directions, movement. "
        "7 Society: community, traditions, social life, public affairs. "
        "8 Arts & Culture: art, film, music, literature. "
        "9 Animals & Living Beings: animals and living creatures, even if edible. "
        "10 Nature & Environment: plants, earth, air, water, weather, landscapes. "
        "11 Science & Technology: science, computers, devices, inventions. "
        "12 Business & Economy: money, trade, markets, finance. "
        "13 Law & Politics: rules, government, crime, rights. "
        "14 Sports & Leisure: games, sports, hobbies, free-time fun. "
        "15 Emotions & Relationships: feelings, family, friendship, love. "
        "16 Other / Abstract: abstract, grammatical, or unclassifiable meanings.")





TOPUP_USER_TMPL = (
    "For EACH sense below, pick ONE primary topic label (id 1..16) AND a weight vector of 1 to 3 "
    "labels (weights 0..1, summing to 1.0). The vector's top entry must be the primary label. "
    "TIE-BREAK & DOMAIN MAPPING (apply strictly): "
    "colors and visual themes (e.g. pink, reddish, bright) "
    "-> Arts & Culture (0.60) + Daily Life & Home (0.40); do NOT leave color terms "
    "as purely abstract. Other physical or sensory attributes (e.g. shallow, dirty, "
    "smooth) belong to their natural domain (Nature & Environment, Daily Life & Home). "
    "Functional, purely quantitative, or directional dimensions (e.g. low, high, once, few) "
    "-> Other / Abstract (1.00); use Travel & Transportation (1.00) only if navigational. "
    "Non-human animals & wildlife -> Animals & Living Beings even if edible "
    "(a swimming fish = Animals, a fish on the table = Food & Drink). "
    "Humans, family, and person nouns stay under Society or Emotions & Relationships. "
    "Eating, cooking, or food acts -> Food & Drink. "
    "Workplace, professions, and office activities -> Work & Careers. "
    "Art, film, music, literature -> Arts & Culture. "
    "Strictly abstract logic, function words, and grammatical operators with no topical anchor "
    "(e.g. about, always, anything, both, each, would, by) -> Other / Abstract (1.00). "
    "MULTI-TOPIC GUIDELINE: use 2 to 3 labels with weights summing to 1.0 whenever a sense "
    "genuinely spans multiple domains. Distribute weights proportionally (e.g. 0.60/0.40 or "
    "0.50/0.50) rather than forcing 1.00 into a single bucket. "
    f"Labels (use EXACT strings, id = position): {V16B_DEFS} "
    f"Id map: {json.dumps(V16B_ID2LABEL)}. "
    'Output: {"results": [{"lemma": "...", "senses": [{"sense_id": "<exact sense id>", '
    '"topic_id": N, "topic_label": "<exact label>", "confidence": 0..1, '
    '"vector": [{"topic_id": N, "topic_label": "<exact label>", "weight": w}]}]}]}. '
    "Cover EVERY sense id from the input exactly once. Weights must sum to 1.0 (+-0.01). "
    "Input follows:\n")


def validate_senses(items, want_ids):
    if not isinstance(items, list):
        return False, None
    if sorted(x.get("sense_id") for x in items if isinstance(x, dict)) != sorted(want_ids):
        return False, None
    if len(items) != len(want_ids):
        return False, None
    normed = []
    for x in items:
        tid, lab = x.get("topic_id"), x.get("topic_label")
        if not isinstance(tid, int) or tid not in V16B_ID2LABEL or V16B_ID2LABEL[tid] != lab:
            return False, None
        try:
            conf = float(x.get("confidence"))
        except (TypeError, ValueError):
            return False, None
        if not 0.0 <= conf <= 1.0:
            return False, None
        entries = x.get("vector")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 3:
            return False, None
        total = 0.0
        for e in entries:
            if not isinstance(e, dict):
                return False, None
            et, el = e.get("topic_id"), e.get("topic_label")
            if not isinstance(et, int) or et not in V16B_ID2LABEL or V16B_ID2LABEL[et] != el:
                return False, None
            try:
                w = float(e.get("weight"))
            except (TypeError, ValueError):
                return False, None
            if not 0.0 < w <= 1.0:
                return False, None
            total += w
        if abs(total - 1.0) > V16B_TOL:
            return False, None
        fixed = sorted(
            ({"topic_id": e["topic_id"], "topic_label": e["topic_label"],
              "weight": round(float(e["weight"]) / total, 4)} for e in entries),
            key=lambda d: -d["weight"])
        normed.append({"sense_id": x["sense_id"], "topic_id": fixed[0]["topic_id"],
                       "topic_label": fixed[0]["topic_label"], "confidence": conf,
                       "vector": fixed, "source": "judge"})
    return True, normed


def topup_lemma_block(lemma, senses):
    lines = [f"LEMMA {lemma}:"]
    for s in senses:
        lines.append(f"- {s['sense_id']} {s.get('gloss', '')[:200]}")
    return "\n".join(lines)


## v16 deterministic leg (frozen from run_v16_topics).


MIGRATE_DEFAULT = {
    "Daily Life & Home": "Daily Life & Home",
    "Food & Drink": "Food & Drink",
    "Health & Body": "Health & Body",
    "Work & Education": None,  # split: see MIGRATION rule
    "Travel & Transportation": "Travel & Transportation",
    "Society & Culture": None,  # split: see MIGRATION rule
    "Nature & Environment": None,  # split: see MIGRATION rule
    "Science & Technology": "Science & Technology",
    "Business & Economy": "Business & Economy",
    "Law & Politics": "Law & Politics",
    "Sports & Leisure": "Sports & Leisure",
    "Emotions & Relationships": "Emotions & Relationships",
    "Other / Abstract": "Other / Abstract",
}


_EVP_BY_LEMMA = {}
_evp = json.loads((pathlib.Path(__file__).resolve().parent.parent
    / "packs" / "en" / "evp_sense.json").read_text(
    encoding="utf-8"))["entries"]
for _k, _v in _evp.items():
    _lem = _k.split("|")[0].lower()
    _EVP_BY_LEMMA.setdefault(_lem, []).append((_k, _v))


def evp_fallback_label(lemma, gloss):
    """Deterministic evp-domain single: entry of this lemma whose guideword occurs in gloss,
    mapped to 16 labels; else None (= caller falls back to Other)."""
    cands = _EVP_BY_LEMMA.get(lemma.lower(), [])
    gl = (gloss or "").lower()
    for _k, _v in cands:
        gw = (_v.get("guideword") or "").lower().replace("_", " ")
        dom = _v.get("domain", "Other / Abstract")
        if dom == "Other / Abstract":
            continue
        # Word-boundary match: raw substring lets guideword "art" hit "heart".
        if gw and re.search(r"\b" + re.escape(gw) + r"\b", gl):
            new = MIGRATE_DEFAULT.get(dom)
            if new:
                return new
    for _k, _v in cands:  # any non-Other domain entry, first hit
        dom = _v.get("domain", "Other / Abstract")
        if dom != "Other / Abstract":
            new = MIGRATE_DEFAULT.get(dom)
            if new:
                return new
    return None


LABEL_BATCH = 16


def _label_prompt(entries):
    """Batched label prompt: TOPUP template + one block per entry.

    The v14.1 tie-break addendum rides AFTER the lemma blocks (the
    head-frozen layout stays byte-identical across batches).
    """
    return TOPUP_USER_TMPL + "\n\n".join(
        topup_lemma_block(e["text"], [{"sense_id": e["sense_id"],
                                  "gloss": e.get("gloss") or ""}])
        for e in entries) + "\n\n" + TOPIC_TIEBREAK


def _label_chunk_via_llm(entries, api_key, transport, sleep_fn, state,
                           model_calls, telemetry, tele_stage, tele_batch,
                           ring, models, provider="zen", key_var="",
                           file_label="factory/.env", tele_run_id="",
                           tele_model_actual=None, tele_attempts=False,
                           tried=None, rings=None):
    """One batched LLM top-up call for up to LABEL_BATCH entries.

    Returns {item-key: {"label", "vector", "model"}}. Validated items
    are salvaged per item (a malformed row fails closed only its own
    item — never the whole chunk); unvalidated keys are absent (caller
    fails them closed) and None means nothing validated. Auth (401/403)
    raises loud; all-keys-429 raises RateLimited via _call_with_rotation
    (caller flushes progress and STOPS). Import failure fails closed
    (fallback telemetry + None — never a stage crash). Other errors
    fall through to the next attempt, then to None.
    """
    try:
        prompt = _label_prompt(entries)
    except Exception:
        if telemetry is not None:
            record_call(telemetry, stage=tele_stage, batch_id=tele_batch,
                         key_idx=0, model="deterministic", latency_s=0.0,
                         outcome="fallback", run_id=tele_run_id,
                         provider="", model_actual="deterministic",
                         cost=resolve_cost(made_call=False))
        return None
    # P2: default chain from the net table (zen topic-label five);
    # explicit models (e.g. avalai/google single-model legs) win.
    base_models = list(models) if models else None
    if ring is None:
        ring = KeyRing([api_key])
    best = {}
    best_model = "deterministic"
    attempt_rows = []
    # R6 provider loop (same rule as the other legs): free legs may
    # continue on the next switch_plan provider after a cooldown
    # (that provider's own ring); providers without a ring are not
    # attempted. Explicit models only ever run on the base provider.
    base_provider = _net.norm_provider(provider) or "zen"
    ordered = [p for p in _net.switch_plan(provider, "topic_label")
               if p == base_provider
               or (rings is not None and p in rings)]
    limited_all = True  # cleared by any model that is not ROTATE-exhausted
    n_tried = 0
    cool_exc = None
    best_eff = base_provider

    def _attempts(eff):
        if tele_attempts and telemetry is not None:
            emit_attempt_rows(telemetry, attempt_rows, stage=tele_stage,
                              batch_id=tele_batch, run_id=tele_run_id,
                              provider=eff,
                              model_actual=tele_model_actual)

    for eff_idx, eff in enumerate(ordered):
        eff_models = (list(base_models)
                      if base_models is not None and eff == base_provider
                      else _net.leg_chain(eff, "topic_label"))
        eff_ring = (rings or {}).get(eff) or ring
        eff_target = _net.target_for(eff)
        eff_key_var = key_var if eff == base_provider else ""
        eff_cooled = False
        for model in eff_models:
            if isinstance(tried, list) and model not in tried:
                tried.append(model)
            n_tried += 1
            if model_calls is not None:
                model_calls[model] = model_calls.get(model, 0) + 1
            for attempt in range(MAX_ATTEMPTS):
                text = prompt if attempt == 0 else RETRY_PREFIX + prompt
                label = "%s/s4-label#%d" % (model, attempt)
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
                    # chain (same chunk, that provider's ring); paid
                    # legs and the last provider STOP loud for a
                    # resume.
                    attempt_rows.extend(list(
                        getattr(eff_ring, "attempt_log", []) or []))
                    if telemetry is not None:
                        record_call(telemetry, stage=tele_stage,
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
                        record_call(telemetry, stage=tele_stage,
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
                    # model in the same leg's chain (the caller still
                    # flushes+STOPS when the whole chain is exhausted).
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
                    by_lemma = {x.get("lemma"): x for x in
                                (data.get("results") or [])
                                if isinstance(x, dict)} \
                        if isinstance(data, dict) else {}
                    rows = [x for x in (data.get("results") or [])
                            if isinstance(x, dict)] \
                        if isinstance(data, dict) else []
                    # Match rows by sense_id (not by lemma dict — two
                    # items may share a lemma text, e.g. word+phrase;
                    # a lemma-keyed map would collapse them and fail
                    # the chunk).
                    used = set()
                    merged = {}
                    for entry in entries:
                        senses = None
                        for idx, row in enumerate(rows):
                            if idx in used:
                                continue
                            have = {s.get("sense_id") for s in
                                    ((row.get("senses") or [])
                                     if isinstance(row.get("senses"), list)
                                     else []) if isinstance(s, dict)}
                            if entry["sense_id"] in have:
                                senses = row.get("senses")
                                used.add(idx)
                                break
                        if senses is None:
                            senses = (by_lemma.get(entry["text"]) or {}).get(
                                "senses")
                        try:
                            good, normed = validate_senses(
                                senses, [entry["sense_id"]])
                        except Exception:
                            good, normed = False, None
                        if not good or not normed:
                            continue
                        found = normed[0].get("topic_label") \
                            or "Other / Abstract"
                        vec = [{"label": e.get("topic_label"),
                                "weight": round(float(e.get("weight")), 4)}
                               for e in (normed[0].get("vector") or [])
                               if isinstance(e, dict)
                               and e.get("topic_label")] or \
                            single_topic_vector(found)
                        # Keyed by item key (not sense_id — duplicate
                        # texts share sense_id shapes but never item
                        # keys).
                        merged[entry["key"]] = (found, vec)
                    if len(merged) > len(best):
                        best = dict(merged)
                        best_model = model
                        best_eff = eff
                    if len(merged) == len(entries):
                        if telemetry is not None:
                            prompt_tokens, completion_tokens = _tele_tokens(
                                usage)
                            last = getattr(eff_ring, "last_call", None) or {}
                            record_call(
                                telemetry, stage=tele_stage,
                                batch_id=tele_batch,
                                key_idx=last.get("key_idx", eff_ring.idx),
                                model=model,
                                latency_s=last.get("latency_s", 0.0),
                                outcome="ok",
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                run_id=tele_run_id,
                                provider=eff,
                                model_actual=(
                                    tele_model_actual or model),
                                cost=resolve_cost(
                                    prompt_tokens=prompt_tokens,
                                    completion_tokens=completion_tokens))
                        _attempts(eff)
                        return {k: {"label": lab, "vector": vec,
                                    "model": model}
                                for k, (lab, vec) in merged.items()}
                except AuthError:
                    raise
                except Exception:
                    continue
            if eff_cooled:
                break
        if eff_cooled:
            # R6: a free-leg cooldown moves to the next provider's
            # chain (same chunk, that provider's ring); the last —
            # or any paid — provider stops loud for a resume.
            if eff_idx + 1 < len(ordered):
                continue
            raise cool_exc
    if limited_all and n_tried:
        # P2 (R6): the whole chain ROTATE-exhausted — STOP loud (the
        # caller flushes progress). Per-model error records exist.
        _attempts(base_provider)
        raise RateLimited(
            "all topic_label models 429 (provider quotas exhausted) — "
            "re-run later (progress flushed, resume safe)")
    if best:
        if telemetry is not None:
            record_call(telemetry, stage=tele_stage, batch_id=tele_batch,
                         key_idx=ring.idx, model=best_model,
                         latency_s=last_attempt_latency(attempt_rows),
                         outcome="ok", run_id=tele_run_id,
                         provider=best_eff,
                         model_actual=tele_model_actual or best_model,
                         cost=resolve_cost(made_call=True))
        _attempts(best_eff)
        return {k: {"label": lab, "vector": vec, "model": best_model}
                for k, (lab, vec) in best.items()}
    if telemetry is not None:
        record_call(telemetry, stage=tele_stage, batch_id=tele_batch,
                     key_idx=ring.idx, model="deterministic",
                     latency_s=last_attempt_latency(attempt_rows),
                     outcome="fallback", run_id=tele_run_id,
                     provider=base_provider,
                     model_actual=tele_model_actual or "deterministic",
                     cost=resolve_cost(made_call=True))
    _attempts(base_provider)
    return None


def label_batch(batch, picks, vector_lookups, api_key, transport,
                sleep_fn, state, progress_path, model_calls,
                telemetry=None, tele_stage="s4", tele_batch=0,
                 ring=None, models=None, lookup=None,
                 provider="zen", key_var="",
                 file_label="factory/.env", tele_run_id="",
                  tele_model_actual=None, tele_attempts=False,
                 counters=None, tried=None, rings=None):
    """Label topics (s4) for one batch, batching the LLM leg (B1).

    batch: sample items; picks: {key: {sense_id, gloss, picks?}};
    vector_lookups: {key: {sense_id: vector}} (S3 vectors, optional).
    Leg 1 (deterministic v16, injectable `lookup` for hermetic tests)
    and the file cache resolve per item with zero LLM; the remaining
    items share one LLM call per LABEL_BATCH chunk. v14.1: judged
    secondary picks resolve through the same legs and ride on the
    primary row as "extra": [{sense_id, gloss, label, vector, method,
    topic_path}] — one row per fanned-out sense, each with its own
    topic vector. Returns {key: assign_topic-shaped row}. transport=None
    skips the LLM leg (all remaining fall back, stated). RateLimited/
    AuthError propagate (caller flushes + stops/aborts); anything else
    fails closed per item to Other / Abstract. Deterministic/cache
    resolutions record cost="none" (no call happened); ``counters``
    (optional {"hit","miss"} dict) is bumped hit = no-LLM resolution,
    miss = LLM consulted, feeding the bar v2 HIT/MISS counters.
    """
    if ring is None:
        ring = KeyRing([api_key])

    def _bump(hit):
        try:
            if isinstance(counters, dict):
                counters["hit" if hit else "miss"] = \
                    counters.get("hit" if hit else "miss", 0) + 1
        except Exception:
            pass
    if lookup is None:
        lookup = _label_leg1_lookup()
    cache = _label_read_cache(progress_path)
    prog_path = pathlib.Path(progress_path) if progress_path else None
    out = {}
    pending = []
    # v14.1 fan-out expansion: one resolution entry per picked sense.
    # Primary entries keep the item key (existing shape); secondaries
    # carry composite keys folded back into "extra" after the chunk
    # resolves (the chunk matcher keys on sense_id, never on key).
    expanded = []
    for item in batch:
        key = item_key(item)
        pick = (picks or {}).get(key) or {}
        text = item.get("text", "")
        vector_lookup = (vector_lookups or {}).get(key)
        subs = fanout_picks(item, pick) or [
            {"sense_id": "", "gloss": ""}]
        for pos, sub in enumerate(subs):
            gloss = sub.get("gloss", "")
            # Same default as card_pilot.assign_topic (text#0): an empty
            # pick still labels under a well-formed sense id in the LLM
            # block.
            sense_id = sub.get("sense_id", "") or (
                "%s#0" % (text or "").strip().lower())
            expanded.append({"key": key if pos == 0 else "%s\x1fs4x\x1f%s"
                             % (key, sense_id),
                             "item_key": key, "primary": pos == 0,
                             "text": text, "gloss": gloss,
                             "sense_id": sense_id,
                             "vector_lookup": vector_lookup})
    for entry in expanded:
        key, text = entry["item_key"], entry["text"]
        gloss, sense_id = entry["gloss"], entry["sense_id"]
        vector_lookup = entry["vector_lookup"]
        label = None
        if lookup is not None:
            try:
                label = lookup(text, gloss or "")
            except Exception:
                label = None
        if label:
            vec = (vector_lookup or {}).get(sense_id)
            if telemetry is not None:
                record_call(telemetry, stage=tele_stage,
                             batch_id=tele_batch, key_idx=0,
                             model="deterministic", latency_s=0.0,
                             outcome="ok", run_id=tele_run_id,
                             provider="", model_actual="deterministic",
                             cost=resolve_cost(made_call=False))
            _bump(True)
            entry["resolved"] = apply_topic_guard(
                {"label": label,
                 "method": TOPIC_METHOD,
                 "vector": list(vec) if vec
                 else single_topic_vector(label),
                 "topic_path": "leg1"}, text, gloss)
            continue
        hit = _label_cache_hit(cache, text, gloss, sense_id,
                               vector_lookup)
        if hit is not None:
            if telemetry is not None:
                record_call(telemetry, stage=tele_stage,
                             batch_id=tele_batch, key_idx=0,
                             model="deterministic", latency_s=0.0,
                             outcome="ok", run_id=tele_run_id,
                             provider="", model_actual="deterministic",
                             cost=resolve_cost(made_call=False))
            _bump(True)
            try:
                if isinstance(counters, dict):
                    counters["cache"] = counters.get("cache", 0) + 1
            except Exception:
                pass
            entry["resolved"] = apply_topic_guard(
                hit, text, gloss)
            continue
        pending.append(entry)
    for chunk_no in range(0, len(pending), LABEL_BATCH):
        chunk = pending[chunk_no:chunk_no + LABEL_BATCH]
        resolved = None
        if transport is not None:
            resolved = _label_chunk_via_llm(
                chunk, api_key, transport, sleep_fn, state, model_calls,
                telemetry, tele_stage, tele_batch, ring, models,
                provider=provider, key_var=key_var,
                file_label=file_label, tele_run_id=tele_run_id,
                tele_model_actual=tele_model_actual,
                tele_attempts=tele_attempts, tried=tried, rings=rings)
        for entry in chunk:
            # The chunk consulted the LLM (or fell back after trying):
            # a miss per entry; transport=None resolves with no call.
            _bump(transport is None)
            ekey, sense_id = entry["key"], entry["sense_id"]
            if resolved is not None and ekey in resolved:
                got = resolved[ekey]
                entry["resolved"] = apply_topic_guard(
                    {"label": got["label"],
                     "method": TOPIC_METHOD,
                     "vector": got["vector"], "topic_path": "llm"},
                    entry["text"], entry["gloss"])
                if isinstance(cache, dict):
                    cache["%s\t%s\t%s" % (
                        entry["text"], entry["gloss"] or "",
                        sense_id)] = {"label": got["label"],
                                      "vector": got["vector"]}
            else:
                entry["resolved"] = apply_topic_guard(
                    label_fallback_result(entry["vector_lookup"],
                                           sense_id),
                    entry["text"], entry["gloss"])
        # One atomic cache write per chunk (tmp + rename — a crash
        # mid-write never truncates the resume cache).
        if isinstance(cache, dict) and prog_path is not None and \
                resolved:
            try:
                tmp = str(prog_path) + ".tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(cache, ensure_ascii=False))
                os.replace(tmp, prog_path)
            except Exception:
                pass
    # v14.1 fold-back: primaries keep the {key: row} shape; secondaries
    # collect under the primary row's additive "extra" list (empty when
    # the judge picked a single sense — existing shape unchanged).
    for entry in expanded:
        row = entry.get("resolved")
        if not isinstance(row, dict) or not row.get("label"):
            row = apply_topic_guard(
                label_fallback_result(entry["vector_lookup"],
                                       entry["sense_id"]),
                entry["text"], entry["gloss"])
        if entry["primary"]:
            out[entry["item_key"]] = row
        else:
            primary = out.setdefault(entry["item_key"], None)
            if primary is None:
                out[entry["item_key"]] = row
            else:
                extra = primary.setdefault("extra", [])
                if all(e.get("sense_id") != entry["sense_id"]
                       for e in extra):
                    extra.append({"sense_id": entry["sense_id"],
                                  "gloss": entry["gloss"],
                                  "label": row.get("label"),
                                  "vector": row.get("vector"),
                                  "method": row.get("method"),
                                  "topic_path": row.get("topic_path")})
    return out


def _label_leg1_lookup():
    """Deterministic v16 lookup (vendored evp_fallback_label)."""
    return evp_fallback_label


def _label_read_cache(progress_path):
    """S4 top-up file cache ({cache_key: {label, vector}}) or {}."""
    if not progress_path:
        return {}
    try:
        cache = json.loads(pathlib.Path(progress_path).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cache if isinstance(cache, dict) else {}


def _label_cache_hit(cache, text, gloss, sense_id, vector_lookup):
    """Cached S4 row for one item (None on miss)."""
    key = "%s\t%s\t%s" % (text, gloss or "", sense_id)
    if not isinstance(cache, dict) or key not in cache:
        return None
    cached = cache[key]
    if isinstance(cached, dict) and cached.get("label"):
        vec = cached.get("vector") or (vector_lookup or {}).get(sense_id)
        return {"label": cached["label"],
                "method": TOPIC_METHOD,
                "vector": list(vec) if vec
                else single_topic_vector(cached["label"]),
                "topic_path": "cache"}
    label = cached if isinstance(cached, str) else "Other / Abstract"
    vec = list((vector_lookup or {}).get(sense_id) or []) or \
        single_topic_vector(label)
    return {"label": label, "method": TOPIC_METHOD,
            "vector": vec, "topic_path": "cache"}


def label_item(item, gloss, sense_id, vector_lookup, api_key, transport,
                   sleep_fn, state, progress_path, model_calls,
                   telemetry=None, tele_stage="s4", tele_batch=0,
                   ring=None, provider="zen", key_var="",
                   file_label="factory/.env", tele_run_id="",
                   tele_model_actual=None, tele_attempts=False,
                   counters=None, rings=None):
    """Label topic (s4) for one item via the batched path (B1).

    Thin single-item wrapper over label_batch (no second code path):
    same leg-1/cache/LLM/fallback semantics, same AuthError/RateLimited
    propagation (caller flushes + stops/aborts), fail-closed to
    Other / Abstract on anything else.
    """
    if ring is None:
        ring = KeyRing([api_key])
    key = item_key(item)
    try:
        out = label_batch(
            [item], {key: {"sense_id": sense_id, "gloss": gloss or ""}},
            {key: vector_lookup} if vector_lookup else None,
            api_key, transport, sleep_fn, state, progress_path,
            model_calls, telemetry=telemetry, tele_stage=tele_stage,
            tele_batch=tele_batch, ring=ring,
            provider=provider, key_var=key_var,
            file_label=file_label, tele_run_id=tele_run_id,
            tele_model_actual=tele_model_actual,
            tele_attempts=tele_attempts, counters=counters, rings=rings)
    except AuthError:
        raise
    except RateLimited:
        raise
    except Exception:
        return {"label": "Other / Abstract",
                "method": TOPIC_METHOD,
                "vector": single_topic_vector(
                    "Other / Abstract"),
                "topic_path": "fallback"}
    got = out.get(key)
    if not isinstance(got, dict) or not got.get("label"):
        return {"label": "Other / Abstract",
                "method": TOPIC_METHOD,
                "vector": single_topic_vector(
                    "Other / Abstract"),
                "topic_path": "fallback"}
    return got


def _needs_fanout_relabel(s4_entry, s2_entry):
    """True when an s4 row predates the v14.1 fan-out (R1 resume-compat).

    Pre-fan-out s4 rows carry no "extra" list; when the s2 entry holds
    more than one judged pick the secondaries still need labels, so the
    item rejoins todo (deterministic re-resolution, same legs — the
    primary row resolves identically, extras are additive). Single-pick
    items and complete rows never re-run.
    """
    try:
        if not isinstance(s4_entry, dict) or not isinstance(s2_entry, dict):
            return False
        if "extra" in s4_entry:
            return False
        return len(fanout_picks({}, s2_entry)) > 1
    except Exception:
        return False


def vectors_batch(batch, judge_map, anchor_map, api_key, transport, sleep_fn,
                    state, telemetry=None, tele_stage="s3", tele_batch=0,
                    ring=None, models=None, provider="zen", key_var="",
                    file_label="factory/.env", tele_run_id="",
                    tele_model_actual=None, tele_attempts=False,
                    tried=None, rings=None):
    """Topic vectors for one batch via the run_v15 path (imported).

    Returns {sense_id: {"vector": [{label, weight}...], "model": ...}}.
    Empty-pick items are absent (caller maps them to the single Other
    fallback). Total failure fails closed per lemma to fallback_vectors.
    429 rotates the KeyRing (brief pause, same-call retry; a
    ROTATE-exhausted model steps down to the next chain model and only
    a fully-exhausted chain raises RateLimited so the runner flushes
    and STOPS); a free leg cooled at project level continues on the
    next switch_plan provider's chain with that provider's own ring
    (R6).
    R27: one telemetry record per batch (ok / fallback / error); tuple
    (text, usage) transports surface token counts (None-tolerated,
    cost-unknown flagged). Terminal records carry the REAL perf_counter
    latency and REAL ring.idx, model vs model_actual, provider, run_id;
    per-try attempt rows only when ``tele_attempts`` is on.
    """
    # P2: default chain from the net table (zen vectors five);
    # explicit models (e.g. avalai/google single-model legs) win.
    base_models = list(models) if models else None
    pseudos = vectors_pseudo_records(batch, judge_map, anchor_map)
    out = {}
    if not pseudos:
        return out
    prompt = V15_USER_TMPL + "\n\n".join(v15_lemma_block(r) for r in pseudos)
    if ring is None:
        ring = KeyRing([api_key])
    attempt_rows = []
    # R6 provider loop (same rule as the other legs): free legs may
    # continue on the next switch_plan provider after a cooldown
    # (that provider's own ring); providers without a ring are not
    # attempted. Explicit models only ever run on the base provider.
    base_provider = _net.norm_provider(provider) or "zen"
    ordered = [p for p in _net.switch_plan(provider, "topic_vectors")
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
                      else _net.leg_chain(eff, "topic_vectors"))
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
                label = "%s/v15#%d" % (model, attempt)
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
                        record_call(telemetry, stage=tele_stage,
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
                        record_call(telemetry, stage=tele_stage,
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
                    # model in the same leg's chain (the caller still
                    # flushes+STOPS when the whole chain is exhausted).
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
                by_lemma = {x.get("lemma"): x for x in
                            (data.get("results") or [])
                            if isinstance(x, dict)} \
                    if isinstance(data, dict) else {}
                ok_all, merged = True, {}
                for pseudo in pseudos:
                    vecs = (by_lemma.get(pseudo["lemma"]) or {}).get(
                        "vectors")
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
                                        "weight": round(
                                            float(e["weight"]), 4)}
                                       for e in entry["vector"]],
                            "model": model}
                if ok_all:
                    if telemetry is not None:
                        prompt_tokens, completion_tokens = _tele_tokens(
                            usage)
                        last = getattr(eff_ring, "last_call", None) or {}
                        record_call(
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
                    return merged
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
        # caller flushes progress). Per-model error records exist.
        _attempts(base_provider)
        raise RateLimited(
            "all topic_vectors models 429 (provider quotas exhausted) "
            "— re-run later (progress flushed, resume safe)")
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
        record_call(telemetry, stage=tele_stage, batch_id=tele_batch,
                     key_idx=ring.idx, model="deterministic",
                     latency_s=last_attempt_latency(attempt_rows),
                     outcome="fallback", run_id=tele_run_id,
                     provider=base_provider,
                     model_actual=tele_model_actual or "deterministic",
                     cost=resolve_cost(made_call=True))
    _attempts(base_provider)
    return out
