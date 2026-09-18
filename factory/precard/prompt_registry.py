"""Versioned precard prompt registry (T-RUN-B, 2026-09-18).

SOLE owner of the precard run prompt wordings: TOPUP / V15 /
sense-judge / inflection-review (+ the v14.1 topic tie-break
addendum). Texts moved here VERBATIM from factory/precard/prompts.py,
factory/precard/topics.py and factory/precard/judge.py — the old
homes keep pure re-export aliases (zero behavior change).

- Version tag: PROMPTS_VERSION (every entry carries it;
  prompt_version(name) reports it).
- Selection: get_prompt(name) resolves the default unless a
  variant is picked via select("name=variant,..."), the repeatable
  precard CLI flag --prompt-variant, or the FACTORY_PROMPT_VARIANT
  env var (same grammar). Explicit select() wins over env; env wins
  over default. select("") / select("default") / reset() restore
  defaults. Unknown names/variants fail closed (KeyError).
- Byte-identity: defaults are pinned by
  tests/factory/test_precard_prompt_registry.py against the
  pre-move snapshot (any prompt byte-diff = FAIL). Wording changes
  are explicit registry edits — never code-side string edits.

The pilot line (factory/pipeline/card_pilot.py) keeps its own copies
and evolves separately (identity-141 R5, unify at T6).
"""

from __future__ import annotations

import os


PROMPTS_VERSION = "v1"

ENV_VAR = "FACTORY_PROMPT_VARIANT"


# ---- frozen defaults (verbatim pre-move bytes; do not hand-edit:
# register a variant instead, or update + re-pin the snapshot) ----

_TEXT_DEFAULTS = {
    'topic_tiebreak': 'V14.1 TIE-BREAK ADDENDUM (apply strictly): biological sex and sociological gender (gender, male/female roles) are NEVER Animals & Living Beings — map biological/anatomical senses to Health & Body and social-role senses to Society. Functional and social concepts (phone calls, employment, public performances, money accumulation, lifting) are NEVER Other / Abstract — assign the concrete domain (technology, work, society, business, daily life). Other / Abstract stays a last resort for genuinely abstract, grammatical, or unclassifiable senses.',
    'inflection_review_sys': 'You are an English learner-dictionary editor for Persian learners. Given an inflected word form and its dictionary gloss, reply {"keep": bool, "reason": "string"}. KEEP criteria (ONLY IF any applies): 1. The inflected form has established, independent usage as an Adjective with a distinct meaning beyond the action of the verb (e.g., \'charming\', \'striking\', \'demanding\'). 2. The form carries a unique, non-transparent nominal or idiomatic sense that a learner cannot deduce from the base lemma (e.g., \'building\', \'drawing\', \'do one\'s best\'). 3. Established legal terms, crimes, physical objects, or field concepts ending in -ing (e.g., \'kidnapping\', \'building\', \'lightning\') are independent headwords -> KEEP. DROP criteria (ONLY IF any applies): 1. Regular plurals (-s, -es) with transparent compositional meaning -> Drop in favor of the singular base lemma. 2. Regular past tense and participles (-ed) acting merely as the verbal completion of the action -> Drop in favor of the base lemma. 3. Plain gerunds/participles (-ing) that simply describe the active progress of the verb (e.g., \'forcing\' = act of forcing; \'wondering\' = act of wondering) -> Drop in favor of the base lemma. 4. Plain grammatical comparatives/superlatives (-er, -est, more, most) -> Drop in favor of the base lemma. Return ONLY raw JSON, no markdown fences, no commentary. Reason MUST be strictly in concise English (max 12 words).',
    'v15_user_tmpl': 'For EACH sense below, assign 1 to 3 topic labels with weights (numbers 0..1) summing to 1.0. The CURRENT label is usually the primary topic — keep it first with the largest weight UNLESS the gloss genuinely spans another topic (e.g. rock music = Society & Culture + Emotions & Relationships; a flat tire on a trip = Travel & Transportation + Daily Life & Home). TIE-BREAK & DOMAIN MAPPING (apply strictly): colors and visual themes (e.g. pink, reddish, bright) -> Arts & Culture (0.60) + Daily Life & Home (0.40); do NOT leave color terms as purely abstract. Other physical or sensory attributes (e.g. shallow, dirty, smooth) belong to their natural domain (Nature & Environment, Daily Life & Home). Functional, purely quantitative, or directional dimensions (e.g. low, high, once, few) -> Other / Abstract (1.00). Use 2+ topics only where genuinely mixed; single-topic senses get one entry with weight 1.0. Allowed labels with ids (use EXACT strings): {"1": "Daily Life & Home", "2": "Food & Drink", "3": "Health & Body", "4": "Work & Education", "5": "Travel & Transportation", "6": "Society & Culture", "7": "Nature & Environment", "8": "Science & Technology", "9": "Business & Economy", "10": "Law & Politics", "11": "Sports & Leisure", "12": "Emotions & Relationships", "13": "Other / Abstract"}. Output: {"results": [{"lemma": "...", "vectors": [{"sense_id": "<exact sense id>", "vector": [{"topic_id": N, "topic_label": "<exact allowed label>", "weight": w}]}]}]}. Cover EVERY sense id from the input exactly once. Weights must sum to 1.0 (±0.01). Input follows:\n',
    'topup_user_tmpl': 'For EACH sense below, pick ONE primary topic label (id 1..16) AND a weight vector of 1 to 3 labels (weights 0..1, summing to 1.0). The vector\'s top entry must be the primary label. TIE-BREAK & DOMAIN MAPPING (apply strictly): colors and visual themes (e.g. pink, reddish, bright) -> Arts & Culture (0.60) + Daily Life & Home (0.40); do NOT leave color terms as purely abstract. Other physical or sensory attributes (e.g. shallow, dirty, smooth) belong to their natural domain (Nature & Environment, Daily Life & Home). Functional, purely quantitative, or directional dimensions (e.g. low, high, once, few) -> Other / Abstract (1.00); use Travel & Transportation (1.00) only if navigational. Non-human animals & wildlife -> Animals & Living Beings even if edible (a swimming fish = Animals, a fish on the table = Food & Drink). Humans, family, and person nouns stay under Society or Emotions & Relationships. Eating, cooking, or food acts -> Food & Drink. Workplace, professions, and office activities -> Work & Careers. Art, film, music, literature -> Arts & Culture. Competitive sports (teams, matches, tournaments) vs casual leisure (hobbies, free-time fun): both map to Sports & Leisure — split across domains only when the gloss genuinely spans one (a pro athlete\'s contract = Sports & Leisure + Work & Careers). Strictly abstract logic, function words, and grammatical operators with no topical anchor (e.g. about, always, anything, both, each, would, by) -> Other / Abstract (1.00). MULTI-TOPIC GUIDELINE: use 2 to 3 labels with weights summing to 1.0 whenever a sense genuinely spans multiple domains. Distribute weights proportionally (e.g. 0.60/0.40 or 0.50/0.50) rather than forcing 1.00 into a single bucket. Labels (use EXACT strings, id = position): 1 Daily Life & Home: everyday routines, household, clothing, time. 2 Food & Drink: eating, cooking, food/drink items and the act of eating. 3 Health & Body: body parts, illness, medicine, hygiene. 4 Work & Careers: jobs, offices, meetings, professional life. 5 Education & Exams: school, study, exams, learning. 6 Travel & Transportation: trips, vehicles, directions, movement. 7 Society: community, traditions, social life, public affairs. 8 Arts & Culture: art, film, music, literature. 9 Animals & Living Beings: animals and living creatures, even if edible. 10 Nature & Environment: plants, earth, air, water, weather, landscapes. 11 Science & Technology: science, computers, devices, inventions. 12 Business & Economy: money, trade, markets, finance. 13 Law & Politics: rules, government, crime, rights. 14 Sports & Leisure: games, sports, hobbies, free-time fun. 15 Emotions & Relationships: feelings, family, friendship, love. 16 Other / Abstract: abstract, grammatical, or unclassifiable meanings. Id map: {"1": "Daily Life & Home", "2": "Food & Drink", "3": "Health & Body", "4": "Work & Careers", "5": "Education & Exams", "6": "Travel & Transportation", "7": "Society", "8": "Arts & Culture", "9": "Animals & Living Beings", "10": "Nature & Environment", "11": "Science & Technology", "12": "Business & Economy", "13": "Law & Politics", "14": "Sports & Leisure", "15": "Emotions & Relationships", "16": "Other / Abstract"}. Output: {"results": [{"lemma": "...", "senses": [{"sense_id": "<exact sense id>", "topic_id": N, "topic_label": "<exact label>", "confidence": 0..1, "vector": [{"topic_id": N, "topic_label": "<exact label>", "weight": w}]}]}]}. Cover EVERY sense id from the input exactly once. Weights must sum to 1.0 (+-0.01). Input follows:\n',
    'v16b_defs': '1 Daily Life & Home: everyday routines, household, clothing, time. 2 Food & Drink: eating, cooking, food/drink items and the act of eating. 3 Health & Body: body parts, illness, medicine, hygiene. 4 Work & Careers: jobs, offices, meetings, professional life. 5 Education & Exams: school, study, exams, learning. 6 Travel & Transportation: trips, vehicles, directions, movement. 7 Society: community, traditions, social life, public affairs. 8 Arts & Culture: art, film, music, literature. 9 Animals & Living Beings: animals and living creatures, even if edible. 10 Nature & Environment: plants, earth, air, water, weather, landscapes. 11 Science & Technology: science, computers, devices, inventions. 12 Business & Economy: money, trade, markets, finance. 13 Law & Politics: rules, government, crime, rights. 14 Sports & Leisure: games, sports, hobbies, free-time fun. 15 Emotions & Relationships: feelings, family, friendship, love. 16 Other / Abstract: abstract, grammatical, or unclassifiable meanings.',
}


_LINE_DEFAULTS = {
    'judge_head': ('PICK the 1-4 most useful senses per item for Persian learners of English, ordered most-useful-first (one card = one atomic sense downstream, so rank every sense worth its own card).', 'Prioritization hierarchy:', "1. High-frequency tangible and conversational meaning over technical, academic, or domain-specific jargon (e.g., cooking/water boil > thermodynamic boil), UNLESS the item's pool_level is C1/C2 or all candidates are strictly abstract/technical.", '2. Modern living usage over archaic, obsolete, or highly regional dialectal senses.', '3. If candidates contain both an independent lexical meaning and a purely grammatical/inflectional reference, ALWAYS pick the independent lexical meaning.', '4. For modal/auxiliary verbs (would, could, should), the grammatical main sense takes absolute precedence over any nominal or philosophical sense.', 'Picked senses must be clearly different meanings (never two wordings of the same sense).', '', 'Output: {"results": [{"key": "<item key>", "picks": ["<sense_id>", ... up to 4]}]}.', 'A single "pick": "<sense_id>" row is also accepted (one sense).', "Every pick MUST be one of that item's candidate ids (empty picks only when the item has no candidates).", 'Input follows:'),
    'inflection_review_head': ('Judge EACH inflected form against its dictionary gloss.', 'Output: {"results": [{"key": "<item key>", "keep": true/false, "reason": "<why>"}]}.', 'Input follows:'),
}


PROMPT_NAMES = tuple(sorted(_TEXT_DEFAULTS) + sorted(_LINE_DEFAULTS))

_TEXT_NAMES = frozenset(_TEXT_DEFAULTS)
_LINE_NAMES = frozenset(_LINE_DEFAULTS)

_VARIANTS = {}
_ACTIVE = {}


def prompt_version(name):
    """Version tag of one registry entry (KeyError on unknown name)."""
    if name not in _TEXT_DEFAULTS and name not in _LINE_DEFAULTS:
        raise KeyError("unknown prompt: %r" % (name,))
    return PROMPTS_VERSION


def _coerce_variant(name, variant, text):
    if name in _TEXT_NAMES:
        if not isinstance(text, str):
            raise TypeError("text prompt %r variant must be str" % (name,))
        return text
    if not isinstance(text, (list, tuple)) or not all(
            isinstance(line, str) for line in text):
        raise TypeError("head prompt %r variant must be a list of str"
                        % (name,))
    return tuple(text)


def register_variant(name, variant, text):
    """Register an alternate wording under (name, variant).

    Unknown names fail closed (KeyError); the "default" variant name is
    reserved (ValueError); kind mismatch with the default fails closed
    (TypeError). Re-registering the same (name, variant) overwrites.
    """
    if name not in _TEXT_DEFAULTS and name not in _LINE_DEFAULTS:
        raise KeyError("unknown prompt: %r" % (name,))
    if variant == "default":
        raise ValueError('variant name "default" is reserved')
    _VARIANTS.setdefault(name, {})[variant] = _coerce_variant(
        name, variant, text)


def _env_selection():
    try:
        raw = os.environ.get(ENV_VAR, "")
    except Exception:
        return {}
    picked = {}
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(
                "%s must be NAME=variant,... (got %r)" % (ENV_VAR, chunk))
        name, _, variant = chunk.partition("=")
        picked[name.strip()] = variant.strip()
    return picked


def select(spec):
    """Activate variants: "name=variant,..." (repeatable via list input).

    "" / "default" / None clears every explicit pick (env still applies).
    A "default" variant clears that name. Unknown names/variants fail
    closed (KeyError) with NOTHING applied; malformed chunks (ValueError).
    """
    if spec is None:
        spec = ""
    if isinstance(spec, (list, tuple)):
        spec = ",".join(spec)
    spec = spec.strip()
    if spec in ("", "default"):
        _ACTIVE.clear()
        return
    picked = {}
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(
                "prompt selection must be NAME=variant,... (got %r)" % (chunk,))
        name, _, variant = chunk.partition("=")
        picked[name.strip()] = variant.strip()
    for name, variant in picked.items():
        if name not in _TEXT_DEFAULTS and name not in _LINE_DEFAULTS:
            raise KeyError("unknown prompt: %r" % (name,))
        if variant != "default" and variant not in _VARIANTS.get(name, {}):
            raise KeyError("unknown variant %r for prompt %r"
                           % (variant, name))
    for name, variant in picked.items():
        if variant == "default":
            _ACTIVE.pop(name, None)
        else:
            _ACTIVE[name] = variant


def selected_variant(name):
    """Active variant for one entry ("default" when none picked)."""
    if name not in _TEXT_DEFAULTS and name not in _LINE_DEFAULTS:
        raise KeyError("unknown prompt: %r" % (name,))
    if name in _ACTIVE:
        return _ACTIVE[name]
    try:
        env = _env_selection()
    except ValueError:
        env = {}
    return env.get(name, "default")


def reset():
    """Clear every explicit pick (variants stay registered)."""
    _ACTIVE.clear()


def _resolve(name):
    variant = None
    if name in _ACTIVE:
        variant = _ACTIVE[name]
    else:
        try:
            variant = _env_selection().get(name)
        except ValueError:
            variant = None
    if variant:
        try:
            return _VARIANTS[name][variant]
        except KeyError:
            raise KeyError("unknown variant %r for prompt %r"
                           % (variant, name))
    if name in _TEXT_DEFAULTS:
        return _TEXT_DEFAULTS[name]
    return _LINE_DEFAULTS[name]


def get_prompt(name, variant=None):
    """Resolve one text prompt (str). Explicit variant wins over select/env."""
    if name not in _TEXT_NAMES:
        raise KeyError("unknown text prompt: %r" % (name,))
    if variant is None:
        return _resolve(name)
    if variant == "default":
        return _TEXT_DEFAULTS[name]
    try:
        return _VARIANTS[name][variant]
    except KeyError:
        raise KeyError("unknown variant %r for prompt %r" % (variant, name))


def get_prompt_lines(name, variant=None):
    """Resolve one head prompt (tuple of lines)."""
    if name not in _LINE_NAMES:
        raise KeyError("unknown head prompt: %r" % (name,))
    if variant is None:
        return _resolve(name)
    if variant == "default":
        return _LINE_DEFAULTS[name]
    try:
        return _VARIANTS[name][variant]
    except KeyError:
        raise KeyError("unknown variant %r for prompt %r" % (variant, name))


# ---- legacy aliases (verbatim defaults; variant-aware call sites read
# through get_prompt/get_prompt_lines at call time) ----
TOPIC_TIEBREAK = _TEXT_DEFAULTS["topic_tiebreak"]
INFLECTION_REVIEW_SYS = _TEXT_DEFAULTS["inflection_review_sys"]
V15_USER_TMPL = _TEXT_DEFAULTS["v15_user_tmpl"]
TOPUP_USER_TMPL = _TEXT_DEFAULTS["topup_user_tmpl"]
V16B_DEFS = _TEXT_DEFAULTS["v16b_defs"]
JUDGE_HEAD = _LINE_DEFAULTS["judge_head"]
INFLECTION_REVIEW_HEAD = _LINE_DEFAULTS["inflection_review_head"]

__all__ = [
    "PROMPTS_VERSION", "ENV_VAR", "PROMPT_NAMES",
    "TOPIC_TIEBREAK", "INFLECTION_REVIEW_SYS", "V15_USER_TMPL",
    "TOPUP_USER_TMPL", "V16B_DEFS", "JUDGE_HEAD", "INFLECTION_REVIEW_HEAD",
    "prompt_version", "get_prompt", "get_prompt_lines",
    "register_variant", "select", "selected_variant", "reset",
]
