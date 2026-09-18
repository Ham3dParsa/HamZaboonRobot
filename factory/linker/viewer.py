"""Linker gallery viewer v3: filterable static HTML over a link table + judge verdicts.

Read-only, stdlib only (inline CSS/JS, no network, no model). Renders from
a TSV link table + verdicts JSON (+ optional candidates JSON) straight into
one self-contained file.

Locked vocabulary (owner round 2) — used for every gauge, chip, filter key
and telemetry key; legacy codes survive ONLY as parenthetical aliases
inside evidence strings::

    lexical-overlap (Sa) · synonym-crossfire (Sb) · example-crossfire (Sc)
    hypernym-topic (Sd) · meaning-similarity (Se) · short-definition
    (short-gloss) · no-signal (0sig) · judge-vote · unanimous (3-0) ·
    split-vote (2-1)

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
    machine_block,
    signal_vocab,
    telemetry_counters,
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


def verdict_summary(verdicts):
    """Judge-agreement counters over verdict dicts (verdicts may be empty)."""
    total = len(verdicts or [])
    judged = unanimous = split = link = none = failed = 0
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
            unanimous += 1
        else:
            split += 1
    return {
        "total": total, "judged": judged, "unanimous": unanimous,
        "split": split, "link": link, "none": none, "failed": failed,
    }


def agreement_key(item):
    """Locked-vocabulary agreement key: unanimous / split-vote / unjudged.

    >>> agreement_key({"votes": [{"ok": True, "verdict": "LINK", "winner_index": 1}]})
    'unjudged'
    >>> agreement_key({"votes": [{"ok": True, "verdict": "LINK", "winner_index": 1}] * 3})
    'unanimous'
    """
    votes = (item or {}).get("votes") or []
    ok_votes = [v for v in votes if v.get("ok")]
    if len(ok_votes) < 2:
        return "unjudged"
    winners = {v.get("winner_index") for v in ok_votes}
    verdict_kinds = {v.get("verdict") for v in ok_votes}
    if len(winners) == 1 and len(verdict_kinds) == 1:
        return "unanimous"
    return "split-vote"


def _agreement_label(item):
    key = agreement_key(item)
    if key == "unanimous":
        return "agree", "آرای یکدست · unanimous"
    if key == "split-vote":
        return "split", "آرای دوشقه · split-vote"
    return "unjudged", "رأی ثبت نشده · unjudged"


def outcome_key(verdict):
    """LINK / NONE / - outcome key for the verdict filter."""
    verdict = (verdict or {}).get("verdict") or ""
    if verdict in ("LINK", "NONE"):
        return verdict
    return "-"


def _stage_of(method):
    method = method or ""
    if method.startswith("LINK"):
        return "link"
    if method in ("JUDGE-NONE", "MANUAL-NONE"):
        return "none"
    if method in ("JUDGE-PENDING", "JUDGE-REVIEW"):
        return "pending"
    if method == "UNMAPPED":
        return "unmapped"
    if method == "twin-pending":
        return "twin"
    if method == "quarantined-known-false":
        return "quarantine"
    return "other"


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

    >>> sorted(row_filter_keys({"method": "LINK:2-sig", "evidence": "Sa:j=0.4", "flags": ""}, {}))
    ['judge:unjudged', 'outcome:-', 'sig:lexical-overlap', 'stage:link']
    """
    keys = ["stage:" + _stage_of(row.get("method", ""))]
    if is_provisional(row):
        keys.append("stage:provisional")
    for name, _fa, _alias in signal_chips(row.get("evidence", "")):
        keys.append("sig:" + name)
    if not signal_chips(row.get("evidence", "")):
        keys.append("sig:no-signal")
    keys.append("judge:" + agreement_key(verdict))
    keys.append("outcome:" + outcome_key(verdict))
    if verdict and outcome_key(verdict) == "-":
        # Failed judge rows (verdict None / vote_status FAILED) keep the
        # legacy "-" key AND carry the pie-slice FAILED key.
        keys.append("outcome:FAILED")
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


def _render_judge_votes(verdict):
    """Per-vote inputs: seed + verdict + winner + latency + quoted reason."""
    votes = (verdict or {}).get("votes") or []
    if not votes:
        return "—"
    items = []
    for n, vote in enumerate(votes, 1):
        raw_verdict = vote.get("verdict") or "—"
        if raw_verdict == "LINK":
            fa_v = "پیوند"
        elif raw_verdict == "NONE":
            fa_v = "بدون‌پیوند"
        else:
            fa_v = "ناموفق/ناشناخته"
        reason = (vote.get("wordnet_evidence")
                  or vote.get("kaikki_evidence") or "—")
        lat = vote.get("latency_s")
        lat_txt = ("%.1fs" % lat) if isinstance(lat, (int, float)) else "—"
        items.append(
            "<li>رأی %d (seed <bdi>%s</bdi>): <b>%s</b> "
            '<span class="code">(<bdi>%s</bdi>)</span> · برنده '
            "<bdi>%s</bdi> · <bdi>%s</bdi> · نقل دلیل: “<bdi>%s</bdi>”</li>"
            % (n, _esc(vote.get("seed", "?")), _esc(fa_v),
               _esc(raw_verdict),
               _esc(vote.get("winner_index")
                    if vote.get("winner_index") is not None else "—"),
               _esc(lat_txt), _esc(reason)))
    return "<ol class='votelist'>%s</ol>" % "".join(items)


def _gap_cells(row, verdict):
    verdict = verdict or {}
    wn_text = verdict.get("wordnet_evidence", "") or ""
    gloss, syns, example = parse_wn_parts(wn_text)
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

    No step may show a bare code: every code ships with its sentence.
    """
    if name == "lexical-overlap":
        point = alias.split("j=")[-1] if "j=" in alias else "?"
        try:
            fires = float(point) >= JACCARD_DEFAULT
        except ValueError:
            fires = False
        verb = "شلیک کرد" if fires else "زیر حد ماند"
        return ("هم‌پوشانی واژگان تعریف: jaccard ‏%s‏ در برابر حد %.2f — %s"
                % (point, JACCARD_DEFAULT, verb))
    if name == "synonym-crossfire":
        word = alias.split(":", 1)[-1]
        return ("هم‌پوشانی مترادف‌ها: واژه مشترک ‏‘%s’‏ دیده شد — شلیک کرد"
                % word)
    if name == "example-crossfire":
        word = alias.split(":", 1)[-1]
        return ("هم‌پوشانی مثال‌ها: واژه مشترک مثال ‏‘%s’‏ دیده شد — شلیک کرد"
                % word)
    if name == "hypernym-topic":
        if "=" in alias:
            head, _, word = alias.partition("=")
            if "hyp" in head:
                return ("ابرنام/موضوع مشترک ‏‘%s’‏ دیده شد — شلیک کرد "
                        "(نه فقط کد)" % word)
            return ("موضوع مشترک ‏‘%s’‏ دیده شد — شلیک کرد" % word)
        return "ابرنام/موضوع مشترک دیده شد — شلیک کرد"
    if name == "meaning-similarity":
        score = alias.split(":", 1)[-1]
        try:
            fires = float(score) >= SE_CUT
        except ValueError:
            fires = False
        verb = "شلیک کرد" if fires else "زیر حد ماند"
        return ("شباهت معنایی: نمره ‏%s‏ در برابر حد %.2f — %s"
                % (score, SE_CUT, verb))
    if name == "short-definition":
        return "تعریف خیلی کوتاه بود پس مستقیم به داور رفت"
    if name == "no-signal":
        return "هیچ سیگنالی شلیک نکرد پس نگاشت‌نشده ماند"
    if name == "judge-vote":
        return "داور وارد میدان شد و رأی داد"
    return "سیگنال ناشناخته ثبت شد: ‏‘%s’‏" % alias


def _signal_why(name, alias):
    """One-line FA why for one firing signal (thresholds inline)."""
    return _signal_exact(name, alias)


def _decision_rule(method, n_fires):
    """(rule FA sentence, threshold comparison) for the decision step."""
    need = LINK_MIN_DEFAULT
    if method.startswith("LINK:exact-sensekey"):
        return ("قاعده کلیددقیق + %d سیگنال" % n_fires,
                "%d سیگنال ≥ حد %d → پیوند "
                "<span class='code'>(<bdi>%s</bdi>)</span>"
                % (n_fires, need, _esc(method)))
    if method.startswith("LINK:judge-v2"):
        return ("قاعده پیوند با داور",
                "رأی داور ← پیوند "
                "<span class='code'>(<bdi>%s</bdi>)</span>" % _esc(method))
    if method.startswith("LINK:manual-override"):
        return ("قاعده پیوند دستی مالک",
                "override مالک ← پیوند "
                "<span class='code'>(<bdi>%s</bdi>)</span>" % _esc(method))
    if method.startswith("LINK"):
        return ("قاعده %d+ سیگنال (حد %d)" % (n_fires, need),
                "%d سیگنال ≥ %d → پیوند "
                "<span class='code'>(<bdi>%s</bdi>)</span>"
                % (n_fires, need, _esc(method)))
    if method in ("JUDGE-PENDING", "JUDGE-REVIEW"):
        return ("قاعده انتظار داور",
                "%d سیگنال < حد %d → انتظار داور "
                "<span class='code'>(<bdi>%s</bdi>)</span>"
                % (n_fires, need, _esc(method)))
    if method == "UNMAPPED":
        return ("قاعده بی‌علامتی",
                "۰ سیگنال → نگاشت‌نشده "
                "<span class='code'>(<bdi>UNMAPPED</bdi>)</span>")
    if method == "twin-pending":
        return ("قاعده دوقلوی تکراری",
                "دوقلو ← معلق، هرگز پیوند نه "
                "<span class='code'>(<bdi>twin-pending</bdi>)</span>")
    if method == "quarantined-known-false":
        return ("قاعده قرنطینه خطای شناخته‌شده",
                "خطای شناخته‌شده ← قرنطینه، هرگز پیوند نه "
                "<span class='code'>(<bdi>quarantined-known-false</bdi>)</span>")
    if method in ("JUDGE-NONE", "MANUAL-NONE"):
        return ("قاعده بدون‌پیوند",
                "بدون‌پیوند اعلام شد "
                "<span class='code'>(<bdi>%s</bdi>)</span>" % _esc(method))
    return ("قاعده تصمیم",
            "تصمیم ثبت شد "
            "<span class='code'>(<bdi>%s</bdi>)</span>" % _esc(method))


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
        snip = (gloss[:90] + "…") if len(gloss) > 90 else gloss
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


def _render_candidates_in(row, cand_entry, winner_key=""):
    """Exact candidates-in inputs: rank/sensekey/locator/gloss/score."""
    kaikki_gloss = row.get("kaikki_gloss", "") or ""
    head = "ورودی: <bdi>%s</bdi>" % _esc(kaikki_gloss or "—")
    return (head, render_candidates_html(row, cand_entry, winner_key))


def _render_trace(row, verdict, cand_entry=None):
    """Five-step stage trace: INPUT → OUTPUT + one-line FA why per step."""
    verdict = verdict or {}
    method = row.get("method", "") or ""
    evidence = row.get("evidence", "") or ""
    chips = signal_chips(evidence)
    rule_fires = [alias for _n, _f, alias in chips if alias != "judge"]
    winner_key = row.get("wordnet_sensekey", "") or ""
    if method in ("UNMAPPED", "MANUAL-NONE") and verdict.get("winner_sensekey"):
        winner_key = verdict.get("winner_sensekey") or winner_key
    wn_gloss = (verdict.get("wordnet_evidence", "") or "").split("||")[0].strip()
    kid = row.get("kaikki_sense_id", "") or ""

    cand_in, cand_out = _render_candidates_in(row, cand_entry, winner_key)
    if winner_key and winner_key != "-":
        cand_out += ('<br>خروجی نامزد برتر: <bdi class="wkey">%s</bdi>%s'
                     % (_esc(winner_key),
                        (" — <bdi>%s</bdi>" % _esc(wn_gloss))
                        if wn_gloss else ""))
        cand_why = ("نامزد برتر با %d سیگنال از فهرست کوتاه انتخاب شد"
                    % len(rule_fires) if rule_fires
                    else "نامزد برتر از داور آمد (بدون سیگنال قاعده‌ای)")
    else:
        cand_out += "<br>خروجی نامزد برتر: —"
        cand_why = "هیچ نامزدی کوتاه‌نیامد چون هیچ سیگنالی شلیک نکرد"

    if chips:
        sig_items = "".join(
            '<li><b>%s</b> <span class="fa">%s</span> '
            '<span class="alias">(<bdi>%s</bdi>)</span><br>'
            '<span class="why">%s</span></li>'
            % (_esc(name), _esc(_disp_fa(name, fa)), _esc(alias),
               _esc(_signal_exact(name, alias)))
            for name, fa, alias in chips)
    else:
        sig_items = ('<li><b>no-signal</b> <span class="fa">بی‌علامت</span><br>'
                     '<span class="why">%s</span></li>'
                     % _esc(_signal_exact("no-signal", "0sig")))

    flags = [f.strip() for f in (row.get("flags", "") or "").split("+")
             if f.strip()]
    flags_txt = ", ".join("%s (%s)" % (f, _flag_fa(f)) for f in flags
                          ) if flags else "—"
    agree = agreement_key(verdict)

    if verdict:
        votes_txt = _vote_badges(verdict)
        judge_out = ('رأی‌ها: %s · برنده: <bdi class="wkey">%s</bdi> '
                     '(<bdi>%s</bdi>)'
                     % (votes_txt, _esc(verdict.get("winner_sensekey")
                                        or winner_key),
                        _esc(verdict.get("verdict") or "—")))
        judge_out += '<br>جزئیات آرا: %s' % _render_judge_votes(verdict)
        if agree == "unanimous":
            judge_why = "هر ۳ داور هم‌نظر بودند پس قطعی است (unanimous)"
        elif agree == "split-vote":
            judge_why = "آرا ۲-۱ شد پس شقه است و موقت می‌ماند (split-vote)"
        else:
            judge_why = "رأی کافی ثبت نشده پس داوری‌نشده است"
    else:
        judge_out = "هنوز به داور نرسیده"
        judge_why = "ردیف در مرحله قاعده‌ای ماند و داوری نشد"

    gaps = _gap_cells(row, verdict)
    gap_items = "".join(
        '<li><b>%s</b> <span class="en" lang="en">%s</span> ← منبع: '
        '<bdi>%s</bdi>: <bdi>%s</bdi></li>'
        % (_esc(fa), _esc(en), _esc(src), _esc(val))
        for _slot, fa, en, val, src in gaps)
    filled = sum(1 for _s, _f, _e, v, _src in gaps if v != "—")

    rule_txt, cmp_txt = _decision_rule(method, len(rule_fires))
    steps = [
        ("نامزدهای ورودی", "candidates-in",
         cand_in, "خروجی: %s" % cand_out, cand_why),
        ("سیگنال‌ها", "signals",
         "ورودی: نامزد برتر + تعریف",
         "خروجی: <ul class='siglist'>%s</ul>" % sig_items,
         "%d سیگنال شلیک کرد" % len(chips) if chips else "صفر سیگنال"),
        ("تصمیم", "decision",
         "ورودی: %s" % (_esc(" + ".join(rule_fires))
                        if rule_fires else "no-signal"),
         "خروجی: %s · %s · پرچم‌ها: <bdi>%s</bdi>"
         % (_esc(rule_txt), cmp_txt, _esc(flags_txt)),
         _decision_why(method, len(rule_fires))),
        ("داوری", "judge",
         "ورودی: تصمیم %s "
         "<span class='code'>(<bdi>%s</bdi>)</span>"
         % (_esc(_method_fa(method)), _esc(method)),
         "خروجی: %s" % judge_out, judge_why),
        ("شکاف‌های چسبیده", "gaps",
          "ورودی: شواهد wordnet + tsv-cefr",
          "خروجی: <ul class='siglist'>%s</ul>" % gap_items,
          "%d شکاف از %d پر شد" % (filled, len(gaps))),
    ]
    # Round 4 owner-locked rename: the gaps step displays «تکمیل فیلدها»;
    # the data-step key stays "gaps" (code, not display).
    steps = [("تکمیل فیلدها" if cls == "gaps" else title, cls, inp, outp,
              why) for title, cls, inp, outp, why in steps]
    items = "".join(
        '<li class="tstep" data-step="%s"><h4>%s</h4>'
        '<p class="io">%s<br>%s</p>'
        '<p class="why">چرا: %s</p></li>' % (cls, _esc(title), inp, outp,
                                             _esc(why))
        for title, cls, inp, outp, why in steps)
    return ('<details class="tracewrap" open>'
            '<summary>ردیابی مرحله‌ها '
            '<span lang="en">stage trace</span> (همیشه باز · debug)</summary>'
            '<ol class="trace" aria-label="stage trace for %s">%s</ol>'
            '</details>'
            % (_esc(kid), items))

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
    """Glossary table: every machine-JSON key beside its FA sentence."""
    rows = []
    for key in ("kid", "method", "signals", "thresholds", "tier", "seed",
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
    return "<dl class='mkeys'>%s</dl>" % "".join(rows)


def _method_badge(method):
    method = method or ""
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
            % (cls, _esc(_method_fa(method)), _esc(method)))


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
    winner = row.get("wordnet_sensekey", "") or ""
    if row.get("method", "") in ("UNMAPPED", "MANUAL-NONE") and verdict.get(
            "winner_sensekey"):
        winner = verdict.get("winner_sensekey") or winner
    blk = machine_block(row)
    fires = [{"sig": name,
              "val": info.get("alias", ""),
              "cut": _EXPORT_CUT.get(name),
              "fired": name != "no-signal"}
             for name, info in blk.get("signals", {}).items()]
    wn_gloss, _syns, _eg = parse_wn_parts(
        verdict.get("wordnet_evidence", "") or "")
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
        "winner_def": wn_gloss,
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
    winner_key = row.get("wordnet_sensekey", "") or ""
    if method in ("UNMAPPED", "MANUAL-NONE") and verdict.get("winner_sensekey"):
        winner_key = verdict.get("winner_sensekey") or winner_key
    keys = " ".join(row_filter_keys(row, verdict, check_keys))
    hay = search_haystack(row, verdict)
    flags = [f.strip() for f in (row.get("flags", "") or "").split("+")
             if f.strip()]
    blk = machine_block(row)
    machine_json = _esc(json.dumps(blk, ensure_ascii=False, indent=1,
                                   sort_keys=True))
    mkeys = _render_mkeys(blk)
    trace = _render_trace(row, verdict, cand_entry)
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
    hist_html = _render_latency_hist(lat)
    checks_html = _render_checks(checks)

    judge_html = (
        '<div class="facts">'
        '<div class="fact"><h3>پوشش <span class="en" lang="en">coverage</span></h3>'
        '<p class="big">داوری‌شده <b>%d</b> از <b>%d</b></p>'
        '<p class="why1">چند معنی به داور رسید و رأی گرفت</p></div>'
        '<div class="fact"><h3>اطمینان <span class="en" lang="en">certainty</span></h3>'
        '<p class="big"><button type="button" class="mini" data-fkey="judge:unanimous" '
        'data-fgroup="judge" aria-pressed="false"><span class="lblfull">اجماعی unanimous</span> '
        '<b class="now">%d</b></button>'
        '<button type="button" class="mini" data-fkey="judge:split-vote" '
        'data-fgroup="judge" aria-pressed="false"><span class="lblfull">شقه split-vote</span> '
        '<b class="now">%d</b></button></p>'
        '<p class="why1">اجماعی یعنی هر ۳ داور هم‌نظر؛ شقه یعنی ۲-۱</p></div>'
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
            judge["unanimous"], judge["split"],
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
        '<span lang="en">help</span></a></nav>')

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
        '<p>هر کارت پنج گام را نشان می‌دهد '
        '<span lang="en">candidates-in · signals · decision · judge · تکمیل فیلدها</span>: '
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
        'روشن؛ آرا فشرده و کم‌حجم‌اند).</p></details>')

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
        '<section id="sec-gauges" aria-label="نشانگرها · gauges">'
        '<div class="gauges">%s</div>\n'
        '<div class="panel"><h2>رأی داوران '
        '<span class="en" lang="en">verdict distribution (click a slice to filter)</span></h2>%s</div>\n'
        '<div class="panel"><h2>تأخیر داور '
        '<span class="en" lang="en">judge latency (per-vote seconds)</span></h2>%s</div>\n'
        '<div class="panel"><h2>بررسی کیفیت '
        '<span class="en" lang="en">quality checklist (click a row to isolate violators)</span></h2>%s</div>\n'
        '</section>'
        '<section id="sec-judge" aria-label="داور · judge">'
        '<div class="panel"><h2>توزیع سیگنال‌ها '
        '<span class="en" lang="en">signal-fire distribution (rows)</span></h2>%s</div>\n'
        '<div class="panel"><h2>توافق داوران '
        '<span class="en" lang="en">judge agreement (where known)</span></h2>%s</div>\n'
        '</section>'
        '<section id="sec-table" aria-label="جدول · table">'
        '<div class="toolbar"><div class="searchbox">'
        '<input type="search" id="search" dir="auto" autocomplete="off" '
        'aria-label="جست‌وجو · search lemma gloss sensekey evidence" '
        'placeholder="جست‌وجو · search…">'
        '<button type="button" class="export" id="searchclear">پاک‌کردن '
        '<span lang="en">clear</span></button></div>'
        '<div id="chips" aria-live="polite"></div>'
        '<span id="countline" aria-live="polite"></span>'
        '<div id="allclear" hidden>۰ نتیجه · no matching rows — '
        '<button type="button" class="export" id="clearall">پاک‌کردن همه '
        'صافی‌ها <span lang="en">clear all</span></button></div>'
        '<label class="exopt"><input type="checkbox" id="exp-cand" checked> '
        'نامزدها <span lang="en">candidates</span></label>'
        '<label class="exopt"><input type="checkbox" id="exp-judge" checked> '
        'آرا <span lang="en">judge votes</span></label>'
        '<button type="button" class="export" id="export">خروجی JSON '
        '<span lang="en">export selected</span></button></div>\n'
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
        '<footer>linker gallery · stdlib static render · '
        'red = quarantined/known-false · amber = provisional/split</footer>\n'
        '</div>\n<script>%s</script>\n</body>\n</html>' % (
            _CSS, tele["total"], judge["total"], nav_html, gauge_html,
            pie_html, hist_html, checks_html,
            sig_rows, judge_html, "\n".join(bodies), help_html, _JS))

    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return {"stats": {"total": tele["total"], "stage": stage,
                      "signals": tele["signals"]},
            "judge": judge, "latency": lat, "checks": checks,
            "words": len(grouped), "out": str(out)}


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
  --font-sans: "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
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
details.tracewrap { margin: 8px 0; }
details.tracewrap > summary { cursor: pointer; font-weight: 700; font-size: 13px;
  color: var(--text-primary); min-height: 44px; display: flex; align-items: center;
  gap: 6px; }
details.tracewrap > summary .en { color: var(--text-muted); font-weight: 400; font-size: 12px; }
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
.badge.m-none { background: var(--none-bg); }
.badge.m-pending { background: var(--pend-bg); border-color: var(--pend-b); color: var(--accent); }
.badge.m-unmapped { background: var(--unmap-bg); }
.badge.m-twin { background: var(--twin-bg); border-color: var(--twin-b); color: #d8b4fe; }
.badge.m-quar { background: #450a0a55; border-color: var(--quar-b); color: var(--quar-t); }
.badge.flag { border-style: dashed; }
.badge.agree { border-color: var(--link-b); color: #6ee7b7; }
.badge.split { border-color: var(--prov-b); color: var(--prov-t); }
span.code { color: var(--text-muted); font-size: 0.85em; }
.chip { font-family: var(--font-mono); font-size: 11px; background: var(--accent-soft);
  border: 1px solid var(--border-strong); border-radius: 999px; padding: 1px 8px;
  color: var(--text-primary); white-space: nowrap; }
.chip .fa { color: var(--text-muted); }
.chip .alias { color: var(--text-secondary); }
button.expand { background: none; border: 1px solid var(--border-strong); border-radius: 999px;
  color: var(--accent); font-size: 12px; padding: 4px 12px; cursor: pointer; min-height: 44px; }
tr.detail td { background: #00000044; }
ol.trace { list-style: none; margin: 8px 0; padding-inline-start: 0; }
li.tstep { position: relative; padding-inline-start: 26px; padding-bottom: 10px;
  border-inline-start: 2px solid var(--border-strong); margin-inline-start: 8px; }
li.tstep::before { content: ""; position: absolute; inset-inline-start: -7px; top: 6px;
  width: 12px; height: 12px; border-radius: 999px; background: var(--accent); }
li.tstep[data-step="signals"]::before { background: #c084fc; }
li.tstep[data-step="decision"]::before { background: #34d399; }
li.tstep[data-step="judge"]::before { background: var(--prov-t); }
li.tstep[data-step="gaps"]::before { background: var(--text-muted); }
li.tstep h4 { font-size: 13px; }
li.tstep p.io { font-size: 13px; color: var(--text-secondary); margin: 2px 0; }
li.tstep p.why { font-size: 13px; color: var(--text-primary); }
ul.siglist, ol.candlist, ol.votelist { padding-inline-start: 20px; font-size: 13px;
  color: var(--text-secondary); }
ol.candlist { list-style: decimal; }
ol.votelist { list-style: decimal; }
ul.siglist .why { color: var(--text-muted); }
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
    s = (s || "").toLowerCase();
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
  syncPressed();
  refreshCounts();
})();
"""


if __name__ == "__main__":
    raise SystemExit(main())
