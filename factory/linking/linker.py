"""Kaikki -> WordNet sense-linker core (pure, hermetic).

Single source of truth for link logic in the repo. Stdlib only; no I/O,
no network, no model, no nltk/torch/embeddings (R37 pattern: candidates,
tables and scores are injected as plain dicts/lists by the caller).

Transferred by hand from the frozen scratch prototype (READ-ONLY source,
never imported):
  W:\\hamzaban_data_factory\\proof-linker\\v1\\linker_v0_6.py
  W:\\hamzaban_data_factory\\proof-linker\\v1\\link_table_v0_7.tsv
  W:\\hamzaban_data_factory\\proof-linker\\v1\\REPORT_v0_5.md
  W:\\hamzaban_data_factory\\proof-linker\\v1\\REPORT_v0_6.md
  W:\\hamzaban_data_factory\\proof-linker\\v1\\REPORT_v0_7.md
  W:\\hamzaban_data_factory\\proof-linker\\v1\\REPORT_v0_8.md (JOB5 rule)
  W:\\hamzaban_data_factory\\proof-linker\\v1\\VERSIONS.md (0.5.x-0.8.x log)

Deliberately NOT transferred (stay out of the repo): the Se embedding
model (only injected Se floats cross the seam via ``se_value``), the
judge leg (only verdict rows cross via ``judge_link``), Oxford/Kaikki
loading, the TSV-twin inventory sweep, and attach gap-fill (F3).

Deviation note (equivalent outcomes): the frozen ``exact_keys`` filtered
twins inside the exact join; here :func:`match_exact` is a total join and
twin suppression lives solely in :func:`arbitrate_link` (``is_twin``), so every
twinned best candidate still surfaces as ``twin-pending``, never LINK.
"""

from __future__ import annotations

import re
import unicodedata

# v0.6 cause-rule (REPORT_v0_6): narrowed per verdict rule — ``hold``
# dropped (it kills the judged-TRUE bear-support LINK).
GENERIC_VERBS = frozenset({"move", "make", "carry", "put", "go", "cause"})

# JOB1 quarantine (linker_v0_6 QUARANTINE): LINK-bound kid demoted to
# quarantined-known-false, surfaced first to the judge leg.
QUARANTINE = frozenset({"en-book-en-verb-hoaZwz7Y"})

SE_CUT = 0.43
SE_VETO_FLOOR = 0.35
SHORTLIST_CAP = 12
ULTRA_SHORT_MIN_TOKENS = 3
JACCARD_DEFAULT = 0.2
LINK_MIN_DEFAULT = 2

EDGE_SKIP_TAGS = frozenset({
    "obsolete", "archaic", "historical", "form-of", "alt-of",
    "ellipsis", "abbreviation", "acronym", "initialism", "misspelling",
})
STUB_RE = re.compile(
    r"^(alternative|past|plural|present|ellipsis|initialism|acronym|"
    r"abbreviation|form|spelling|synonym|misspelling|elongated|clipping|"
    r"eye dialect|pronunciation spelling)\b",
    re.I,
)


def norm_tokens(text):
    """Lowercase NFKC word tokens with a light English deplural.

    Witness: the IC5yKMhe causative gloss (REPORT_v0_6 MUST-DEMOTE row).

    >>> norm_tokens("To cause to come or go or move.")
    ['to', 'cause', 'to', 'come', 'or', 'go', 'or', 'move']
    >>> norm_tokens("stakeholders")
    ['stakeholder']
    """
    text = unicodedata.normalize("NFKC", (text or "").lower())
    toks = re.findall(r"[a-z']+", text)
    out = []
    for tok in toks:
        tok = tok.strip("'")
        if len(tok) < 2:
            continue
        if tok.endswith("ies") and len(tok) > 4:
            tok = tok[:-3] + "y"
        elif tok.endswith("ses") and len(tok) > 4:
            tok = tok[:-2]
        elif tok.endswith("s") and not tok.endswith("ss") and len(tok) > 3:
            tok = tok[:-1]
        out.append(tok)
    return out


def syn_norm(word):
    """Normalized single lemma form (underscores -> spaces).

    >>> syn_norm("light_source")
    'light source'
    """
    return re.sub(r"\s+", " ", str(word).lower().replace("_", " ").strip())


def self_forms(lemma):
    """Headword forms excluded from cross-fire (else vacuous).

    >>> sorted(self_forms("run"))
    ['run']
    """
    out = {syn_norm(lemma)}
    out |= set(norm_tokens(lemma))
    return out


def deweight_toks(tokens):
    """Generic verbs contribute ZERO as Sa/Sb/Sc evidence words.

    Witness: REPORT_v0_5 FIX2 — rumor-run PENDING (``Sd:hyp=move`` only,
    Sa:move dead); arrival-become PENDING (``Sa:j=0.27`` alone, Sb:go dead).

    >>> sorted(deweight_toks({"rumor", "move"}))
    ['rumor']
    >>> sorted(deweight_toks({"cause", "stake"}))
    ['stake']
    >>> GENERIC_VERBS == {"move", "make", "carry", "put", "go", "cause"}
    True
    """
    return {tok for tok in tokens if tok not in GENERIC_VERBS}


def shortlist(candidates, cap=SHORTLIST_CAP):
    """L3 cap: at most ``cap`` same-lemma same-pos candidates, order kept.

    >>> shortlist(list(range(20))) == list(range(12))
    True
    >>> shortlist(["a", "b"])
    ['a', 'b']
    """
    return list(candidates)[:cap]


def match_exact(candidate_keys, table_keys):
    """L2 exact join: candidate sensekeys present in the TSV table.

    Pure seam of the frozen index.sense resolution: callers inject already
    resolved candidate key strings. Order follows ``candidate_keys``.

    >>> match_exact(["get%2:35:03::", "run%1:28:00::"], ["run%1:28:00::"])
    ['run%1:28:00::']
    >>> match_exact(["a%1:01:00::"], ["b%1:02:00::"])
    []
    """
    table = set(table_keys)
    return [key for key in candidate_keys if key in table]


def gloss_overlap_signal(gloss_toks, cand_toks, stopwords=frozenset(), jaccard=JACCARD_DEFAULT):
    """Sa: jaccard overlap of deweighted gloss/definition token sets.

    Returns ``(j, fires)``. Ultra-short guard: either side under 3
    deweighted tokens forces ``j = -1.0`` (Sa cannot fire).

    Witness FALSE-must-park (REPORT_v0_5 FIX2): rumor-run keeps only
    ``Sd:hyp=move`` — a move-only overlap never fires Sa:

    >>> j, fires = gloss_overlap_signal({"rumor", "move", "report", "hearsay"}, {"run", "move", "flow", "stream"})
    >>> (round(j, 2), fires)
    (0.0, False)

    >>> j, fires = gloss_overlap_signal({"an"}, {"mistake", "error", "fault"})
    >>> (j, fires)
    (-1.0, False)
    """
    stops = set(stopwords)
    gloss_dw = deweight_toks({tok for tok in gloss_toks if tok not in stops})
    cand_dw = deweight_toks({tok for tok in cand_toks if tok not in stops})
    union = gloss_dw | cand_dw
    jacc = len(gloss_dw & cand_dw) / len(union) if union else 0.0
    if gloss_dw and cand_dw and jacc >= jaccard:
        return jacc, True
    if len(gloss_dw) < 3 or len(cand_dw) < 3:
        return -1.0, False
    return jacc, False


def synonym_crossfire_signal(gloss_toks, kaikki_syns, cand_lemmas, self=frozenset(),
              stopwords=frozenset()):
    """Sb: synonym cross-fire, ONE signal (both directions, same family).

    (i) kaikki synonyms cap WN lemmas; (ii) kaikki gloss content tokens cap
    WN lemma component tokens. Deweighted, sorted, capped at 6.

    Witness MUST-DEMOTE (REPORT_v0_6): IC5yKMhe "To cause to come or go or
    move." — Sb:cause dies under the cause-rule, row drops below 2-sig:

    >>> synonym_crossfire_signal({"cause", "come", "go", "move"}, set(), {"stimulate"})
    []

    Witness TRUE-must-stay (REPORT_v0_5 FIX2): bear-support keeps
    ``Sa:j=0.40+Sb:hold``:

    >>> synonym_crossfire_signal({"support", "hold"}, set(), {"hold", "carry", "bear"})
    ['hold']
    """
    self_set = set(self)
    stops = set(stopwords)
    cand_ns = {lem for lem in cand_lemmas if lem not in self_set}
    kaikki_ns = {syn for syn in kaikki_syns if syn not in self_set}
    words = set(kaikki_ns & cand_ns)
    lem_toks = (
        {tok for lem in cand_ns for tok in norm_tokens(lem)}
        - self_set - stops
    )
    words |= {tok for tok in gloss_toks if tok in lem_toks}
    return sorted(deweight_toks(words))[:6]


def example_crossfire_signal(kaikki_ex_toks, cand_ex_toks, kaikki_lemmas, cand_lemmas,
              sb_words, self=frozenset()):
    """Sc: example cross-fire minus words already counted in Sb.

    Generic verbs (or words containing one) never count. Sorted, cap 4.

    Witness (REPORT_v0_5 FIX2): the only convey1->deport LINK left is the
    behave-TRUE ``Sa:j=0.20+Sb:behave,conduct`` — Sc stays silent there:

    >>> example_crossfire_signal({"behave"}, {"conduct"}, {"behave"}, {"behave", "conduct"}, {"behave", "conduct"})
    []
    """
    self_set = set(self)
    sb_toks = set(sb_words) | {
        tok for word in sb_words for tok in norm_tokens(word)
    }
    kaikki_ns = {lem for lem in kaikki_lemmas if lem not in self_set}
    cand_ns = {lem for lem in cand_lemmas if lem not in self_set}
    ex_ns = {tok for tok in kaikki_ex_toks if tok not in self_set}
    pre = sorted(((cand_ns & ex_ns) | (kaikki_ns & set(cand_ex_toks))) - sb_toks)
    hits = [
        word for word in pre
        if word not in GENERIC_VERBS
        and not (set(norm_tokens(word)) & GENERIC_VERBS)
    ]
    return hits[:4]


def hypernym_topic_signal(hyp_lemmas, gloss_toks, sb_tok_set, topics=(),
              cand_def_toks=frozenset(), cand_lexname=""):
    """Sd: hypernym/topic fire (UNTOUCHED by generic deweight by verdict scope).

    Priority: hyp cap gloss (minus Sb words) > topic cap
    def/lexname (minus Sb words). Else None. The frozen Oxford-fallback
    branch is a no-op ``pass`` there, so dropping it changes nothing.

    Witness FALSE-must-park (REPORT_v0_5 FIX2): rumor-run survives on
    ``Sd:hyp=move`` only:

    >>> hypernym_topic_signal({"move", "run"}, {"rumor", "move"}, set())
    'Sd:hyp=move'

    Witness TRUE-must-stay (REPORT_v0_6 fate table): spring-leap keeps
    firing alongside Sa:

    >>> hypernym_topic_signal({"leap", "jump"}, {"leap", "spring"}, set())
    'Sd:hyp=leap'

    >>> hypernym_topic_signal({"run"}, {"error"}, set()) is None
    True
    """
    sb_toks = set(sb_tok_set)
    gloss = set(gloss_toks)
    hyp_hit = sorted((set(hyp_lemmas) & gloss) - sb_toks)
    if hyp_hit:
        return "Sd:hyp=%s" % ",".join(hyp_hit[:3])
    topic_set = {str(top).lower() for top in topics}
    lex_tail = (cand_lexname or "").split(".")[-1]
    topic_hit = sorted((topic_set & (set(cand_def_toks) | {lex_tail})) - sb_toks)
    if topics and topic_hit:
        return "Sd:topic=%s" % ",".join(topic_hit)
    return None


def evidence_families(fires, sa_words=frozenset(), self_forms=frozenset()):
    """Distinct non-self evidence words across firing signals.

    Witness (REPORT_v0_5 FIX3): lie-TRUE ``Sb:consist+Sd:hyp=exist``
    (Se 0.305) is correctly multi-family, so the Se veto must NOT fire:

    >>> sorted(evidence_families(["Sb:consist", "Sd:hyp=exist"]))
    ['consist', 'exist']
    """
    words = set(sa_words)
    for fire in fires:
        if fire.startswith("Sa:"):
            continue
        if fire.startswith("Sb:") or fire.startswith("Sc:"):
            parts = fire.split(":", 1)[1].split(",")
        elif fire.startswith("Sd:"):
            parts = fire.split("=", 1)[1].split(",") if "=" in fire else []
        else:
            continue
        for part in parts:
            words |= set(norm_tokens(part))
    return words - set(self_forms)


def se_fires(value, cut=SE_CUT):
    """Fire predicate for the calibrated Se cut.

    >>> (se_fires(0.692), se_fires(0.209))
    (True, False)
    """
    return value >= cut


def operational_signal_veto(se_value, families, generic_free, is_exact, floor=SE_VETO_FLOOR):
    """FIX3 veto: Se<floor demotes only single-family, generic-verb-free,
    non-exact-sensekey LINK candidates.

    Witnesses (REPORT_v0_5 FIX3 + REPORT_v0_6): lie-TRUE (Se 0.305,
    multi-family) NOT vetoed; exact-sensekey run-row NOT vetoed; luck
    (Se 0.633) NOT vetoed:

    >>> operational_signal_veto(0.305, {"consist", "exist"}, True, False)
    False
    >>> operational_signal_veto(0.20, {"bring"}, True, True)
    False
    >>> operational_signal_veto(0.633, {"period"}, True, False)
    False
    >>> operational_signal_veto(0.30, {"period"}, True, False)
    True
    """
    if is_exact:
        return False
    if not generic_free:
        return False
    if len(set(families)) > 1:
        return False
    return se_value is not None and se_value < floor


def quarantine_check(kid, method):
    """Emit-stage guard: LINK-bound quarantined kid demotes, else None.

    Witness (link_table_v0_7.tsv): ``en-book-en-verb-hoaZwz7Y`` LINK-bound
    -> ``quarantined-known-false``:

    >>> quarantine_check("en-book-en-verb-hoaZwz7Y", "LINK:2-sig")
    'quarantined-known-false'
    >>> quarantine_check("en-book-en-verb-hoaZwz7Y", "JUDGE-PENDING") is None
    True
    >>> quarantine_check("en-run-en-noun-lQEeVMDo", "LINK:2-sig") is None
    True
    """
    if method.startswith("LINK") and kid in QUARANTINE:
        return "quarantined-known-false"
    return None


def provisional_consensus(n_signals, sd_only, unanimous):
    """JOB5 rule (REPORT_v0_8): LINK on flip-family evidence is provisional.

    Flip-family = 1-signal Sd-only, or an N=3 non-unanimous majority.
    Witnesses: idx16 convey1->wear (1-signal ``Sd:hyp=feature``, unanimous
    3/3 yet flagged) True; idx20 hold (1-signal Sb, unanimous) False;
    idx7 get (2-sig) False:

    >>> (provisional_consensus(1, True, True), provisional_consensus(1, False, True))
    (True, False)
    >>> (provisional_consensus(2, False, True), provisional_consensus(2, False, False))
    (False, True)
    """
    return (n_signals == 1 and sd_only) or not unanimous


def edge_reason(pos, kid, lemma, gloss, tags=frozenset()):
    """Never-link edge rows (-> UNMAPPED), checked before candidacy.

    Witness (REPORT_v0_5 FIX1 regression guard): 3 edge rows stay UNMAPPED
    (mistake ``B~Axe-q2`` edge:obsolete, get ``mRQCjz-a`` edge:obsolete).

    >>> edge_reason("noun", "en-mistake-en-noun-B~Axe-q2", "mistake", "An error.", {"obsolete"})
    'edge:obsolete'
    >>> edge_reason("name", "en-hot-en-name-X1", "hot", "A place.", set())
    'edge:name-pos'
    >>> edge_reason("noun", "en-run-en-noun-lQEeVMDo", "run", "Something continuous.", set()) is None
    True
    """
    tag_hit = set(tags) & EDGE_SKIP_TAGS
    if tag_hit:
        return "edge:" + ",".join(sorted(tag_hit))
    if STUB_RE.match(gloss or ""):
        return "edge:stub-gloss"
    if pos == "name":
        return "edge:name-pos"
    head = re.match(r"en-(.+?)-en-", kid or "")
    if head and head.group(1) != lemma and head.group(1).lower() != lemma.lower():
        return "edge:proper-variant"
    return None


def arbitrate_link(kid, best_key, fires, *, ultra_short=False, is_twin=False,
           twin_cefr=(), is_exact=False, se_value=None,
           sa_words=frozenset(), self_form_set=frozenset(), link_min=LINK_MIN_DEFAULT,
           edge=None, manual_none=None, judge_link=None, manual_override=None,
           provisional=False):
    """Three-way decision: LINK / JUDGE-PENDING / UNMAPPED plus flags.

    Returns ``{"sensekey", "method", "evidence", "flags"}``. Flag members:
    ``twin-pending`` / ``quarantined-known-false`` / ``manual-none`` /
    ``provisional_consensus``. Precedence: MANUAL-NONE > manual-override >
    judge-v2 > twin > ultra-short > LINK/veto/quarantine > PENDING/UNMAPPED;
    ``edge`` rows bypass to UNMAPPED.

    Witness TRUE-must-link (REPORT_v0_5 E2 erratum + FIX2): occ0
    source_of_illumination -> light_source LINK ``Sa:j=0.27+Sb:source``:

    >>> d = arbitrate_link("en-light-en-noun-en:source_of_illumination", "light_source%1:06:00::", ["Sa:j=0.27", "Sb:source"], se_value=0.677, sa_words={"source"})
    >>> (d["method"], d["flags"])
    ('LINK:2-sig', [])

    Witness FALSE-must-park (REPORT_v0_5 FIX2): arrival-become
    ``Sa:j=0.27`` alone -> PENDING, never LINK:

    >>> d = arbitrate_link("en-arrival-en-noun-X", "become%2:38:00::", ["Sa:j=0.27"])
    >>> (d["sensekey"], d["method"])
    ('become%2:38:00::', 'JUDGE-PENDING')

    Witness ultra-short (REPORT_v0_5 FIX1): mistake kjZERp8U "An error."
    -> JUDGE-PENDING short-gloss, best-cand mistake%1:04:00:::

    >>> d = arbitrate_link("en-mistake-en-noun-kjZERp8U", "mistake%1:04:00::", ["Sb:error,fault"], ultra_short=True)
    >>> (d["method"], d["evidence"])
    ('JUDGE-PENDING', 'short-gloss:Sb:error,fault')

    Witness twin-suppress (link_table_v0_7.tsv): outside-E7dgXPoq:

    >>> d = arbitrate_link("en-outside-en-adv-E7dgXPoq", "outside%4:02:00::", ["Sa:j=0.40"], is_twin=True, twin_cefr=("A1", "A2"))
    >>> (d["method"], d["evidence"], d["flags"])
    ('twin-pending', 'best-cand-twinned;tsv-cefr=A1,A2', ['twin-pending'])

    Witness quarantine (link_table_v0_7.tsv): book-hoaZwz7Y:

    >>> d = arbitrate_link("en-book-en-verb-hoaZwz7Y", "book%2:41:00::", ["Sa:j=0.33", "Sd:hyp=record"], se_value=0.437, sa_words={"record"})
    >>> (d["method"], d["flags"])
    ('quarantined-known-false', ['quarantined-known-false'])

    Witness exact-sensekey (link_table_v0_7.tsv): call-f7fqB9u1:

    >>> d = arbitrate_link("en-call-en-noun-f7fqB9u1", "call%1:04:03::", ["Sa:j=0.33", "Sd:hyp=visit"], is_exact=True, se_value=0.709, sa_words={"visit"})
    >>> d["method"]
    'LINK:exact-sensekey+2-sig'

    Witness MANUAL-NONE (link_table_v0_7.tsv): E1 Q12969754:

    >>> d = arbitrate_link("en-light-en-noun-en:Q12969754", "visible_radiation%1:19:00::", ["Sa:j=0.29", "Sb:radiation"], manual_none="owner-locked:E1-any-wavelength-neq-visible+was-LINK:visible_radiation%1:19:00::")
    >>> (d["sensekey"], d["method"], d["flags"])
    ('-', 'MANUAL-NONE', ['manual-none'])

    Witness judge-v2 + provisional (REPORT_v0_7 + REPORT_v0_8 JOB5):
    idx16 convey1->wear LINK:judge-v2, 1-signal Sd-only -> flagged:

    >>> d = arbitrate_link("en-bear-en-verb-en:convey1", "wear%2:29:04::", ["Sd:hyp=feature"], judge_link={"sensekey": "wear%2:29:04::", "tag": "judge-v2:idx16:3/3:wear%2:29:04::"}, provisional=True)
    >>> (d["method"], d["evidence"], d["flags"])
    ('LINK:judge-v2', 'Sd:hyp=feature+judge-v2:idx16:3/3:wear%2:29:04::', ['provisional_consensus'])

    Witness manual override (REPORT_v0_7 pass-2): luck lQEeVMDo HIT at
    rank 6 -> streak%1:14:00:: ("an unbroken series of events"):

    >>> d = arbitrate_link("en-run-en-noun-lQEeVMDo", "run%1:28:00::", ["Sa:j=0.25", "Sd:hyp=period"], manual_override={"sensekey": "streak%1:14:00::", "evidence": "pass-2-LINK:streak%1:14:00::+was-LINK:run%1:28:00::"})
    >>> (d["sensekey"], d["method"])
    ('streak%1:14:00::', 'LINK:manual-override')
    """
    fires = list(fires)
    if edge:
        return {
            "sensekey": "-",
            "method": "UNMAPPED",
            "evidence": edge,
            "flags": [],
        }
    if manual_none is not None:
        return {
            "sensekey": "-",
            "method": "MANUAL-NONE",
            "evidence": manual_none,
            "flags": ["manual-none"],
        }
    if manual_override is not None:
        return {
            "sensekey": manual_override["sensekey"],
            "method": "LINK:manual-override",
            "evidence": manual_override["evidence"],
            "flags": [],
        }
    if judge_link is not None:
        evidence = "+".join(fires)
        if evidence:
            evidence += "+"
        evidence += judge_link["tag"]
        return {
            "sensekey": judge_link["sensekey"],
            "method": "LINK:judge-v2",
            "evidence": evidence,
            "flags": ["provisional_consensus"] if provisional else [],
        }
    if is_twin:
        return {
            "sensekey": best_key,
            "method": "twin-pending",
            "evidence": "best-cand-twinned;tsv-cefr=%s" % ",".join(sorted(twin_cefr)),
            "flags": ["twin-pending"],
        }
    if ultra_short:
        return {
            "sensekey": best_key,
            "method": "JUDGE-PENDING",
            "evidence": "short-gloss:" + ("+".join(fires) if fires else "0sig"),
            "flags": [],
        }
    if not ultra_short and len(fires) >= link_min:
        method = "LINK:exact-sensekey+%d-sig" % len(fires) if is_exact else "LINK:%d-sig" % len(fires)
        evidence = "+".join(fires)
        se_tag = "" if se_value is None else "+Se:%.3f" % se_value
        families = evidence_families(fires, sa_words, self_form_set)
        pre_words = (
            set(sa_words)
            | {word for fire in fires if fire.startswith(("Sb:", "Sc:")) for word in norm_tokens(fire.split(":", 1)[1])}
            | {word for fire in fires if fire.startswith("Sd:") and "=" in fire for word in norm_tokens(fire.split("=", 1)[1])}
        )
        generic_free = not (pre_words & GENERIC_VERBS)
        if operational_signal_veto(se_value, families, generic_free, is_exact):
            return {
                "sensekey": best_key,
                "method": "JUDGE-PENDING",
                "evidence": evidence + se_tag + "+se-veto",
                "flags": [],
            }
        quarantined = quarantine_check(kid, method)
        if quarantined:
            return {
                "sensekey": best_key,
                "method": quarantined,
                "evidence": evidence + se_tag + "+judge-first",
                "flags": ["quarantined-known-false"],
            }
        return {
            "sensekey": best_key,
            "method": method,
            "evidence": evidence + se_tag,
            "flags": [],
        }
    if not fires:
        return {
            "sensekey": best_key,
            "method": "UNMAPPED",
            "evidence": "0sig",
            "flags": [],
        }
    return {
        "sensekey": best_key,
        "method": "JUDGE-PENDING",
        "evidence": "+".join(fires),
        "flags": [],
    }


def validate_table_rows(rows):
    """Pure vendor-table guard: LINK rows carry evidence; flagged rows never LINK.

    Takes plain row dicts (``method``/``evidence``/``wordnet_sensekey``),
    returns a list of violation strings (empty = clean). Used by F3/F4;
    the F2 vendor step runs it over the shipped TSV.

    >>> validate_table_rows([{"kaikki_sense_id": "k", "wordnet_sensekey": "s%1:01:00::", "method": "LINK:2-sig", "evidence": ""}])
    ['LINK without evidence: k']
    >>> validate_table_rows([{"kaikki_sense_id": "k", "wordnet_sensekey": "s%1:01:00::", "method": "twin-pending", "evidence": "best-cand-twinned;tsv-cefr=A1"}])
    []
    >>> validate_table_rows([{"kaikki_sense_id": "k", "wordnet_sensekey": "-", "method": "MANUAL-NONE", "evidence": "owner-locked:x"}])
    []
    """
    violations = []
    for row in rows:
        kid = row.get("kaikki_sense_id", "?")
        method = row.get("method", "")
        evidence = row.get("evidence", "")
        sensekey = row.get("wordnet_sensekey", "")
        if method.startswith("LINK") and not (evidence or "").strip():
            violations.append("LINK without evidence: %s" % kid)
        if method in ("twin-pending", "quarantined-known-false", "MANUAL-NONE"):
            if method.startswith("LINK"):
                violations.append("flagged row LINKs: %s" % kid)
            if method == "MANUAL-NONE" and sensekey != "-":
                violations.append("MANUAL-NONE without '-' sensekey: %s" % kid)
    return violations


# --- Stage telemetry (ADDITIVE, F3/F4 display helper; no behavior change) ---
#
# COMPLETION_DESIGN_V2 §8 sketches ``LINK_METHOD_VOCAB`` + ``link_stats``.
# Followed with one extension (reason): the §8 sketch lists 9 values, but
# real run tables also emit UNMAPPED / JUDGE-PENDING / JUDGE-NONE /
# JUDGE-REVIEW (see run20), so the vocab covers those too — otherwise the
# gallery would hide real rows inside an "other" bucket.
LINK_METHOD_VOCAB = frozenset({
    "LINK:2-sig",
    "LINK:3-sig",
    "LINK:exact-sensekey+2-sig",
    "LINK:judge-v2",
    "LINK:manual-override",
    "twin-pending",
    "quarantined-known-false",
    "MANUAL-NONE",
    "UNMAPPED",
    "JUDGE-PENDING",
    "JUDGE-NONE",
    "JUDGE-REVIEW",
    "absent",
})

_STAGE_NONE = frozenset({"JUDGE-NONE", "MANUAL-NONE"})
_STAGE_PENDING = frozenset({"JUDGE-PENDING", "JUDGE-REVIEW"})


def _stats_stage(method):
    """Bucket one link method into a gallery stage name."""
    method = method or ""
    if method.startswith("LINK"):
        return "link"
    if method in _STAGE_NONE:
        return "none"
    if method in _STAGE_PENDING:
        return "pending"
    if method == "UNMAPPED":
        return "unmapped"
    if method == "twin-pending":
        return "twin"
    if method == "quarantined-known-false":
        return "quarantine"
    return "other"


def _stats_signals(evidence):
    """Per-row signal presence parsed from one evidence string.

    Only the rule half (before ``|``) counts as rule fires; the judge
    tail counts as ``judge``.
    """
    text = evidence or ""
    rule, _, tail = text.partition("|")
    hits = set()
    for tok in rule.split("+"):
        tok = tok.strip()
        if tok.startswith("Sa:"):
            hits.add("Sa")
        elif tok.startswith("Sb:"):
            hits.add("Sb")
        elif tok.startswith("Sc:"):
            hits.add("Sc")
        elif tok.startswith("Sd:"):
            hits.add("Sd")
        elif tok.startswith("Se:"):
            hits.add("Se")
        elif "short-gloss" in tok:
            hits.add("short-gloss")
        elif tok == "0sig":
            hits.add("zero-sig")
    if "judge:" in tail or "judge:" in rule:
        hits.add("judge")
    return hits


def link_stats(rows):
    """Count per-stage / per-signal / per-flag telemetry over link rows.

    Pure rows-only helper for the linker gallery (COMPLETION_DESIGN_V2
    §8). Takes plain row dicts (``method``/``evidence``/``flags``),
    returns ``{"total", "method_counts", "unknown_methods", "stage",
    "signals", "flags"}``. ``stage["provisional"]`` is orthogonal: a
    row whose flags or evidence mentions ``provisional`` counts there
    AND in its method stage, so stage buckets minus provisional sum to
    ``total`` while provisional overlaps.

    >>> rows = [
    ...     {"kaikki_sense_id": "a", "method": "LINK:2-sig",
    ...      "evidence": "Sa:j=0.27+Sb:source", "flags": ""},
    ...     {"kaikki_sense_id": "b", "method": "JUDGE-PENDING",
    ...      "evidence": "Sa:j=0.27", "flags": ""},
    ...     {"kaikki_sense_id": "c", "method": "UNMAPPED",
    ...      "evidence": "0sig", "flags": ""},
    ... ]
    >>> s = link_stats(rows)
    >>> (s["total"], s["stage"]["link"], s["stage"]["pending"])
    (3, 1, 1)
    >>> (s["signals"]["Sa"], s["signals"]["Sb"], s["unknown_methods"])
    (2, 1, [])
    """
    rows = list(rows or [])
    method_counts = {}
    stage = {"link": 0, "none": 0, "pending": 0, "unmapped": 0,
             "twin": 0, "quarantine": 0, "provisional": 0, "other": 0}
    signals = {"Sa": 0, "Sb": 0, "Sc": 0, "Sd": 0, "Se": 0,
               "judge": 0, "short-gloss": 0, "zero-sig": 0}
    flags = {}
    for row in rows:
        method = row.get("method") or ""
        evidence = row.get("evidence", "")
        method_counts[method] = method_counts.get(method, 0) + 1
        stage[_stats_stage(method)] += 1
        flag_text = row.get("flags", "") or ""
        if "provisional" in flag_text or "provisional" in (evidence or ""):
            stage["provisional"] += 1
        for hit in _stats_signals(evidence):
            signals[hit] += 1
        for flag in flag_text.split("+"):
            flag = flag.strip()
            if flag:
                flags[flag] = flags.get(flag, 0) + 1
    unknown = sorted(m for m in method_counts if m not in LINK_METHOD_VOCAB)
    return {
        "total": len(rows),
        "method_counts": method_counts,
        "unknown_methods": unknown,
        "stage": stage,
        "signals": signals,
        "flags": flags,
    }


# --- Gallery vocabulary + per-card machine telemetry (ADDITIVE, no behavior change) ---
#
# Locked gallery vocabulary (owner round 2): every gauge/chip/telemetry key
# uses these names everywhere. Legacy Sa..Se / short-gloss / 0sig codes
# survive ONLY as parenthetical aliases inside evidence strings, so old
# tables stay readable. Nothing below is consulted by arbitrate_link/link_stats.
SIGNAL_VOCAB = {
    "Sa": {"name": "lexical-overlap", "fa": "هم‌پوشانی واژگان تعریف"},
    "Sb": {"name": "synonym-crossfire", "fa": "آتش متقابل هم‌معنی‌ها"},
    "Sc": {"name": "example-crossfire", "fa": "آتش متقابل مثال‌ها"},
    "Sd": {"name": "hypernym-topic", "fa": "ابرنام/موضوع"},
    "Se": {"name": "meaning-similarity", "fa": "شباهت معنایی"},
    "short-gloss": {"name": "short-definition", "fa": "تعریف کوتاه"},
    "zero-sig": {"name": "no-signal", "fa": "بی‌علامت"},
    "judge": {"name": "judge-vote", "fa": "رأی داور"},
}

# Raw evidence tokens that are aliases of a canonical code (legacy 0sig).
SIGNAL_ALIAS = {"0sig": "zero-sig"}

# Canonical locked-vocabulary signal names (single source; the viewer
# reuses these — never a parallel copy). ``CANON_SIGNAL_NAMES`` is the
# full display vocabulary; ``CANON_RULE_SIGNAL_NAMES`` is the quorum
# subset that may count toward ``n_fires`` (no-signal never fires,
# judge-vote is a judge fact, never a rule signal).
#
# >>> sorted(CANON_SIGNAL_NAMES) == sorted(
# ...     entry["name"] for entry in SIGNAL_VOCAB.values())
# True
# >>> "judge-vote" in CANON_RULE_SIGNAL_NAMES
# False
CANON_SIGNAL_NAMES = frozenset(
    entry["name"] for entry in SIGNAL_VOCAB.values())
CANON_RULE_SIGNAL_NAMES = frozenset(
    name for name in CANON_SIGNAL_NAMES
    if name not in ("no-signal", "judge-vote"))

JUDGE_VOCAB = {
    "unanimous": {"name": "unanimous", "fa": "اجماعی 3-0"},
    "split": {"name": "split-vote", "fa": "شقه 2-1"},
}


def signal_vocab(code):
    """Map a legacy signal code to the locked gallery vocabulary entry.

    Returns ``{"code", "name", "fa"}``; unknown codes pass through with
    ``name == code`` (fail-soft for future signals).

    >>> signal_vocab("Sa")["name"]
    'lexical-overlap'
    >>> signal_vocab("0sig")["name"]
    'no-signal'
    >>> signal_vocab("Se")["fa"]
    'شباهت معنایی'
    >>> signal_vocab("judge")["name"]
    'judge-vote'
    >>> signal_vocab("Sx")["name"]
    'Sx'
    """
    canon = SIGNAL_ALIAS.get(code, code)
    entry = SIGNAL_VOCAB.get(canon)
    if entry is None:
        return {"code": code, "name": code, "fa": code}
    return {"code": canon, "name": entry["name"], "fa": entry["fa"]}


def telemetry_counters(rows):
    """Vocabulary-keyed counters over link rows (gallery display helper).

    Same row scan as :func:`link_stats` but signal keys are locked
    vocabulary names (``lexical-overlap`` … ``no-signal``,
    ``judge-vote``) instead of legacy codes. Stage buckets identical.

    >>> rows = [
    ...     {"kaikki_sense_id": "a", "method": "LINK:2-sig",
    ...      "evidence": "Sa:j=0.27+Sb:source", "flags": ""},
    ...     {"kaikki_sense_id": "c", "method": "UNMAPPED",
    ...      "evidence": "0sig", "flags": ""},
    ... ]
    >>> c = telemetry_counters(rows)
    >>> (c["total"], c["signals"]["lexical-overlap"], c["signals"]["no-signal"])
    (2, 1, 1)
    >>> c["stage"]["link"]
    1
    """
    rows = list(rows or [])
    signals = {entry["name"]: 0 for entry in SIGNAL_VOCAB.values()}
    stage = {"link": 0, "none": 0, "pending": 0, "unmapped": 0,
             "twin": 0, "quarantine": 0, "provisional": 0, "other": 0}
    for row in rows:
        stage[_stats_stage(row.get("method", ""))] += 1
        flag_text = row.get("flags", "") or ""
        if "provisional" in flag_text or "provisional" in (row.get("evidence", "") or ""):
            stage["provisional"] += 1
        for hit in _stats_signals(row.get("evidence", "")):
            name = signal_vocab(hit)["name"]
            signals[name] = signals.get(name, 0) + 1
    return {"total": len(rows), "signals": signals, "stage": stage}


def machine_block(row):
    """Per-card machine telemetry for the gallery (pure, JSON-safe).

    Parses the row's rule-half evidence into per-signal fired detail
    (exact words/scores), attaches the frozen decision thresholds, and
    the tier/seed/build parsed from the ``provenance`` column (if any).

    >>> row = {"kaikki_sense_id": "k", "method": "LINK:2-sig",
    ...        "evidence": "Sa:j=0.40+Sd:hyp=move", "flags": "",
    ...        "provenance": "rules:v0.6-equiv:se=None:STOP=base:seed=20260918:build=run20"}
    >>> blk = machine_block(row)
    >>> (blk["signals"]["lexical-overlap"]["detail"], blk["tier"], blk["seed"])
    ('Sa:j=0.40', 'base', '20260918')
    >>> blk["thresholds"]["link_min"]
    2
    >>> machine_block({"kaikki_sense_id": "u", "method": "UNMAPPED",
    ...                "evidence": "0sig", "flags": ""})["signals"]["no-signal"]["detail"]
    '0sig'
    """
    row = row or {}
    evidence = row.get("evidence", "") or ""
    rule, _, _ = evidence.partition("|")
    signals = {}
    for tok in rule.split("+"):
        tok = tok.strip()
        if not tok:
            continue
        if tok.startswith("Sa:"):
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
        name = signal_vocab(code)["name"]
        signals.setdefault(name, {"code": signal_vocab(code)["code"],
                                  "alias": tok, "detail": tok})
    provenance = row.get("provenance", "") or ""
    tier = seed = build = ""
    for chunk in provenance.split(":"):
        if chunk.startswith("STOP="):
            tier = chunk[len("STOP="):]
        elif chunk.startswith("seed="):
            seed = chunk[len("seed="):]
        elif chunk.startswith("build="):
            build = chunk[len("build="):]
    flags = [f.strip() for f in (row.get("flags", "") or "").split("+") if f.strip()]
    return {
        "kid": row.get("kaikki_sense_id", ""),
        "method": row.get("method", ""),
        "signals": signals,
        "thresholds": {
            "jaccard": JACCARD_DEFAULT,
            "se_cut": SE_CUT,
            "se_veto_floor": SE_VETO_FLOOR,
            "link_min": LINK_MIN_DEFAULT,
            "shortlist_cap": SHORTLIST_CAP,
            "ultra_short_min_tokens": ULTRA_SHORT_MIN_TOKENS,
        },
        "tier": tier or "unknown",
        "seed": seed or "unknown",
        "build": build or "unknown",
        "flags": flags,
        "provenance": provenance,
    }


# --- Per-card flow-trace model (ADDITIVE, gallery display helper) ---
#
# Owner-locked flow-tracer build: one pure ``flow_trace_data`` helper feeds
# the factory/linking gallery tracer (five nodes + four wires per card).
# No scoring behavior change; nothing above is consulted by arbitrate_link().

_FLOW_NONE_METHODS = frozenset({"JUDGE-NONE", "MANUAL-NONE"})


def _flow_locator(sensekey):
    """Synset locator for the flow tracer (``38:00`` style, no invention).

    >>> _flow_locator("run%2:38:00::")
    '38:00'
    >>> _flow_locator("-")
    '—'
    """
    text = sensekey or ""
    if "%" not in text:
        return "—"
    tail = text.split("%", 1)[-1].split(":")
    if len(tail) < 3 or not tail[1].isdigit():
        return "—"
    return "%s:%s" % (tail[1], tail[2] or "—")


def _flow_signal_code(tok):
    """Legacy evidence token -> canonical signal code (tracer mapping)."""
    if tok.startswith("Sa:"):
        return "Sa"
    if tok.startswith("Sb:"):
        return "Sb"
    if tok.startswith("Sc:"):
        return "Sc"
    if tok.startswith("Sd:"):
        return "Sd"
    if tok.startswith("Se:"):
        return "Se"
    if "short-gloss" in tok:
        return "short-gloss"
    if tok in ("0sig", "zero-sig"):
        return "zero-sig"
    if "judge:" in tok:
        return "judge"
    return tok


def flow_trace_data(row, verdict=None, candidates=None):
    """Per-card flow-trace model from real table + verdict rows (pure).

    Takes a link-table ``row`` dict, a judge ``verdict`` dict (may be
    empty) and a candidates entry (``{"top3": [...]}``, may be empty).
    Returns a JSON-safe dict: input sense, candidates with FULL defs /
    scores / winner flags, signals with exact words/scores, decision,
    votes, flags, plus four wire specs (from/to/label/status over the
    success / warn / fail / twin / bypassed palette).

    >>> row = {"kaikki_sense_id": "k", "lemma": "run",
    ...        "kaikki_gloss": "To move fast.",
    ...        "method": "LINK:2-sig",
    ...        "wordnet_sensekey": "run%2:38:00::",
    ...        "evidence": "Sa:j=0.40+Sd:hyp=move", "flags": ""}
    >>> d = flow_trace_data(row, {}, {"top3": [
    ...     {"sensekey": "run%2:38:00::", "gloss": "move fast",
    ...      "jaccard": 0.40, "lemmas": ["run"], "fires": []}]})
    >>> (d["method"], d["candidates"][0]["is_winner"])
    ('LINK:2-sig', True)
    >>> [w["status"] for w in d["wires"]]
    ['success', 'success', 'bypassed', 'success']
    >>> flow_trace_data(dict(row, method="twin-pending"),
    ...                 {}, None)["wires"][2]["status"]
    'twin'
    """
    row = dict(row or {})
    verdict = dict(verdict or {})
    candidates = candidates or {}
    method = row.get("method", "") or ""
    evidence = row.get("evidence", "") or ""
    flags = [f.strip()
             for f in (row.get("flags", "") or "").split("+") if f.strip()]

    winner = row.get("wordnet_sensekey", "") or ""
    if method in ("UNMAPPED", "MANUAL-NONE") and verdict.get("winner_sensekey"):
        winner = verdict.get("winner_sensekey") or winner

    rule, _, _ = evidence.partition("|")
    signals = []
    for tok in rule.split("+"):
        tok = tok.strip()
        if not tok:
            continue
        code = _flow_signal_code(tok)
        name = signal_vocab(code)["name"]
        signals.append({"code": code, "name": name, "alias": tok,
                        "fired": name != "no-signal"})
    if not signals:
        signals = [{"code": "zero-sig", "name": "no-signal",
                    "alias": "0sig", "fired": False}]
    n_fires = sum(1 for s in signals
                  if s["fired"] and s["name"] in CANON_RULE_SIGNAL_NAMES)

    top3 = list((candidates or {}).get("top3") or [])
    cand_rows = []
    for rank, cand in enumerate(top3, 1):
        skey = (cand or {}).get("sensekey", "") or ""
        cand_rows.append({
            "rank": rank,
            "key": skey,
            "locator": _flow_locator(skey),
            "def": (cand or {}).get("gloss", "") or "",
            "j": (cand or {}).get("jaccard"),
            "lemmas": list((cand or {}).get("lemmas") or []),
            "fires": list((cand or {}).get("fires") or []),
            "is_winner": bool(winner and winner != "-" and skey == winner),
        })

    votes = verdict.get("votes") or []
    ok_votes = [v for v in votes if (v or {}).get("ok")]
    if len(ok_votes) < 2:
        agree = "unjudged"
    else:
        winners = {(v or {}).get("winner_index") for v in ok_votes}
        kinds = {(v or {}).get("verdict") for v in ok_votes}
        agree = ("unanimous" if len(winners) == 1 and len(kinds) == 1
                 else "split-vote")

    if method == "twin-pending":
        gate = "twin"
    elif method == "JUDGE-REVIEW":
        gate = "review"
    elif method == "JUDGE-PENDING":
        gate = "pending"
    elif method.startswith("LINK:judge-v2") or (
            method.startswith("LINK") and votes):
        gate = "judge"
    elif method.startswith("LINK"):
        gate = "rule"
    else:
        gate = "none"

    has_cands = bool(cand_rows)
    w1 = {"from": 1, "to": 2, "label": "استخراج کاندیداها",
          "status": "success" if has_cands else "warn"}
    w2 = {"from": 2, "to": 3, "label": "ارسال کاندیداها به ارزیابی",
          "status": "success" if has_cands and n_fires > 0 else "warn"}
    if gate == "twin":
        w3 = {"from": 3, "to": 4, "label": "کشف تقاضای همزاد (توقف)",
              "status": "twin"}
    elif gate == "rule":
        w3 = {"from": 3, "to": 4,
              "label": "عبور از داور (قاعده برنده شد)",
              "status": "bypassed"}
    elif gate == "review":
        w3 = {"from": 3, "to": 4, "label": "ارجاع فوری به داور",
              "status": "warn"}
    elif gate == "pending":
        w3 = {"from": 3, "to": 4, "label": "ارجاع به داور",
              "status": "warn"}
    elif gate == "judge":
        w3 = {"from": 3, "to": 4, "label": "ارجاع به داور",
              "status": "success" if agree == "unanimous" else "warn"}
    elif method in _FLOW_NONE_METHODS:
        w3 = {"from": 3, "to": 4, "label": "ارجاع به داور",
              "status": "warn"}
    else:
        w3 = {"from": 3, "to": 4, "label": "توقف (بدون سیگنال)",
              "status": "warn"}
    if method.startswith("LINK"):
        w4 = {"from": 4, "to": 5, "label": "تأیید پیوند",
              "status": "success"}
    elif method == "twin-pending":
        w4 = {"from": 4, "to": 5, "label": "تعلیق پیوند در صف دوقلوها",
              "status": "twin"}
    elif method in _FLOW_NONE_METHODS:
        w4 = {"from": 4, "to": 5, "label": "رد قطعی داور",
              "status": "fail"}
    elif method in ("JUDGE-PENDING", "JUDGE-REVIEW",
                    "quarantined-known-false", "UNMAPPED"):
        w4 = {"from": 4, "to": 5, "label": "توقف جهت بازبینی",
              "status": "warn"}
    else:
        w4 = {"from": 4, "to": 5, "label": "توقف جهت بازبینی",
              "status": "warn"}

    wn_gloss = ((verdict.get("wordnet_evidence", "") or "").split("||")[0]
                .strip())
    return {
        "kid": row.get("kaikki_sense_id", "") or "",
        "lemma": row.get("lemma", "") or "",
        "in_def": row.get("kaikki_gloss", "") or "",
        "method": method,
        "evidence": evidence,
        "flags": flags,
        "winner": winner,
        "winner_locator": _flow_locator(winner),
        "winner_def": wn_gloss,
        "n_fires": n_fires,
        "gate": gate,
        "agree": agree,
        "candidates": cand_rows,
        "signals": signals,
        "votes": votes,
        "verdict": verdict.get("verdict") or "",
        "winner_sensekey": verdict.get("winner_sensekey") or "",
        "wires": [w1, w2, w3, w4],
    }


def verdict_wire45(verdict=None, method="", winner_key=""):
    """Judge-wire (4→5) spec from the VERDICT first, table state second (pure).

    Gallery display rule (owner-locked): the 4→5 wire reflects the judge
    verdict — LINK verdict → approval (``تأیید پیوند``/success), NONE
    verdict → rejection (``رد قطعی داور``/fail), no verdict → hold
    (``توقف جهت بازبینی``/warn). Table-consumption pending (JUDGE-PENDING)
    is a separate node-5 fact, never a wire label. Verdict-less fallbacks:
    mechanical rule LINK + winner → approval; twin-pending → twin hold;
    anything else → hold-for-review.

    >>> verdict_wire45({"verdict": "LINK"}, "JUDGE-PENDING", "run%2:38:00::")
    {'from': 4, 'to': 5, 'label': 'تأیید پیوند', 'status': 'success'}
    >>> verdict_wire45({"verdict": "NONE"}, "JUDGE-PENDING", "-")
    {'from': 4, 'to': 5, 'label': 'رد قطعی داور', 'status': 'fail'}
    >>> verdict_wire45({}, "JUDGE-PENDING", "run%2:38:11::")
    {'from': 4, 'to': 5, 'label': 'توقف جهت بازبینی', 'status': 'warn'}
    >>> verdict_wire45({}, "LINK:2-sig", "run%2:38:00::")
    {'from': 4, 'to': 5, 'label': 'تأیید پیوند', 'status': 'success'}
    >>> verdict_wire45({}, "twin-pending", "-")
    {'from': 4, 'to': 5, 'label': 'تعلیق پیوند در صف دوقلوها', 'status': 'twin'}
    >>> verdict_wire45({"verdict": "LINK", "vote_status": "FAILED"}, "JUDGE-PENDING", "k")
    {'from': 4, 'to': 5, 'label': 'توقف جهت بازبینی', 'status': 'warn'}
    """
    verdict = verdict or {}
    vverdict = verdict.get("verdict") or ""
    votes = verdict.get("votes") or []
    failed = (verdict.get("vote_status") == "FAILED"
              or any(not (v or {}).get("ok", True) for v in votes))
    if failed:
        # A crashed judge run is neither an approval nor a rejection —
        # hold for review (mirrors _flowtrace_status: failed ≠ LINK).
        return {"from": 4, "to": 5, "label": "توقف جهت بازبینی",
                "status": "warn"}
    if vverdict == "LINK":
        return {"from": 4, "to": 5, "label": "تأیید پیوند",
                "status": "success"}
    if vverdict == "NONE":
        return {"from": 4, "to": 5, "label": "رد قطعی داور",
                "status": "fail"}
    if (method or "").startswith("LINK") and winner_key and winner_key != "-":
        return {"from": 4, "to": 5, "label": "تأیید پیوند",
                "status": "success"}
    if method == "twin-pending":
        return {"from": 4, "to": 5,
                "label": "تعلیق پیوند در صف دوقلوها", "status": "twin"}
    return {"from": 4, "to": 5, "label": "توقف جهت بازبینی",
            "status": "warn"}


# --- Gallery run-version (ADDITIVE, display helper; no behavior change) ---
#
# The gallery shows its OWN version (viewer.GALLERY_VERSION) AND the SOURCE
# RUN's version — which linker build made the DATA. The run version is
# derived from rows' provenance strings at gallery build time, never
# guessed: only ``rules:<tag>:...:seed=<n>:...:build=<name>`` triples count
# (see run20: ``rules:v0.6-equiv:...:build=run20:...``). Legacy
# (``linker-v0.6:…``), inventory (``inventory:tsv-twin``) and owner-manual
# provenances carry no triple and count as absent. Nothing below is
# consulted by arbitrate_link/link_stats/machine_block/flow_trace_data.


def parse_run_provenance(provenance):
    """Parse the run-version triple from one row provenance string (pure).

    Returns ``{"rules", "build", "seed"}`` or None when the string carries
    no triple (absent/unparseable) — never guesses. A judge tail after
    ``|`` is ignored (same run, verdict facet only).

    >>> parse_run_provenance("rules:v0.6-equiv:se=None:STOP=base:seed=20260918:build=run20:factory-linker=x")
    {'rules': 'v0.6-equiv', 'build': 'run20', 'seed': '20260918'}
    >>> parse_run_provenance("rules:v0.6-equiv:se=None:STOP=base:seed=20260918:build=run20|judge-v2:pass1:3-0:LINK/1")
    {'rules': 'v0.6-equiv', 'build': 'run20', 'seed': '20260918'}
    >>> parse_run_provenance("linker-v0.6:link_table_v0_7.tsv") is None
    True
    >>> parse_run_provenance("inventory:tsv-twin") is None
    True
    >>> parse_run_provenance("rules:v0.6-equiv:se=None") is None
    True
    >>> parse_run_provenance("") is None
    True
    >>> parse_run_provenance(None) is None
    True
    """
    run_half = (provenance or "").split("|", 1)[0]
    chunks = run_half.split(":")
    if len(chunks) < 2 or chunks[0] != "rules" or not chunks[1].strip():
        return None
    rules = chunks[1].strip()
    build = seed = ""
    for chunk in chunks[2:]:
        if chunk.startswith("build=") and not build:
            build = chunk[len("build="):].strip()
        elif chunk.startswith("seed=") and not seed:
            seed = chunk[len("seed="):].strip()
    if not build or not seed:
        return None
    return {"rules": rules, "build": build, "seed": seed}


def run_version(rows):
    """Gallery run-version over link-table rows (pure, never guesses).

    Takes plain row dicts (``provenance``), returns ``{"status", "label",
    "build", "rules", "seed"}``:

    - ``single``: every row carries the SAME triple — label is
      ``"<build> (<rules>)"`` (e.g. ``"run20 (v0.6-equiv)"``);
    - ``mixed``: triples disagree, or some rows carry one and others
      don't (majority never wins) — label ``"mixed"``;
    - ``unknown``: no row carries a triple (or no rows) — label
      ``"unknown (absent)"``.

    >>> run_version([{"provenance": "rules:v0.6-equiv:se=None:STOP=base:seed=20260918:build=run20"}])["label"]
    'run20 (v0.6-equiv)'
    >>> run_version([{"provenance": "rules:v0.6-equiv:se=None:STOP=base:seed=20260918:build=run20"}, {"provenance": "inventory:tsv-twin"}])["label"]
    'mixed'
    >>> run_version([{"provenance": ""}, {}])["label"]
    'unknown (absent)'
    >>> run_version([])["status"]
    'unknown'
    """
    triples = []
    untripled = 0
    for row in rows or []:
        triple = parse_run_provenance((row or {}).get("provenance", ""))
        if triple is None:
            untripled += 1
        else:
            triples.append((triple["rules"], triple["build"],
                            triple["seed"]))
    if not triples:
        return {"status": "unknown", "label": "unknown (absent)",
                "build": "", "rules": "", "seed": ""}
    if untripled or len(set(triples)) > 1:
        return {"status": "mixed", "label": "mixed",
                "build": "", "rules": "", "seed": ""}
    rules, build, seed = triples[0]
    return {"status": "single", "label": "%s (%s)" % (build, rules),
            "build": build, "rules": rules, "seed": seed}
