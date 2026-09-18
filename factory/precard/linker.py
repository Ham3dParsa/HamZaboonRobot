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
twin suppression lives solely in :func:`decide` (``is_twin``), so every
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
NAME_RE = re.compile(r"^[A-Z]")


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


def signal_sa(gloss_toks, cand_toks, stopwords=frozenset(), jaccard=JACCARD_DEFAULT):
    """Sa: jaccard overlap of deweighted gloss/definition token sets.

    Returns ``(j, fires)``. Ultra-short guard: either side under 3
    deweighted tokens forces ``j = -1.0`` (Sa cannot fire).

    Witness FALSE-must-park (REPORT_v0_5 FIX2): rumor-run keeps only
    ``Sd:hyp=move`` — a move-only overlap never fires Sa:

    >>> j, fires = signal_sa({"rumor", "move", "report", "hearsay"}, {"run", "move", "flow", "stream"})
    >>> (round(j, 2), fires)
    (0.0, False)

    >>> j, fires = signal_sa({"an"}, {"mistake", "error", "fault"})
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


def signal_sb(gloss_toks, kaikki_syns, cand_lemmas, self=frozenset(),
              stopwords=frozenset()):
    """Sb: synonym cross-fire, ONE signal (both directions, same family).

    (i) kaikki synonyms cap WN lemmas; (ii) kaikki gloss content tokens cap
    WN lemma component tokens. Deweighted, sorted, capped at 6.

    Witness MUST-DEMOTE (REPORT_v0_6): IC5yKMhe "To cause to come or go or
    move." — Sb:cause dies under the cause-rule, row drops below 2-sig:

    >>> signal_sb({"cause", "come", "go", "move"}, set(), {"stimulate"})
    []

    Witness TRUE-must-stay (REPORT_v0_5 FIX2): bear-support keeps
    ``Sa:j=0.40+Sb:hold``:

    >>> signal_sb({"support", "hold"}, set(), {"hold", "carry", "bear"})
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


def signal_sc(kaikki_ex_toks, cand_ex_toks, kaikki_lemmas, cand_lemmas,
              sb_words, self=frozenset()):
    """Sc: example cross-fire minus words already counted in Sb.

    Generic verbs (or words containing one) never count. Sorted, cap 4.

    Witness (REPORT_v0_5 FIX2): the only convey1->deport LINK left is the
    behave-TRUE ``Sa:j=0.20+Sb:behave,conduct`` — Sc stays silent there:

    >>> signal_sc({"behave"}, {"conduct"}, {"behave"}, {"behave", "conduct"}, {"behave", "conduct"})
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


def signal_sd(hyp_lemmas, gloss_toks, sb_tok_set, topics=(),
              cand_def_toks=frozenset(), cand_lexname=""):
    """Sd: hypernym/topic fire (UNTOUCHED by generic deweight by verdict scope).

    Priority: hyp cap gloss (minus Sb words) > topic cap
    def/lexname (minus Sb words). Else None. The frozen Oxford-fallback
    branch is a no-op ``pass`` there, so dropping it changes nothing.

    Witness FALSE-must-park (REPORT_v0_5 FIX2): rumor-run survives on
    ``Sd:hyp=move`` only:

    >>> signal_sd({"move", "run"}, {"rumor", "move"}, set())
    'Sd:hyp=move'

    Witness TRUE-must-stay (REPORT_v0_6 fate table): spring-leap keeps
    firing alongside Sa:

    >>> signal_sd({"leap", "jump"}, {"leap", "spring"}, set())
    'Sd:hyp=leap'

    >>> signal_sd({"run"}, {"error"}, set()) is None
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


def se_veto(se_value, families, generic_free, is_exact, floor=SE_VETO_FLOOR):
    """FIX3 veto: Se<floor demotes only single-family, generic-verb-free,
    non-exact-sensekey LINK candidates.

    Witnesses (REPORT_v0_5 FIX3 + REPORT_v0_6): lie-TRUE (Se 0.305,
    multi-family) NOT vetoed; exact-sensekey run-row NOT vetoed; luck
    (Se 0.633) NOT vetoed:

    >>> se_veto(0.305, {"consist", "exist"}, True, False)
    False
    >>> se_veto(0.20, {"bring"}, True, True)
    False
    >>> se_veto(0.633, {"period"}, True, False)
    False
    >>> se_veto(0.30, {"period"}, True, False)
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


def decide(kid, best_key, fires, *, ultra_short=False, is_twin=False,
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

    >>> d = decide("en-light-en-noun-en:source_of_illumination", "light_source%1:06:00::", ["Sa:j=0.27", "Sb:source"], se_value=0.677, sa_words={"source"})
    >>> (d["method"], d["flags"])
    ('LINK:2-sig', [])

    Witness FALSE-must-park (REPORT_v0_5 FIX2): arrival-become
    ``Sa:j=0.27`` alone -> PENDING, never LINK:

    >>> d = decide("en-arrival-en-noun-X", "become%2:38:00::", ["Sa:j=0.27"])
    >>> (d["sensekey"], d["method"])
    ('become%2:38:00::', 'JUDGE-PENDING')

    Witness ultra-short (REPORT_v0_5 FIX1): mistake kjZERp8U "An error."
    -> JUDGE-PENDING short-gloss, best-cand mistake%1:04:00:::

    >>> d = decide("en-mistake-en-noun-kjZERp8U", "mistake%1:04:00::", ["Sb:error,fault"], ultra_short=True)
    >>> (d["method"], d["evidence"])
    ('JUDGE-PENDING', 'short-gloss:Sb:error,fault')

    Witness twin-suppress (link_table_v0_7.tsv): outside-E7dgXPoq:

    >>> d = decide("en-outside-en-adv-E7dgXPoq", "outside%4:02:00::", ["Sa:j=0.40"], is_twin=True, twin_cefr=("A1", "A2"))
    >>> (d["method"], d["evidence"], d["flags"])
    ('twin-pending', 'best-cand-twinned;tsv-cefr=A1,A2', ['twin-pending'])

    Witness quarantine (link_table_v0_7.tsv): book-hoaZwz7Y:

    >>> d = decide("en-book-en-verb-hoaZwz7Y", "book%2:41:00::", ["Sa:j=0.33", "Sd:hyp=record"], se_value=0.437, sa_words={"record"})
    >>> (d["method"], d["flags"])
    ('quarantined-known-false', ['quarantined-known-false'])

    Witness exact-sensekey (link_table_v0_7.tsv): call-f7fqB9u1:

    >>> d = decide("en-call-en-noun-f7fqB9u1", "call%1:04:03::", ["Sa:j=0.33", "Sd:hyp=visit"], is_exact=True, se_value=0.709, sa_words={"visit"})
    >>> d["method"]
    'LINK:exact-sensekey+2-sig'

    Witness MANUAL-NONE (link_table_v0_7.tsv): E1 Q12969754:

    >>> d = decide("en-light-en-noun-en:Q12969754", "visible_radiation%1:19:00::", ["Sa:j=0.29", "Sb:radiation"], manual_none="owner-locked:E1-any-wavelength-neq-visible+was-LINK:visible_radiation%1:19:00::")
    >>> (d["sensekey"], d["method"], d["flags"])
    ('-', 'MANUAL-NONE', ['manual-none'])

    Witness judge-v2 + provisional (REPORT_v0_7 + REPORT_v0_8 JOB5):
    idx16 convey1->wear LINK:judge-v2, 1-signal Sd-only -> flagged:

    >>> d = decide("en-bear-en-verb-en:convey1", "wear%2:29:04::", ["Sd:hyp=feature"], judge_link={"sensekey": "wear%2:29:04::", "tag": "judge-v2:idx16:3/3:wear%2:29:04::"}, provisional=True)
    >>> (d["method"], d["evidence"], d["flags"])
    ('LINK:judge-v2', 'Sd:hyp=feature+judge-v2:idx16:3/3:wear%2:29:04::', ['provisional_consensus'])

    Witness manual override (REPORT_v0_7 pass-2): luck lQEeVMDo HIT at
    rank 6 -> streak%1:14:00:: ("an unbroken series of events"):

    >>> d = decide("en-run-en-noun-lQEeVMDo", "run%1:28:00::", ["Sa:j=0.25", "Sd:hyp=period"], manual_override={"sensekey": "streak%1:14:00::", "evidence": "pass-2-LINK:streak%1:14:00::+was-LINK:run%1:28:00::"})
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
        if se_veto(se_value, families, generic_free, is_exact):
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
