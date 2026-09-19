"""Linker gallery viewer v3: filterable static HTML over a link table + judge verdicts.

Read-only, stdlib only (inline CSS/JS, no network, no model). Renders from
a TSV link table + verdicts JSON (+ optional candidates JSON) straight into
one self-contained file.

Locked vocabulary (owner round 2) — used for every gauge, chip, filter key
and telemetry key; legacy codes survive ONLY as parenthetical aliases
inside evidence strings::

    lexical-overlap (Sa) · synonym-crossfire (Sb) · example-crossfire (Sc)
    hypernym-topic (Sd) · meaning-similarity (Se) · short-definition
    (short-gloss) · no-signal (0sig) · judge-vote · unanimous (3-0,
    same reason) · concordant (3-0, different reasons) · split-vote (2-1)

Round 3 (owner round 3): borrowed gauges from the judge report (verdict pie,
latency histogram, quality checklist — never its link display), live search,
per-step exact input components, naming polish (sentence + muted code),
sticky pill nav + density pass.

Round 4 (owner round 4): nav observer threshold split (short help section
without a negative rootMargin) + jump-to-table link + wider gloss column on
wide screens; filter OR-within-group/AND-across-groups + grouped chips +
now/tot only while filtering + global zero-results with clear-all; search
field prefixes (key:/kid:) + <mark> highlight + 175ms debounce; trace always
open + machine/raw merged into one tabbed details + +N signal badge +
is-winner candidate class; locked renames (gaps → تکمیل فیلدها, table
column → وضعیت/روش, crossfire display labels); per-record export array.

Page shape (less scroll): nav + gauges + filters + compact table (one row per
sense) with expandable per-card detail (same page, collapsible); technical
fields (machine JSON, raw evidence) behind one tabbed per-card collapsible.

Public entry: :func:`build_linker_gallery`.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import unicodedata
from collections import OrderedDict
from pathlib import Path

from factory.linker.cli import word_matches_kid
from factory.linker.linker import (
    JACCARD_DEFAULT,
    LINK_MIN_DEFAULT,
    QUARANTINE,
    SE_CUT,
    SE_VETO_FLOOR,
    SHORTLIST_CAP,
    ULTRA_SHORT_MIN_TOKENS,
    flow_trace_data,
    machine_block,
    norm_tokens,
    run_version,
    _stats_stage,
    signal_vocab,
    telemetry_counters,
    verdict_wire45,
)

# Gallery version: MAJOR.MINOR.PATCH-for-viewer — MAJOR = gallery
# rewrite/redesign, MINOR = new visible block or behavior change,
# PATCH = wording/fix-only change. Bump on every viewer-visible change.
GALLERY_VERSION = "4.0.0"

# Gallery changelog: one line per shipped round, dated (oldest first).
# Rendered in the footer collapsible; append (never rewrite) per round.
GALLERY_CHANGELOG = (
    ("2026-09-18", "flow-trace tracer: 5 nodes + 4 wires per card"),
    ("2026-09-19", "per-card scores only; decision cuts once page-wide"),
    ("2026-09-19", "signal sentences + shoot glossary; codes muted beside"),
    ("2026-09-19", "winner-def example fallback labeled example-shown-as-def"),
    ("2026-09-19", "navbar filter+search panel; sprawling drawer removed"),
    ("2026-09-19", "sticky filter panel under sticky nav; compact judge node"),
    ("2026-09-19", "judge wire follows verdict (pending-table is node-5 fact); "
                    "panel close button + compact caps"),
    ("2026-09-19", "flowtrace rewrite: S-flow 3-col RTL layout replaces old trace"),
    ("2026-09-19", "concordant tier beside unanimous/split (never certain)"),
    ("2026-09-19", "verdict-first wires + status badges on every card"),
    ("2026-09-19", "sticky toolbar + panel close button"),
    ("2026-09-19", "export redesign: per-record schema, capsule grouping"),
    ("2026-09-19", "certainty language removed (no certain-claim strings)"),
    ("2026-09-19", "candidate fallback renders winner when pack is empty"),
    ("2026-09-19", "NFKC parity: python + JS search normalize alike"),
    ("2026-09-19", "None-crash guard: null votes/verdicts render safe"),
    ("2026-09-19", "single-source vocab: chips read signal_vocab only"),
)

_GAP_SLOTS = ("def", "cefr", "syns", "antos", "example")

# EXPORT_SCHEMA (also documented in the gallery help panel) — round 4:
# per-record array, short fixed keys (NOT parallel dicts):
# {"records": [{kid, row_ref, lemma, in_def,
#   decision{method, winner, locator}, fires[{sig, val, cut, fired}],
#   winner_def (FULL, never truncated), candidates[{rank, key, j, def}],
#   judge{votes (compact), agree}, flags}]}
# judge + candidates are dropped per-record when their export-toolbar
# checkbox is off (both default ON; judge votes stay compact/small).
# row_ref is "<table filename>#L<1-based TSV line>" (header-aware: data
# row n lives on file line n+1). PIPELINE DEBT: rows carry no row_no
# column yet, so ordinals come from render order, not the table itself;
# a future pipeline change should stamp row_no at build time instead.


def _esc(text):
    return html.escape("" if text is None else str(text), quote=True)


# Round 4 display-label overrides (owner-locked): Sb/Sc FA display strings
# ONLY. Legacy codes (Sa..Sd) and raw evidence strings stay byte-identical
# everywhere; the canonical vocab in linker.py is untouched.
_SIGNAL_FA_DISPLAY = {
    "synonym-crossfire": "هم‌پوشانی مترادف‌ها",
    "example-crossfire": "هم‌پوشانی مثال‌ها",
}


def _disp_fa(name, fa):
    """Viewer display FA for a locked-vocab signal name."""
    return _SIGNAL_FA_DISPLAY.get(name, fa)


def parse_rule_chips(evidence):
    """Rule-fire chips from the rule half of an evidence string.

    >>> parse_rule_chips("Sa:j=0.33+Sd:hyp=record+judge-first")
    ['Sa:j=0.33', 'Sd:hyp=record', 'judge-first']
    >>> parse_rule_chips("0sig")
    ['0sig']
    >>> parse_rule_chips("Sd:hyp=move | judge:kaikki=\\"x\\" wordnet=\\"y\\"")
    ['Sd:hyp=move', 'judge']
    """
    text = evidence or ""
    rule, _, tail = text.partition("|")
    chips = [tok.strip() for tok in rule.split("+") if tok.strip()]
    if tail.strip():
        chips.append("judge")
    return chips


def signal_chips(evidence):
    """Rule tokens as ``(vocab_name, fa, alias_token)`` triples.

    Legacy codes stay ONLY as the parenthetical alias token.

    >>> signal_chips("Sa:j=0.40+Sd:hyp=move")
    [('lexical-overlap', 'هم‌پوشانی واژگان تعریف', 'Sa:j=0.40'), ('hypernym-topic', 'ابرنام/موضوع', 'Sd:hyp=move')]
    >>> signal_chips("0sig")
    [('no-signal', 'بی‌علامت', '0sig')]
    """
    out = []
    for tok in parse_rule_chips(evidence):
        if tok == "judge":
            code = "judge"
        elif tok.startswith("Sa:"):
            code = "Sa"
        elif tok.startswith("Sb:"):
            code = "Sb"
        elif tok.startswith("Sc:"):
            code = "Sc"
        elif tok.startswith("Sd:"):
            code = "Sd"
        elif tok.startswith("Se:"):
            code = "Se"
        elif "short-gloss" in tok:
            code = "short-gloss"
        elif tok in ("0sig", "zero-sig"):
            code = "zero-sig"
        elif "judge:" in tok:
            code = "judge"
        else:
            code = tok
        entry = signal_vocab(code)
        out.append((entry["name"], entry["fa"], tok))
    return out


def top_signal(row):
    """Locked-vocabulary name of the first firing rule signal (or no-signal).

    >>> top_signal({"evidence": "Sa:j=0.40+Sd:hyp=move"})
    'lexical-overlap'
    >>> top_signal({"evidence": "0sig"})
    'no-signal'
    >>> top_signal({"evidence": ""})
    'no-signal'
    """
    chips = signal_chips(row.get("evidence", ""))
    return chips[0][0] if chips else "no-signal"


def top_signal_fa(row):
    """FA sentence for the top signal (naming polish: sentence + muted code).

    >>> top_signal_fa({"evidence": "Sd:hyp=move"})
    ('ابرنام/موضوع', 'hypernym-topic')
    """
    chips = signal_chips(row.get("evidence", ""))
    if not chips:
        return ("بی‌علامت", "no-signal")
    return (_disp_fa(chips[0][0], chips[0][1]), chips[0][0])


def parse_twin_cefr(evidence):
    """Twin TSV CEFR labels carried in twinned evidence strings."""
    text = evidence or ""
    marker = "tsv-cefr="
    at = text.find(marker)
    if at < 0:
        return ""
    return text[at + len(marker):].split(";")[0].split("|")[0].strip()


def is_provisional(row):
    """True when flags or evidence mark a provisional hold."""
    return ("provisional" in (row.get("flags", "") or "")
            or "provisional" in (row.get("evidence", "") or ""))


def is_quarantined(row):
    """True for quarantined / known-false rows (red border)."""
    method = row.get("method", "") or ""
    flags = row.get("flags", "") or ""
    return (method == "quarantined-known-false"
            or "quarantin" in flags or "known-false" in flags)


def parse_wn_parts(text):
    """Split a ``gloss || words: a; b || eg: ...`` string.

    Returns ``(gloss, syns, example)``; missing parts are "" / [] / "".

    >>> parse_wn_parts("move fast || words: run || eg: run far")
    ('move fast', ['run'], 'run far')
    >>> parse_wn_parts("")
    ('', [], '')
    """
    gloss, syns, example = "", [], ""
    for part in (text or "").split("||"):
        chunk = part.strip()
        low = chunk.lower()
        if low.startswith("words:"):
            syns = [w.strip() for w in chunk[6:].split(";") if w.strip()]
        elif low.startswith("eg:"):
            example = chunk[3:].strip()
        elif chunk and not gloss:
            gloss = chunk
    return gloss, syns, example


_WS_RE = re.compile(r"\s+")


def _norm_evidence_text(text):
    """Normalize one quoted evidence: strip + collapse whitespace."""
    return _WS_RE.sub(" ", str(text or "")).strip()


def _vote_evidence_key(vote):
    """Normalized (kaikki, wordnet) evidence pair quoted by one vote."""
    vote = vote or {}
    return (_norm_evidence_text(vote.get("kaikki_evidence")),
            _norm_evidence_text(vote.get("wordnet_evidence")))


def verdict_summary(verdicts):
    """Judge-agreement counters over verdict dicts (verdicts may be empty).

    ``unanimous`` needs same verdict + same winner + same normalized
    evidences; same verdict + same winner with divergent evidences is
    ``concordant`` (needs review, like split — never certain).
    """
    total = len(verdicts or [])
    judged = unanimous = concordant = split = link = none = failed = 0
    for item in verdicts or []:
        votes = item.get("votes") or []
        ok_votes = [v for v in votes if v.get("ok")]
        verdict = item.get("verdict")
        if verdict == "LINK":
            link += 1
        elif verdict == "NONE":
            none += 1
        else:
            failed += 1
        if len(ok_votes) < 2:
            continue
        judged += 1
        winners = {v.get("winner_index") for v in ok_votes}
        verdict_kinds = {v.get("verdict") for v in ok_votes}
        if len(winners) == 1 and len(verdict_kinds) == 1:
            evidences = {_vote_evidence_key(v) for v in ok_votes}
            if len(evidences) == 1:
                unanimous += 1
            else:
                concordant += 1
        else:
            split += 1
    return {
        "total": total, "judged": judged, "unanimous": unanimous,
        "concordant": concordant,
        "split": split, "link": link, "none": none, "failed": failed,
    }


def agreement_key(item):
    """Locked-vocabulary agreement key: unanimous / concordant / split-vote / unjudged.

    Unanimous needs same verdict + same winner + same normalized
    evidences (strip + collapse-whitespace on both evidence fields);
    same verdict + same winner with divergent evidences is concordant.

    >>> agreement_key({"votes": [{"ok": True, "verdict": "LINK", "winner_index": 1}]})
    'unjudged'
    >>> agreement_key({"votes": [{"ok": True, "verdict": "LINK", "winner_index": 1}] * 3})
    'unanimous'
    >>> agreement_key({"votes": [
    ...     {"ok": True, "verdict": "LINK", "winner_index": 1,
    ...      "kaikki_evidence": "gloss", "wordnet_evidence": "wn"},
    ...     {"ok": True, "verdict": "LINK", "winner_index": 1,
    ...      "kaikki_evidence": "example quote", "wordnet_evidence": "wn"},
    ... ]})
    'concordant'
    """
    votes = (item or {}).get("votes") or []
    ok_votes = [v for v in votes if v.get("ok")]
    if len(ok_votes) < 2:
        return "unjudged"
    winners = {v.get("winner_index") for v in ok_votes}
    verdict_kinds = {v.get("verdict") for v in ok_votes}
    if len(winners) == 1 and len(verdict_kinds) == 1:
        evidences = {_vote_evidence_key(v) for v in ok_votes}
        if len(evidences) == 1:
            return "unanimous"
        return "concordant"
    return "split-vote"


def _agreement_label(item):
    key = agreement_key(item)
    if key == "unanimous":
        return "agree", "آرای یکدست · unanimous"
    if key == "concordant":
        # Needs-review like split: same vote, different quoted reasons —
        # the "split" badge class keeps the amber provisional styling.
        return "split", "هم‌نظر در رأی، متفاوت در دلیل (concordant)"
    if key == "split-vote":
        return "split", "آرای دوشقه · split-vote"
    return "unjudged", "رأی ثبت نشده · unjudged"


def outcome_key(verdict):
    """LINK / NONE / - outcome key for the verdict filter."""
    verdict = (verdict or {}).get("verdict") or ""
    if verdict in ("LINK", "NONE"):
        return verdict
    return "-"


# Canonical locked-vocabulary signal names allowed as ``sig:`` filter keys.
# Audit rule (owner gallery round 5): every filter key must match real
# data — raw evidence tokens (``edge:…``, ``inventory…``, ``judge-first``,
# ``no-candidates:…``, ``best-cand-twinned…``) fall through signal_vocab()
# with name == code and must NEVER become filter keys.
_CANON_SIG_NAMES = frozenset({
    signal_vocab(code)["name"]
    for code in ("Sa", "Sb", "Sc", "Sd", "Se", "short-gloss",
                 "zero-sig", "judge")
})

# Real Persian rule names for mechanical (judge-less) LINK methods — a
# rule win shows one of these, never a bare «قاعده».
_RULE_FA = {
    "LINK:2-sig": "پیوند قاعده‌ای: ۲ سیگنال مستقل",
    "LINK:3-sig": "پیوند قاعده‌ای: ۳ سیگنال مستقل",
    "LINK:exact-sensekey+2-sig": "پیوند قاعده‌ای: کلیددقیق + ۲ سیگنال",
}


def _rule_fa(method):
    """Real Persian rule name for a mechanical LINK method.

    >>> _rule_fa("LINK:2-sig")
    'پیوند قاعده‌ای: ۲ سیگنال مستقل'
    >>> _rule_fa("LINK:exact-sensekey+2-sig")
    'پیوند قاعده‌ای: کلیددقیق + ۲ سیگنال'
    >>> _rule_fa("LINK:judge-v2")
    'پیوند با داور'
    """
    method = method or ""
    if method in _RULE_FA:
        return _RULE_FA[method]
    if method.startswith("LINK:exact-sensekey"):
        return "پیوند قاعده‌ای: کلیددقیق + سیگنال"
    if method.startswith("LINK:judge-v2"):
        return "پیوند با داور"
    if method.startswith("LINK"):
        # Digits-only fallback: hostile method text can never leak here.
        n = "".join(ch for ch in method if ch.isdigit()) or "؟"
        return "پیوند قاعده‌ای: %s سیگنال مستقل" % n
    return _method_fa(method)


def _is_mechanical_link(row, verdict=None):
    """True for judge-less rule-decided LINK rows (gallery filter ``src:mechanical``).

    Mechanical = method is a rule LINK (``LINK:2-sig``,
    ``LINK:exact-sensekey+2-sig``, ``LINK:3-sig`` …) with NO judge
    verdict attached. Judge-driven (``LINK:judge-v2``) and owner
    overrides (``LINK:manual-override``) never count, even verdict-less.

    >>> _is_mechanical_link({"method": "LINK:2-sig"}, {})
    True
    >>> _is_mechanical_link({"method": "LINK:exact-sensekey+2-sig"}, None)
    True
    >>> _is_mechanical_link({"method": "LINK:judge-v2"}, {})
    False
    >>> _is_mechanical_link({"method": "LINK:2-sig"}, {"verdict": "LINK"})
    False
    >>> _is_mechanical_link({"method": "JUDGE-PENDING"}, {})
    False
    """
    method = ((row or {}).get("method", "") or "")
    if not method.startswith("LINK"):
        return False
    if "judge" in method or "manual" in method:
        return False
    return not (verdict or {})


def _winner_def_status(row, verdict=None):
    """(kind, text) for the winner definition shown gallery-side.

    Kinds: ``def`` (a real definition), ``example-as-def`` (upstream
    judge quoted a BARE example sentence — no ``||`` structure — where
    a ``gloss || words: .. || eg: ..`` string belongs; never present it
    as a definition, label it explicitly), ``missing`` (honest gap).

    >>> _winner_def_status({"wordnet_gloss": "move fast"}, {})
    ('def', 'move fast')
    >>> _winner_def_status({}, {"wordnet_evidence": "move fast || words: run"})
    ('def', 'move fast')
    >>> _winner_def_status({}, {"wordnet_evidence": "who are these people running around?"})
    ('example-as-def', 'who are these people running around?')
    >>> _winner_def_status({}, {})
    ('missing', '')
    """
    row = row or {}
    for key in ("wordnet_gloss", "winner_def"):
        val = (row.get(key) or "").strip()
        if val and val != "-":
            return ("def", val)
    raw = ((verdict or {}).get("wordnet_evidence", "") or "").strip()
    if not raw:
        return ("missing", "")
    if "||" not in raw:
        return ("example-as-def", raw)
    gloss, _syns, _eg = parse_wn_parts(raw)
    if gloss:
        return ("def", gloss)
    return ("missing", "")


def _winner_def_from_row(row, verdict=None):
    """Winner definition from data already on the row (no recompute).

    Returns the definition text ONLY when it really is one; a bare
    upstream example sentence (see :func:`_winner_def_status`) yields ""
    so callers render the labeled ``example-shown-as-def (upstream)``
    fallback instead of mislabeling it. Empty string = honest gap (the
    caller renders the gap line, never a silent empty node).

    >>> _winner_def_from_row({"wordnet_gloss": "move fast"}, {})
    'move fast'
    >>> _winner_def_from_row({}, {"wordnet_evidence": "move fast || words: run"})
    'move fast'
    >>> _winner_def_from_row({}, {"wordnet_evidence": "who runs around?"})
    ''
    >>> _winner_def_from_row({}, {})
    ''
    """
    kind, text = _winner_def_status(row, verdict)
    return text if kind == "def" else ""


# Flag → color-chip class (node-5): green filled ok, amber provisional,
# red quarantine, purple twin. Judge/owner tags fall back to green.
def _flag_chip(flag):
    """Color chip for one flag (FA sentence + raw code, never plain text)."""
    flag = flag or ""
    if "quarantin" in flag or "known-false" in flag:
        cls = "flag-quar"
    elif "provisional" in flag:
        cls = "flag-prov"
    elif "twin" in flag:
        cls = "flag-twin"
    elif flag.startswith("judge-v2"):
        cls = "flag-judge"
    else:
        cls = "flag-ok"
    return ('<span class="flagchip %s">%s '
            '<span class="code">(<bdi>%s</bdi>)</span></span>'
            % (cls, _esc(_flag_fa(flag)), _esc(flag)))


def _group_votes(verdict):
    """Group ok votes by (verdict, winner, normalized evidence pair).

    DIFF-VIEW: identical repeated votes collapse to one group rendered
    ONCE with ×N; per-vote blocks appear only for differing content.
    First-seen order is kept.

    >>> v = {"votes": [
    ...     {"ok": True, "verdict": "LINK", "winner_index": 1, "seed": 42,
    ...      "kaikki_evidence": "g", "wordnet_evidence": "w"},
    ...     {"ok": True, "verdict": "LINK", "winner_index": 1, "seed": 43,
    ...      "kaikki_evidence": "g", "wordnet_evidence": "w"},
    ...     {"ok": True, "verdict": "LINK", "winner_index": 2, "seed": 44,
    ...      "kaikki_evidence": "g2", "wordnet_evidence": "w2"}]}
    >>> [(g["verdict"], g["winner"], g["count"], g["seeds"]) for g in _group_votes(v)]
    [('LINK', 1, 2, [42, 43]), ('LINK', 2, 1, [44])]
    """
    groups = OrderedDict()
    for vote in (verdict or {}).get("votes") or []:
        vote = vote or {}
        if not vote.get("ok"):
            continue
        key = (vote.get("verdict"), vote.get("winner_index"),
               _vote_evidence_key(vote))
        groups.setdefault(key, []).append(vote)
    out = []
    for (verdict_name, winner, _ev), votes in groups.items():
        out.append({"verdict": verdict_name, "winner": winner,
                    "ev": _vote_evidence_key(votes[0]),
                    "seeds": [v.get("seed", "?") for v in votes],
                    "lats": [v.get("latency_s") for v in votes],
                    "count": len(votes)})
    return out


# Single source: stage bucketing lives in linker._stats_stage (covers all 13
# LINK_METHOD_VOCAB methods); this alias keeps existing call sites working.
_stage_of = _stats_stage


def _fgroup_of(key):
    """Filter group of one key: the prefix before ``:`` (stage/sig/...)."""
    key = key or ""
    return key.split(":", 1)[0] if ":" in key else key


def row_matches_filters(keys, active):
    """OR within one key group, AND across groups (round 4 real fix).

    Same-group keys (``stage:link`` + ``stage:none``) used to AND and
    always match nothing; now one hit per touched group suffices.

    >>> row_matches_filters(["stage:link"], {"stage:link", "stage:none"})
    True
    >>> row_matches_filters(["stage:link"], {"stage:link", "sig:judge-vote"})
    False
    >>> row_matches_filters(["stage:link"], set())
    True
    """
    keys = set(keys or [])
    active = set(active or [])
    if not active:
        return True
    groups = {}
    for item in active:
        groups.setdefault(_fgroup_of(item), set()).add(item)
    return all(keys & wanted for wanted in groups.values())


def row_filter_keys(row, verdict, check_keys=()):
    """Filter keys carried by one card (matched OR-in-group/AND-across).

    ``sig:`` keys are canonical locked-vocabulary names only (raw
    evidence tokens never leak in — see ``_CANON_SIG_NAMES``).
    Judge-less rule LINKs additionally carry ``src:mechanical``.

    >>> sorted(row_filter_keys({"method": "LINK:2-sig", "evidence": "Sa:j=0.4", "flags": ""}, {}))
    ['judge:unjudged', 'outcome:-', 'sig:lexical-overlap', 'src:mechanical', 'stage:link']
    >>> sorted(row_filter_keys({"method": "JUDGE-PENDING", "evidence": "edge:obsolete+Sd:hyp=x", "flags": ""}, {}))
    ['judge:unjudged', 'outcome:-', 'sig:hypernym-topic', 'stage:pending']
    """
    keys = ["stage:" + _stage_of(row.get("method", ""))]
    if is_provisional(row):
        keys.append("stage:provisional")
    for name, _fa, _alias in signal_chips(row.get("evidence", "")):
        if name in _CANON_SIG_NAMES:
            keys.append("sig:" + name)
    if not signal_chips(row.get("evidence", "")):
        keys.append("sig:no-signal")
    keys.append("judge:" + agreement_key(verdict))
    keys.append("outcome:" + outcome_key(verdict))
    if verdict and outcome_key(verdict) == "-":
        # Failed judge rows (verdict None / vote_status FAILED) keep the
        # legacy "-" key AND carry the pie-slice FAILED key.
        keys.append("outcome:FAILED")
    if _is_mechanical_link(row, verdict):
        keys.append("src:mechanical")
    keys.extend(check_keys or ())
    return sorted(set(keys))


# --- Search (round 3): normalized substring match over lemma/gloss/keys ---

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
_LAT_DIGITS = "0123456789" * 2
_DIGIT_TRANS = str.maketrans(_FA_DIGITS, _LAT_DIGITS)


def normalize_search(text):
    """Normalize for search: NFKC + lowercase + Persian/Arabic digits → Latin.

    >>> normalize_search("رفتن ۱۲۳")
    'رفتن 123'
    >>> normalize_search("Run FAST")
    'run fast'
    """
    return unicodedata.normalize(
        "NFKC", "" if text is None else str(text)).lower().translate(
            _DIGIT_TRANS)


def search_haystack(row, verdict):
    """Normalized combined haystack: lemma/gloss/sensekey/evidence.

    >>> "run" in search_haystack({"lemma": "Run", "kaikki_gloss": "To move", "kaikki_sense_id": "k", "wordnet_sensekey": "s", "evidence": "e"}, {})
    True
    """
    verdict = verdict or {}
    parts = [
        row.get("lemma", ""), row.get("kaikki_gloss", ""),
        row.get("kaikki_sense_id", ""), row.get("wordnet_sensekey", ""),
        row.get("evidence", ""),
        verdict.get("winner_sensekey", "") or "",
        verdict.get("wordnet_evidence", "") or "",
    ]
    return normalize_search(" ".join(p for p in parts if p))


def match_search(row, verdict, query):
    """Normalized search with field prefixes checked before substring.

    ``kid:<id>`` matches the kaikki sense id only; ``key:<sensekey>``
    matches the row winner key or the judge winner sensekey. Anything
    else is a normalized substring over the haystack. Empty query
    matches everything (no search filter).

    >>> row = {"lemma": "run", "kaikki_gloss": "", "kaikki_sense_id": "k1",
    ...        "wordnet_sensekey": "run%2:38:00::", "evidence": ""}
    >>> (match_search(row, {}, "kid:k1"), match_search(row, {}, "kid:k2"))
    (True, False)
    >>> (match_search(row, {}, "key:run%2:38"), match_search(row, {}, "key:take"))
    (True, False)
    >>> match_search(row, {}, "RUN")
    True
    >>> match_search(row, {}, "take")
    False
    """
    query = normalize_search(query).strip()
    if not query:
        return True
    if query.startswith("kid:"):
        needle = query[4:].strip()
        return bool(needle) and needle in normalize_search(
            row.get("kaikki_sense_id", ""))
    if query.startswith("key:"):
        needle = query[4:].strip()
        hay = normalize_search(" ".join([
            row.get("wordnet_sensekey", ""),
            (verdict or {}).get("winner_sensekey", "") or "",
        ]))
        return bool(needle) and needle in hay
    return query in search_haystack(row, verdict)


# --- Latency gauges (round 3, borrowed from the judge report) ---

_LATENCY_BUCKETS = [
    (0, 3, "0-3s"), (3, 6, "3-6s"), (6, 9, "6-9s"), (9, 12, "9-12s"),
    (12, 15, "12-15s"), (15, 18, "15-18s"), (18, 25, "18-25s"),
    (25, None, "25s+"),
]


def verdict_latencies(verdicts):
    """All per-vote latency_s floats across verdicts (order kept).

    >>> verdict_latencies([{"votes": [{"latency_s": 7.0}, {"latency_s": "x"}]}])
    [7.0]
    """
    out = []
    for item in verdicts or []:
        for vote in item.get("votes") or []:
            lat = vote.get("latency_s")
            if isinstance(lat, bool):
                continue
            if isinstance(lat, (int, float)):
                out.append(float(lat))
    return out


def latency_stats(latencies):
    """Bucket counts + avg/p50/p90/max over per-vote latencies.

    >>> s = latency_stats([6.0, 7.0, 8.0, 9.0])
    >>> ([b["count"] for b in s["buckets"]], s["avg"], s["p50"], s["p90"], s["max"])
    ([0, 0, 3, 1, 0, 0, 0, 0], 7.5, 8.0, 9.0, 9.0)
    >>> latency_stats([])["n"]
    0
    """
    lats = sorted(float(v) for v in (latencies or []))
    buckets = []
    for lo, hi, label in _LATENCY_BUCKETS:
        if hi is None:
            count = sum(1 for v in lats if v >= lo)
        else:
            count = sum(1 for v in lats if lo <= v < hi)
        buckets.append({"label": label, "lo": lo, "hi": hi, "count": count})
    if not lats:
        return {"buckets": buckets, "n": 0, "avg": None,
                "p50": None, "p90": None, "max": None}

    def _pct(p):
        idx = min(len(lats) - 1, int(p * len(lats)))
        return lats[idx]

    return {"buckets": buckets, "n": len(lats),
            "avg": sum(lats) / len(lats), "p50": _pct(0.5),
            "p90": _pct(0.9), "max": lats[-1]}


# --- Quality checklist (round 3, borrowed check/value/status shape) ---

_CHECKS = [
    ("link-evidence", "هر پیوند مدرک دارد", "every-LINK-has-evidence"),
    ("quarantine-clean", "قرنطینه هرگز پیوند نمی‌خورد", "quarantine-never-LINK"),
    ("twin-clean", "دوقلو هرگز پیوند نمی‌خورد", "twin-never-LINK"),
    ("unanimous-rate", "نرخ اجماع داوران", "unanimous-rate"),
    ("response-cap", "پاسخ‌ها بدون بریدگی سقف", "response-cap-zero-truncation"),
    ("counts-reconcile", "جمع شمارش‌ها می‌خواند", "counts-reconcile"),
]


def quality_checks(rows, verdicts):
    """Automated checklist: [{id, fa, en, value, status, violators}].

    Status is PASS/WARN. ``violators`` are kaikki kids whose cards carry
    the ``check:<id>`` filter key (click a row to isolate them; empty =
    all-clear state).

    >>> rows = [{"kaikki_sense_id": "k1", "method": "LINK:2-sig", "evidence": "", "flags": ""}]
    >>> checks = quality_checks(rows, [])
    >>> {c["id"]: (c["status"], c["violators"]) for c in checks}["link-evidence"]
    ('WARN', ['k1'])
    """
    rows = list(rows or [])
    verdicts = list(verdicts or [])
    judge = verdict_summary(verdicts)
    by_kid = {v.get("kid"): v for v in verdicts if v.get("kid")}

    link_bare, quar_link, twin_link = [], [], []
    for row in rows:
        kid = row.get("kaikki_sense_id", "") or ""
        method = row.get("method", "") or ""
        evidence = row.get("evidence", "") or ""
        flags = row.get("flags", "") or ""
        if not method.startswith("LINK"):
            continue
        if not evidence.strip():
            link_bare.append(kid)
        if kid in QUARANTINE or "quarantin" in flags or "known-false" in flags:
            quar_link.append(kid)
        if "twinned" in evidence or "twin-pending" in flags:
            twin_link.append(kid)

    split_kids = [v.get("kid") for v in verdicts
                  if v.get("kid") and agreement_key(v) == "split-vote"]
    judged = judge["judged"]
    rate = (judge["unanimous"] / judged) if judged else 1.0

    trunc_kids = []
    n_votes = 0
    for item in verdicts:
        for vote in item.get("votes") or []:
            n_votes += 1
            note = (vote.get("note") or "").lower()
            if "truncat" in note or (
                    not vote.get("ok") and not (vote.get("raw") or "")):
                trunc_kids.append(item.get("kid"))
                break
    trunc_kids = sorted(set(k for k in trunc_kids if k))

    tele = telemetry_counters(rows)
    stage_sum = sum(v for k, v in tele["stage"].items() if k != "provisional")
    counts_ok = (stage_sum == tele["total"]
                 and judge["link"] + judge["none"] + judge["failed"]
                 == judge["total"])

    return [
        {"id": "link-evidence",
         "fa": "هر پیوند مدرک دارد", "en": "every-LINK-has-evidence",
         "value": "%d بی‌مدرک / %d پیوند" % (len(link_bare),
                                              tele["stage"]["link"]),
         "status": "PASS" if not link_bare else "WARN",
         "violators": sorted(set(link_bare))},
        {"id": "quarantine-clean",
         "fa": "قرنطینه هرگز پیوند نمی‌خورد",
         "en": "quarantine-never-LINK",
         "value": "%d تخلف قرنطینه" % len(quar_link),
         "status": "PASS" if not quar_link else "WARN",
         "violators": sorted(set(quar_link))},
        {"id": "twin-clean",
         "fa": "دوقلو هرگز پیوند نمی‌خورد", "en": "twin-never-LINK",
         "value": "%d تخلف دوقلو" % len(twin_link),
         "status": "PASS" if not twin_link else "WARN",
         "violators": sorted(set(twin_link))},
        {"id": "unanimous-rate",
         "fa": "نرخ اجماع داوران", "en": "unanimous-rate",
         "value": ("—" if not judged else "%d%% (%d/%d اجماعی)"
                   % (round(100 * rate), judge["unanimous"], judged)),
         "status": "PASS" if rate >= 0.5 else "WARN",
         "violators": sorted(set(split_kids))},
        {"id": "response-cap",
         "fa": "پاسخ‌ها بدون بریدگی سقف",
         "en": "response-cap-zero-truncation",
         "value": "%d بریده / %d رأی" % (len(trunc_kids), n_votes),
         "status": "PASS" if not trunc_kids else "WARN",
         "violators": trunc_kids},
        {"id": "counts-reconcile",
         "fa": "جمع شمارش‌ها می‌خواند", "en": "counts-reconcile",
         "value": "سطرها %d=%d · آرا %d=%d" % (
             stage_sum, tele["total"],
             judge["link"] + judge["none"] + judge["failed"],
             judge["total"]),
         "status": "PASS" if counts_ok else "WARN",
         "violators": []},
    ]


def _vote_badges(item):
    votes = item.get("votes") or []
    badges = []
    for vote in votes:
        verdict = vote.get("verdict") or "?"
        winner = vote.get("winner_index")
        label = "%s#%s (seed %s)" % (
            verdict, winner if winner is not None else "-", vote.get("seed", "?"))
        cls = "vote-link" if verdict == "LINK" else (
            "vote-none" if verdict == "NONE" else "vote-fail")
        badges.append('<span class="vote %s"><bdi>%s</bdi></span>'
                      % (cls, _esc(label)))
    return " ".join(badges)


def _render_agreement_lines(verdict, winner_label=None):
    """Collapsed agreement lines: ONE per (verdict, winner) position.

    Identical agreements render ONCE with ×N (DIFF-VIEW); only divergent
    positions get their own line. A concordant/split card therefore shows
    a single agreement line plus the expanded divergent reasons.
    ``winner_label`` (a winner sensekey) replaces the raw winner index
    in the compact judge node so the verdict line quotes the key once.
    """
    groups = _group_votes(verdict)
    positions = OrderedDict()
    for group in groups:
        key = (group["verdict"], group["winner"])
        positions.setdefault(key, []).append(group)
    lines = []
    for (verdict_name, winner), members in positions.items():
        total = sum(g["count"] for g in members)
        if verdict_name == "LINK":
            fa_v = "پیوند"
        elif verdict_name == "NONE":
            fa_v = "بدون‌پیوند"
        else:
            fa_v = "ناموفق/ناشناخته"
        rep = (" <span class='rep'>×%d</span>" % total) if total > 1 else ""
        shown = winner_label if winner_label is not None else (
            winner if winner is not None else "—")
        lines.append(
            "<div class='agree-line'>رأی: <b>%s</b> "
            '<span class="code">(<bdi>%s</bdi>)</span> · برنده '
            "<bdi>%s</bdi>%s</div>"
            % (_esc(fa_v), _esc(verdict_name or "—"),
               _esc(shown), rep))
    return "".join(lines)


def _render_judge_votes(verdict):
    """Compact per-group quote list (DIFF-VIEW over _group_votes).

    Identical votes render ONCE with ×N + every quoting seed; the quoted
    reason appears a single time per group. Only differing content
    (different winner/verdict/quote) gets its own block. Verdict + winner
    live ONCE in the compact verdict/winner lines above, so each item
    carries ONLY its quote + seeds (no verdict/winner repeat). Class
    names (``votelist vote-minis`` / ``vote-mini``) and the «نقل دلیل»
    marker are kept for the existing gallery contracts.
    """
    groups = _group_votes(verdict)
    if not groups:
        return "—"
    # Seeds live ONCE in the compact seeds line; per-item seed tags appear
    # ONLY on divergent cards (len(groups) > 1) so the identical-votes
    # single block never repeats them.
    divergent = len(groups) > 1
    items = []
    for group in groups:
        kaikki_q, wn_q = group["ev"]
        rep = (" <span class='rep'>×%d</span>" % group["count"]
               if group["count"] > 1 else "")
        if divergent:
            seeds = " (<bdi>%s</bdi>)" % _esc(
                " · ".join("seed %s" % s for s in group["seeds"]))
        else:
            seeds = ""
        items.append(
            "<li class='vote-mini'>نقل دلیل: kaikki “<bdi>%s</bdi>” · "
            "wordnet: “<bdi>%s</bdi>”%s%s</li>"
            % (_esc(kaikki_q or "—"), _esc(wn_q or "—"), seeds, rep))
    return "<ol class='votelist vote-minis'>%s</ol>" % "".join(items)


def _render_judge_compact(verdict, winner_key, flags, agree,
                          judge_title, judge_why):
    """Compact judge node body: every string renders ONCE (×N for repeats).

    Header (title; the LLM badge lives once in the node-4 card header
    ft-badge) + latency-seeds collapsible; verdict line ONCE (via _render_agreement_lines with the winner sensekey); winner
    line ONCE; latencies inline; a single نقل دلیل quote per identical
    group (concordant divergences expand via _render_distinct_reasons
    instead of quote lis); seeds line once; flags line once. Per-vote
    blocks appear ONLY for differing content.
    """
    votes = [v for v in (verdict or {}).get("votes") or []
             if (v or {}).get("ok")]
    lats = []
    for vote in votes:
        lat = (vote or {}).get("latency_s")
        if isinstance(lat, bool):
            continue
        if isinstance(lat, (int, float)):
            txt = "%.1fs" % lat
            if txt not in lats:
                lats.append(txt)
    lat_txt = " • ".join(lats) if lats else "—"
    seeds = " • ".join(
        "seed %s" % (v or {}).get("seed", "?") for v in votes) or "—"
    winner_shown = (verdict or {}).get("winner_sensekey") or winner_key or "—"
    agree_html = _render_agreement_lines(verdict, winner_label=winner_shown)
    if not agree_html and (verdict or {}).get("verdict"):
        # Vote-less verdict (e.g. upstream example-as-def rows): single
        # verdict line from the top-level fields, never per-vote blocks.
        raw = (verdict or {}).get("verdict") or "—"
        fa_v = ("پیوند" if raw == "LINK" else
                "بدون‌پیوند" if raw == "NONE" else "ناموفق/ناشناخته")
        agree_html = (
            "<div class='agree-line'>رأی: <b>%s</b> "
            '<span class="code">(<bdi>%s</bdi>)</span> · برنده '
            "<bdi>%s</bdi></div>"
            % (_esc(fa_v), _esc(raw), _esc(winner_shown)))
    if agree == "concordant":
        quotes = _render_distinct_reasons(verdict)
    else:
        quotes = _render_judge_votes(verdict)
    flag_chips = (" ".join(_flag_chip(f) for f in (flags or []))
                  if flags else "—")
    return (
        "<div class='jhead'>%s</div>"
        "<details class='jlatseeds'><summary>تأخیرها: <bdi>%s</bdi> "
        "<span class='en' lang='en'>latencies</span></summary>"
        "<div class='jseeds'>بذرها: <bdi>%s</bdi> "
        "<span class='code'>(<bdi>seeds</bdi>)</span></div></details>"
        "%s"
        "<div class='jwinner'>برنده: <bdi class='wkey'>%s</bdi></div>"
        "%s"
        "<div class='jflags'>پرچم‌ها: %s</div>"
        % (_esc(judge_title), _esc(lat_txt), _esc(seeds),
           agree_html,
           _esc(winner_shown), quotes, flag_chips))


def _render_distinct_reasons(verdict):
    """Distinct quoted reasons for concordant cards: each once + seed tags.

    Groups ok votes by normalized evidence pair (first-seen order);
    identical quotes collapse to one line tagged with every quoting seed
    plus ×N when a group holds more than one vote (DIFF-VIEW).
    """
    groups = OrderedDict()
    for vote in (verdict or {}).get("votes") or []:
        if not (vote or {}).get("ok"):
            continue
        groups.setdefault(_vote_evidence_key(vote), []).append(
            vote.get("seed", "?"))
    items = []
    for (kaikki_q, wn_q), seeds in groups.items():
        tags = ", ".join("seed %s" % s for s in seeds)
        rep = (" <span class='rep'>×%d</span>" % len(seeds)
               if len(seeds) > 1 else "")
        items.append(
            "<li><span class='seeds'>(<bdi>%s</bdi>)</span>%s "
            "kaikki: “<bdi>%s</bdi>” · wordnet: “<bdi>%s</bdi>”</li>"
            % (_esc(tags), rep, _esc(kaikki_q or "—"), _esc(wn_q or "—")))
    return ("<div class='flowtrace-reasons'>"
            "<div class='flowtrace-reasonstitle'>"
            "دلایل متفاوت نقل‌شده (concordant):</div>"
            "<ul class='reasonlist'>%s</ul></div>" % "".join(items))


def _gap_cells(row, verdict):
    verdict = verdict or {}
    # Winner-def rule: a bare upstream example must never fill the def
    # slot with a ✓ — only a real definition transfers (the labeled
    # example fallback lives in the winner area, not here).
    kind, wdef = _winner_def_status(row, verdict)
    gloss = wdef if kind == "def" else ""
    raw = (verdict.get("wordnet_evidence", "") or "")
    if "||" in raw:
        _g, syns, example = parse_wn_parts(raw)
    else:
        syns, example = [], ""
    cefr = parse_twin_cefr(row.get("evidence", ""))
    return [
        ("def", "تعریف", "def", gloss or "—", "wordnet"),
        ("cefr", "سطح", "cefr", cefr or "—", "tsv-cefr"),
        ("syns", "مترادف‌ها", "syns", "; ".join(syns) if syns else "—", "wordnet"),
        ("antos", "متضادها", "antos", "—", "—"),
        ("example", "مثال + منبع", "example+src",
         ("%s (wordnet)" % example) if example else "—", "wordnet"),
    ]


def _signal_exact(name, alias):
    """Human sentence quoting the EXACT token/word/score that fired.

    Per-case numbers only — decision cuts live ONCE in the page-level
    global constants block, never here. No step shows a bare code:
    every code ships with its sentence.
    """
    if name == "lexical-overlap":
        point = alias.split("j=")[-1] if "j=" in alias else "?"
        return ("هم‌پوشانی واژگان تعریف: نمره جاکارد ‏%s‏ از واژه‌های مشترک "
                "دو تعریف آمد، پس ۱ امتیاز" % point)
    if name == "synonym-crossfire":
        word = alias.split(":", 1)[-1]
        return ("هم‌پوشانی مترادف‌ها: واژه مشترک ‏‘%s’‏ در هر دو فهرست هست، "
                "پس ۱ امتیاز" % word)
    if name == "example-crossfire":
        word = alias.split(":", 1)[-1]
        return ("هم‌پوشانی مثال‌ها: واژه مشترک مثال ‏‘%s’‏ در هر دو نمونه هست، "
                "پس ۱ امتیاز" % word)
    if name == "hypernym-topic":
        if "=" in alias:
            head, _, word = alias.partition("=")
            if "hyp" in head:
                return ("ابرنام/موضوع مشترک ‏‘%s’‏: در رده‌بندی معنایی هر دو "
                        "تعریف هست، پس ۱ امتیاز" % word)
            return ("موضوع مشترک ‏‘%s’‏: در هر دو تعریف هست، پس ۱ امتیاز"
                    % word)
        return ("ابرنام/موضوع مشترک دیده شد: در رده‌بندی معنایی هست، "
                "پس ۱ امتیاز")
    if name == "meaning-similarity":
        score = alias.split(":", 1)[-1]
        return ("شباهت معنایی: نمره ‏%s‏ از سنجش معنایی آمد، پس ۱ امتیاز"
                % score)
    if name == "short-definition":
        return "تعریف خیلی کوتاه بود پس مستقیم به داور رفت"
    if name == "no-signal":
        return "هیچ سیگنالی شلیک نکرد پس نگاشت‌نشده ماند"
    if name == "judge-vote":
        return "داور وارد میدان شد و رأی داد"
    return "سیگنال ناشناخته ثبت شد: ‏‘%s’‏" % alias


# Glossary for «شلیک»: full quorum-numbered form lives ONCE in the
# page-level global constants block; per-card nodes carry the short
# number-free pointer below so cuts never repeat per card.
_SHOOT_GLOSSARY_FULL = ("شلیک = سیگنال شمرده‌شده در حدنصاب ۲تایی پیوند "
                        "(synonyms: vote/point)")
_SHOOT_GLOSSARY_SHORT = "شلیک = سیگنال شمرده‌شده در حدنصاب پیوند"


def _signal_why(name, alias):
    """One-line FA why for one firing signal (thresholds inline)."""
    return _signal_exact(name, alias)


def _decision_rule(method, n_fires):
    """(rule FA sentence, threshold comparison) for the decision step.

    The comparison is method-code-free on purpose: node-5 shows the
    method once (winner line + badge) and cross-references it here, so
    the decision line never duplicates it (single source each).
    """
    need = LINK_MIN_DEFAULT
    if method.startswith("LINK:exact-sensekey"):
        return (_rule_fa(method),
                "%d سیگنال ≥ حد %d → پیوند" % (n_fires, need))
    if method.startswith("LINK:judge-v2"):
        return ("قاعده پیوند با داور",
                "رأی داور ← پیوند")
    if method.startswith("LINK:manual-override"):
        return ("قاعده پیوند دستی مالک",
                "override مالک ← پیوند")
    if method.startswith("LINK"):
        # Mechanical rule win: real Persian rule name, never bare «قاعده».
        return (_rule_fa(method),
                "%d سیگنال ≥ %d → پیوند" % (n_fires, need))
    if method in ("JUDGE-PENDING", "JUDGE-REVIEW"):
        return ("قاعده انتظار داور",
                "%d سیگنال < حد %d → انتظار داور" % (n_fires, need))
    if method == "UNMAPPED":
        return ("قاعده بی‌علامتی",
                "۰ سیگنال → نگاشت‌نشده")
    if method == "twin-pending":
        return ("قاعده دوقلوی تکراری",
                "دوقلو ← معلق، هرگز پیوند نه")
    if method == "quarantined-known-false":
        return ("قاعده قرنطینه خطای شناخته‌شده",
                "خطای شناخته‌شده ← قرنطینه، هرگز پیوند نه")
    if method in ("JUDGE-NONE", "MANUAL-NONE"):
        return ("قاعده بدون‌پیوند",
                "بدون‌پیوند اعلام شد")
    return ("قاعده تصمیم",
            "تصمیم ثبت شد")


def _decision_why(method, n_fires):
    rule, _cmp = _decision_rule(method, n_fires)
    if method.startswith("LINK"):
        return "%s؛ %d سیگنال ≥ حد %d پس پیوند خورد" % (
            rule, n_fires, LINK_MIN_DEFAULT)
    if method in ("JUDGE-PENDING", "JUDGE-REVIEW"):
        return "کمتر از %d سیگنال پس در انتظار داور ماند" % LINK_MIN_DEFAULT
    if method == "UNMAPPED":
        return "بی‌علامت بود پس نگاشت نشد"
    if method == "twin-pending":
        return "دوقلوی تکراری بود پس جدا نگه داشته شد"
    if method == "quarantined-known-false":
        return "خطای شناخته‌شده بود پس قرنطینه شد"
    if method == "MANUAL-NONE":
        return "مالک دستی بدون‌پیوند اعلام کرد"
    return "قاعده تصمیم ثبت شد"


def _method_fa(method):
    """Locked-vocabulary FA sentence for a link method.

    >>> _method_fa("LINK:exact-sensekey+2-sig")
    'پیوند کلیددقیق + 2 علامت'
    >>> _method_fa("UNMAPPED")
    'نگاشت\u200cنشده'
    """
    method = method or ""
    if method.startswith("LINK:exact-sensekey"):
        tail = method.split("+", 1)[-1] if "+" in method else ""
        n = "".join(ch for ch in tail if ch.isdigit()) or "?"
        return "پیوند کلیددقیق + %s علامت" % n
    if method.startswith("LINK:judge-v2"):
        return "پیوند با داور"
    if method.startswith("LINK:manual-override"):
        return "پیوند دستی مالک"
    if method.startswith("LINK"):
        n = "".join(ch for ch in method if ch.isdigit()) or "?"
        return "پیوند · %s سیگنال" % n
    return {
        "JUDGE-PENDING": "در انتظار داور",
        "JUDGE-REVIEW": "بازبینی داور",
        "JUDGE-NONE": "بدون‌پیوند داور",
        "MANUAL-NONE": "بدون‌پیوند دستی",
        "UNMAPPED": "نگاشت‌نشده",
        "twin-pending": "دوقلوی معلق",
        "quarantined-known-false": "قرنطینه خطای شناخته‌شده",
    }.get(method, method or "—")


_FLAG_FA = {
    "provisional_consensus": "اجماع موقت",
    "quarantined-known-false": "قرنطینه خطای شناخته‌شده",
    "twin-pending": "دوقلوی معلق",
    "manual-none": "بدون‌پیوند دستی",
}


def _flag_fa(flag):
    """FA sentence for a flag; judge-v2 tags collapse to «رأی داور»."""
    if flag.startswith("judge-v2"):
        return "رأی داور"
    return _FLAG_FA.get(flag, flag)

def _parse_sensekey_locator(sensekey):
    """Synset locator parsed from a sensekey (lexfile:sense, no invention).

    >>> _parse_sensekey_locator("run%2:38:11::")
    '38:11'
    >>> _parse_sensekey_locator("-")
    '—'
    """
    text = sensekey or ""
    if "%" not in text:
        return "—"
    tail = text.split("%", 1)[-1].split(":")
    if len(tail) < 3 or not tail[1].isdigit():
        return "—"
    return "%s:%s" % (tail[1], tail[2] or "—")


def evidence_sa_j(evidence):
    """First ``Sa:j=<float>`` value in the rule half, else None.

    >>> evidence_sa_j("Sa:j=0.40+Sd:hyp=move")
    0.4
    >>> evidence_sa_j("Sd:hyp=move") is None
    True
    >>> evidence_sa_j("0sig") is None
    True
    """
    rule, _, _ = (evidence or "").partition("|")
    for tok in rule.split("+"):
        tok = tok.strip()
        if tok.startswith("Sa:j="):
            try:
                return float(tok[len("Sa:j="):])
            except ValueError:
                return None
    return None


def render_candidates_html(row, cand_entry, winner_key=""):
    """Candidate `<ol>` with winner highlight + jaccard-vs-Sa warning.

    The `<li>` whose sensekey equals ``winner_key`` gets the
    ``is-winner`` class (green edge + ✓). When the winner's
    shortlist-jaccard differs from the row's signal-Sa value beyond
    0.01, an inline bilingual warning names both numbers.
    """
    top3 = (cand_entry or {}).get("top3") or []
    if not top3:
        return ("<p class='candnone'>فهرست نامزدها در دسترس نیست "
                "<span class='code'>(<bdi>no-candidates</bdi>)</span>؛ "
                "نامزد برتر از داور/قاعده آمد</p>")
    sa_j = evidence_sa_j(row.get("evidence", ""))
    items = []
    for rank, cand in enumerate(top3, 1):
        skey = cand.get("sensekey", "") or ""
        gloss = cand.get("gloss", "") or ""
        # Flow-tracer DATA rule: candidate defs are FULL, never truncated.
        snip = gloss
        score = cand.get("jaccard", "—")
        lemmas = ", ".join(cand.get("lemmas") or []) or "—"
        fires = cand.get("fires") or []
        fire_txt = ", ".join(fires) if fires else "بدون شلیک"
        is_winner = bool(winner_key and winner_key != "-"
                         and skey == winner_key)
        warn = ""
        # Winner-scoped (round 4 T7): only the winner's own shortlist
        # score is compared against the row's signal-Sa; sibling
        # candidates never warn, so a matching winner stays clean.
        if (is_winner and sa_j is not None
                and isinstance(score, (int, float))
                and abs(float(score) - sa_j) > 0.01):
            warn = ("<br><span class='warn'>ناهمخوانی هم‌پوشانی: "
                    "shortlist-jaccard ‏%s‏ در برابر signal-Sa ‏%s‏ "
                    "<span class='code'>(<bdi>shortlist-jaccard ≠ "
                    "signal-Sa</bdi>)</span></span>"
                    % (_esc(score), _esc(sa_j)))
        items.append(
            "<li%s>رتبه %d%s · کلید <bdi class='wkey'>%s</bdi> · مکان سینست "
            "<bdi>%s</bdi> "
            "<span class='code'>(<bdi>synset-locator</bdi>)</span> · "
            "امتیاز فهرست‌کوتاه <bdi>%s</bdi> "
            "<span class='code'>(<bdi>shortlist-jaccard</bdi>)</span><br>"
            "تعریف: “<bdi>%s</bdi>” · هم‌معنی‌ها: <bdi>%s</bdi> · "
            "شلیک‌ها: <bdi>%s</bdi>%s</li>"
            % (' class="is-winner"' if is_winner else "",
               rank, " ✓" if is_winner else "",
               _esc(skey), _esc(_parse_sensekey_locator(skey)),
               _esc(score), _esc(snip), _esc(lemmas), _esc(fire_txt),
               warn))
    return "<ol class='candlist'>%s</ol>" % "".join(items)


# --- Flow tracer (owner-locked Gemini build): 5 nodes + 4 wires per card ---
#
# Wholesale replacement of the old step list: per-card tracer carrying
# Gemini's node titles / concept tooltips / wire-color legend verbatim
# (arrow chars stripped), our exact evidence strings beside them as muted
# proof, and dynamic grid layout (no fixed coords, no drag, no presets,
# no storage). Per-card inline SVG wires are drawn from
# getBoundingClientRect + ResizeObserver; wire labels use perpendicular
# offsets flipped until clear of node boxes.
_FLOWTRACE_TITLES = (
    "معنی ورودی مبدأ",
    "غربالگری کاندیداها",
    "ارزیابی سیگنال‌ها",
    "حل تعارض و داوری",
    "فرجام پیوند و تکمیل",
)

_FLOWTRACE_CONCEPTS = (
    ("ضریب جاکارد (Jaccard)",
     "شاخص اشتراک واژگان: کلمات مشترک تقسیم بر کل کلمات منحصر‌به‌فرد. "
     "نمره بالای ۰.۲۰ نشان‌دهنده هم‌پوشانی جدی است.",
     "#f59e0b"),
    ("سینست (Locator)",
     "کد مکان در وردنت: آدرس موضوعی و رده‌بندی معنایی در درخت وردنت "
     "(مثلاً 38:00 رده حرکت است).",
     "#38bdf8"),
    ("همزاد (Twin)",
     "تعارض همزاد: زمانی که دو سنس ورودی کایکی متقاضی یک سنس یکسان "
     "در وردنت باشند.",
     "#c084fc"),
    ("بازبینی (Flip-Review)",
     "پرچم هشدار کیفی: نوسان غیرمنتظره در رأی مدل زبانی که جهت "
     "جلوگیری از خطا به اپراتور انسان ارجاع می‌شود.",
     "#f43f5e"),
)

_FLOWTRACE_LEGEND = (
    ("success", "موفق / تأیید"),
    ("warn", "داوری / هشدار"),
    ("fail", "رد / مسدودسازی"),
    ("twin", "تعارض دوقلو"),
    ("bypassed", "عبور داده شده"),
)

_FLOWTRACE_WIRE_COLORS = {
    "success": "#10b981",
    "warn": "#f59e0b",
    "fail": "#f43f5e",
    "twin": "#c084fc",
    "bypassed": "#475569",
}

# Per-row tracer status badge (Gemini binding): exact hex per state —
# REVIEW #f59e0b · twin #c084fc · LINK #10b981 · NONE/FAILED #ef4444 ·
# bypassed #475569. Driven per-row from that row's (row, verdict),
# never from a scenario bar.
_FLOWTRACE_STATUS_COLORS = {
    "REVIEW": "#f59e0b",
    "twin": "#c084fc",
    "LINK": "#10b981",
    "NONE": "#ef4444",
    "FAILED": "#ef4444",
    "bypassed": "#475569",
}


def _flowtrace_status(row, verdict, gate=""):
    """Per-row status (label, color) from the row's own verdict first.

    Verdict-first (owner-locked): a LINK verdict is LINK-green even when
    the table row is still JUDGE-PENDING (table consumption is a
    separate node-5 fact); a NONE verdict is NONE-red. Verdict-less
    mechanical LINKs stay LINK-green; pending rows with no verdict yet
    are REVIEW-amber (awaiting review, like the warn wires).
    """
    row = row or {}
    verdict = verdict or {}
    method = row.get("method", "") or ""
    vverdict = verdict.get("verdict") or ""
    votes = verdict.get("votes") or []
    failed = (verdict.get("vote_status") == "FAILED"
              or any(not (v or {}).get("ok", True) for v in votes))
    if method == "twin-pending" or gate == "twin":
        return ("twin", _FLOWTRACE_STATUS_COLORS["twin"])
    if method == "JUDGE-REVIEW" or gate == "review":
        return ("REVIEW", _FLOWTRACE_STATUS_COLORS["REVIEW"])
    if vverdict == "LINK":
        return ("LINK", _FLOWTRACE_STATUS_COLORS["LINK"])
    if failed or vverdict in ("NONE", "FAILED") or method in (
            "JUDGE-NONE", "MANUAL-NONE"):
        label = "FAILED" if (failed or vverdict == "FAILED") else "NONE"
        return (label, _FLOWTRACE_STATUS_COLORS["FAILED"])
    if method.startswith("LINK"):
        return ("LINK", _FLOWTRACE_STATUS_COLORS["LINK"])
    if gate == "pending" or method in ("JUDGE-PENDING",):
        return ("REVIEW", _FLOWTRACE_STATUS_COLORS["REVIEW"])
    if gate == "rule":
        return ("bypassed", _FLOWTRACE_STATUS_COLORS["bypassed"])
    return ("bypassed", _FLOWTRACE_STATUS_COLORS["bypassed"])


def _card_winner(row, verdict=None):
    """Authoritative winner sensekey for one card (viewer single source).

    The judge's ``winner_sensekey`` wins whenever a verdict carries one
    (judge decided; a JUDGE-PENDING table row is stale until consumed).
    Otherwise the row's own ``wordnet_sensekey``.

    >>> _card_winner({"wordnet_sensekey": "run%2:38:11::"},
    ...              {"winner_sensekey": "run%2:38:00::"})
    'run%2:38:00::'
    >>> _card_winner({"wordnet_sensekey": "run%2:38:11::"}, {})
    'run%2:38:11::'
    >>> _card_winner({"wordnet_sensekey": "-"}, {})
    '-'
    """
    row, verdict = row or {}, verdict or {}
    if (verdict.get("winner_sensekey") or ""):
        return verdict.get("winner_sensekey") or ""
    return row.get("wordnet_sensekey", "") or ""


# Table-consumption states: the judge decided but the link table was not
# updated yet. Shown as a node-5 fact line, never on the judge (4→5) wire.
_TABLE_PENDING_METHODS = frozenset({"JUDGE-PENDING", "JUDGE-REVIEW"})


def _table_pending_note(method):
    """Node-5 consumption note for pending-table methods, else "".

    >>> _table_pending_note("JUDGE-PENDING")
    'جدول هنوز به\u200cروز نشده · pending-table'
    >>> _table_pending_note("LINK:2-sig")
    ''
    """
    if (method or "") in _TABLE_PENDING_METHODS:
        return "جدول هنوز به‌روز نشده · pending-table"
    return ""


_FLOWTRACE_GUIDE = (
    "هدایت نگاه: ۱. معنی ورودی ۲. غربالگری کاندیداها "
    "۳. ارزیابی سیگنال‌ها ۴. حل تعارض و داوری ۵. فرجام نهایی پیوند"
)


def _flowtrace_ports():
    """Four magnet-port spans (top/bottom/left/right edge midpoints)."""
    return "".join(
        '<span class="magnet-port flowtrace-port-%s"></span>' % pos
        for pos in ("top", "bottom", "left", "right"))


def _render_trace(row, verdict, cand_entry=None, row_ref=""):
    """Per-card flow tracer: 5 nodes + 4 wires from real table+verdicts."""
    row = row or {}
    verdict = verdict or {}
    flow = flow_trace_data(row, verdict, cand_entry)
    kid = flow["kid"]
    method = flow["method"]
    evidence = flow["evidence"]
    # Winner single source: the judge's winner_sensekey wins whenever the
    # verdict carries one (a JUDGE-PENDING table row is stale until
    # consumed) — candidate highlight, node-5 line and data-winner below
    # all follow this key, never the raw table cell.
    winner_key = _card_winner(row, verdict)
    n_fires = flow["n_fires"]
    gate = flow["gate"]
    # Canonical agreement lives here (3-tier, evidence-aware); linker's
    # flow["agree"] is the legacy 2-tier copy kept for wire compat.
    agree = agreement_key(verdict)
    flags = flow["flags"]
    # Per-case machine numbers (tier/seed from this row's provenance;
    # verdict-tier from this card's judge verdict) — thresholds stay out,
    # they live once in the page-level global constants block.
    mblk = machine_block(row)

    # Node 1: input sense (Gemini guide sentences + exact row proof).
    lemma = flow["lemma"] or "—"
    in_def = flow["in_def"] or "—"
    toks = norm_tokens(flow["in_def"])[:8]
    node1 = (
        '<div class="flowtrace-in">'
        '<div class="flowtrace-lemma"><bdi lang="en" dir="ltr">%s</bdi> '
        '<span class="flowtrace-pos">%s</span></div>'
        '<div class="flowtrace-defbox">'
        '<span class="flowtrace-guidelabel">تعریف تحت بررسی:</span>'
        '<p class="flowtrace-indef" lang="en" dir="ltr">%s</p></div>'
        '<div class="flowtrace-kv">'
        '<span>کلمات استخراج‌شده:</span> '
        '<bdi class="flowtrace-toks">%s</bdi></div>'
        '<div class="flowtrace-kv"><span>شناسه سنس:</span> '
        '<bdi>%s</bdi></div>'
        '<details class="flowtrace-meta"><summary>متادیتای ردیف مبدأ</summary>'
        '<div>ردیف فایل: <bdi>%s</bdi></div>'
        '<div>شواهد: <bdi>%s</bdi></div></details>'
        '</div>'
        % (_esc(lemma), _esc(row.get("kaikki_pos", "") or "—"),
           _esc(in_def),
           _esc(", ".join(toks) if toks else "ندارد"),
           _esc(kid), _esc(row_ref or "—"),
           _esc(evidence or "0sig")))

    # Node 2: candidates with FULL defs/scores/winner flags.
    rule_fires = [s["alias"] for s in flow["signals"]
                  if s["fired"] and s["alias"] != "judge"]
    if winner_key and winner_key != "-":
        if rule_fires:
            cand_why = ("نامزد برتر با %d سیگنال از فهرست کوتاه انتخاب شد"
                        % len(rule_fires))
        elif verdict:
            cand_why = "نامزد برتر از داور آمد (بدون سیگنال قاعده‌ای)"
        else:
            cand_why = ("نامزد برتر ردیف است "
                        "(بدون سیگنال قاعده‌ای؛ داوری نشد)")
    else:
        cand_why = "هیچ نامزدی کوتاه‌نیامد چون هیچ سیگنالی شلیک نکرد"
    if flow["candidates"]:
        # Re-mark winner flags against the authoritative card winner
        # (linker marks the raw table cell; the judge's key wins here).
        cand_list = [dict(cand, is_winner=bool(
            winner_key and winner_key != "-"
            and cand.get("key") == winner_key))
            for cand in flow["candidates"]]
    else:
        # Fallback: parse the raw caller cand_entry top3 when the flow
        # model carries no candidates (caller shape {"top3": [...]}).
        cand_list = []
        for rank, cand in enumerate((cand_entry or {}).get("top3") or [], 1):
            cand = cand or {}
            skey = cand.get("sensekey", "") or ""
            cand_list.append({
                "rank": rank,
                "key": skey,
                "locator": _parse_sensekey_locator(skey),
                "j": cand.get("jaccard"),
                "def": cand.get("gloss", "") or "",
                "lemmas": list(cand.get("lemmas") or []),
                "fires": list(cand.get("fires") or []),
                "is_winner": bool(winner_key and winner_key != "-"
                                  and skey == winner_key),
            })
    if cand_list:
        cand_items = []
        for cand in cand_list:
            lemmas = ", ".join(cand["lemmas"]) or "—"
            fires = ", ".join(cand["fires"]) if cand["fires"] else "بدون شلیک"
            cand_items.append(
                "<li%s>رتبه %d%s · کلید <bdi class='wkey'>%s</bdi> · "
                "مکان سینست <bdi>%s</bdi> "
                "<span class='code'>(<bdi>synset-locator</bdi>)</span> · "
                "امتیاز فهرست‌کوتاه <bdi>%s</bdi> "
                "<span class='code'>(<bdi>shortlist-jaccard</bdi>)</span><br>"
                "تعریف: “<bdi>%s</bdi>” · هم‌معنی‌ها: <bdi>%s</bdi> · "
                "شلیک‌ها: <bdi>%s</bdi></li>"
                % (' class="is-winner"' if cand["is_winner"] else "",
                   cand["rank"], " ✓" if cand["is_winner"] else "",
                   _esc(cand["key"]), _esc(cand["locator"]),
                   _esc(cand["j"]), _esc(cand["def"]),
                   _esc(lemmas), _esc(fires)))
        node2 = ("<ol class='candlist'>%s</ol>" % "".join(cand_items)
                 + "<p class='flowtrace-why'>چرا: %s</p>" % _esc(cand_why))
    elif winner_key and winner_key != "-":
        # Mechanical LINKs carry no candidate pack (0/46 in run20): never
        # a silent empty node — state the missing pack explicitly, then
        # show the WINNER key + its definition from the row's wordnet
        # data when present, else an honest gap.
        wkind, wdef = _winner_def_status(row, verdict)
        if wkind == "def":
            wdef_html = ("تعریف برنده: “<bdi>%s</bdi>”" % _esc(wdef))
        elif wkind == "example-as-def":
            wdef_html = ("مثالِ نقل‌شده به‌جای تعریف: “<bdi>%s</bdi>” "
                         "<span class='code'>(<bdi>example-shown-as-def "
                         "(upstream)</bdi>)</span>" % _esc(wdef))
        else:
            wdef_html = ("<span class='wdef-gap'>تعریف برنده در ردیف نیست "
                         "<span class='code'>(<bdi>winner-def-missing</bdi>)"
                         "</span></span>")
        node2 = ("<p class='candempty'>کاندیداها در بسته نیست "
                 "<span class='code'>(<bdi>shortlist recompute لازم</bdi>)"
                 "</span></p>"
                 "<div class='candwinner'>نامزد برتر: "
                 "<bdi class='wkey'>%s</bdi> · مکان سینست <bdi>%s</bdi><br>%s</div>"
                 "<p class='flowtrace-why'>چرا: %s</p>"
                 % (_esc(winner_key),
                    _esc(_parse_sensekey_locator(winner_key)),
                    wdef_html, _esc(cand_why)))
    else:
        node2 = ("<p class='candnone'>هیچ کاندیدایی به این مرحله نرسید "
                 "(پایان در گام اول)</p>"
                 "<p class='flowtrace-why'>چرا: %s</p>" % _esc(cand_why))

    # Node 3: signals with exact words/scores + rule verdict. Per-case
    # numbers ONLY here — decision cuts live once in the page-level
    # global constants block (see _render_global_thresholds); this node
    # carries just a pointer plus the number-free shoot gloss.
    # Node 3: signals with exact words/scores + rule verdict (per-case
    # numbers only; cuts live once in the global constants block).
    sig_items = "".join(
        "<li><b>%s</b> "
        "<span class='code'>(<bdi>%s</bdi>)</span><br>"
        "<span class='why'>%s</span></li>"
        % (_esc(s["name"]), _esc(s["alias"]),
           _esc(_signal_exact(s["name"], s["alias"])))
        for s in flow["signals"])
    need = LINK_MIN_DEFAULT
    if n_fires >= need:
        rule_title = "✓ احراز حد نصاب قاعده‌ای"
        rule_desc = ("%d سیگنال مستقل تأیید شد (≥ %d). برنده از فهرست "
                     "کوتاه مستقیماً برگزیده شد." % (n_fires, need))
    else:
        rule_title = "ارجاع پرونده به داور"
        rule_desc = ("تعداد شواهد اولیه کمتر از %d سیگنال؛ انتخاب برنده "
                     "به داور ارجاع شد." % need)
    node3 = (
        "<ul class='flowtrace-siglist'>%s</ul>"
        "<div class='flowtrace-rule'><b>%s</b><p>%s</p>"
        "<p class='flowtrace-shoot'>%s</p>"
        "<p class='flowtrace-cutptr'>حدها در بلوک سراسری بالا "
        "<span class='code'>(<bdi>global-thresholds</bdi>)</span></p></div>"
        "<p class='flowtrace-why'>چرا: %s</p>"
        % (sig_items, _esc(rule_title), _esc(rule_desc),
           _esc(_SHOOT_GLOSSARY_SHORT),
           _esc("%d سیگنال شلیک کرد" % n_fires if n_fires
               else "صفر سیگنال")))

    # Node 4: conflict resolution + judge.
    if gate == "rule":
        judge_body = (
            "<div class='flowtrace-gatebody'>تأیید فوری با «%s»: "
            "%d سیگنال قوی بود پس بدون نیاز به داور "
            "پیوند قطعی شد.</div>"
            "<div class='flowtrace-tech'>تعداد آرای داور: ۰ "
            "(قاعده برنده شد)</div>" % (_esc(_rule_fa(method)), n_fires))
        judge_badge = "عبور از داور"
        judge_why = "قاعده %d سیگنال داشت پس داوری لازم نشد" % n_fires
    elif gate == "twin":
        judge_body = (
            "<div class='flowtrace-gatebody'>رقابت متقارن در جدول: ردیف "
            "در حالت <span class='code'>(<bdi>twin-pending</bdi>)</span> "
            "نگه‌داشته می‌شود تا کل داده‌ها کامل شوند.</div>"
            "<div class='flowtrace-tech'>قانون دوقلو: twin-pending فعال شد"
            "</div>")
        judge_badge = "تعارض همزاد"
        judge_why = "دوقلوی تکراری بود پس جدا نگه داشته شد"
    elif gate == "review":
        judge_body = (
            "<div class='flowtrace-gatebody'>پرچم Flip-Review: نوسان "
            "غیرمنتظره در رأی مدل زبانی کشف شد؛ پرونده جهت بازبینی "
            "انسانی علامت‌گذاری شد.</div>"
            "<div class='flowtrace-tech'>پرچم: flip-review</div>")
        judge_badge = "هشدار بازبینی"
        judge_why = "بازبینی انسانی لازم شد پس معلق ماند"
    elif verdict:
        if agree == "unanimous":
            judge_title = "هر ۳ داور هم‌نظر (unanimous)"
            judge_why = ("هر ۳ داور هم‌نظر بودند (unanimous)؛ "
                         "رأی مدل است، قطعیت نیست")
        elif agree == "concordant":
            judge_title = "هم‌نظر در رأی، متفاوت در دلیل (concordant)"
            judge_why = ("هر ۳ داور یک رأی دادند ولی دلیل‌های نقل‌شده "
                         "فرق دارد (concordant)؛ رأی مدل است، "
                         "قطعیت نیست")
        elif agree == "split-vote":
            judge_title = "آرا ۲-۱ شد (split-vote)"
            judge_why = "آرا ۲-۱ شد پس شقه است و موقت می‌ماند (split-vote)"
        else:
            judge_title = "داوری ناقص"
            judge_why = "رأی کافی ثبت نشده پس داوری‌نشده است"
        # Compact judge node: verdict/winner/quote/seeds/flags each ONCE
        # (×N for repeats); per-vote blocks only for differing content.
        # _vote_badges per-vote spans are retired (verdict/winner repeat).
        judge_body = (
            "<div class='flowtrace-gatebody'>%s</div>"
            % _render_judge_compact(
                verdict, winner_key, flags, agree,
                judge_title, judge_why))
        judge_badge = "هیئت داوری LLM"
    else:
        judge_body = "<div class='flowtrace-gatebody'>هنوز به داور نرسیده</div>"
        judge_badge = "در انتظار"
        judge_why = "ردیف در مرحله قاعده‌ای ماند و داوری نشد"
    if verdict and (verdict.get("votes") or verdict.get("verdict")):
        # Judged path: compact node owns header + latency/seeds +
        # flags; the tier line keeps tier names only (no seed/flag
        # repeat — seeds/flags live once in the compact body).
        node4 = (judge_body
                 + "<div class='flowtrace-tech'>ردیف: tier <bdi>%s</bdi> · "
                 "verdict-tier <bdi>%s</bdi></div>"
                 "<p class='flowtrace-why'>چرا: %s</p>"
                 % (_esc(mblk["tier"]),
                    _esc(verdict.get("tier") or "—"), _esc(judge_why)))
    else:
        node4 = ("<div class='flowtrace-techhead'>لیتنسی و بذرها</div>"
                 + judge_body
                 + "<div class='flowtrace-tech'>ردیف: tier <bdi>%s</bdi> · "
                 "seed <bdi>%s</bdi> · verdict-tier <bdi>%s</bdi></div>"
                 "<p class='flowtrace-why'>چرا: %s</p>"
                 % (_esc(mblk["tier"]), _esc(mblk["seed"]),
                    _esc(verdict.get("tier") or "—"), _esc(judge_why)))

    # Node 5: link finale + wordnet field fill (تکمیل فیلدها).
    # Data-cleanup rule: drop empty fields, show only filled gaps with ✓;
    # honest fallback line when nothing transferred. DIFF-VIEW: the winner
    # definition and the method live ONLY in the winner line (single
    # source); the gap-def row and the decision line cross-reference them
    # instead of repeating the full strings. Viewer-side winner-def rule:
    # flow["winner_def"] (linker) may carry a bare upstream example, so
    # the displayed text always comes from _winner_def_status here.
    wkind, winner_def = _winner_def_status(row, verdict)
    if wkind == "example-as-def":
        winner_line = ("مثالِ نقل‌شده به‌جای تعریف: “<bdi>%s</bdi>” "
                       "<span class='code'>(<bdi>example-shown-as-def "
                       "(upstream)</bdi>)</span>" % _esc(winner_def))
    else:
        winner_line = "“<bdi>%s</bdi>”" % _esc(winner_def or "—")
    gaps = _gap_cells(row, verdict)
    filled_gaps = [g for g in gaps if g[3] != "—"]
    if filled_gaps:
        gap_items = "".join(
            ("<li>✓ <b>%s</b> <span class='en' lang='en'>%s</span> ← منبع: "
             "<bdi>%s</bdi>: %s</li>")
            % (_esc(fa), _esc(en), _esc(src),
               ("<span class='wdef-ref'>همان تعریف برنده (بالا)</span>"
                if slot == "def" and winner_def and val == winner_def
                else "<bdi>%s</bdi>" % _esc(val)))
            for slot, fa, en, val, src in filled_gaps)
        gap_block = "<ul class='flowtrace-gaplist'>%s</ul>" % gap_items
    else:
        gap_block = "<p class='flowtrace-gapnone'>هیچ فیلدی منتقل نشد</p>"
    filled = len(filled_gaps)
    rule_txt, cmp_txt = _decision_rule(method, n_fires)
    flag_chips = (" ".join(_flag_chip(f) for f in flags)
                  if flags else "<span class='flagchip flag-ok'>بدون پرچم "
                  "<span class='code'>(<bdi>no-flags</bdi>)</span></span>")
    # Table-consumption pending is a node-5 fact, never a judge-wire
    # label: the judge decided, the link table just hasn't consumed it.
    pending_note = _table_pending_note(method)
    pending_html = ("<div class='flowtrace-pending'>%s "
                    "<span class='code'>(<bdi>table-not-consumed</bdi>)</span></div>"
                    % _esc(pending_note)) if pending_note else ""
    node5 = (
        "<div class='flowtrace-winner'>سنس برنده در وردنت: "
        "<bdi class='wkey'>%s</bdi> · سینست: <bdi>%s</bdi><br>"
        "تعریف برنده: %s</div>"
        "<div class='flowtrace-enrich'><span class='flowtrace-guidelabel'>"
        "تزریق فیلدهای وردنت:</span> تکمیل فیلدها "
        "<span class='code'>(<bdi>gaps</bdi>)</span>"
        "%s</div>"
        "<div class='flowtrace-decision'>%s · %s "
        "<span class='code'>(<bdi>روش در سربرگ · method-in-header</bdi>)</span> · "
        "پرچم‌ها: %s</div>"
        "%s"
        "<div class='flowtrace-jsonptr'>رکورد خروجی JSON در برگه فنی "
        "(machine JSON) همین کارت است</div>"
        "<p class='flowtrace-why'>چرا: %s · %d شکاف از %d پر شد</p>"
        % (_esc(winner_key or "—"),
           _esc(_parse_sensekey_locator(winner_key) if winner_key else "—"),
           winner_line, gap_block,
           _esc(rule_txt), cmp_txt, flag_chips, pending_html,
           _esc(_decision_why(method, n_fires)), filled, len(gaps)))

    nodes = (node1, node2, node3, node4, node5)
    # PIC-2 card grammar per node: compact header (title + badge), body
    # (main content, definitions full), footer (meta chips, smaller text).
    # Colors, wires, tooltips and RTL are untouched — only the grammar.
    _ftbadges = (
        '<span class="ft-badge">%s '
        '<span class="code">(<bdi>pos</bdi>)</span></span>'
        % _esc(row.get("kaikki_pos", "") or "—"),
        ('<span class="ft-badge">%d کاندیدا '
         '<span class="code">(<bdi>candidates</bdi>)</span></span>'
         % len(cand_list)) if cand_list else
        '<span class="ft-badge">بدون بسته '
        '<span class="code">(<bdi>no-pack</bdi>)</span></span>',
        '<span class="ft-badge">%d سیگنال '
        '<span class="code">(<bdi>fires</bdi>)</span></span>' % n_fires,
        '<span class="ft-badge">%s</span>' % _esc(judge_badge),
        _method_badge(method),
    )
    _ftfoots = (
        '<span class="ft-chip">ردیف <bdi>%s</bdi></span> '
        '<span class="ft-chip"><bdi>%s</bdi></span>'
        % (_esc(row_ref or "—"), _esc(kid)),
        '<span class="ft-chip">سقف فهرست‌کوتاه ۱۲ '
        '<span class="code">(<bdi>shortlist_cap=12</bdi>)</span></span>',
        '<span class="ft-chip">حدها: بلوک سراسری بالا '
        '<span class="code">(<bdi>global-thresholds</bdi>)</span></span>',
        '<span class="ft-chip">بذر <bdi>%s</bdi> '
        '<span class="code">(<bdi>seed</bdi>)</span></span>' % _esc(mblk["seed"]),
        '<span class="ft-chip">رکورد JSON در برگه فنی '
        '<span class="code">(<bdi>machine-JSON</bdi>)</span></span>',
    )
    card_no = _render_trace._seq
    _render_trace._seq += 1

    def _ftnode(pos, title, badge, body, foot):
        return (
            '<section class="flowtrace-node" data-ftnode="%d" '
            'id="ft-%d-%d"><div class="ft-head">'
            '<span class="flowtrace-nodetitle">%s</span>%s</div>%s'
            '<div class="ft-body">%s</div>'
            '<div class="ft-foot">%s</div>'
            "</section>"
            % (pos, card_no, pos, _esc(title), badge,
               _flowtrace_ports(), body, foot))

    # Ticket-locked 3-column RTL S-flow: right col nodes 1+2, middle col
    # nodes 3+4, left col node 5 centered. DOM order stays 1..5; direction
    # rtl puts the first column on the right. Wire/label JS queries
    # section.flowtrace-node by data-ftnode under div.flowtrace, so the
    # column wrappers need no selector change.
    node_html = (
        '<div class="flowtrace-col flowtrace-col-right">'
        + _ftnode(1, _FLOWTRACE_TITLES[0], _ftbadges[0], nodes[0], _ftfoots[0])
        + _ftnode(2, _FLOWTRACE_TITLES[1], _ftbadges[1], nodes[1], _ftfoots[1])
        + "</div>"
        '<div class="flowtrace-col flowtrace-col-mid">'
        + _ftnode(3, _FLOWTRACE_TITLES[2], _ftbadges[2], nodes[2], _ftfoots[2])
        + _ftnode(4, _FLOWTRACE_TITLES[3], _ftbadges[3], nodes[3], _ftfoots[3])
        + "</div>"
        '<div class="flowtrace-col flowtrace-col-left">'
        + _ftnode(5, _FLOWTRACE_TITLES[4], _ftbadges[4], nodes[4], _ftfoots[4])
        + "</div>")

    concepts = "".join(
        '<span class="tooltip-box flowtrace-concept" style="color:%s">%s'
        '<span class="tooltip-content">%s</span></span>'
        % (color, _esc(title), _esc(text))
        for title, text, color in _FLOWTRACE_CONCEPTS)
    legend = "".join(
        '<span class="flowtrace-litem" style="color:%s">'
        '<span class="flowtrace-dot" style="background:%s;box-shadow:0 0 6px %s"></span> %s</span>'
        % (_FLOWTRACE_WIRE_COLORS[status],
           _FLOWTRACE_WIRE_COLORS[status],
           _FLOWTRACE_WIRE_COLORS[status], _esc(label))
        for status, label in _FLOWTRACE_LEGEND)
    # Canonical 1→2→3→4→5 wires (viewer-owned; overrides flow["wires"]
    # for rendering so the tracer always shows 4 wires).
    cand_ok = bool(cand_list)
    # Concordant needs review like split (same vote, different reasons —
    # never certain): warn wires + no link confirmation.
    is_split = agree in ("split-vote", "concordant")
    is_review = (gate == "review")
    is_pending = (gate == "pending")
    is_twin = (gate == "twin")
    is_rule = (gate == "rule")
    _w12 = {"from": 1, "to": 2, "label": "استخراج کاندیداها",
            "status": "success" if cand_ok else "warn"}
    _w23 = {"from": 2, "to": 3, "label": "ارسال کاندیداها به ارزیابی",
            "status": "success" if cand_ok else "warn"}
    if is_rule:
        _w34 = {"from": 3, "to": 4,
                "label": "عبور از داور (قاعده برنده شد)",
                "status": "bypassed"}
    elif is_twin:
        _w34 = {"from": 3, "to": 4,
                "label": "کشف تقاضای همزاد (توقف)",
                "status": "twin"}
    # Pending (JUDGE-PENDING) warns like review/split — the verdict was
    # never consumed, so the edge must never claim rejection (linker
    # parity: pending w3/w4 are both warn).
    elif is_review or is_split or is_pending:
        _w34 = {"from": 3, "to": 4, "label": "ارجاع به داور",
                "status": "warn"}
    else:
        _w34 = {"from": 3, "to": 4, "label": "ارجاع به داور",
                "status": "success"}
    # Judge-wire single source (owner-locked): the 4→5 wire reflects the
    # VERDICT, never the table-consumption state. verdict_wire45 (linker)
    # owns the mapping. Table-pending stays a node-5 fact
    # (see _table_pending_note).
    _w45 = verdict_wire45(verdict, method, winner_key)
    canonical_wires = [_w12, _w23, _w34, _w45]
    wirelist = "".join(
        '<li class="flowtrace-wire" data-from="%d" data-to="%d" '
        'data-status="%s" data-color="%s">%s</li>'
        % (wire["from"], wire["to"], wire["status"],
           _FLOWTRACE_WIRE_COLORS.get(wire["status"], "#475569"),
           _esc(wire["label"]))
        for wire in canonical_wires)

    status_label, status_color = _flowtrace_status(row, verdict, gate)
    status_badge = (
        '<span class="flowtrace-status" style="border-color:%s;color:%s">'
        "وضعیت: %s</span>" % (status_color, status_color, _esc(status_label)))
    return (
        '<details class="flowtrace-wrap" open>'
        '<summary>ردیاب جریان پیوند '
        '<span lang="en">flow trace</span> (همیشه باز · debug)%s</summary>'
        '<div class="flowtrace" data-flowtrace="%s" data-status="%s">'
        '<div class="flowtrace-guide">%s</div>'
        '<div class="flowtrace-concepts">'
        '<span class="flowtrace-conceptstitle">راهنمای مفاهیم:</span>%s</div>'
        '<div class="flowtrace-legend">'
        '<span class="flowtrace-legendtitle">راهنمای نوری سیم‌ها:</span>%s</div>'
        '<div class="flowtrace-grid">%s'
        '<svg class="flowtrace-wires" aria-hidden="true"></svg>'
        '<div class="flowtrace-labels z-50" aria-hidden="true"></div>'
        '</div>'
        '<ul class="flowtrace-wirelist" aria-label="wires">%s</ul>'
        '</div></details>'
        % (status_badge, _esc(kid), _esc(status_label),
           _esc(_FLOWTRACE_GUIDE), concepts, legend,
           node_html, wirelist))


_render_trace._seq = 1

# FA glosses for machine-JSON keys (naming polish: no bare keys).
_MKEY_FA = {
    "kid": "شناسه معنی kaikki",
    "method": "روش تصمیم",
    "signals": "سیگنال‌های شلیک‌کرده",
    "thresholds": "حدهای تصمیم",
    "tier": "رده اجرا",
    "seed": "بذر تصادفی",
    "build": "ساخت",
    "flags": "پرچم‌ها",
    "provenance": "منشأ ردیف",
    "jaccard": "حد هم‌پوشانی واژگان",
    "se_cut": "حد شباهت معنایی",
    "se_veto_floor": "کف وتوی معنایی",
    "link_min": "کمینه سیگنال برای پیوند",
    "shortlist_cap": "سقف فهرست‌کوتاه",
    "ultra_short_min_tokens": "کمینه واژه تعریف کوتاه",
    "code": "کد",
    "alias": "نام مستعار",
    "detail": "جزئیات",
}


def _render_mkeys(blk):
    """Glossary table: every machine-JSON key beside its FA sentence.

    Thresholds render ONCE page-wide (global constants block), so the
    per-card table carries a pointer instead of repeating them.
    """
    rows = []
    for key in ("kid", "method", "signals", "tier", "seed",
                "build", "flags", "provenance"):
        val = blk.get(key, "")
        if isinstance(val, dict):
            inner = "; ".join(
                "%s (%s)=%s" % (_MKEY_FA.get(k, k), k,
                                v if not isinstance(v, dict) else "…")
                for k, v in val.items())
        elif isinstance(val, list):
            inner = ", ".join(str(v) for v in val) or "—"
        else:
            inner = str(val) or "—"
        rows.append(
            "<dt><span lang='fa'>%s</span> "
            "<span class='code'>(<bdi>%s</bdi>)</span></dt>"
            "<dd><bdi>%s</bdi></dd>"
            % (_esc(_MKEY_FA.get(key, key)), _esc(key), _esc(inner)))
    rows.append(
        "<dt><span lang='fa'>%s</span> "
        "<span class='code'>(<bdi>thresholds</bdi>)</span></dt>"
        "<dd>بلوک سراسری بالا "
        "<span class='code'>(<bdi>global-thresholds</bdi>)</span></dd>"
        % _esc(_MKEY_FA["thresholds"]))
    return "<dl class='mkeys'>%s</dl>" % "".join(rows)


def _method_badge(method):
    method = method or ""
    if _is_mechanical_link({"method": method}):
        # Mechanical rule LINK: own badge (real rule name), distinct from
        # the judge LINK badge.
        cls, label = "m-rule", _rule_fa(method)
    else:
        label = _method_fa(method)
        if method.startswith("LINK"):
            cls = "m-link"
        elif method in ("JUDGE-NONE", "MANUAL-NONE"):
            cls = "m-none"
        elif method in ("JUDGE-PENDING", "JUDGE-REVIEW"):
            cls = "m-pending"
        elif method == "UNMAPPED":
            cls = "m-unmapped"
        elif method == "twin-pending":
            cls = "m-twin"
        elif method == "quarantined-known-false":
            cls = "m-quar"
        else:
            cls = ""
    return ('<span class="badge %s">%s '
            '<span class="code">(<bdi>%s</bdi>)</span></span>'
            % (cls, _esc(label), _esc(method)))


def _card_class(row, verdict):
    if is_quarantined(row):
        return "is-quarantine"
    agree, _ = _agreement_label(verdict or {})
    if is_provisional(row) or agree == "split":
        return "is-provisional"
    return ""


# Short-key cut attached per fired signal in export fires[] (None = n/a).
_EXPORT_CUT = {"lexical-overlap": JACCARD_DEFAULT,
               "meaning-similarity": SE_CUT}


def export_record(row, verdict, cand_entry, row_ref, n=0):
    """One per-record export dict with short fixed keys (round 4 schema).

    ``winner_def`` and candidate ``def`` values are FULL (never
    truncated); judge votes stay compact (verdict/winner/seed/latency —
    no raw text) so the default-ON judge checkbox stays small.
    ``n`` is the 1-based card ordinal (kept for future row_no debt work).

    >>> row = {"kaikki_sense_id": "k", "lemma": "run",
    ...        "kaikki_gloss": "To move.", "method": "LINK:2-sig",
    ...        "wordnet_sensekey": "run%2:38:00::",
    ...        "evidence": "Sa:j=0.40", "flags": ""}
    >>> rec = export_record(row, {}, None, "t.tsv#L2", n=1)
    >>> (rec["kid"], rec["decision"]["locator"], rec["fires"][0]["cut"])
    ('k', '38:00', 0.2)
    """
    row, verdict = row or {}, verdict or {}
    winner = _card_winner(row, verdict)
    blk = machine_block(row)
    fires = [{"sig": name,
              "val": info.get("alias", ""),
              "cut": _EXPORT_CUT.get(name),
              "fired": name != "no-signal"}
             for name, info in blk.get("signals", {}).items()]
    wkind, wtext = _winner_def_status(row, verdict)
    if wkind == "def":
        export_wdef = wtext
    elif wkind == "example-as-def":
        export_wdef = "[example-shown-as-def (upstream)] " + wtext
    else:
        export_wdef = ""
    top3 = (cand_entry or {}).get("top3") or []
    return {
        "kid": row.get("kaikki_sense_id", "") or "",
        "row_ref": row_ref,
        "lemma": row.get("lemma", "") or "",
        "in_def": row.get("kaikki_gloss", "") or "",
        "decision": {"method": row.get("method", "") or "",
                     "winner": winner,
                     "locator": _parse_sensekey_locator(winner)},
        "fires": fires,
        "winner_def": export_wdef,
        "candidates": [{"rank": rank,
                        "key": cand.get("sensekey", "") or "",
                        "j": cand.get("jaccard"),
                        "def": cand.get("gloss", "") or ""}
                       for rank, cand in enumerate(top3, 1)],
        "judge": {"agree": agreement_key(verdict),
                  "votes": [{"v": vote.get("verdict"),
                             "w": vote.get("winner_index"),
                             "s": vote.get("seed"),
                             "lat": vote.get("latency_s")}
                            for vote in verdict.get("votes") or []]},
        "flags": [f.strip()
                  for f in (row.get("flags", "") or "").split("+")
                  if f.strip()],
    }


def _render_card(n, row, verdict, check_keys=(), cand_entry=None,
                 table_label=""):
    verdict = verdict or {}
    method = row.get("method", "") or ""
    kid = row.get("kaikki_sense_id", "") or ""
    lemma = row.get("lemma", "") or ""
    gloss = row.get("kaikki_gloss", "") or ""
    snip = (gloss[:80] + "…") if len(gloss) > 80 else gloss
    chips = signal_chips(row.get("evidence", ""))
    chip_html = "".join(
        '<span class="chip">%s <span class="fa" lang="fa">%s</span> '
        '<span class="alias">(<bdi>%s</bdi>)</span></span>'
        % (_esc(name), _esc(_disp_fa(name, fa)), _esc(alias))
        for name, fa, alias in chips)
    agree_cls, agree_title = _agreement_label(verdict)
    agree_badge = ""
    if verdict:
        agree_badge = ('<span class="badge %s" title="%s">%s '
                       '<span class="code">(<bdi>%s</bdi>)</span></span>'
                       % ("agree" if agree_cls == "agree" else
                          "split" if agree_cls == "split" else "flag",
                          _esc(agree_title),
                          _esc(agree_title.split("·")[0].strip()),
                          _esc(agreement_key(verdict))))
    winner_key = _card_winner(row, verdict)
    keys = " ".join(row_filter_keys(row, verdict, check_keys))
    hay = search_haystack(row, verdict)
    flags = [f.strip() for f in (row.get("flags", "") or "").split("+")
             if f.strip()]
    blk = machine_block(row)
    machine_json = _esc(json.dumps(blk, ensure_ascii=False, indent=1,
                                   sort_keys=True))
    mkeys = _render_mkeys(blk)
    trace = _render_trace(row, verdict, cand_entry,
                          "%s#L%d" % (table_label or "table", n + 1))
    tech = (
        '<details class="tech"><summary>فنی <span lang="en">machine + raw'
        '</span> (scores · thresholds · evidence)</summary>'
        '<div class="tabbar" role="tablist" aria-label="فنی · technical">'
        '<button type="button" role="tab" aria-selected="true" '
        'aria-controls="techm-%d" id="techtab-m-%d">ماشین '
        '<span lang="en">machine JSON</span></button>'
        '<button type="button" role="tab" aria-selected="false" '
        'aria-controls="techr-%d" id="techtab-r-%d">شواهد خام '
        '<span lang="en">raw evidence</span></button></div>'
        '<div role="tabpanel" id="techm-%d" aria-labelledby="techtab-m-%d">'
        '%s<pre>%s</pre></div>'
        '<div role="tabpanel" id="techr-%d" aria-labelledby="techtab-r-%d" '
        'hidden><p><bdi>%s</bdi></p></div>'
        '</details>' % (n, n, n, n, n, n, mkeys, machine_json, n, n,
                        _esc(row.get("evidence", "") or "")))
    flag_badges = "".join(
        '<span class="badge flag">%s '
        '<span class="code">(<bdi>%s</bdi>)</span></span>'
        % (_esc(_flag_fa(f)), _esc(f)) for f in flags)
    top_fa, top_code = top_signal_fa(row)
    more = (('<span class="more" title="%d سیگنال دیگر · more signals">'
             '+%d</span>' % (len(chips) - 1, len(chips) - 1))
            if len(chips) > 1 else "")
    row_ref = "%s#L%d" % (table_label or "table", n + 1)
    payload = _esc(json.dumps(
        export_record(row, verdict, cand_entry, row_ref, n=n),
        ensure_ascii=False))
    return (
        '<tbody class="cardbody %s" id="c-%d" data-keys="%s" data-search="%s">'
        '<tr class="summary" data-kid="%s" data-gloss="%s" data-winner="%s" '
        'data-evidence="%s" data-flags="%s" data-export="%s">'
        '<td><input type="checkbox" class="rowcheck" aria-label="select %s"></td>'
        '<td><bdi lang="en" dir="ltr">%s</bdi></td>'
        '<td class="gloss-snip" lang="en" dir="ltr">%s</td>'
        '<td>%s%s</td>'
        '<td>%s <span class="code">(<bdi>%s</bdi>)</span>%s</td>'
        '<td><button type="button" class="expand" aria-expanded="false">+ detail</button></td>'
        '</tr>'
        '<tr class="detail" hidden><td colspan="6">'
        '<div class="cardhead"><code class="kid"><bdi>%s</bdi></code> %s%s%s</div>'
        '<blockquote class="glossfull" lang="en" dir="ltr">“%s”</blockquote>'
        '<div class="chips">%s</div>'
        '%s'
        '%s'
        '</td></tr>'
        '</tbody>' % (
            _card_class(row, verdict), n, _esc(keys), _esc(hay),
            _esc(kid), _esc(gloss), _esc(winner_key),
            _esc(row.get("evidence", "") or ""), _esc("+".join(flags)),
            payload,
            _esc(kid), _esc(lemma), _esc(snip),
            _method_badge(method), agree_badge,
            _esc(top_fa), _esc(top_code), more,
            _esc(kid), _method_badge(method), flag_badges, agree_badge,
            _esc(gloss), chip_html, trace, tech))

_STAGE_GAUGES = [
    ("stage:link", "g-link", "پیوند", "LINK"),
    ("stage:none", "g-none", "بدون پیوند", "NONE"),
    ("stage:pending", "g-pending", "در انتظار", "PENDING"),
    ("stage:unmapped", "g-unmapped", "نگاشت‌نشده", "UNMAPPED"),
    ("stage:twin", "g-twin", "دوقلو", "twin"),
    ("stage:quarantine", "g-quar", "قرنطینه", "quarantine"),
    ("stage:provisional", "g-prov", "موقت", "provisional"),
]

_PIE_COLORS = {"LINK": "#10b981", "NONE": "#f59e0b", "FAILED": "#ef4444"}
_PIE_FA = {"LINK": "پیوند", "NONE": "بدون‌پیوند", "FAILED": "ناموفق"}


def _pie_slices(link, none, failed):
    """SVG pie paths for the verdict distribution (borrowed geometry).

    >>> paths = _pie_slices(2, 1, 1)
    >>> len(paths)
    3
    >>> _pie_slices(0, 0, 0)
    []
    """
    total = link + none + failed
    if total <= 0:
        return []
    parts = [("LINK", link), ("NONE", none), ("FAILED", failed)]
    parts = [(k, c) for k, c in parts if c > 0]
    if len(parts) == 1:
        key, _c = parts[0]
        return [("<circle cx='100' cy='100' r='80' fill='%s' "
                 "stroke='#0f172a' stroke-width='2' class='pieslice' "
                 "data-fkey='outcome:%s' tabindex='0' role='button' "
                 "aria-label='%s · 100%%'>"
                 "<title>%s · 100%%</title></circle>")
                % (_PIE_COLORS[key], key, _PIE_FA[key], _PIE_FA[key])]
    out = []
    angle = -90.0
    for key, count in parts:
        frac = count / total
        a0, a1 = angle, angle + 360.0 * frac
        large = 1 if frac > 0.5 else 0
        x0 = 100 + 80 * math.cos(a0 * math.pi / 180.0)
        y0 = 100 + 80 * math.sin(a0 * math.pi / 180.0)
        x1 = 100 + 80 * math.cos(a1 * math.pi / 180.0)
        y1 = 100 + 80 * math.sin(a1 * math.pi / 180.0)
        pct = 100.0 * count / total
        out.append(
            "<path d='M 100,100 L %.2f,%.2f A 80,80 0 %d 1 %.2f,%.2f Z' "
            "fill='%s' stroke='#0f172a' stroke-width='2' class='pieslice' "
            "data-fkey='outcome:%s' tabindex='0' role='button' "
            "aria-label='%s · %.1f%%'><title>%s · %.1f%%</title></path>"
            % (x0, y0, large, x1, y1, _PIE_COLORS[key], key,
               _PIE_FA[key], pct, _PIE_FA[key], pct))
        angle = a1
    return out


def _render_verdict_pie(judge):
    total = judge["total"] or 1
    slices = _pie_slices(judge["link"], judge["none"], judge["failed"])
    legend = ""
    for key, count in (("LINK", judge["link"]), ("NONE", judge["none"]),
                       ("FAILED", judge["failed"])):
        pct = 100.0 * count / total if judge["total"] else 0.0
        legend += (
            '<button type="button" class="piebtn" data-fkey="outcome:%s" '
            'data-fgroup="verdict" aria-pressed="false">'
            '<span class="dot" style="background:%s"></span> '
            '<span class="lblfull">%s %s</span> '
            '<b class="now">%d</b> <span class="pct">(%.1f%%)</span>'
            '</button>' % (key, _PIE_COLORS[key], _esc(_PIE_FA[key]), key,
                            count, pct))
    return ("<div class=\"pie-wrap\"><svg class=\"pie-svg\" viewBox=\"0 0 200 200\" "
            "id=\"verdictpie\" role=\"img\" "
            "aria-label='توزیع رأی داوران · verdict distribution'>%s</svg>"
            "<div class='pielegend'>%s</div></div>"
            % ("".join(slices), legend))


def _render_latency_hist(stats):
    peak = max([b["count"] for b in stats["buckets"]] + [1])
    bars = []
    for bucket in stats["buckets"]:
        height = 120.0 * bucket["count"] / peak
        bars.append(
            "<div class='latency-bar-wrap'>"
            "<div class='latency-bar' style='height:%.1fpx'></div>"
            "<span class='latency-label'><bdi>%s</bdi></span>"
            "<span class='latency-count'>%d</span></div>"
            % (height, bucket["label"], bucket["count"]))
    if stats["n"]:
        line = ("avg %.1fs | p50 %.1fs | p90 %.1fs | max %.1fs · %d رأی"
                % (stats["avg"], stats["p50"], stats["p90"], stats["max"],
                   stats["n"]))
    else:
        line = "بدون رأی ثبت‌شده · no votes yet"
    return ("<div class=\"latency-chart\" id=\"lathist\" role=\"img\" "
            "aria-label='نمودار تأخیر داور · judge latency histogram'>%s</div>"
            "<div class='latline'><bdi>%s</bdi></div>"
            % ("".join(bars), _esc(line)))


def _render_checks(checks):
    rows = []
    for check in checks:
        status = check["status"]
        if status == "PASS":
            badge = ('<span class="badge agree">گذشت '
                     '<span class="code">(PASS)</span></span>')
        else:
            badge = ('<span class="badge split">هشدار '
                     '<span class="code">(WARN)</span></span>')
        rows.append(
            "<tr><td><button type='button' class='checkbtn' "
            "data-fkey='check:%s' data-fgroup='check' aria-pressed='false'>"
            "<span class='lblfull'>%s · %s</span></button></td>"
            "<td><bdi>%s</bdi></td><td>%s</td></tr>"
            % (_esc(check["id"]), _esc(check["fa"]), _esc(check["en"]),
               _esc(check["value"]), badge))
    return ("<div class=\"tablewrap\"><table class=\"checks\">"
            "<thead><tr><th>بررسی <span lang='en'>check</span></th>"
            "<th>مقدار <span lang='en'>value</span></th>"
            "<th>وضعیت <span lang='en'>status</span></th></tr></thead>"
            "<tbody>%s</tbody></table></div>" % "".join(rows))


# --- Top redress (S1/S2): summary strip + slim latency strip ---

# Vazirmatn embedded from LOCAL system files (offline law: read-only copy
# at render time, Base64 data-URI, no download, no googleapis). Fail-soft:
# missing files render the system fallback stack unchanged.
_FONT_FILES = (
    ("Vazirmatn", 400, r"C:\Windows\Fonts\Vazirmatn-Regular.ttf"),
    ("Vazirmatn", 700, r"C:\Windows\Fonts\Vazirmatn-Bold.ttf"),
)


def _font_face_css():
    """Base64 @font-face block for Vazirmatn Regular(400)+Bold(700).

    >>> css = _font_face_css()
    >>> "@font-face" in css and "Vazirmatn" in css
    True
    """
    import base64
    blocks = []
    for family, weight, path in _FONT_FILES:
        try:
            raw = Path(path).read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        b64 = base64.b64encode(raw).decode("ascii")
        blocks.append(
            "@font-face{font-family:'%s';font-style:normal;font-weight:%d;"
            "font-display:swap;src:url(data:font/ttf;base64,%s)"
            " format('truetype');}"
            % (family, weight, b64))
    return "".join(blocks)


def _render_latency_strip(stats):
    """Slim judge-latency strip (S2): avg/p90 + 8 CSS mini-bars (<=28px).

    The full histogram moves behind the strip's own expander (collapsed
    by default); numbers come from the existing per-vote ``latency_s``.

    >>> html_out = _render_latency_strip(latency_stats([6.0, 7.0, 8.0, 9.0]))
    >>> ('id="latstrip"' in html_out and html_out.count("latstrip-bar'") == 8)
    True
    >>> "avg 7.5s" in html_out and "p90 9.0s" in html_out
    True
    """
    peak = max([b["count"] for b in stats["buckets"]] + [1])
    bars = []
    for bucket in stats["buckets"]:
        height = 28.0 * bucket["count"] / peak
        bars.append(
            "<span class='latstrip-bar' style='height:%.1fpx' "
            "title='%s: %d'></span>"
            % (height, bucket["label"], bucket["count"]))
    if stats["n"]:
        line = ("avg %.1fs · p90 %.1fs"
                % (stats["avg"], stats["p90"]))
    else:
        line = "بدون رأی ثبت‌شده · no votes yet"
    return ("<div class=\"latstrip\" id=\"latstrip\" role=\"img\" "
            "aria-label='نوار تأخیر داور · judge latency strip'>"
            "<span class='latstrip-nums'><bdi>%s</bdi></span>"
            "<span class='latstrip-bars'>%s</span></div>"
            "<details class=\"top-panel\" id=\"panel-latency-full\">"
            "<summary>نمودار کامل تأخیر "
            "<span lang='en'>full histogram</span></summary>%s</details>"
            % (_esc(line), "".join(bars), _render_latency_hist(stats)))


def _render_summary_strip(tele, stage, judge, run_label=""):
    """One-line top summary (S1): totals + coverage + unanimous + expand.

    Carries BOTH versions side by side: ``viewer:`` is this gallery's own
    version (which viewer renders the page); ``data:`` is the source run's
    version (which linker build made the DATA — ``<build> (<rules-tag>)``
    when every row shares one provenance triple, ``mixed`` when rows
    disagree, ``unknown (absent)`` when no row carries one; never guessed).
    """
    if judge["total"]:
        coverage = 100.0 * judge["judged"] / judge["total"]
    else:
        coverage = 0.0
    unanim = (100.0 * judge["unanimous"] / judge["judged"]
              if judge["judged"] else 0.0)
    return (
        '<div id="summary-strip" role="status">'
        'کل معنی‌ها <b>%d</b> · پیوند <b>%d</b> · بدون‌پیوند <b>%d</b> · '
        'پوشش داور <b>%.0f%%</b> · اجماع <b>%.0f%%</b> · '
        'viewer: %s · data: %s '
        '<a class="sumexpand" href="#sec-table">نمایش جدول '
        '<span lang="en">expand · jump to table</span></a></div>'
        % (tele["total"], stage["link"], stage["none"],
           coverage, unanim, _esc(GALLERY_VERSION), _esc(run_label)))


def _threshold_signatures(rows):
    """Distinct machine-threshold signatures across rows (uniformity assert).

    Thresholds are frozen module constants, so every row must share one
    signature; more than one means the page constants diverged and the
    differing card must show its own values inline (flagged).
    """
    sigs = set()
    for row in rows or []:
        sigs.add(json.dumps(machine_block(row).get("thresholds", {}),
                            sort_keys=True))
    return sigs


def _render_global_thresholds(rows):
    """Page-level decision constants, rendered ONCE per gallery.

    Carries every frozen cut (with FA labels + codes) plus the full
    shoot glossary. Asserts page-wide uniformity; on divergence renders
    the flag and returns diverged=True so cards show inline values.
    """
    sigs = _threshold_signatures(rows)
    diverged = len(sigs) > 1
    consts = machine_block({}).get("thresholds", {})
    order = ("jaccard", "se_cut", "se_veto_floor", "link_min",
             "shortlist_cap", "ultra_short_min_tokens")
    items = "".join(
        "<li>%s <span class='code'>(<bdi>%s</bdi>)</span> = <bdi>%s</bdi></li>"
        % (_esc(_MKEY_FA.get(key, key)), _esc(key),
           _esc(consts.get(key, "—")))
        for key in order)
    flag = ""
    if diverged:
        flag = ("<p class='thr-flag'>ناهمخوانی حدها در ردیف‌ها "
                "<span class='code'>(<bdi>thresholds-diverged</bdi>)</span>؛ "
                "مقدار متفاوت هر کارت کنار نمره همان کارت آمده</p>")
    return (diverged,
            '<details class="top-panel" id="global-thresholds">'
            '<summary>حدهای سراسری تصمیم '
            '<span lang="en">global decision constants</span></summary>'
            "<ul class='thr-list'>%s</ul>"
            "<p class='shoot-gloss'>%s</p>%s</details>"
            % (items, _esc(_SHOOT_GLOSSARY_FULL), flag))


def _render_navpanel():
    """ONE dropdown panel under the nav: search + every filter key.

    Replaces the sprawling filter drawer (deleted): the nav's filter /
    search buttons toggle this single panel. Common keys (stage /
    signal / judge / outcome LINK+NONE) sit in the main group;
    advanced / rare keys (outcome FAILED, src:mechanical, checks) hide
    in a second inner collapsible. Same data-fkey/data-fgroup keys as
    the diagnostic panels (syncPressed loops all); state stays in the
    URL hash (see _JS readHash/writeHash).
    """
    stage_btns = "".join(
        '<button type="button" class="fbtn %s" data-fkey="%s" '
        'data-fgroup="stage" aria-pressed="false">'
        '<span class="lblfull">%s · %s</span></button>'
        % (cls, fkey, _esc(fa), _esc(en))
        for fkey, cls, fa, en in _STAGE_GAUGES)
    sig_btns = "".join(
        '<button type="button" class="fbtn" data-fkey="sig:%s" '
        'data-fgroup="signal" aria-pressed="false">'
        '<span class="lblfull">%s · %s</span></button>'
        % (entry["name"], _esc(entry["name"]),
           _esc(_disp_fa(entry["name"], entry["fa"])))
        for code in ("Sa", "Sb", "Sc", "Sd", "Se", "short-gloss",
                     "zero-sig", "judge")
        for entry in (signal_vocab(code),))
    judge_btns = (
        '<button type="button" class="fbtn" data-fkey="judge:unanimous" '
        'data-fgroup="judge" aria-pressed="false">'
        '<span class="lblfull">اجماعی unanimous</span></button>'
        '<button type="button" class="fbtn" data-fkey="judge:concordant" '
        'data-fgroup="judge" aria-pressed="false">'
        '<span class="lblfull">هم‌نظر concordant</span></button>'
        '<button type="button" class="fbtn" data-fkey="judge:split-vote" '
        'data-fgroup="judge" aria-pressed="false">'
        '<span class="lblfull">شقه split-vote</span></button>'
        '<button type="button" class="fbtn" data-fkey="judge:unjudged" '
        'data-fgroup="judge" aria-pressed="false">'
        '<span class="lblfull">داوری‌نشده unjudged</span></button>')
    outcome_btns = "".join(
        '<button type="button" class="fbtn" data-fkey="outcome:%s" '
        'data-fgroup="verdict" aria-pressed="false">'
        '<span class="lblfull">%s %s</span></button>'
        % (key, _esc(_PIE_FA[key]), key)
        for key in ("LINK", "NONE"))
    outcome_rare = "".join(
        '<button type="button" class="fbtn" data-fkey="outcome:%s" '
        'data-fgroup="verdict" aria-pressed="false">'
        '<span class="lblfull">%s %s</span></button>'
        % (key, _esc(_PIE_FA[key]), key)
        for key in ("FAILED",))
    check_btns = "".join(
        '<button type="button" class="fbtn" data-fkey="check:%s" '
        'data-fgroup="check" aria-pressed="false">'
        '<span class="lblfull">%s · %s</span></button>'
        % (_esc(check_id), _esc(check_fa), _esc(check_en))
        for check_id, check_fa, check_en in _CHECKS)
    # Judge-less mechanical LINKs (rule wins, no verdict): exact key, so
    # the owner filter isolates exactly those rows (run20: 46).
    src_btns = (
        '<button type="button" class="fbtn" data-fkey="src:mechanical" '
        'data-fgroup="source" aria-pressed="false">'
        '<span class="lblfull">پیوند قاعده‌ای بدون داور · mechanical</span>'
        '</button>')
    return (
        '<div class="navpanel" id="navpanel" hidden>'
        '<div class="navpanel-bar">'
        '<span class="navpanel-title">صافی‌ها و جست‌وجو '
        '<span lang="en">filters · search</span></span>'
        '<button type="button" class="navclose" id="navclose" '
        'aria-label="بستن پنل · close panel">× بستن '
        '<span lang="en">close</span></button></div>'
        '<div class="navsearch">'
        '<input type="search" id="search" dir="auto" autocomplete="off" '
        'aria-label="جست‌وجو · search lemma gloss sensekey evidence" '
        'placeholder="جست‌وجو · search…">'
        '<button type="button" class="export" id="searchclear">پاک‌کردن '
        '<span lang="en">clear</span></button></div>'
        '<div class="panel-group"><h3>مرحله <span lang="en">stage</span></h3>%s</div>'
        '<div class="panel-group"><h3>سیگنال <span lang="en">signal</span></h3>%s</div>'
        '<div class="panel-group"><h3>داور <span lang="en">judge</span></h3>%s</div>'
        '<div class="panel-group"><h3>نتیجه <span lang="en">outcome</span></h3>%s</div>'
        '<details class="panel-advanced" id="navpanel-advanced">'
        '<summary>پیشرفته <span lang="en">advanced / rare</span></summary>'
        '<div class="panel-group"><h3>ناموفق <span lang="en">failed</span></h3>%s</div>'
        '<div class="panel-group"><h3>منبع <span lang="en">source</span></h3>%s</div>'
        '<div class="panel-group"><h3>بررسی <span lang="en">checks</span></h3>%s</div>'
        '</details>'
        '<button type="button" class="export" id="filter-clear">'
        'پاک‌کردن همه صافی‌ها <span lang="en">clear all</span></button>'
        '</div>'
        % (stage_btns, sig_btns, judge_btns, outcome_btns, outcome_rare,
            src_btns, check_btns))


def build_linker_gallery(rows, verdicts, out_html, candidates=None,
                         table_label=""):
    """Render a static filterable linker gallery; return the summary dict.

    ``rows`` are link-table dicts, ``verdicts`` judge-verdict dicts,
    ``candidates`` an optional ``{kid: {"top3": [...]}}`` mapping feeding
    the per-card candidates-in inputs (both plain data, all may be empty).
    ``table_label`` feeds export ``row_ref`` (table filename); empty falls
    back to ``"table"``. Writes ``out_html``.
    """
    rows = list(rows or [])
    verdicts = list(verdicts or [])
    candidates = candidates or {}
    judge = verdict_summary(verdicts)
    tele = telemetry_counters(rows)
    lats = verdict_latencies(verdicts)
    lat = latency_stats(lats)
    checks = quality_checks(rows, verdicts)
    by_kid = {v.get("kid"): v for v in verdicts if v.get("kid")}

    violators = {}
    for check in checks:
        for kid in check["violators"]:
            violators.setdefault(kid, []).append("check:" + check["id"])

    grouped = OrderedDict()
    for row in rows:
        grouped.setdefault(row.get("lemma", "") or "—", []).append(row)

    stage = tele["stage"]
    stage_counts = {
        "stage:link": stage["link"], "stage:none": stage["none"],
        "stage:pending": stage["pending"], "stage:unmapped": stage["unmapped"],
        "stage:twin": stage["twin"], "stage:quarantine": stage["quarantine"],
        "stage:provisional": stage["provisional"],
    }
    gauge_html = (
        '<button type="button" class="gauge g-link" data-fkey="__total__" disabled>'
        '<b class="num">%d</b>'
        '<span class="lbl"><span class="lblfull">کل معنی‌ها · total senses</span></span></button>'
        % tele["total"])
    for fkey, cls, fa, en in _STAGE_GAUGES:
        short = fkey.split(":", 1)[1]
        gauge_html += (
            '<button type="button" class="gauge %s" data-fkey="%s" '
            'data-fgroup="stage" data-tot="%d" aria-pressed="false">'
            '<b class="num"><span class="base">%d</span><span class="now">%d</span> '
            '<span class="tot">/ %d</span></b>'
            '<span class="lbl"><span class="lblfull">%s · %s</span> (%s)</span></button>'
            % (cls, fkey, stage_counts[fkey],
               stage_counts[fkey], stage_counts[fkey], stage_counts[fkey],
               fa, _esc(en), short))

    sig_total = max(tele["total"], 1)
    sig_rows = ""
    for code in ("Sa", "Sb", "Sc", "Sd", "Se", "short-gloss", "zero-sig", "judge"):
        entry = signal_vocab(code)
        name, fa = entry["name"], _disp_fa(entry["name"], entry["fa"])
        count = tele["signals"].get(name, 0)
        sig_rows += (
            '<div class="sig-row"><button type="button" class="sigbtn" '
            'data-fkey="sig:%s" data-fgroup="signal" aria-pressed="false">'
            '<code><bdi>%s</bdi></code> <span class="fa" lang="fa">%s</span> '
            '<span class="alias">(<bdi>%s</bdi>)</span> '
            '<span class="lblfull" hidden>%s · %s</span>'
            '<b class="now">%d</b><span class="bar"><i style="width:%d%%"></i></span>'
            '</button></div>'
            % (name, _esc(name), _esc(fa), _esc(code),
               _esc(name), _esc(fa), count, round(100 * count / sig_total)))

    pie_html = _render_verdict_pie(judge)
    checks_html = _render_checks(checks)
    # S1: every top diagnostic collapsed by default (no `open`); the
    # full-width latency row is deleted here — S2 moves a slim strip
    # plus the full histogram (behind its own expander) into the judge
    # panel. Expanded state persists per session via localStorage (JS).
    gauges_panel = (
        '<details class="top-panel" id="panel-gauges">'
        '<summary>نشانگرهای مرحله '
        '<span lang="en">stage gauges</span></summary>'
        '<div class="gauges">%s</div></details>' % gauge_html)
    verdict_panel = (
        '<details class="top-panel" id="panel-verdict">'
        '<summary>رأی داوران '
        '<span lang="en">verdict distribution (click a slice to filter)</span>'
        '</summary>%s</details>' % pie_html)
    checks_panel = (
        '<details class="top-panel" id="panel-checks">'
        '<summary>بررسی کیفیت '
        '<span lang="en">quality checklist (click a row to isolate violators)</span>'
        '</summary>%s</details>' % checks_html)
    latstrip_html = _render_latency_strip(lat)
    run_info = run_version(rows)
    summary_html = _render_summary_strip(tele, stage, judge,
                                         run_info["label"])
    panel_html = _render_navpanel()
    _thr_diverged, thr_html = _render_global_thresholds(rows)

    judge_html = (
        '<div class="facts">'
        '<div class="fact"><h3>پوشش <span class="en" lang="en">coverage</span></h3>'
        '<p class="big">داوری‌شده <b>%d</b> از <b>%d</b></p>'
        '<p class="why1">چند معنی به داور رسید و رأی گرفت</p></div>'
        '<div class="fact"><h3>اطمینان <span class="en" lang="en">certainty</span></h3>'
        '<p class="big"><button type="button" class="mini" data-fkey="judge:unanimous" '
        'data-fgroup="judge" aria-pressed="false"><span class="lblfull">اجماعی unanimous</span> '
        '<b class="now">%d</b></button>'
        '<button type="button" class="mini" data-fkey="judge:concordant" '
        'data-fgroup="judge" aria-pressed="false"><span class="lblfull">هم‌نظر concordant</span> '
        '<b class="now">%d</b></button>'
        '<button type="button" class="mini" data-fkey="judge:split-vote" '
        'data-fgroup="judge" aria-pressed="false"><span class="lblfull">شقه split-vote</span> '
        '<b class="now">%d</b></button></p>'
        '<p class="why1">اجماعی یعنی هر ۳ داور هم‌نظر و هم‌دلیل؛ هم‌نظر یعنی هم‌رأی با دلیل متفاوت؛ شقه یعنی ۲-۱</p></div>'
        '<div class="fact"><h3>نتیجه <span class="en" lang="en">outcome</span></h3>'
        '<p class="big"><button type="button" class="mini" data-fkey="outcome:LINK" '
        'data-fgroup="verdict" aria-pressed="false"><span class="lblfull">پیوند LINK</span> '
        '<b class="now">%d</b></button>'
        '<button type="button" class="mini" data-fkey="outcome:NONE" '
        'data-fgroup="verdict" aria-pressed="false"><span class="lblfull">بدون‌پیوند NONE</span> '
        '<b class="now">%d</b></button>'
        '<button type="button" class="mini" data-fkey="outcome:FAILED" '
        'data-fgroup="verdict" aria-pressed="false"><span class="lblfull">ناموفق FAILED</span> '
        '<b class="now">%d</b></button></p>'
        '<p class="why1">نتیجه نهایی داور: پیوند خورد، نخورد، یا ناموفق بود</p></div>'
        '</div>' % (
            judge["judged"], judge["total"],
            judge["unanimous"], judge["concordant"], judge["split"],
            judge["link"], judge["none"], judge["failed"]))

    bodies = []
    n = 0
    for lemma, items in grouped.items():
        for row in items:
            n += 1
            kid = row.get("kaikki_sense_id", "") or ""
            bodies.append(_render_card(
                n, row, by_kid.get(kid) or {}, violators.get(kid, ()),
                candidates.get(kid), table_label))

    nav_html = (
        '<nav class="pillnav" id="pillnav" aria-label="بخش‌ها · sections">'
        '<a id="tab-gauges" href="#sec-gauges">نشانگرها '
        '<span lang="en">gauges</span></a>'
        '<a id="tab-judge" href="#sec-judge">داور '
        '<span lang="en">judge</span></a>'
        '<a id="tab-table" href="#sec-table">جدول '
        '<span lang="en">table</span></a>'
        '<a id="tab-help" href="#sec-help">راهنما '
        '<span lang="en">help</span></a>'
        '<button type="button" class="navbtn" id="navfilter" '
        'aria-expanded="false" aria-controls="navpanel">صافی‌ها '
        '<span lang="en">filters</span></button>'
        '<button type="button" class="navbtn" id="navsearch" '
        'aria-expanded="false" aria-controls="navpanel">جست‌وجو '
        '<span lang="en">search</span></button></nav>'
        '%s' % panel_html)

    help_html = (
        '<details class="help"><summary>راهنما <span lang="en">help</span></summary>'
        '<p>هر عدد یک دکمه صافی است: بزن تا سطرها صاف شوند. صافی‌های هم‌گروه '
        'با OR ترکیب می‌شوند (مثلاً پیوند یا بدون‌پیوند) و صافی‌های گروه‌های '
        'مختلف با AND. صافی‌های فعال بالا به‌صورت چیپ «گروه · نام ×» '
        'قابل‌حذف دیده می‌شوند. برش‌های نمودار دایره‌ای رأی '
        '(<span lang="en">pie slices</span>) و سطرهای جدول بررسی هم صافی‌اند: '
        'سطر بررسی، سطرهای متخلف را جدا می‌کند؛ اگر هیچ سطری نماند پیام '
        '«نتیجه‌ای نیست» با دکمه پاک‌کردن همه صافی‌ها دیده می‌شود.</p>'
        '<p>جعبه جست‌وجو روی واژه، تعریف، کلیدها و شواهد می‌گردد '
        '<span lang="en">lemma · gloss · sensekey · evidence</span>؛ '
        'نویسه‌ها بی‌توجه به بزرگی/کوچکی و ارقام فارسی/لاتین یکسان‌اند. '
        'پیشوند <code>kid:</code> فقط روی شناسه kaikki و پیشوند '
        '<code>key:</code> فقط روی کلید wordnet (سطر یا برنده داور) '
        'می‌گردد؛ بقیه عبارت‌ها زیررشته‌اند. تطابق در ستون تعریف با '
        '<span lang="en">highlight</span> دیده می‌شود. شمار نتیجه‌ها زنده است.</p>'
        '<p>هر کارت ردیاب جریان پیوند را نشان می‌دهد '
        '<span lang="en">flow trace</span>: معنی ورودی مبدأ، غربالگری '
        'کاندیداها، ارزیابی سیگنال‌ها، حل تعارض و داوری، فرجام پیوند و '
        'تکمیل — با سیم‌های نوری پویا (رنگ سیم = سرنوشت گام)؛ '
        'نامزدهای ورودی با رتبه و امتیاز فهرست‌کوتاه (برنده با لبه سبز و ✓)، '
        'سیگنال‌ها با واژه/نمره دقیق شلیک، تصمیم با قاعده و مقایسه حد، '
        'داوری با آرا و نقل دلیل، تکمیل فیلدها با منبع هر میدان. ردیابی '
        'مرحله‌ها همیشه باز است؛ جزئیات فنی (ماشین + شواهد خام) در یک '
        'بخش دوبرگه است. هیچ کدی بدون جمله فارسی‌اش نیست: کدها در '
        'قالب خاکستری کوچک کنار جمله‌اند.</p>'
        '<p>خروجی دکمه Export برای ارزیابی مدل زبانی است '
        '<span lang="en">for LLM evaluation</span>: یک آرایه '
        '<code>records</code> که هر رکورد شناسه، ارجاع سطر '
        '(<code>row_ref</code>)، تعریف ورودی، تصمیم، سیگنال‌های شلیک‌کرده، '
        'تعریف کامل برنده (هرگز بریده نمی‌شود)، نامزدها، آرای فشرده داور و '
        'پرچم‌ها را دارد — همان شمای <code>EXPORT_SCHEMA</code> بالای فایل. '
        'نامزدها و آرا با دو گزینه کنار دکمه حذف می‌شوند (هر دو پیش‌فرض '
        'روشن؛ آرا فشرده و کم‌حجم‌اند).</p>'
        '<p>نوار بالای صفحه دو نسخه را کنار هم نشان می‌دهد '
        '<span lang="en">versions</span>: نسخه گالری '
        '<span lang="en">gallery version = which viewer renders it</span> '
        'یعنی کدام نماگر این صفحه را می‌سازد؛ نسخه اجرا '
        '<span lang="en">run version = which linker build made the data'
        '</span> یعنی کدام ساخت لینکر داده‌ها را ساخته است. '
        'نسخه اجرا از ستون منشأ ردیف‌ها خوانده می‌شود و هرگز حدس زده '
        'نمی‌شود: اگر همه ردیف‌ها یک سه‌تایی مشترک داشته باشند به‌صورت '
        '«ساخت (برچسب قاعده)» دیده می‌شود، اگر ردیف‌ها ناهمخوان باشند '
        '«مخلوط» و اگر منشأ قابل‌خواندن نباشد «نامشخص» است.</p></details>')

    changelog_items = "".join(
        "<li><bdi>%s</bdi> · %s</li>" % (_esc(date), _esc(line))
        for date, line in GALLERY_CHANGELOG)
    footer_html = (
        '<footer>linker gallery v%s · stdlib static render · '
        'red = quarantined/known-false · amber = provisional/split/concordant<br>'
        '<details class="glog"><summary>تغییرات نما '
        '<span lang="en">gallery changelog</span></summary>'
        '<ul>%s</ul></details></footer>'
        % (_esc(GALLERY_VERSION), changelog_items))

    page = (
        '<!DOCTYPE html>\n<html lang="fa" dir="rtl">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<title>نمایشگر پیوند · linker gallery</title>\n'
        '<style>%s</style>\n</head>\n<body>\n<div class="shell">\n'
        '<!-- EXPORT_SCHEMA: {"records": [{kid, row_ref, lemma, in_def, '
        'decision{method, winner, locator}, fires[{sig, val, cut, fired}], '
        'winner_def (FULL), candidates[{rank, key, j, def}], '
        'judge{votes (compact), agree}, flags}]} -->\n'
        '<header class="top"><h1>نمایشگر پیوند '
        '<span class="en" lang="en" dir="ltr">linker gallery</span></h1>\n'
        '<p class="meta">link table rows: %d · verdicts: %d · '
        'provisional overlaps its method stage</p>\n'
        '<a class="jumptable" id="jumptable" href="#sec-table">پرش به جدول '
        '<span lang="en">jump straight to table</span> ↓</a></header>\n'
        '%s\n'
        '%s\n'
        '%s\n'
        '<section id="sec-gauges" aria-label="نشانگرها · gauges">'
        '%s\n'
        '%s\n'
        '%s\n'
        '</section>'
        '<section id="sec-judge" aria-label="داور · judge">'
        '<div class="panel"><h2>توزیع سیگنال‌ها '
        '<span class="en" lang="en">signal-fire distribution (rows)</span></h2>%s</div>\n'
        '<div class="panel"><h2>توافق داوران '
        '<span class="en" lang="en">judge agreement (where known)</span></h2>%s</div>\n'
        '<div class="panel"><h2>تأخیر داور '
        '<span class="en" lang="en">judge latency (per-vote seconds)</span></h2>%s</div>\n'
        '</section>'
        '<section id="sec-table" aria-label="جدول · table">'
        '<div class="toolbar">'
        '<div id="chips" aria-live="polite"></div>'
        '<span id="countline" aria-live="polite"></span>'
        '<div id="allclear" hidden>۰ نتیجه · no matching rows — '
        '<button type="button" class="export" id="clearall">پاک‌کردن همه '
        'صافی‌ها <span lang="en">clear all</span></button></div>'
        '<div class="export-capsule" id="export-capsule">'
        '<span class="export-capsule-label">شامل خروجی '
        '<span lang="en">export includes</span></span>'
        '<label class="exopt"><input type="checkbox" id="exp-cand" checked> '
        'نامزدها <span lang="en">candidates</span></label>'
        '<label class="exopt"><input type="checkbox" id="exp-judge" checked> '
        'آرا <span lang="en">judge votes</span></label>'
        '<button type="button" class="export" id="export">خروجی JSON '
        '<span lang="en">export selected</span></button></div></div>\n'
        '<div class="tablewrap"><table class="senses">'
        '<thead><tr><th><input type="checkbox" id="checkall" aria-label="select all"></th>'
        '<th>واژه <span lang="en">lemma</span></th>'
        '<th>تعریف <span lang="en">gloss</span></th>'
        '<th>وضعیت/روش <span lang="en">status · method</span></th>'
        '<th>سیگنال برتر <span lang="en">top signal</span></th>'
        '<th></th></tr></thead>\n'
        '%s\n'
        '</table></div>\n'
        '</section>'
        '<section id="sec-help" aria-label="راهنما · help">%s</section>\n'
        '%s\n'
        '</div>\n<script>%s</script>\n</body>\n</html>' % (
            _font_face_css() + _CSS, tele["total"], judge["total"],
            summary_html, nav_html, thr_html, gauges_panel, verdict_panel,
            checks_panel, sig_rows, judge_html, latstrip_html,
            "\n".join(bodies), help_html, footer_html, _JS))

    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return {"stats": {"total": tele["total"], "stage": stage,
                      "signals": tele["signals"]},
            "judge": judge, "latency": lat, "checks": checks,
            "words": len(grouped), "out": str(out),
            "run_version": run_info}


def main(argv=None):
    """CLI: render a gallery from a TSV link table + verdicts JSON."""
    parser = argparse.ArgumentParser(
        description="Render a static filterable linker gallery (stdlib only).")
    parser.add_argument("--table", required=True, help="link table TSV path")
    parser.add_argument("--verdicts", default="",
                        help="judge verdicts JSON path (optional)")
    parser.add_argument("--candidates", default="",
                        help="candidates JSON path {kid: {top3}} (optional)")
    parser.add_argument("--out", required=True, help="output HTML path")
    parser.add_argument("--words", default="",
                        help="comma-separated lemma subset (optional)")
    args = parser.parse_args(argv)
    with open(args.table, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    verdicts = []
    if args.verdicts:
        payload = json.load(open(args.verdicts, encoding="utf-8"))
        verdicts = payload.get("verdicts", payload
                               if isinstance(payload, list) else [])
    candidates = {}
    if args.candidates:
        payload = json.load(open(args.candidates, encoding="utf-8"))
        if isinstance(payload, dict):
            candidates = payload
    wanted = {w.strip() for w in args.words.split(",") if w.strip()}
    if wanted:
        # Real tables carry no ``lemma`` column — match on the kaikki id
        # via cli.word_matches_kid (single source; see
        # factory/linker/cli.py).
        rows = [r for r in rows
                if any(word_matches_kid(w, r.get("kaikki_sense_id", ""))
                       for w in wanted)]
        verdicts = [v for v in verdicts
                    if v.get("lemma") in wanted
                    or any(word_matches_kid(w, v.get("kid", ""))
                           for w in wanted)]
        candidates = {k: v for k, v in candidates.items()
                      if (v or {}).get("lemma", "") in wanted
                      or k in {r.get("kaikki_sense_id", "") for r in rows}}
    summary = build_linker_gallery(rows, verdicts, args.out,
                                   candidates=candidates,
                                   table_label=Path(args.table).name)
    print("gallery: %s (rows=%d words=%d)" % (
        summary["out"], summary["stats"]["total"], summary["words"]))
    return 0


_CSS = """
:root {
  color-scheme: dark;
  --font-sans: "Vazirmatn", system-ui, "Segoe UI", Tahoma, sans-serif;
  --font-mono: "JetBrains Mono", "SF Mono", Consolas, monospace;
  --bg-page: #121316;
  --bg-surface: #191a1f;
  --bg-surface-hover: #22232a;
  --border-subtle: #292b34;
  --border-strong: #3a3d4a;
  --text-primary: #f3f4f6;
  --text-secondary: #9da3af;
  --text-muted: #6b7280;
  --accent: #38bdf8;
  --accent-soft: #0369a133;
  --link-b: #065f46; --link-bg: #064e3b55;
  --none-b: #6b7280; --none-bg: #27272a55;
  --pend-b: #075985; --pend-bg: #0369a133;
  --unmap-b: #3f3f46; --unmap-bg: #18181b66;
  --twin-b: #7c3aed; --twin-bg: #581c8733;
  --quar-b: #7f1d1d; --quar-t: #f87171;
  --prov-b: #78350f; --prov-t: #fbbf24;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  font-family: var(--font-sans);
  background: var(--bg-page);
  color: var(--text-primary);
  line-height: 1.45;
  font-size: 15px;
}
section { scroll-margin-top: 76px; }
.shell { max-width: 1180px; margin: 0 auto; padding: 16px 14px 64px; }
header.top h1 { font-size: 23px; font-weight: 800; }
header.top h1 .en { color: var(--text-muted); font-weight: 400; font-size: 14px; }
header.top p.meta {
  font-family: var(--font-mono); font-size: 12px; color: var(--text-secondary);
  margin-top: 4px;
}
nav.pillnav {
  position: sticky; top: 8px; z-index: 50;
  display: flex; gap: 8px; flex-wrap: wrap;
  background: #191a1fcc; backdrop-filter: blur(10px);
  border: 1px solid var(--border-subtle); border-radius: 999px;
  padding: 6px 10px; margin: 12px 0;
}
nav.pillnav a {
  border-radius: 999px; padding: 6px 16px; min-height: 44px;
  display: inline-flex; align-items: center; gap: 6px;
  color: var(--text-secondary); text-decoration: none; font-size: 13px;
  border: 1px solid transparent;
}
nav.pillnav a:hover { background: var(--bg-surface-hover); color: var(--text-primary); }
nav.pillnav a.active { border-color: var(--accent); color: var(--text-primary);
  box-shadow: 0 0 0 1px var(--accent); }
nav.pillnav a .en { color: var(--text-muted); font-size: 12px; }
button.navbtn {
  border-radius: 999px; padding: 6px 16px; min-height: 44px;
  display: inline-flex; align-items: center; gap: 6px;
  color: var(--text-secondary); font: inherit; font-size: 13px;
  border: 1px solid var(--border-strong); background: none; cursor: pointer;
}
button.navbtn:hover { background: var(--bg-surface-hover); color: var(--text-primary); }
button.navbtn[aria-expanded="true"] { border-color: var(--accent); color: var(--text-primary);
  box-shadow: 0 0 0 1px var(--accent); }
button.navbtn .en { color: var(--text-muted); font-size: 12px; }
.navpanel {
  position: sticky; top: 64px; z-index: 49;
  background: var(--bg-surface); border: 1px solid var(--border-strong);
  border-radius: 12px; padding: 10px 12px; margin: 0 auto 12px;
  max-width: 760px; width: min(100%, 760px);
  max-height: 62vh; overflow-y: auto; overscroll-behavior: contain;
}
.navpanel[hidden] { display: none; }
.navpanel-bar { display: flex; align-items: center;
  justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.navpanel-title { font-size: 13px; font-weight: 700;
  color: var(--text-primary); }
.navpanel-title .en { color: var(--text-muted); font-weight: 400;
  font-size: 12px; }
button.navclose { background: none; border: 1px solid var(--border-strong);
  border-radius: 999px; color: var(--text-secondary); font: inherit;
  font-size: 13px; padding: 6px 14px; min-height: 44px; min-width: 44px;
  cursor: pointer; }
button.navclose:hover { background: var(--bg-surface-hover);
  color: var(--text-primary); }
.navsearch { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.navsearch #search { min-height: 40px; font-size: 13px;
  padding: 6px 14px; }
.panel-group { margin: 8px 0; }
.panel-group h3 { font-size: 12px; color: var(--text-muted); margin-bottom: 4px; }
.panel-group h3 .en { font-weight: 400; }
details.panel-advanced { border: 1px dashed var(--border-strong);
  border-radius: 10px; padding: 6px 10px; margin: 8px 0; }
details.panel-advanced > summary { cursor: pointer; font-weight: 700;
  font-size: 13px; min-height: 44px; display: flex; align-items: center;
  gap: 6px; }
ul.thr-list { padding-inline-start: 20px; font-size: 13px;
  color: var(--text-secondary); }
p.shoot-gloss, p.flowtrace-shoot { font-size: 12px; color: var(--text-secondary);
  background: #00000033; border: 1px solid var(--border-subtle);
  border-radius: 8px; padding: 4px 10px; margin-top: 6px; }
p.thr-flag { color: var(--prov-t); font-size: 13px; font-weight: 700; }
p.flowtrace-cutptr { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
details.glog { margin-top: 8px; font-size: 12px; color: var(--text-secondary); }
details.glog > summary { cursor: pointer; min-height: 44px;
  display: flex; align-items: center; gap: 6px; }
details.glog ul { padding-inline-start: 20px; }
details.help { background: var(--bg-surface); border: 1px solid var(--border-subtle);
  border-radius: 10px; padding: 8px 10px; margin: 12px 0; font-size: 13px;
  color: var(--text-secondary); }
details.help summary { cursor: pointer; font-weight: 700; color: var(--text-primary);
  min-height: 44px; display: flex; align-items: center; }
details.help code { font-family: var(--font-mono); font-size: 12px; color: var(--accent); }
.gauges { display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  gap: 8px; margin: 14px 0; }
button.gauge { background: var(--bg-surface); border: 1px solid var(--border-subtle);
  border-radius: 10px; padding: 7px 9px; color: var(--text-primary);
  font-family: inherit; text-align: start; cursor: pointer; min-height: 44px; }
button.gauge:hover { background: var(--bg-surface-hover); }
button.gauge[aria-pressed="true"] { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
button.gauge:disabled { opacity: 0.45; cursor: default; }
button.gauge b.num { display: block; font-size: 26px; font-family: var(--font-mono); }
button.gauge b.num .tot { font-size: 12px; color: var(--text-muted); }
button.gauge b.num .now, button.gauge b.num .tot { display: none; }
body.filtering button.gauge b.num .base { display: none; }
body.filtering button.gauge b.num .now,
body.filtering button.gauge b.num .tot { display: inline; }
mark { background: #fde68a; color: #111827; border-radius: 3px; padding: 0 1px; }
button.gauge span.lbl { font-size: 13px; color: var(--text-secondary); }
button.gauge span.lbl .en { color: var(--text-muted); }
button.gauge span.why1 { display: block; font-size: 12px; color: var(--text-muted); }
button.gauge.g-link b.num { color: #34d399; } button.gauge.g-none b.num { color: #9ca3af; }
button.gauge.g-pending b.num { color: var(--accent); } button.gauge.g-unmapped b.num { color: #71717a; }
button.gauge.g-twin b.num { color: #c084fc; } button.gauge.g-quar b.num { color: var(--quar-t); }
button.gauge.g-prov b.num { color: var(--prov-t); }
.panel { background: var(--bg-surface); border: 1px solid var(--border-subtle);
  border-radius: 10px; padding: 8px 10px; margin: 10px 0; }
.panel h2 { font-size: 14px; margin-bottom: 6px; }
.panel h2 .en { color: var(--text-muted); font-weight: 400; font-size: 12px; }
.pie-wrap { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.pie-svg { width: 150px; height: 150px; flex-shrink: 0; }
.pieslice { cursor: pointer; }
.pieslice:hover { opacity: 0.85; }
.pieslice:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.pielegend { display: flex; flex-direction: column; gap: 6px; }
button.piebtn { display: flex; align-items: center; gap: 8px; background: none;
  border: 1px solid transparent; border-radius: 999px; color: var(--text-primary);
  font: inherit; font-size: 13px; cursor: pointer; padding: 6px 10px; min-height: 44px;
  text-align: start; }
button.piebtn:hover { background: var(--bg-surface-hover); }
button.piebtn[aria-pressed="true"] { border-color: var(--accent); }
button.piebtn .dot { width: 10px; height: 10px; border-radius: 999px; flex-shrink: 0; }
button.piebtn .pct { color: var(--text-muted); font-family: var(--font-mono); font-size: 12px; }
.latency-chart { display: flex; align-items: flex-end; gap: 8px; height: 150px; padding: 8px 0; }
.latency-bar-wrap { display: flex; flex-direction: column; align-items: center;
  flex: 1; height: 100%; justify-content: flex-end; min-width: 40px; }
.latency-bar { width: 100%; max-width: 44px; border-radius: 4px 4px 0 0;
  background: var(--accent); }
.latency-label { font-size: 10px; color: var(--text-muted); margin-top: 4px; }
.latency-count { font-size: 11px; color: var(--text-primary); font-weight: 600;
  font-family: var(--font-mono); }
.latline { font-size: 13px; color: var(--text-secondary); font-family: var(--font-mono);
  margin-top: 4px; }
table.checks { width: 100%; border-collapse: collapse; font-size: 13px; }
table.checks th, table.checks td { padding: 6px 8px; border-bottom: 1px solid var(--border-subtle);
  text-align: start; vertical-align: middle; }
table.checks thead th { font-size: 12px; color: var(--text-muted); }
button.checkbtn { background: none; border: 1px solid transparent; border-radius: 999px;
  color: var(--text-primary); font: inherit; font-size: 13px; cursor: pointer;
  padding: 6px 10px; min-height: 44px; text-align: start; }
button.checkbtn:hover { background: var(--bg-surface-hover); }
button.checkbtn[aria-pressed="true"] { border-color: var(--accent); }
.sig-row { display: flex; align-items: center; gap: 8px; margin: 3px 0;
  font-size: 13px; color: var(--text-secondary); }
button.sigbtn { flex: 1; display: flex; align-items: center; gap: 8px;
  background: none; border: 1px solid transparent; border-radius: 10px;
  color: inherit; font: inherit; cursor: pointer; padding: 4px 6px; min-height: 44px;
  text-align: start; }
button.sigbtn:hover { background: var(--bg-surface-hover); }
button.sigbtn[aria-pressed="true"] { border-color: var(--accent); }
button.sigbtn .bar { flex: 1; height: 8px; background: #00000055; border-radius: 10px;
  overflow: hidden; }
button.sigbtn .bar i { display: block; height: 100%; background: var(--accent); }
button.sigbtn code { font-family: var(--font-mono); }
button.sigbtn .fa { color: var(--text-muted); }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px; }
.fact { background: #00000033; border: 1px solid var(--border-subtle);
  border-radius: 10px; padding: 6px 10px; }
.fact h3 { font-size: 13px; }
.fact h3 .en { color: var(--text-muted); font-weight: 400; font-size: 12px; }
.fact p.big { font-size: 14px; margin: 4px 0; }
.fact p.why1 { font-size: 12px; color: var(--text-muted); }
.fact button.mini { background: var(--accent-soft); border: 1px solid var(--border-strong);
  border-radius: 999px; color: var(--text-primary); font-family: var(--font-mono);
  font-size: 12px; padding: 4px 12px; margin-inline-end: 6px; cursor: pointer;
  min-height: 44px; }
.fact button.mini[aria-pressed="true"] { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 10px 0; }
.searchbox { display: flex; gap: 8px; align-items: center; flex: 1 1 280px; }
#search { flex: 1; background: var(--bg-surface); border: 1px solid var(--border-strong);
  border-radius: 999px; color: var(--text-primary); font: inherit; font-size: 14px;
  padding: 8px 16px; min-height: 44px; min-width: 180px; }
#search:focus { border-color: var(--accent); outline: none; }
#allclear { font-size: 13px; color: #6ee7b7; background: var(--link-bg);
  border: 1px solid var(--link-b); border-radius: 999px; padding: 6px 14px; }
#chips { display: flex; flex-wrap: wrap; gap: 6px; }
button.chipx { background: var(--accent-soft); border: 1px solid var(--accent);
  border-radius: 999px; color: var(--text-primary); font-size: 12px;
  font-family: var(--font-mono); padding: 6px 12px; cursor: pointer; min-height: 44px; }
#countline { font-size: 12px; font-family: var(--font-mono); color: var(--text-secondary); }
button.export { background: #065f46; border: 1px solid var(--link-b); border-radius: 999px;
  color: #ecfdf5; font-size: 13px; padding: 8px 18px; cursor: pointer; min-height: 44px; }
button.export:hover { background: #047857; }
.tablewrap { overflow-x: auto; border: 1px solid var(--border-subtle); border-radius: 10px; }
table.senses { width: 100%; border-collapse: collapse; font-size: 14px; min-width: 640px; }
table.senses th, table.senses td { padding: 6px 8px; border-bottom: 1px solid var(--border-subtle);
  text-align: start; vertical-align: top; }
table.senses thead th { font-size: 12px; color: var(--text-muted); background: var(--bg-surface); }
table.senses tbody.cardbody tr.summary:hover { background: var(--bg-surface-hover); }
.gloss-snip { color: var(--text-secondary); max-width: 44ch;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
@media (min-width: 900px) {
  .gloss-snip { max-width: 72ch; }
  table.senses { min-width: 760px; }
}
.gloss-snip mark { background: var(--accent-soft); color: var(--text-primary);
  border-radius: 3px; padding: 0 2px; }
a.jumptable { display: inline-flex; align-items: center; gap: 6px;
  margin-top: 8px; border: 1px solid var(--accent); border-radius: 999px;
  padding: 6px 16px; min-height: 44px; color: var(--text-primary);
  text-decoration: none; font-size: 13px; background: var(--accent-soft); }
a.jumptable:hover { background: var(--bg-surface-hover); }
a.jumptable .en { color: var(--text-muted); font-size: 12px; }
span.more { font-family: var(--font-mono); font-size: 11px; color: var(--accent);
  border: 1px solid var(--border-strong); border-radius: 999px; padding: 1px 8px;
  margin-inline-start: 6px; white-space: nowrap; }
span.warn { color: var(--prov-t); font-size: 12px; }
ol.candlist li.is-winner { border-inline-start: 3px solid #34d399;
  padding-inline-start: 8px; border-radius: 4px; background: var(--link-bg); }
details.flowtrace-wrap { margin: 8px 0; }
details.flowtrace-wrap > summary { cursor: pointer; font-weight: 700; font-size: 13px;
  color: var(--text-primary); min-height: 44px; display: flex; align-items: center;
  gap: 6px; }
details.flowtrace-wrap > summary .en { color: var(--text-muted); font-weight: 400; font-size: 12px; }
.flowtrace { background: #06070a; border: 1px solid var(--border-subtle);
  border-radius: 12px; padding: 10px 12px; }
.flowtrace-guide { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.flowtrace-concepts, .flowtrace-legend { display: flex; flex-wrap: wrap; gap: 8px;
  align-items: center; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.flowtrace-conceptstitle, .flowtrace-legendtitle { font-weight: 700; }
.flowtrace-concept { color: #fde68a; font-weight: 700;
  text-decoration: underline dotted; text-underline-offset: 2px; }
.tooltip-box { position: relative; display: inline-flex; align-items: center; cursor: help; }
.tooltip-content { visibility: hidden; opacity: 0; transition: opacity 0.2s;
  position: absolute; top: calc(100% + 6px); right: 0;
  background: #181d2a; border: 1px solid #38bdf8; color: #f1f5f9;
  padding: 8px 12px; border-radius: 8px; font-size: 12px; width: 230px; z-index: 70;
  line-height: 1.45; box-shadow: 0 10px 30px rgba(0,0,0,0.6); pointer-events: none; }
.tooltip-box:hover .tooltip-content, .tooltip-box:focus-within .tooltip-content {
  visibility: visible; opacity: 1; }
.flowtrace-dot { display: inline-block; width: 10px; height: 10px; border-radius: 999px; }
.flowtrace-litem { display: inline-flex; align-items: center; gap: 4px; }
.flowtrace-grid { position: relative; display: grid; direction: rtl;
  grid-template-columns: 1fr 1.15fr 1fr; column-gap: 70px; row-gap: 40px; }
.flowtrace-col { display: flex; flex-direction: column; gap: 36px;
  min-width: 0; justify-content: space-between; }
.flowtrace-col-left { justify-content: center; }
@media (max-width: 900px) {
  .flowtrace-grid { grid-template-columns: minmax(0, 1fr); }
}
.flowtrace-node { position: relative; background: var(--bg-surface);
  border: 1px solid var(--border-strong); border-radius: 12px;
  padding: 10px 12px; font-size: 13px; z-index: 2; }
.flowtrace-node[data-ftnode="1"] { border-color: #38bdf866; }
.flowtrace-node[data-ftnode="5"] { border-color: #10b98166; }
.flowtrace-nodetitle { display: block; font-size: 12px; font-weight: 800; margin-bottom: 6px; }
.flowtrace-node[data-ftnode="1"] .flowtrace-nodetitle { color: #38bdf8; }
.flowtrace-node[data-ftnode="2"] .flowtrace-nodetitle { color: #c084fc; }
.flowtrace-node[data-ftnode="3"] .flowtrace-nodetitle { color: #f59e0b; }
.flowtrace-node[data-ftnode="4"] .flowtrace-nodetitle { color: #a5b4fc; }
.flowtrace-node[data-ftnode="5"] .flowtrace-nodetitle { color: #10b981; }
.magnet-port { position: absolute; width: 10px; height: 10px; border-radius: 999px;
  background: #06070a; border: 2px solid #38bdf8; opacity: 0.5; pointer-events: none; }
.flowtrace-node:hover .magnet-port { opacity: 1; }
.flowtrace-port-top { top: -5px; left: 50%; margin-left: -5px; }
.flowtrace-port-bottom { bottom: -5px; left: 50%; margin-left: -5px; }
.flowtrace-port-left { left: -5px; top: 50%; margin-top: -5px; }
.flowtrace-port-right { right: -5px; top: 50%; margin-top: -5px; }
.flowtrace-wires { position: absolute; inset: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 1; overflow: visible; }
.wire-pulse { stroke-dasharray: 6 6; animation: flowDash 1.2s linear infinite; }
@keyframes flowDash { from { stroke-dashoffset: 24; } to { stroke-dashoffset: 0; } }
.flowtrace-glow-green { filter: drop-shadow(0 0 3px rgba(16,185,129,0.45)); }
.flowtrace-glow-amber { filter: drop-shadow(0 0 3px rgba(245,158,11,0.45)); }
.flowtrace-glow-red { filter: drop-shadow(0 0 3px rgba(244,63,94,0.45)); }
.flowtrace-glow-purple { filter: drop-shadow(0 0 3px rgba(192,132,252,0.45)); }
.flowtrace-glow-blue { filter: drop-shadow(0 0 3px rgba(56,189,248,0.45)); }
.flowtrace-labels { position: absolute; inset: 0; pointer-events: none; z-index: 50; }
.flowtrace-wirelabel { position: absolute; transform: translate(-50%, -50%); z-index: 50;
  font-size: 11px; font-weight: 700; border: 1px solid; border-radius: 999px;
  padding: 1px 10px; white-space: nowrap; background: #06070a; }
.flowtrace-wirelist { display: none !important; flex-wrap: wrap; gap: 6px; list-style: none;
  margin: 8px 0 0; padding: 0; font-size: 12px; }
.candempty { font-size: 13px; color: var(--text-muted); }
.candwinner { font-size: 13px; color: var(--text-primary); background: var(--link-bg);
  border: 1px solid var(--link-b); border-radius: 10px; padding: 6px 10px; margin-top: 6px; }
.flowtrace-wire { border: 1px solid var(--border-strong); border-radius: 999px;
  padding: 1px 10px; color: var(--text-secondary); }
.flowtrace-guidelabel { display: block; font-size: 11px; color: var(--text-muted);
  font-weight: 700; margin-bottom: 2px; }
.flowtrace-lemma { font-size: 16px; font-weight: 800; margin-bottom: 6px; }
.flowtrace-pos { font-size: 11px; background: #38bdf826; color: #38bdf8;
  border-radius: 999px; padding: 1px 10px; }
.flowtrace-defbox { background: #00000033; border: 1px solid var(--border-subtle);
  border-radius: 10px; padding: 6px 10px; margin-bottom: 6px; }
.flowtrace-indef { font-size: 12px; color: var(--text-primary); }
.flowtrace-kv { font-size: 12px; color: var(--text-secondary); margin: 2px 0; }
.flowtrace-toks { color: #fcd34d; font-family: var(--font-mono); }
details.flowtrace-meta { font-size: 12px; color: var(--text-secondary); margin-top: 6px; }
details.flowtrace-meta summary { cursor: pointer; min-height: 44px;
  display: flex; align-items: center; }
.flowtrace-why { font-size: 13px; color: var(--text-primary); margin-top: 6px; }
ul.flowtrace-siglist, ul.flowtrace-gaplist { padding-inline-start: 20px;
  font-size: 13px; color: var(--text-secondary); }
ul.flowtrace-siglist .why { color: var(--text-muted); }
.flowtrace-rule { background: #00000033; border: 1px solid var(--border-subtle);
  border-radius: 10px; padding: 6px 10px; margin-top: 6px; font-size: 12px; }
.flowtrace-gatebody { font-size: 13px; color: var(--text-secondary); }
.flowtrace-tech { font-size: 11px; font-family: var(--font-mono);
  color: var(--text-muted); margin-top: 4px; }
.flowtrace-techhead { font-size: 11px; font-weight: 700;
  color: var(--text-secondary); margin-bottom: 4px; }
.jhead { font-size: 13px; font-weight: 800; color: var(--text-primary);
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
details.jlatseeds { font-size: 12px; color: var(--text-secondary);
  margin: 6px 0; }
details.jlatseeds > summary { cursor: pointer; min-height: 44px;
  display: flex; align-items: center; gap: 6px; }
.jseeds { font-family: var(--font-mono); font-size: 11px;
  color: var(--text-muted); margin-top: 4px; }
.jwinner { font-size: 13px; color: var(--text-primary); margin: 4px 0; }
.jflags { font-size: 12px; color: var(--text-secondary); margin-top: 6px; }
.flowtrace-jsonptr { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.flowtrace-votes { margin-top: 6px; }
.flowtrace-winner { background: #00000033; border: 1px solid #10b98166;
  border-radius: 10px; padding: 6px 10px; font-size: 13px; }
.flowtrace-enrich { font-size: 12px; margin-top: 6px; }
.flowtrace-decision { font-size: 12px; color: var(--text-secondary); margin-top: 6px; }
details.tech { margin: 8px 0; font-size: 12px; background: #00000033;
  border: 1px solid var(--border-subtle); border-radius: 10px; padding: 8px 12px; }
details.tech > summary { cursor: pointer; color: var(--text-primary); font-weight: 700;
  min-height: 44px; display: flex; align-items: center; gap: 6px; }
details.tech > summary .en { color: var(--text-muted); font-weight: 400; }
.tabbar { display: flex; gap: 6px; margin: 6px 0; }
.tabbar [role="tab"] { background: none; border: 1px solid var(--border-strong);
  border-radius: 999px; color: var(--text-secondary); font: inherit; font-size: 12px;
  padding: 6px 14px; min-height: 44px; cursor: pointer; }
.tabbar [role="tab"][aria-selected="true"] { border-color: var(--accent);
  color: var(--text-primary); box-shadow: 0 0 0 1px var(--accent); }
details.tech pre { font-family: var(--font-mono); font-size: 11px; direction: ltr;
  text-align: left; background: #00000066; border: 1px solid var(--border-subtle);
  border-radius: 10px; padding: 10px 12px; overflow-x: auto; color: var(--text-secondary); }
label.exopt { display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
  color: var(--text-secondary); border: 1px solid var(--border-subtle);
  border-radius: 999px; padding: 6px 12px; min-height: 44px; cursor: pointer; }
label.exopt .en { color: var(--text-muted); }
.badge { font-size: 11px; font-family: var(--font-mono); border-radius: 999px;
  padding: 1px 10px; border: 1px solid var(--border-strong); color: var(--text-secondary);
  white-space: nowrap; }
.badge.m-link { background: var(--link-bg); border-color: var(--link-b); color: #6ee7b7; }
.badge.m-rule { background: #1e3a8a55; border-color: #60a5fa; color: #bfdbfe; }
.badge.m-none { background: var(--none-bg); }
.badge.m-pending { background: var(--pend-bg); border-color: var(--pend-b); color: var(--accent); }
.badge.m-unmapped { background: var(--unmap-bg); }
.badge.m-twin { background: var(--twin-bg); border-color: var(--twin-b); color: #d8b4fe; }
.badge.m-quar { background: #450a0a55; border-color: var(--quar-b); color: var(--quar-t); }
.badge.flag { border-style: dashed; }
.badge.agree { border-color: var(--link-b); color: #6ee7b7; }
.badge.split { border-color: var(--prov-b); color: var(--prov-t); }
.flagchip { font-size: 11px; border-radius: 999px; padding: 1px 10px;
  border: 1px solid; white-space: nowrap; }
.flagchip .code { font-size: 0.85em; opacity: 0.85; }
.flagchip.flag-ok { background: #10b98133; border-color: #10b981; color: #6ee7b7; }
.flagchip.flag-prov { background: #f59e0b22; border-color: #f59e0b; color: #fcd34d; }
.flagchip.flag-quar { background: #ef444433; border-color: #ef4444; color: #fca5a5; }
.flagchip.flag-twin { background: #c084fc22; border-color: #c084fc; color: #d8b4fe; }
.flagchip.flag-judge { background: #38bdf822; border-color: #38bdf8; color: #7dd3fc; }
.agree-line { font-size: 13px; color: var(--text-primary); margin: 4px 0;
  padding: 4px 10px; background: #00000033; border-radius: 8px; }
.rep { font-family: var(--font-mono); color: var(--accent); font-weight: 700; }
.ft-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 10px 12px 6px; }
.ft-head .flowtrace-nodetitle { font-weight: 800; font-size: 14px; }
.ft-badge { font-size: 11px; color: var(--text-secondary); border: 1px solid
  var(--border-subtle); border-radius: 999px; padding: 1px 10px;
  white-space: nowrap; }
.ft-body { padding: 6px 12px; }
.ft-body > :first-child { margin-top: 0; }
.ft-body > :last-child { margin-bottom: 0; }
.ft-foot { display: flex; flex-wrap: wrap; gap: 4px 8px; padding: 6px 12px 10px; }
.ft-chip { font-size: 11px; color: var(--text-muted); }
.ft-chip .code { font-size: 0.9em; }
span.code { color: var(--text-muted); font-size: 0.85em; }
.chip { font-family: var(--font-mono); font-size: 11px; background: var(--accent-soft);
  border: 1px solid var(--border-strong); border-radius: 999px; padding: 1px 8px;
  color: var(--text-primary); white-space: nowrap; }
.chip .fa { color: var(--text-muted); }
.chip .alias { color: var(--text-secondary); }
button.expand { background: none; border: 1px solid var(--border-strong); border-radius: 999px;
  color: var(--accent); font-size: 12px; padding: 4px 12px; cursor: pointer; min-height: 44px; }
tr.detail td { background: #00000044; }
ol.candlist, ol.votelist { padding-inline-start: 20px; font-size: 13px;
  color: var(--text-secondary); }
ol.candlist { list-style: decimal; }
ol.votelist { list-style: decimal; }
ol.vote-minis { display: grid; gap: 6px; padding-inline-start: 0; list-style: none; }
ol.vote-minis li.vote-mini { border: 1px solid var(--border-strong);
  border-radius: 10px; padding: 6px 10px; font-size: 12px;
  background: #00000033; }
.flowtrace-status { display: inline-block; font-size: 12px; font-weight: 800;
  border: 1px solid; border-radius: 999px; padding: 1px 12px; margin-inline-start: 8px; }
.flowtrace-gapnone { font-size: 13px; color: var(--text-muted); margin: 6px 0; }
.candnone { font-size: 13px; color: var(--text-muted); }
.wkey { font-family: var(--font-mono); color: var(--accent); }
dl.mkeys { display: grid; grid-template-columns: auto 1fr; gap: 2px 12px;
  font-size: 12px; margin: 8px 0; background: #00000033;
  border: 1px solid var(--border-subtle); border-radius: 10px; padding: 8px 12px; }
dl.mkeys dt { color: var(--text-primary); white-space: nowrap; }
dl.mkeys dd { color: var(--text-secondary); overflow-wrap: anywhere; }
details.machine, details.raw { margin: 8px 0; font-size: 12px; }
details.machine summary, details.raw summary { cursor: pointer; color: var(--text-secondary);
  min-height: 44px; display: flex; align-items: center; }
details.machine pre { font-family: var(--font-mono); font-size: 11px; direction: ltr;
  text-align: left; background: #00000066; border: 1px solid var(--border-subtle);
  border-radius: 10px; padding: 10px 12px; overflow-x: auto; color: var(--text-secondary); }
.vote { font-family: var(--font-mono); font-size: 11px; border-radius: 999px;
  padding: 1px 8px; border: 1px solid var(--border-strong); margin-inline-end: 4px; }
.vote-link { color: #6ee7b7; } .vote-none { color: #9ca3af; } .vote-fail { color: var(--prov-t); }
input[type="checkbox"] { width: 20px; height: 20px; accent-color: var(--accent); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
footer { margin-top: 32px; color: var(--text-muted); font-size: 12px;
  font-family: var(--font-mono); }
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  * { transition: none; }
}
#summary-strip { background: var(--bg-surface); border: 1px solid var(--border-strong);
  border-radius: 999px; padding: 6px 16px; margin: 10px 0; font-size: 13px;
  color: var(--text-secondary); display: flex; flex-wrap: wrap; gap: 4px 10px;
  align-items: center; }
#summary-strip b { color: var(--text-primary); font-family: var(--font-mono); }
#summary-strip a.sumexpand { margin-inline-start: auto; border: 1px solid var(--accent);
  border-radius: 999px; padding: 4px 14px; min-height: 44px; display: inline-flex;
  align-items: center; color: var(--text-primary); text-decoration: none;
  background: var(--accent-soft); font-size: 12px; }
details.top-panel { background: var(--bg-surface); border: 1px solid var(--border-subtle);
  border-radius: 10px; padding: 8px 10px; margin: 10px 0; }
details.top-panel > summary { cursor: pointer; font-weight: 700; font-size: 14px;
  color: var(--text-primary); min-height: 44px; display: flex; align-items: center;
  gap: 6px; }
details.top-panel > summary .en { color: var(--text-muted); font-weight: 400; font-size: 12px; }
.latstrip { display: flex; align-items: flex-end; gap: 10px; max-height: 40px;
  overflow: hidden; padding: 2px 0; }
.latstrip-nums { font-size: 13px; color: var(--text-primary);
  font-family: var(--font-mono); white-space: nowrap; }
.latstrip-bars { display: flex; align-items: flex-end; gap: 3px; }
.latstrip-bar { width: 14px; max-height: 28px; background: var(--accent);
  border-radius: 3px 3px 0 0; }
button.fbtn { background: none; border: 1px solid var(--border-subtle);
  border-radius: 999px; color: var(--text-secondary); font: inherit; font-size: 12px;
  padding: 6px 12px; margin: 2px 4px 2px 0; min-height: 44px; cursor: pointer; }
button.fbtn:hover { background: var(--bg-surface-hover); color: var(--text-primary); }
button.fbtn[aria-pressed="true"] { border-color: var(--accent); color: var(--text-primary);
  box-shadow: 0 0 0 1px var(--accent); }
.export-capsule { display: inline-flex; flex-wrap: wrap; gap: 8px; align-items: center;
  border: 1px solid var(--link-b); border-radius: 999px; padding: 4px 6px 4px 14px;
  background: #064e3b33; }
.export-capsule-label { font-size: 12px; color: var(--text-secondary); }
.export-capsule-label .en { color: var(--text-muted); }
"""

_JS = """
(function () {
  var active = new Set();
  var query = "";
  var rows = Array.prototype.slice.call(document.querySelectorAll("tbody.cardbody"));
  var chipsBox = document.getElementById("chips");
  var countline = document.getElementById("countline");
  var allclear = document.getElementById("allclear");
  var search = document.getElementById("search");
  var searchclear = document.getElementById("searchclear");
  var total = rows.length;
  var FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩";
  function norm(s) {
    s = (s || "").normalize("NFKC").toLowerCase();
    var out = "";
    for (var i = 0; i < s.length; i++) {
      var at = FA_DIGITS.indexOf(s[i]);
      out += at >= 0 ? String(at % 10) : s[i];
    }
    return out;
  }
  function escHtml(s) {
    return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function groupOf(k) {
    var i = (k || "").indexOf(":");
    return i < 0 ? (k || "") : k.slice(0, i);
  }
  var searchTimer = null;
  function keyLabel(key) {
    var el = document.querySelector('[data-fkey="' + key + '"] .lblfull');
    return el ? el.textContent.trim() : key;
  }
  function rowKeys(tb) { return (tb.getAttribute("data-keys") || "").split(" "); }
  function matches(tb) {
    // Round 4 T1: OR within one key-prefix group, AND across groups.
    var keys = rowKeys(tb);
    var seen = {};
    var groups = [];
    active.forEach(function (k) {
      var g = groupOf(k);
      if (!seen[g]) { seen[g] = []; groups.push(seen[g]); }
      seen[g].push(k);
    });
    for (var i = 0; i < groups.length; i++) {
      var hit = false;
      for (var j = 0; j < groups[i].length; j++) {
        if (keys.indexOf(groups[i][j]) >= 0) { hit = true; break; }
      }
      if (!hit) { return false; }
    }
    if (query) {
      var hay = tb.getAttribute("data-search") || "";
      if (hay.indexOf(query) < 0) { return false; }
    }
    return true;
  }
  function paintHighlight(tb) {
    // Round 4 T4: mark-highlight the query hit inside the gloss cell,
    // from escaped slices (never regex over raw HTML).
    var cells = tb.querySelectorAll("td.gloss-snip");
    for (var i = 0; i < cells.length; i++) {
      var cell = cells[i];
      if (cell.getAttribute("data-orig") === null) {
        cell.setAttribute("data-orig", cell.textContent);
      }
      var orig = cell.getAttribute("data-orig") || "";
      if (!query) { cell.innerHTML = escHtml(orig); continue; }
      var at = orig.toLowerCase().indexOf(query.toLowerCase());
      if (at < 0) { cell.innerHTML = escHtml(orig); continue; }
      cell.innerHTML = escHtml(orig.slice(0, at)) + "<mark>"
        + escHtml(orig.slice(at, at + query.length)) + "</mark>"
        + escHtml(orig.slice(at + query.length));
    }
  }
  function refreshCounts() {
    var visible = 0;
    var perKey = {};
    var filtering = active.size > 0 || !!query;
    document.body.classList.toggle("filtering", filtering);
    rows.forEach(function (tb) {
      var vis = matches(tb);
      tb.style.display = vis ? "" : "none";
      if (vis) { visible += 1; paintHighlight(tb); }
      rowKeys(tb).forEach(function (k) {
        if (vis) { perKey[k] = (perKey[k] || 0) + 1; }
      });
    });
    document.querySelectorAll("[data-fkey]").forEach(function (btn) {
      var n = btn.querySelector(".now");
      if (n) { n.textContent = (perKey[btn.getAttribute("data-fkey")] || 0); }
    });
    countline.textContent = "showing " + visible + " of " + total
      + (query ? ' · search "' + query + '"' : "");
    if (allclear) {
      allclear.hidden = (visible !== 0);
    }
    chipsBox.innerHTML = "";
    if (active.size === 0 && !query) {
      chipsBox.innerHTML = '<span class="none">no filters</span>';
    }
    active.forEach(function (k) {
      var b = document.createElement("button");
      b.className = "chipx";
      b.setAttribute("type", "button");
      b.textContent = groupOf(k) + " · " + keyLabel(k) + " ×";
      b.setAttribute("aria-label", "remove filter " + groupOf(k) + " · " + keyLabel(k));
      b.addEventListener("click", function () {
        active.delete(k);
        syncPressed();
        refreshCounts();
      });
      chipsBox.appendChild(b);
    });
    writeHash();
  }
  function writeHash() {
    // S3: filter + search state lives in the URL hash (shareable,
    // clear-all resets it via refreshCounts).
    var parts = [];
    if (active.size > 0) {
      var keys = [];
      active.forEach(function (k) { keys.push(k); });
      keys.sort();
      parts.push("f=" + encodeURIComponent(keys.join(",")));
    }
    if (query) { parts.push("q=" + encodeURIComponent(query)); }
    var h = parts.length > 0 ? "#" + parts.join("&") : "";
    var cur = window.location.hash || "";
    if (cur !== h) {
      if (h) { history.replaceState(null, "", h); }
      else {
        history.replaceState(null, "",
          window.location.pathname + window.location.search);
      }
    }
  }
  function readHash() {
    var h = (window.location.hash || "").replace(/^#/, "");
    if (!h) { return; }
    h.split("&").forEach(function (kv) {
      var i = kv.indexOf("=");
      if (i < 0) { return; }
      var k = kv.slice(0, i), v = null;
      try { v = decodeURIComponent(kv.slice(i + 1)); } catch (e) { return; }
      if (k === "f") {
        v.split(",").forEach(function (key) {
          if (key) { active.add(key); }
        });
      } else if (k === "q") {
        query = norm(v).trim();
        if (search) { search.value = v; }
      }
    });
  }
  function syncPressed() {
    document.querySelectorAll("[data-fkey]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", active.has(btn.getAttribute("data-fkey")) ? "true" : "false");
    });
  }
  document.querySelectorAll("[data-fkey]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var k = btn.getAttribute("data-fkey");
      if (k === "__total__") { return; }
      if (active.has(k)) { active.delete(k); } else { active.add(k); }
      syncPressed();
      refreshCounts();
    });
    if (btn.tagName !== "BUTTON") {
      btn.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          btn.click();
        }
      });
    }
  });
  if (search) {
    search.addEventListener("input", function () {
      // Round 4 T4: 150-200ms debounce; reset the timer each keystroke.
      if (searchTimer !== null) { clearTimeout(searchTimer); }
      searchTimer = setTimeout(function () {
        searchTimer = null;
        query = norm(search.value).trim();
        refreshCounts();
      }, 175);
    });
  }
  if (searchclear) {
    searchclear.addEventListener("click", function () {
      if (search) { search.value = ""; }
      query = "";
      refreshCounts();
      if (search) { search.focus(); }
    });
  }
  function clearAllFilters() {
    active.clear();
    query = "";
    if (search) { search.value = ""; }
    syncPressed();
    refreshCounts();
  }
  var clearall = document.getElementById("clearall");
  if (clearall) {
    clearall.addEventListener("click", clearAllFilters);
  }
  var filterClear = document.getElementById("filter-clear");
  if (filterClear) {
    filterClear.addEventListener("click", clearAllFilters);
  }
  document.querySelectorAll("button.expand").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var tb = btn.closest("tbody.cardbody");
      var det = tb.querySelector("tr.detail");
      var open = det.hasAttribute("hidden");
      if (open) { det.removeAttribute("hidden"); } else { det.setAttribute("hidden", ""); }
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      btn.textContent = open ? "− detail" : "+ detail";
    });
  });
  var all = document.getElementById("checkall");
  if (all) {
    all.addEventListener("change", function () {
      rows.forEach(function (tb) {
        if (tb.style.display === "none") { return; }
        var c = tb.querySelector("input.rowcheck");
        if (c) { c.checked = all.checked; }
      });
    });
  }
  var exp = document.getElementById("export");
  if (exp) {
    exp.addEventListener("click", function () {
      // Round 4 T8: per-record array; judge + candidates dropped
      // per-record when their toolbar checkbox is off (both default ON).
      var wantCand = !document.getElementById("exp-cand")
        || document.getElementById("exp-cand").checked;
      var wantJudge = !document.getElementById("exp-judge")
        || document.getElementById("exp-judge").checked;
      var records = [];
      rows.forEach(function (tb) {
        var c = tb.querySelector("input.rowcheck");
        if (!c || !c.checked) { return; }
        var raw = tb.querySelector("tr.summary").dataset.export || "{}";
        var rec;
        try { rec = JSON.parse(raw); } catch (e) { rec = {}; }
        if (!wantCand) { delete rec.candidates; }
        if (!wantJudge) { delete rec.judge; }
        records.push(rec);
      });
      var out = {records: records};
      var blob = new Blob([JSON.stringify(out, null, 2)], {type: "application/json"});
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "linker_export.json";
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    });
  }
  var TABIDS = ["tab-gauges", "tab-judge", "tab-table", "tab-help"];
  var SECIDS = ["sec-gauges", "sec-judge", "sec-table", "sec-help"];
  function setActiveTab(id) {
    TABIDS.forEach(function (t) {
      var el = document.getElementById(t);
      if (el) { el.classList.toggle("active", t === id); }
    });
  }
  if ("IntersectionObserver" in window) {
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          var idx = SECIDS.indexOf(e.target.id);
          if (idx >= 0) { setActiveTab(TABIDS[idx]); }
        }
      });
    }, {rootMargin: "-40% 0px -55% 0px", threshold: 0});
    ["sec-gauges", "sec-judge", "sec-table"].forEach(function (s) {
      var el = document.getElementById(s);
      if (el) { obs.observe(el); }
    });
    // Round 4: the short help section never crosses the negative
    // rootMargin band, so it gets its own observer without rootMargin.
    var helpObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { setActiveTab("tab-help"); }
      });
    }, {threshold: 0.2});
    var helpEl = document.getElementById("sec-help");
    if (helpEl) { helpObs.observe(helpEl); }
  }
  var navpanel = document.getElementById("navpanel");
  var navfilter = document.getElementById("navfilter");
  var navsearchbtn = document.getElementById("navsearch");
  function setPanel(open, focusSearch) {
    if (!navpanel) { return; }
    if (open) { navpanel.removeAttribute("hidden"); }
    else { navpanel.setAttribute("hidden", ""); }
    [navfilter, navsearchbtn].forEach(function (b) {
      if (b) { b.setAttribute("aria-expanded", open ? "true" : "false"); }
    });
    if (open && focusSearch && search) { search.focus(); }
  }
  if (navfilter) {
    navfilter.addEventListener("click", function () {
      setPanel(navpanel.hasAttribute("hidden"), false);
    });
  }
  if (navsearchbtn) {
    navsearchbtn.addEventListener("click", function () {
      setPanel(true, true);
    });
  }
  var navclose = document.getElementById("navclose");
  if (navclose) {
    navclose.addEventListener("click", function () {
      setPanel(false, false);
      if (navfilter) { navfilter.focus(); }
    });
  }
  readHash();
  syncPressed();
  refreshCounts();
  // S1: top-panel expanded state persists per session, never by default.
  document.querySelectorAll("details.top-panel").forEach(function (d) {
    var k = "gallery:top:" + (d.id || "panel");
    try {
      if (localStorage.getItem(k) === "open") { d.setAttribute("open", ""); }
    } catch (e) {}
    d.addEventListener("toggle", function () {
      try {
        if (d.open) { localStorage.setItem(k, "open"); }
        else { localStorage.removeItem(k); }
      } catch (e) {}
    });
  });
  window.addEventListener("hashchange", function () {
    active.clear();
    query = "";
    if (search) { search.value = ""; }
    readHash();
    syncPressed();
    refreshCounts();
  });
  // Flow tracer: dynamic per-card SVG wires (3-column RTL S-flow grid,
  // no fixed coords, no presets, no storage). Corridor routing: vertical
  // 1->2 and 3->4 corridors plus S-curves 2->3 and 4->5 in free space;
  // labels offset perpendicular until clear of node boxes.
  var FT_GLOW = {success: "flowtrace-glow-green", warn: "flowtrace-glow-amber",
    fail: "flowtrace-glow-red", twin: "flowtrace-glow-purple", bypassed: ""};
  function ftPorts(svgRect, rect) {
    var cx = rect.left - svgRect.left + rect.width / 2;
    var cy = rect.top - svgRect.top + rect.height / 2;
    return {
      top: {x: cx, y: rect.top - svgRect.top, nx: 0, ny: -1},
      bottom: {x: cx, y: rect.bottom - svgRect.top, nx: 0, ny: 1},
      left: {x: rect.left - svgRect.left, y: cy, nx: -1, ny: 0},
      right: {x: rect.right - svgRect.left, y: cy, nx: 1, ny: 0}
    };
  }
  function ftBestPorts(svgRect, ra, rb, fromId, toId) {
    var pa = ftPorts(svgRect, ra), pb = ftPorts(svgRect, rb);
    var a, b, bend;
    var dist0 = Math.hypot(
      (rb.left + rb.width / 2) - (ra.left + ra.width / 2),
      (rb.top + rb.height / 2) - (ra.top + ra.height / 2));
    // Corridor routing: vertical pairs 1->2 and 3->4 share a grid
    // column, so each runs a straight vertical corridor bottom->top;
    // S-curve pairs (2->3, 4->5) cross the free inter-column gap side->side.
    if (fromId === "1" && toId === "2") {
      a = pa.bottom;
      b = pb.top;
      bend = Math.min(Math.max(Math.abs(b.y - a.y) * 0.35, 30), 90);
    } else if (fromId === "3" && toId === "4") {
      a = pa.bottom;
      b = pb.top;
      bend = Math.min(Math.max(Math.abs(b.y - a.y) * 0.35, 30), 90);
    } else if ((fromId === "2" && toId === "3")
        || (fromId === "4" && toId === "5")) {
      var dx = (rb.left + rb.width / 2) - (ra.left + ra.width / 2);
      if (dx <= 0) {
        a = pa.left;
        b = pb.right;
      } else {
        a = pa.right;
        b = pb.left;
      }
      bend = Math.min(Math.max(dist0 * 0.45, 60), 140);
    } else {
      var dx2 = (rb.left + rb.width / 2) - (ra.left + ra.width / 2);
      var dy2 = (rb.top + rb.height / 2) - (ra.top + ra.height / 2);
      if (Math.abs(dx2) > Math.abs(dy2)) {
        a = dx2 < 0 ? pa.left : pa.right;
        b = dx2 < 0 ? pb.right : pb.left;
      } else {
        a = dy2 > 0 ? pa.bottom : pa.top;
        b = dy2 > 0 ? pb.top : pb.bottom;
      }
      bend = Math.min(Math.max(dist0 * 0.4, 50), 140);
    }
    return {a: a, b: b,
      c1: {x: a.x + a.nx * bend, y: a.y + a.ny * bend},
      c2: {x: b.x + b.nx * bend, y: b.y + b.ny * bend}};
  }
  function ftBezier(p0, c1, c2, p3, t) {
    var mt = 1 - t;
    return {x: mt*mt*mt*p0.x + 3*mt*mt*t*c1.x + 3*mt*t*t*c2.x + t*t*t*p3.x,
      y: mt*mt*mt*p0.y + 3*mt*mt*t*c1.y + 3*mt*t*t*c2.y + t*t*t*p3.y};
  }
  function ftTangent(p0, c1, c2, p3, t) {
    var mt = 1 - t;
    return {x: 3*mt*mt*(c1.x - p0.x) + 6*mt*t*(c2.x - c1.x) + 3*t*t*(p3.x - c2.x),
      y: 3*mt*mt*(c1.y - p0.y) + 6*mt*t*(c2.y - c1.y) + 3*t*t*(p3.y - c2.y)};
  }
  function ftLabelClear(boxes, x, y) {
    var halfW = 65, halfH = 14;
    for (var i = 0; i < boxes.length; i++) {
      var b = boxes[i], pad = 10;
      if (x + halfW > b.x - pad && x - halfW < b.x + b.w + pad
          && y + halfH > b.y - pad && y - halfH < b.y + b.h + pad) {
        return false;
      }
    }
    return true;
  }
  function drawFlowtrace(root) {
    var svg = root.querySelector("svg.flowtrace-wires");
    var layer = root.querySelector("div.flowtrace-labels");
    if (!svg || !layer) { return; }
    var svgRect = svg.getBoundingClientRect();
    if (svgRect.width < 2) { return; }
    svg.innerHTML = "";
    layer.innerHTML = "";
    svg.setAttribute("viewBox", "0 0 " + svgRect.width + " " + svgRect.height);
    var nodes = {};
    root.querySelectorAll("section.flowtrace-node").forEach(function (el) {
      nodes[el.getAttribute("data-ftnode")] = el.getBoundingClientRect();
    });
    var boxes = Object.keys(nodes).map(function (k) {
      var r = nodes[k];
      return {x: r.left - svgRect.left, y: r.top - svgRect.top,
        w: r.width, h: r.height};
    });
    var NS = "http://www.w3.org/2000/svg";
    root.querySelectorAll("li.flowtrace-wire").forEach(function (w) {
      var ra = nodes[w.getAttribute("data-from")];
      var rb = nodes[w.getAttribute("data-to")];
      if (!ra || !rb) { return; }
      var color = w.getAttribute("data-color") || "#475569";
      var status = w.getAttribute("data-status") || "bypassed";
      var pair = ftBestPorts(svgRect, ra, rb,
        w.getAttribute("data-from"), w.getAttribute("data-to"));
      var d = "M " + pair.a.x + " " + pair.a.y + " C "
        + pair.c1.x + " " + pair.c1.y + ", "
        + pair.c2.x + " " + pair.c2.y + ", "
        + pair.b.x + " " + pair.b.y;
      var path = document.createElementNS(NS, "path");
      path.setAttribute("d", d);
      path.setAttribute("stroke", color);
      path.setAttribute("stroke-width", "2.8");
      path.setAttribute("fill", "none");
      var glow = FT_GLOW[status] || "";
      path.setAttribute("class",
        ((status === "bypassed") ? "" : "wire-pulse ") + glow);
      if (status === "bypassed") {
        path.setAttribute("stroke-dasharray", "5 5");
      }
      svg.appendChild(path);
      var tan = ftTangent(pair.a, pair.c1, pair.c2, pair.b, 1.0);
      var ang = Math.atan2(tan.y, tan.x);
      var L = 12, tipX = pair.b.x, tipY = pair.b.y;
      var lx = tipX - L * Math.cos(ang - Math.PI / 6);
      var ly = tipY - L * Math.sin(ang - Math.PI / 6);
      var rx = tipX - L * Math.cos(ang + Math.PI / 6);
      var ry = tipY - L * Math.sin(ang + Math.PI / 6);
      var head = document.createElementNS(NS, "polygon");
      head.setAttribute("points",
        tipX + "," + tipY + " " + lx + "," + ly + " " + rx + "," + ry);
      head.setAttribute("fill", color);
      if (glow) { head.setAttribute("class", glow); }
      svg.appendChild(head);
      var mid = ftBezier(pair.a, pair.c1, pair.c2, pair.b, 0.5);
      var cleanText = (w.textContent || "").replace(new RegExp(String.fromCharCode(9660, 9650, 9668, 9658, 8594, 8592), "g"), "").trim();
      var px = pair.a.x, py = pair.a.y, placed = false;
      var tSamples = [0.3, 0.5, 0.7, 0.4, 0.6];
      var offSamples = [18, 38, 58, -18, -38, -58];
      outer: for (var ti = 0; ti < tSamples.length; ti++) {
        var t = tSamples[ti];
        var pt = ftBezier(pair.a, pair.c1, pair.c2, pair.b, t);
        var tm = ftTangent(pair.a, pair.c1, pair.c2, pair.b, t);
        var tlen = Math.hypot(tm.x, tm.y) || 1;
        var nx = -tm.y / tlen, ny = tm.x / tlen;
        for (var oi = 0; oi < offSamples.length; oi++) {
          var cx = pt.x + nx * offSamples[oi], cy = pt.y + ny * offSamples[oi];
          if (ftLabelClear(boxes, cx, cy)) {
            px = cx; py = cy; placed = true;
            break outer;
          }
        }
      }
      var lab = document.createElement("div");
      lab.className = "flowtrace-wirelabel z-50";
      lab.style.left = px + "px";
      lab.style.top = py + "px";
      lab.style.borderColor = color;
      lab.style.color = color;
      lab.textContent = cleanText || (w.textContent || "").trim();
      if (!placed) { lab.style.left = pair.a.x + "px"; lab.style.top = pair.a.y + "px"; }
      layer.appendChild(lab);
    });
  }
  function drawAllFlowtraces() {
    document.querySelectorAll("div.flowtrace").forEach(drawFlowtrace);
  }
  if ("ResizeObserver" in window) {
    var ftObs = new ResizeObserver(function () { drawAllFlowtraces(); });
    document.querySelectorAll("div.flowtrace-grid").forEach(function (g) {
      ftObs.observe(g);
    });
  }
  window.addEventListener("resize", function () { drawAllFlowtraces(); });
  document.querySelectorAll("button.expand").forEach(function (btn) {
    btn.addEventListener("click", function () {
      setTimeout(drawAllFlowtraces, 50);
    });
  });
  drawAllFlowtraces();
})();
"""


if __name__ == "__main__":
    raise SystemExit(main())
