"""Anchor + preprocess (anchor_rank + preprocess stages).

Scorer chain vendored frozen from factory/pipeline/card_pilot
(provenance: vendored-v14 scorer, precard line R1-R6, 2026-09-14);
preprocess gates + anchor rank + reroutes moved verbatim from
factory/pipeline/precard_pipeline. Parity with the old home is pinned
by tests/factory/test_precard_anchor.py.
"""

from __future__ import annotations

import json
import re

from factory.precard.accounting import item_key

ANCHOR_STAGES = ("preprocess", "anchor_rank")


ALSO_TOPIC_UNASSIGNED = "unassigned-cheap-only"


CANDIDATE_BUCKET_A1A2 = 6


CANDIDATE_BUCKET_UPPER = 10


FREQ_TIE_EPS = 0.05


IPA_SRC_DATASET = "dataset"


IPA_SRC_MODEL = "model"


JUDGE_WINDOW_CAP = 10


PROPER_NOUN_POS = {"name", "propn"}

# Frozen from factory/pipeline/card_pilot (provenance: precard line,
# 2026-09-14).
VULGAR_TAGS = {"vulgar", "offensive", "derogatory", "obscene", "profane",
               "ethnic-slur", "slur"}


REGISTER_META_RX = re.compile(r"^senses relating to\b")


XREF_METHOD_TAG = "xref-resolved"


_ABBREV_RX = re.compile(
    r"(?i)^\s*(?:initialism\s+of|abbreviation\s+of|short\s+for|"
    r"contraction\s+of)\s+(.+?)\s*\.?\s*$")


_FORMOF_CACHE: dict = {}


_FORMOF_CACHE_MAX = 5000


_INFLECTION_RX = re.compile(
    r"(?i)\b(?:plural|past(?:\s+participle)?|present\s+participle"
    r"(?:\s+and\s+gerund)?|gerund|comparative(?:\s+degree)?|"
    r"superlative(?:\s+degree)?|third(?:-|\s+)person\s+singular)"
    r"\s+of\b")


_POS_ALIASES = {
    "adjective": "adj", "adverb": "adv", "preposition": "prep",
    "prep_phrase": "prep", "pronoun": "pron", "conjunction": "conj",
    "determiner": "det", "number": "num",
}


_SUPERLATIVE_RX = re.compile(
    r"(?i)^\s*(?:superlative|comparative)(?:\s+form)?\s+of\s+(.+?)\s*\.?\s*$")


_XREF_RES = (
    re.compile(r"(?i)^\s*alternative\s+(?:[\w\-]+\s+)?"
               r"(?:form|spelling)\s+of\s+(.+?)\s*\.?\s*$"),
    re.compile(r"(?i)^\s*(?:synonym|variant)\s+of\s+(.+?)\s*\.?\s*$"),
    re.compile(r"(?i)^\s*see\s+(?:also\s+)?(.+?)\s*\.?\s*$"),
)


def _collect_kaikki_senses(entries, read_entry):
    """Flatten index rows -> [(entry_pos, entry, sense_dict, gloss)].

    File order is preserved (sense ids are file-order indices); entries
    that fail to read are skipped. R10: the entry travels with the sense
    so the anchored sense's sounds[] (IPA) comes from the same read used
    for the gloss anchor.
    """
    out = []
    for row in entries or []:
        entry = _safe_read(read_entry, row)
        if not isinstance(entry, dict):
            continue
        entry_pos = str(entry.get("pos") or row.get("pos") or "")
        for sense in entry.get("senses") or []:
            if not isinstance(sense, dict):
                continue
            gloss = ""
            for cand in sense.get("glosses") or []:
                if isinstance(cand, str) and cand.strip():
                    gloss = cand.strip()
                    break
            if gloss:
                out.append((entry_pos, entry, sense, gloss))
    return out


def _decay_prescore(file_index, preg, ppos):
    """R38 v10 pre-score: (1/sqrt(file_index+1)) * preg * ppos."""
    import math as _math
    return (1.0 / _math.sqrt(float(file_index) + 1.0)) * preg * ppos


def _freq_norm(values):
    """R37 owner: run_v14_phase1 ranking norm() (min-max, 0.5 on tie).

    Pure stdlib: the vendored copy must stay numpy-free (see the R37
    note above — importing run_v14_phase1 would pull numpy/torch and
    break hermetic CI installs where numpy is not a dependency).
    """
    vals = [float(v) for v in values]
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return [0.5] * len(vals)
    span = hi - lo
    return [(v - lo) / span for v in vals]


def _freq_zipf_single(word):
    """Single-word zipf via wordfreq; None when unknown/uninstalled."""
    try:
        from wordfreq import zipf_frequency
        return float(zipf_frequency(word, "en"))
    except Exception:
        return None


def _is_formof_sense(sense):
    """True when the sense is a form-of inflection stub (tag/pointer).

    Requires the "form-of" tag or a non-empty form_of[] mother pointer;
    bare participle/gerund/past-family tags alone are not stub signals.
    """
    try:
        raw_tags = (sense or {}).get("tags") or []
        # Cache key: normalized tag tuple + form_of presence (lazy/per-shape).
        tag_key = tuple(sorted(
            str(t or "").strip().casefold() for t in raw_tags
            if str(t or "").strip()))
        forms = (sense or {}).get("form_of") or []
        if isinstance(forms, dict):
            # Empty dict {} is no mother pointer (pre-cache behavior:
            # len(list(forms)) > 0 was False for {}).
            has_forms = len(forms) > 0
        else:
            try:
                has_forms = len(list(forms)) > 0
            except TypeError:
                has_forms = bool(forms)
        cache_key = (tag_key, has_forms)
        if cache_key in _FORMOF_CACHE:
            return _FORMOF_CACHE[cache_key]
        tags = {t for t in tag_key if t}
        if "form-of" in tags:
            if len(_FORMOF_CACHE) >= _FORMOF_CACHE_MAX \
                    and cache_key not in _FORMOF_CACHE:
                _FORMOF_CACHE.pop(next(iter(_FORMOF_CACHE)))
            _FORMOF_CACHE[cache_key] = True
            return True
        result = bool(has_forms)
        if len(_FORMOF_CACHE) >= _FORMOF_CACHE_MAX \
                and cache_key not in _FORMOF_CACHE:
            _FORMOF_CACHE.pop(next(iter(_FORMOF_CACHE)))
        _FORMOF_CACHE[cache_key] = result
        return result
    except Exception:
        return False


def _is_meta_gloss(gloss):
    """R40: True on kaikki grouped meta-gloss buckets."""
    return bool(REGISTER_META_RX.match((gloss or "").strip().lower()))


def _safe_read(read_entry, row):
    try:
        return read_entry(row)
    except Exception:
        return None


def _target_rows(index, target):
    """R34: index rows for an xref target (full-phrase key, else 1st token).

    Returns [] when the target has no entry (unresolvable).
    """
    if not target or not isinstance(index, dict):
        return []
    key = target.strip().lower()
    if key in index:
        return list(index[key])
    first = (key.split() or [""])[0]
    return list(index.get(first, []))


def _v14_freq_per_sense(gloss, synonyms, lemma, zipf_fn=None):
    """R37 owner: run_v14_phase1 freq_per_sense (mean zipf, None if <3w)."""
    words = _v14_sense_words(gloss, synonyms, lemma)
    if len(words) < 3:
        return None  # shrink to median later (owner R1 note)
    get = zipf_fn or _freq_zipf_single
    try:
        sc = [get(w) for w in words]
    except Exception:
        return None
    sc = [s for s in sc if isinstance(s, (int, float)) and s > 0]
    return float(sum(sc) / len(sc)) if sc else None


def _v14_ppos(entry_pos, pool_pos):
    """R6 POS factor, owner: factory/archive/v14_v16/run_v14_phase1.py ranking (ppos line).

    Exact v14 rule: verb-source senses shown to non-verb lemmas are
    down-weighted 0.70; everything else 1.0. Score still decides (no hard
    POS filter here — R4 name-only drops happen at sampling).
    """
    if normalize_pos(entry_pos) == "verb" and normalize_pos(pool_pos) != "verb":
        return 0.70
    return 1.0


def _v14_register_penalty(tags, gloss):
    """R6 sense score, owner: factory/archive/v14_v16/run_v14_phase1.py::main.<locals>.register_penalty.

    Vendored (minimal faithful copy) because the owner is nested inside
    main() and importing run_v14_phase1 pulls torch/sentence-transformers/
    sklearn + embedding models (side effects, non-hermetic). Logic is
    byte-faithful to the v14 ranking used for the v14c judge picks.
    R34 v9: v14-pattern gap fixed — the owner regex requires a qualifier
    word ("alternative <X> form of") so the bare "alternative form of X"
    stub scored 1.0 here; it now scores 0.50 like its siblings. The
    owner function (run_v14_phase1.py) is untouched.
    """
    import re as _re
    t = set((tags or []))
    if t & {"slang", "vulgar", "derogatory", "offensive"}:
        return 0.60
    g = (gloss or "").strip()
    if _re.search(r"alternative (?:[\w\-]+ )?form of|alternative spelling of|alternative name for",
                  g.lower()):
        return 0.50
    if len(g.split()) == 1 and g[:1].isupper() and g[1:2].islower():
        return 0.50
    if g in ("A surname.", "A place name.", "A surname.", "A given name."):
        return 0.50
    if t & {"obsolete", "archaic", "dated", "historical"}:
        return 0.80
    return 1.0


def _v14_sense_words(gloss, synonyms, lemma):
    """R37 owner: run_v14_phase1 sense_words (words len>=3, minus lemma)."""
    words = [w for w in re.findall(
        r"[a-zA-Z']+", (gloss or "").lower())
        if len(w) >= 3 and w != (lemma or "").lower()]
    for s in synonyms or []:
        w = (s.get("word") if isinstance(s, dict) else str(s)) or ""
        words += [p for p in re.findall(
            r"[a-zA-Z']+", w.lower().replace("_", " ")) if len(p) >= 3]
    return words


def anchor_entry_pos_for_entries(text, entries, pool_pos, read_entry):
    """Entry POS of the anchored sense's entry ("" when no anchor).

    The anchor itself is always chosen by pick_anchor_sense_full (the ONE
    anchor choke point); this helper only REPORTS that entry's POS so the
    pre-card pipeline S1 can drop proper-noun anchors
    (entry POS in PROPER_NOUN_POS, deterministic, no name lists).
    anchor_item_en itself never drops.
    """
    _, _, _, entry = pick_anchor_sense_full(
        text, entries, pool_pos, read_entry)
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("pos") or "").strip().casefold()


def anchor_item_en(item, index, read_entry, vector_lookup=None,
                   zipf_fn=None, candidate_k=3):
    """R6 anchor + R10 IPA + R17 candidates + R18 second sense.

    Fills sense_id/en_def + ipa/ipa_src (R6/R10, unchanged) and the audit
    trail: sense_candidates (top-candidate_k [{sense_id, gloss, score}],
    3 by default for the pilot shortlist display, JUDGE_WINDOW_CAP for
    the S2 judge window via candidate_k) from the SAME entries the
    anchor was picked from, plus also_sense (second-best
    {sense_id, gloss, topic, topic_method}, None when single-sense).
    The also-sense topic uses the cheap vector_lookup leg only (R18
    choice: no LLM for an audit-only field).
    R29 v8: abbrev_expansion parsed dataset-first from the anchored gloss
    ("" when the gloss is not an abbreviation pattern). R32 v8:
    item["pos"] becomes the dataset tag list (anchored entry POS first,
    1-3 tags) with pos_src "dataset" ("none" when nothing anchors); the
    pool POS string it replaces was already consumed by the scorer above.
    R34 v9: bare-xref top senses resolve through the same kaikki index
    (pick_anchor_sense_full with index=): a hit re-bases sense_id/en_def/
    ipa/candidates/POS onto the TARGET entry (sense_id is the target's,
    xref_method "xref-resolved", xref_resolved_from the original sense
    id); unresolvable xref (no target entry / target also bare-xref,
    1 hop max) keeps the original gloss and sets xref_unresolvable=True
    (S1 drops it as no-real-def — this helper itself never drops).
    anchor_pos carries the anchored entry POS ("" when no anchor).
    """
    text = (item.get("text") or "").strip()
    sense, entry = None, None
    cand_entries, cand_pos = [], ""
    if item.get("kind") == "word":
        entries = index.get(text.lower(), [])
        cand_entries, cand_pos = entries, item.get("pos", "")
        sid, gloss, sense, entry = pick_anchor_sense_full(
            text, entries, item.get("pos", ""), read_entry,
            index=index, zipf_fn=zipf_fn)
    else:
        key = text.lower()
        if key in index:
            cand_entries = index[key]
            sid, gloss, sense, entry = pick_anchor_sense_full(
                text, index[key], "", read_entry,
                index=index, zipf_fn=zipf_fn)
        else:
            sid, gloss = "", ""
            for token in sorted(set(key.split()),
                                key=lambda t: (-len(t), t)):
                cand_sid, cand, sense, entry = pick_anchor_sense_full(
                    text, index.get(token, []), "", read_entry,
                    index=index, zipf_fn=zipf_fn)
                if cand:
                    sid, gloss = cand_sid, cand
                    cand_entries = index.get(token, [])
                    break
            else:
                sense, entry = None, None
    key = text.lower()
    sid_lemma = sid.rpartition("#")[0] if "#" in (sid or "") else ""
    item["xref_method"] = ""
    item["xref_resolved_from"] = ""
    item["xref_unresolvable"] = False
    cand_text = text
    if sid and sid_lemma and sid_lemma != key:
        # R34 resolved: re-base candidates/POS onto the target rows.
        try:
            raw = score_senses(text, cand_entries, cand_pos, read_entry,
                               zipf_fn=zipf_fn)
            orig_sid = "%s#%d" % (key, raw[0][1]) if raw else ""
        except Exception:
            orig_sid = ""
        item["xref_method"] = XREF_METHOD_TAG
        item["xref_resolved_from"] = orig_sid
        cand_entries = _target_rows(index, sid_lemma)
        cand_text = sid_lemma
    elif gloss and detect_xref(gloss) is not None:
        item["xref_unresolvable"] = True
    item["sense_id"] = sid
    item["en_def"] = gloss
    ipa = first_entry_ipa(entry)
    item["ipa"] = ipa
    item["ipa_src"] = IPA_SRC_DATASET if ipa else IPA_SRC_MODEL
    item["anchor_pos"] = (str((entry or {}).get("pos") or "").strip()
                          .casefold() if isinstance(entry, dict) else "")
    # Anchor sense tags ride along for the vulgar-anchor drop (dataset
    # signal: vulgar/offensive/derogatory senses never become learner cards).
    try:
        _tags = ((sense or {}).get("tags") or [])
        item["anchor_tags"] = sorted(
            {str(t).strip().casefold() for t in _tags if str(t or "").strip()})
    except Exception:
        item["anchor_tags"] = []
    # Mother-lemma carrier (additive, no consumer yet): the form_of
    # target(s) of the anchored sense — singleton -> string, multi ->
    # list + flag, missing -> ""/[]/False.
    try:
        _mother, _mothers, _multi = parse_mother_lemma(sense)
    except Exception:
        _mother, _mothers, _multi = "", [], False
    item["mother_lemma"] = _mother
    item["mother_lemmas"] = list(_mothers)
    item["mother_multi"] = bool(_multi)
    item["abbrev_expansion"] = parse_abbrev_expansion(gloss)
    pos_tags = anchor_pos_tags(cand_text, cand_entries, cand_pos,
                               read_entry)
    item["pos"] = pos_tags
    item["pos_src"] = "dataset" if pos_tags else "none"
    # R39 v10: the shortlist display rides the same tiered bucket window
    # as the judge window (pool_level carried for the bucket size;
    # candidate_k selects display width 3 vs judge width JUDGE_WINDOW_CAP
    # in a SINGLE scorer pass — no extra read_entry sweep).
    _lvl = item.get("pool_level") or "A1"
    if isinstance(_lvl, list):
        _lvl = _lvl[0] if _lvl else "A1"
    try:
        _k = max(1, int(candidate_k or 3))
    except (TypeError, ValueError):
        _k = 3
    candidates = top_sense_candidates(
        cand_text, cand_entries, cand_pos, read_entry, k=_k,
        zipf_fn=zipf_fn, pool_level=str(_lvl or "A1"),
        window_cap=max(_k, JUDGE_WINDOW_CAP if _k > 3 else
                       candidate_bucket_cap(str(_lvl or "A1"))))
    item["sense_candidates"] = candidates
    item["also_sense"] = build_also_sense(candidates, vector_lookup)
    return item


def anchor_pos_tags(text, entries, pool_pos, read_entry, limit=3):
    """R32 v8: dataset POS tags from the anchored entry (1-3 tags).

    The anchored sense's entry POS comes first, then the remaining
    distinct entry POS values in file order (casefolded, deduped,
    capped at ``limit``). [] when nothing anchors.
    """
    sid, _, _, _ = pick_anchor_sense_full(
        text, entries, pool_pos, read_entry)
    if not sid:
        return []
    try:
        want = int(sid.split("#")[-1])
    except (TypeError, ValueError):
        return []
    try:
        flat = _collect_kaikki_senses(entries, read_entry)
    except Exception:
        return []
    if want < 0 or want >= len(flat):
        return []
    first = ((flat[want][0] or "").strip().casefold())
    tags = []
    for entry_pos, _, _, _ in flat:
        tag = (entry_pos or "").strip().casefold()
        if tag and tag not in tags:
            tags.append(tag)
    if first and first in tags:
        tags.remove(first)
        tags.insert(0, first)
    return tags[:max(1, limit)]


def build_also_sense(candidates, vector_lookup=None):
    """R18: second-best sense {sense_id, gloss, topic, topic_method}.

    Single-sense (or empty) candidate lists -> None (card unchanged).
    Topic via the cheap vector_lookup leg only; else null + tag.
    """
    if not candidates or len(candidates) < 2:
        return None
    second = candidates[1]
    vec = (vector_lookup or {}).get(second["sense_id"])
    if vec:
        # Local import: topics -> judge -> anchor would cycle at module
        # top (single source stays factory.precard.topics.TOPIC_METHOD).
        from factory.precard.topics import TOPIC_METHOD
        return {"sense_id": second["sense_id"], "gloss": second["gloss"],
                "topic": vec[0]["label"],
                "topic_method": TOPIC_METHOD}
    return {"sense_id": second["sense_id"], "gloss": second["gloss"],
            "topic": None, "topic_method": ALSO_TOPIC_UNASSIGNED}


def build_pos_sets(index):
    """lemma.lower() -> kaikki POS set, for the R4 sampling filter."""
    return {word: kaikki_pos_set(rows) for word, rows in index.items()}


def candidate_bucket_cap(pool_level):
    """R39: file-index bucket size by pool level (6 for A1/A2, else 10)."""
    return CANDIDATE_BUCKET_A1A2 \
        if (pool_level or "").strip().upper() in ("A1", "A2") else \
        CANDIDATE_BUCKET_UPPER


def detect_xref(gloss):
    """R34: cross-reference target of a bare-xref gloss, else None.

    Returns the stripped target string ("colour" for 'Alternative
    spelling of "colour".'). Non-bare glosses (prose merely mentioning
    "see" mid-sentence) never match: patterns are whole-gloss anchored.
    """
    g = (gloss or "").strip()
    if not g:
        return None
    for rx in _XREF_RES:
        hit = rx.match(g)
        if hit:
            target = (hit.group(1) or "").strip().strip(
                "'\"“”‘’").strip().rstrip(".").strip()
            return target or None
    return None


def first_entry_ipa(entry):
    """R10: first ipa string of a kaikki entry's sounds[] ("" if none)."""
    for sound in (entry or {}).get("sounds") or []:
        if not isinstance(sound, dict):
            continue
        ipa = sound.get("ipa")
        if isinstance(ipa, str) and ipa.strip():
            return ipa.strip()
    return ""


def is_inflection_gloss(gloss):
    """R36: True when the gloss is an inflection stub ("plural of X")."""
    return bool(_INFLECTION_RX.search(gloss or ""))


def is_proper_noun_lemma(lemma, pos_set):
    """R4: single-token lemma whose kaikki POS set is subset of {name, propn}."""
    text = (lemma or "").strip()
    return bool(text) and " " not in text and bool(pos_set) \
        and set(pos_set) <= PROPER_NOUN_POS


def is_stub_sense(sense, gloss):
    """Stub predicate for the S2 judge window: form-of-tagged senses
    plus the shared gloss stubs (S0b/F4 boundary, inherited — the veto
    keeps its own gloss-only path, the window adds the tag leg)."""
    return bool(_is_formof_sense(sense)
                or is_inflection_gloss(gloss)
                or is_superlative_gloss(gloss))


def is_superlative_gloss(gloss):
    """R44: True when the gloss is a superlative/comparative-pattern stub."""
    return bool(parse_superlative_base(gloss))


def kaikki_pos_set(entries):
    """POS set of one lemma's index rows (same source R1 resolves from)."""
    return {str(e.get("pos") or "").strip().casefold()
            for e in (entries or [])
            if str(e.get("pos") or "").strip()}


def normalize_pos(pos):
    """Casefold a POS tag through the minimal alias map (R1 gloss match).

    NOTE: cefr.py has a same-named cousin with a stricter contract
    (raises on empty, no alias map). Keep them separate; parity between
    them is neither expected nor wanted.

    R32 v8: tolerates the dataset tag list in item["pos"] (uses the
    first tag) so re-ranking an already-anchored item never crashes.
    """
    if isinstance(pos, (list, tuple)):
        pos = pos[0] if pos else ""
    if not isinstance(pos, str):
        pos = str(pos or "")
    key = pos.strip().casefold()
    return _POS_ALIASES.get(key, key)


def parse_abbrev_expansion(gloss):
    """R29: expansion of an abbreviation gloss ("" when not matching).

    Matches the whole gloss only (anchored ^...$) so prose glosses that
    merely mention "short for" mid-sentence never parse.
    """
    hit = _ABBREV_RX.match(gloss or "")
    if not hit:
        return ""
    return (hit.group(1) or "").strip().rstrip(".")


def parse_mother_lemma(sense):
    """Mother lemma(s) of a form-of sense from form_of[].word.

    Cleaning mirrors parse_superlative_base (strip quotes/dots, cut
    trailing qualifiers at [:;,(], single alpha token only — a
    multi-word target is not a clean redirect, EXCEPT the dataset
    multi-target shape (better#0 form_of=[{word: "good and well"}]):
    one form_of word joining two+ alpha tokens with "and"
    splits into a mothers list + multi True; a comma always cuts as a
    trailing qualifier, never a multi delimiter). Returns
    (mother, mothers, multi): singletons -> ("go", ["go"], False);
    multi-target (better: good+well, one string or two entries) ->
    ("good", ["good", "well"], True); missing/unclean ->
    ("", [], False). Order-preserving dedupe; the stored form is the
    cleaned dataset word, case as-is.
    """
    try:
        forms = (sense or {}).get("form_of") or []
    except AttributeError:
        return "", [], False
    mothers = []
    try:
        items = list(forms) if not isinstance(forms, dict) else [forms]
    except TypeError:
        return "", [], False
    for form in items:
        if isinstance(form, dict):
            word = form.get("word")
        elif isinstance(form, str):
            word = form
        else:
            continue
        target = (word or "").strip().strip(
            "'\"\u201c\u201d\u2018\u2019").strip().rstrip(".").strip()
        # Multi-target single string ("good and well"): "and" joins two+
        # alpha tokens into a mothers list + multi True. A comma NEVER
        # splits — it cuts as a qualifier tail like parse_superlative_base
        # (review: ("go, archaic") must stay one qualified singleton, not
        # persist a phantom second mother; no dataset instance shows a
        # comma joining two real mothers, only the "and"-joined shape).
        if "," in target:
            target = re.split(r"[:;,(]", target, maxsplit=1)[0].strip()
            if re.fullmatch(r"[A-Za-z]+", target or "") \
                    and target not in mothers:
                mothers.append(target)
            continue
        # No comma: split on "and"/slashes/& first, then clean pieces
        # (cut pieces at [:;(] only).
        parts = re.split(r"\s+and\s+|/\s*|\s+&\s+",
                         target, flags=re.IGNORECASE)
        for part in parts:
            piece = (part or "").strip().strip(
                "'\"\u201c\u201d\u2018\u2019").strip().rstrip(
                ".").strip()
            piece = re.split(r"[:;(]", piece, maxsplit=1)[0].strip()
            if re.fullmatch(r"[A-Za-z]+", piece or "") \
                    and piece not in mothers:
                mothers.append(piece)
    if not mothers:
        return "", [], False
    if len(mothers) == 1:
        return mothers[0], mothers, False
    return mothers[0], mothers, True


def parse_superlative_base(gloss):
    """R44: base lemma of a superlative/comparative gloss ("" if none).

    Whole-gloss anchored (^...$): prose merely mentioning
    "superlative of" mid-sentence never parses. The base must be a
    single alpha token (multi-word/qualified targets are not clean
    redirects). Target is stripped of quotes/dots. Index membership
    is checked by the CALLER (S0b), keeping this helper pure.
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


def pick_anchor_sense_full(text, entries, pool_pos, read_entry,
                           index=None, zipf_fn=None):
    """R6 anchor + R10/R11 carriers: (sense_id, gloss, sense, entry).

    Scoring is Score_pre = file-index decay * register_penalty * ppos
    (R38 v10; freq_per_sense survives only as <0.05 tie-breaker); sense_id
    is "<text.lower()>#<file-order-sense-idx>". Empty entries ->
    ("", "", None, None). R34 v9: when the top scorer is a bare xref
    and the same kaikki index is passed, the anchor resolves to the
    target entry's top sense (4-tuple of the TARGET: its sense_id/gloss/
    sense/entry); unresolvable xref (no target entry, target also
    bare-xref) returns the ORIGINAL top tuple unchanged — the caller
    (anchor_item_en / S1) flags it via detect_xref for the no-real-def
    drop. index=None preserves the legacy unresolved behavior.
    """
    scored = score_senses(text, entries, pool_pos, read_entry,
                          zipf_fn=zipf_fn)
    if not scored:
        return "", "", None, None
    _, best_idx, best_entry, best_sense, best_gloss = scored[0]
    key = (text or "").strip().lower()
    if index is not None and detect_xref(best_gloss) is not None:
        target = detect_xref(best_gloss)
        resolved = resolve_xref_anchor(
            target, pool_pos, read_entry, index, zipf_fn=zipf_fn)
        if resolved[0]:
            return resolved
    return "%s#%d" % (key, best_idx), best_gloss, best_sense, best_entry


def raw_first_gloss(entries, read_entry):
    """Gloss of the file-order-first collected sense ("" when none).

    S0b inflection review asks about the RAW lemma head, not the
    demoted anchor top: stub demotion (form-of/meta buckets) must not
    silence the "is this lemma inflection-led?" question.
    """
    try:
        senses = _collect_kaikki_senses(entries, read_entry)
    except Exception:
        return ""
    if not senses:
        return ""
    return senses[0][3] or ""


def resolve_xref_anchor(target, pool_pos, read_entry, index, zipf_fn=None):
    """R34: top sense of the xref target entry (max 1 hop, no chains).

    Returns (sense_id, gloss, sense, entry) of the target's top scorer,
    or (None, None, None, None) when unresolvable: no target entry, or
    the target top is itself a bare xref (chains stop after 1 hop).
    sense_id is "<target.lower()>#<file-order-sense-idx>".
    """
    rows = _target_rows(index, target)
    if not rows:
        return None, None, None, None
    tkey = (target or "").strip().lower()
    if tkey not in (index or {}):
        tkey = (tkey.split() or [""])[0]
    scored = score_senses(tkey, rows, pool_pos, read_entry,
                          zipf_fn=zipf_fn)
    if not scored:
        return None, None, None, None
    _, best_idx, best_entry, best_sense, best_gloss = scored[0]
    if detect_xref(best_gloss) is not None:
        return None, None, None, None  # 1-hop max: target also bare-xref
    return "%s#%d" % (tkey, best_idx), best_gloss, best_sense, best_entry


def score_senses(text, entries, pool_pos, read_entry, zipf_fn=None):
    """Score every kaikki sense: [(score, file-idx, entry, sense, gloss)].

    R38 v10: Score_pre = (1/sqrt(file_index+1)) * preg * ppos where
    file_index is the stable file-order sense idx, preg is the vendored
    v14 register_penalty (incl. the R34 bare-alt-form extension) and
    ppos the vendored v14 POS factor (both kept as-is). The vendored
    v14 freq_per_sense leg survives ONLY as the final tie-breaker: when
    two pre-scores differ by less than FREQ_TIE_EPS (0.05) the higher
    freq_norm wins; otherwise file-decay order wins. zipf_fn injects
    the per-word zipf lookup (hermetic tests); None uses wordfreq live.
    Shared by the anchor pick and the R17/R18 audit helpers so the anchor,
    the top-3 candidates, and the second sense never diverge.
    """
    import functools as _ft
    senses = _collect_kaikki_senses(entries, read_entry)
    lemma = (text or "").strip()
    fraw = [_v14_freq_per_sense(
        gloss, (sense or {}).get("synonyms", []), lemma, zipf_fn)
        for _, _, sense, gloss in senses]
    present = [x for x in fraw if x is not None]
    if present:
        import statistics as _st
        med = float(_st.median(present))
    else:
        med = 3.0  # owner fallback when every sense is short/unknown
    fnorm = _freq_norm([x if x is not None else med for x in fraw])
    scored = []
    for idx, ((entry_pos, entry, sense, gloss), fn) in enumerate(
            zip(senses, fnorm)):
        preg = _v14_register_penalty(
            (sense or {}).get("tags"), gloss)
        ppos = _v14_ppos(entry_pos, pool_pos)
        # R40 (#607): meta buckets demote below real senses (flag rides
        # along for the comparator; the score itself is untouched).
        # Form-of stubs ride the same demoted bucket (weight ZERO —
        # strict sort below every real sense, never a multiplicative
        # penalty file-decay could outrank). The flag is the SHARED
        # stub predicate (tag/pointer form-of AND gloss stubs), exactly
        # what the judge window filters — so the anchor top always sits
        # inside its own window (top == window rank 1 invariant).
        score = _decay_prescore(idx, preg, ppos)
        scored.append([score, idx, entry, sense, gloss, float(fn),
                       _is_meta_gloss(gloss),
                       is_stub_sense(sense, gloss)])

    def _cmp(a, b):
        # R40 (#607): meta-vs-real sorts first (intended — a meta bucket
        # never outranks a real sense, even a penalized vulgar/obsolete
        # one); preg/ppos/freq legs only order within the same class.
        # Form-of stubs share the demoted bucket: any demoted sense
        # (meta OR form-of) sorts below every real sense.
        ad, bd = (a[6] or a[7]), (b[6] or b[7])
        if ad != bd:
            return 1 if ad else -1
        if abs(a[0] - b[0]) >= FREQ_TIE_EPS:
            return -1 if a[0] > b[0] else 1
        if abs(a[5] - b[5]) >= 1e-12:
            return -1 if a[5] > b[5] else 1
        if a[1] != b[1]:
            return -1 if a[1] < b[1] else 1
        return 0

    scored.sort(key=_ft.cmp_to_key(_cmp))
    return [(s, i, e, se, g) for s, i, e, se, g, _fn, _m, _f in scored]


def select_candidate_window(scored, pool_pos="", pool_level="A1", cap=10):
    """R39: tiered candidate window over score_senses output (score order).

    scored is the score_senses list [(score, file-idx, entry, sense,
    gloss)] already in rank order. The window starts as the senses whose
    file-idx falls inside the level bucket (0-5 for A1/A2, 0-9 above);
    when pool_pos is given and NO window sense has an entry POS matching
    it, the window expands to the full list (fallback-to-higher). Then
    POS coverage is enforced: for every distinct entry POS in scored
    missing from the window, the top-scored sense of that POS is pulled
    in. The result preserves score order and is capped at cap entries.
    Stub senses (is_stub_sense: form-of-tagged/pointed plus the shared
    gloss stubs) are filtered BEFORE bucketing and POS coverage — a
    stub-only POS is never pulled back in.
    """
    scored = list(scored or [])
    if not scored:
        return []
    # Stub-free judge window: form-of/stub senses never reach the judge
    # (fewer tokens, zero stub-picks). Fail-closed: an all-stub list
    # keeps every candidate — a veto reroutes, it never drops.
    # POS coverage below runs over the filtered list, so a stub-only
    # POS is never pulled back in.
    live = [t for t in scored
            if not is_stub_sense(t[3] if len(t) > 3 else None,
                                 t[4] if len(t) > 4 else "")]
    if live:
        scored = live
    try:
        cap = max(1, int(cap))
    except (TypeError, ValueError):
        cap = 10
    bucket = candidate_bucket_cap(pool_level)
    by_idx = sorted(scored, key=lambda t: t[1])
    window_ids = {t[1] for t in by_idx[:bucket]}
    window = [t for t in scored if t[1] in window_ids]
    if not window:
        window = list(scored)
    want = normalize_pos(pool_pos) if (pool_pos or "") else ""
    if want:
        def _pos_of(t):
            try:
                return normalize_pos((t[2] or {}).get("pos") or "")
            except Exception:
                return ""
        if not any(_pos_of(t) == want for t in window):
            window = list(scored)
    # POS coverage: at least one candidate per POS present.
    def _pos_of(t):
        try:
            return normalize_pos((t[2] or {}).get("pos") or "")
        except Exception:
            return ""
    have = {_pos_of(t) for t in window if _pos_of(t)}
    all_pos = [_pos_of(t) for t in scored if _pos_of(t)]
    for pos in dict.fromkeys(all_pos):
        if pos and pos not in have:
            for cand in scored:
                if _pos_of(cand) == pos:
                    window.append(cand)
                    have.add(pos)
                    break
    seen = set()
    ordered = []
    for t in window:
        if t[1] not in seen:
            seen.add(t[1])
            ordered.append(t)
    ordered.sort(key=lambda t: ([i for i, s in enumerate(scored)
                                 if s[1] == t[1]] or [0])[0])
    return ordered[:cap]


def top_sense_candidates(text, entries, pool_pos, read_entry, k=3,
                         zipf_fn=None, pool_level="A1", window_cap=None):
    """R17 top-k anchor candidates [{sense_id, gloss, score}] (ranked).

    R39 v10: candidates are drawn from the tiered bucket window
    (select_candidate_window) before slicing the top-k, so the anchor,
    the shortlist display, and the S2 judge window never diverge.
    sense_id is "<text.lower()>#<file-order-sense-idx>"; score rounded
    to 3 decimals. Empty entries -> [].
    """
    key = (text or "").strip().lower()
    scored = score_senses(text, entries, pool_pos, read_entry,
                          zipf_fn=zipf_fn)
    cap = window_cap if window_cap is not None else max(
        k, candidate_bucket_cap(pool_level))
    try:
        cap = max(int(k), int(cap))
    except (TypeError, ValueError):
        cap = max(3, int(k))
    window = select_candidate_window(scored, pool_pos, pool_level, cap=cap)
    return [{"sense_id": "%s#%d" % (key, idx), "gloss": gloss,
             "score": round(score, 3)}
            for score, idx, _, _, gloss in window[:k]]


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


ZIPF_FLOORS = {"A1": 3.0, "A2": 3.0, "B1": 3.0, "B2": 3.0,
               "C1": 2.5, "C2": 1.5}


ZIPF_MIN = 3.0


_ZIPF_CACHE: dict = {}


_G2_FORM_RX = re.compile(
    r"\b(third[ -]?person singular|simple past|past of|past tense|"
    r"past participle|present participle|present of|gerund|plural of|"
    r"comparative|superlative)\b",
    re.IGNORECASE)


_G5_DEMONYM_RX = re.compile(
    r"\b(nationality|demonym|capital of|city in|native of|"
    r"inhabitant of|person from|"
    r"countr(y|ies)\b[^.]{0,20}?\b(language|nation|nationality)\b|"
    r"language spoken)\b", re.IGNORECASE)


_G5_PERTAIN_RX = re.compile(
    r"\b[Oo][Ff] [Oo][Rr] "
    r"([Pp][Ee][Rr][Tt][Aa][Ii][Nn][Ii][Nn][Gg]|"
    r"[Rr][Ee][Ll][Aa][Tt][Ii][Nn][Gg]) "
    r"[Tt][Oo] ([Tt][Hh][Ee] [A-Z]|[A-Z])")


_NAME_GLOSS_RX = re.compile(
    r"^\s*(?:a|an|the)\s+"
    r"(?:(?:male|female|unisex|masculine|feminine)\s+)?"
    r"(?:[\w'’-]+\s+){0,2}"
    r"(?:given\s+name|surname|family\s+name|place\s+name|first\s+name|"
    r"last\s+name|maiden\s+name|nickname|pet\s+form\s+of|"
    r"diminutive\s+of|short\s+form\s+of)\b",
    re.IGNORECASE)


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


def anchor_rank_item(item, index, read_entry):
    """Anchor deterministic rank (s1) via the card_pilot anchor path.

    Returns {"candidates": [{sense_id, gloss, score, tags}...],
             "top": {"sense_id", "gloss"} or None,
             "en_def": gloss or "",
             "anchor_pos": entry POS of the anchored sense ("" if none)}.
    Candidates carry the full kaikki tag set (sorted list, [] when
    unresolvable) so the sense-judge prompt can show [tags] next to each
    gloss. Tags are display-only: scoring and the anchor top never read
    them.
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
    anchor_item_en(
        probe, index, read_entry,
        candidate_k=JUDGE_WINDOW_CAP)
    cands = [c for c in (probe.get("sense_candidates") or [])
             if isinstance(c, dict) and c.get("sense_id")]
    tag_map = _candidate_tag_map(item, cands, index, read_entry)
    for cand in cands:
        cand["tags"] = list(tag_map.get(cand.get("sense_id", ""), []))
    top = {"sense_id": cands[0]["sense_id"], "gloss": cands[0].get("gloss", "")} \
        if cands else None
    entries, pos = _entries_for(item, index)
    anchor_pos = probe.get("anchor_pos") or \
        anchor_entry_pos_for_entries(
            item.get("text", ""), entries, pos, read_entry)
    return {"candidates": cands, "top": top,
            "en_def": probe.get("en_def", "") or "",
            "anchor_pos": anchor_pos,
            "anchor_tags": list(probe.get("anchor_tags") or []),
            "mother_lemma": probe.get("mother_lemma", "") or "",
            "mother_lemmas": list(probe.get("mother_lemmas") or []),
            "mother_multi": bool(probe.get("mother_multi")),
            "xref_method": probe.get("xref_method", "") or "",
            "resolved_from": probe.get("xref_resolved_from", "") or "",
            "xref_unresolvable": bool(probe.get("xref_unresolvable"))}


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
            if pos and pos not in PROPER_NOUN_POS:
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
    dropping. A lookup/structure error inside this helper keeps the
    input top (marked name_eval_error, WITHOUT the reroute flag) so the
    caller keeps instead of dropping — uncertainty keeps, and the mark
    re-arms evaluation on resume (transient errors self-heal). Returns
    (top, en_def, anchor_pos), or None when the top is not a name gloss
    or every candidate is a name (true names still drop) or the input
    has no usable top.
    """
    try:
        if not _is_name_gloss((ranked.get("top") or {}).get("gloss", "")):
            return None
        for cand in ranked.get("candidates") or []:
            sid = cand.get("sense_id", "")
            if not sid or _is_name_gloss(cand.get("gloss", "")):
                continue
            pos = _picked_entry_pos(item, sid, index, read_entry)
            if pos not in PROPER_NOUN_POS:
                rest = [c for c in ranked["candidates"]
                        if c.get("sense_id") != sid]
                ranked["candidates"] = [cand] + rest
                ranked.pop("name_eval_error", None)
                ranked["rerouted_from_name"] = True
                return ({"sense_id": sid,
                         "gloss": cand.get("gloss", "")},
                        cand.get("gloss", ""), pos)
    except (KeyError, TypeError, AttributeError, ValueError):
        try:
            top = ranked.get("top") or {}
        except Exception:
            return None
        if not top.get("sense_id"):
            return None
        ranked["name_eval_error"] = True
        return ({"sense_id": top.get("sense_id", ""),
                 "gloss": top.get("gloss", "")},
                top.get("gloss", ""), ranked.get("anchor_pos", ""))
    return None


def _mother_for_top(item, sense_id, index, read_entry):
    """Mother triple for the current anchor top (None when unresolvable).

    Refreshes the carrier after a reroute (proper/name paths re-anchor
    onto a different sense — the mother must describe the FINAL top).
    Returns None when the sense cannot be resolved (transient lookup
    failure) so callers preserve the ranked carrier — mirroring the
    `if fresh:` anchor_tags guard (review: unconditional overwrite
    wiped the good carrier on lookup failure). A resolved sense with
    no mother still returns ("", [], False).
    """
    try:
        sense = _window_sense(item, sense_id, index, read_entry)
    except Exception:
        return None
    if sense is None:
        return None
    try:
        return parse_mother_lemma(sense)
    except Exception:
        return None


def _candidate_tag_map(item, cands, index, read_entry):
    """{sense_id: sorted tag list} for anchor candidates in one scorer
    pass per distinct lemma.

    Same resolution as _target_sense_tags (xref-target switch included)
    but a single score_senses call covers the whole window instead of one
    per candidate — production read_entry seeks raw Kaikki per call, so
    per-candidate passes would multiply disk I/O by the window size.
    Lookup errors fail open to [] — tags are display-only for the
    sense-judge prompt, never drops.
    """
    groups = {}
    for cand in cands:
        if not isinstance(cand, dict) or not cand.get("sense_id"):
            continue
        sid = cand.get("sense_id", "")
        lemma = sid.rpartition("#")[0].strip().lower() or \
            (item.get("text") or "").strip().lower()
        groups.setdefault(lemma, []).append(cand)
    out = {}
    for lemma, group in groups.items():
        try:
            if lemma and lemma != (
                    item.get("text") or "").strip().lower():
                rows = (index or {}).get(lemma)
                if rows:
                    entries, pos = list(rows), ""
                else:
                    entries, pos = _entries_for(item, index)
            else:
                entries, pos = _entries_for(item, index)
            scored = score_senses(
                lemma or item.get("text", ""), entries, pos, read_entry)
        except Exception:
            continue
        tags_by_idx = {}
        for _score, idx, _entry, sense, _gloss in scored:
            tags_by_idx.setdefault(idx, _sense_tag_set(sense))
        for cand in group:
            try:
                want = int((cand.get("sense_id") or "").split("#")[-1])
            except (TypeError, ValueError, AttributeError):
                out[cand.get("sense_id", "")] = []
                continue
            out[cand.get("sense_id", "")] = sorted(
                tags_by_idx.get(want, set()))
    return out


def _needs_tag_backfill(done_entry):
    """True when a KEPT s1 entry predates the tags backfill (R4).

    Dropped entries never backfill (drops are never re-run); entries
    whose candidates all carry "tags" (even []) are current.
    """
    return (isinstance(done_entry, dict)
            and "dropped" not in done_entry
            and isinstance(done_entry.get("candidates"), list)
            and any(isinstance(c, dict) and "tags" not in c
                    for c in done_entry["candidates"]))


def _backfill_candidate_tags(batch, anchor_map, index, read_entry):
    """Attach missing candidate tags in place (selective-stage resume).

    When s1 is skipped (--only/--stages without s1) the resume guard
    never runs, yet sense-judge consumes the stored anchor entries — so
    tagless entries get their tags attached here, in memory, before the
    judge prompt is built. Deterministic local reads only, never LLM;
    dropped entries are untouched. Mutations persist via the regular
    per-batch progress flush.
    """
    for item in batch:
        entry = (anchor_map or {}).get(item_key(item))
        if not _needs_tag_backfill(entry):
            continue
        try:
            tag_map = _candidate_tag_map(
                item, entry["candidates"], index, read_entry)
        except Exception:
            continue
        for cand in entry["candidates"]:
            if isinstance(cand, dict) and "tags" not in cand:
                cand["tags"] = list(
                    tag_map.get(cand.get("sense_id", ""), []))


def _window_sense(item, sense_id, index, read_entry):
    """Sense dict for one window sense_id (None when unresolvable).

    Mirrors the xref-target switch: a sense_id carrying the TARGET lemma
    resolves against the target rows, not the item rows. Lookup errors
    fail open to None — carriers only ever add information, never drops.
    """
    try:
        want_idx = int((sense_id or "").split("#")[-1])
    except (TypeError, ValueError, AttributeError):
        return None
    try:
        entries, pos = _entries_for(item, index)
        sid_lemma = (sense_id or "").rpartition("#")[0].strip().lower()
        if sid_lemma and sid_lemma != (
                item.get("text") or "").strip().lower():
            target_rows = (index or {}).get(sid_lemma)
            if target_rows:
                entries, pos = list(target_rows), ""
        scored = score_senses(
            sid_lemma or item.get("text", ""), entries, pos, read_entry)
    except Exception:
        return None
    for _score, idx, _entry, sense, _gloss in scored:
        if idx == want_idx:
            return sense
    return None


def _target_sense_tags(item, sense_id, index, read_entry):
    """Kaikki tag set of one window candidate (empty set when
    unresolvable). Mirrors _picked_entry_pos's xref-target switch, but
    returns the sense's tags (via the C3 _sense_tag_set normalizer)
    instead of the entry POS. Lookup errors fail open to empty — tags
    only ever add drops, never keeps, so uncertainty keeps.
    """
    return _sense_tag_set(
        _window_sense(item, sense_id, index, read_entry))


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
        scored = score_senses(
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


def _sense_tag_set(sense):
    """Lowercased kaikki tag set of one sense dict ({} on bad shape)."""
    try:
        tags = (sense or {}).get("tags") or []
    except AttributeError:
        return set()
    return _normalize_tags(tags)


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


def _is_name_gloss(gloss):
    """F2: True when the gloss is a name head (given/surname/place-name)."""
    return bool(_NAME_GLOSS_RX.match(gloss or ""))


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
        if is_proper_noun_lemma(
                text, (pos_sets if pos_sets is not None else {}).get(
                    text.lower(), set())):
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


def _is_academic(item, awl_set):
    """Academic tag: explicit academic/evp field on the sample item, else
    lemma membership in the AWL families set."""
    if bool(item.get("academic")):
        return True
    evp = item.get("evp")
    if isinstance(evp, dict) and bool(evp.get("academic")):
        return True
    return (item.get("text") or "").strip().lower() in (awl_set or set())


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
    if picked_pos not in PROPER_NOUN_POS \
            or anchored in PROPER_NOUN_POS:
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
