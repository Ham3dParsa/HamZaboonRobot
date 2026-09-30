"""Mechanical runner (R1–R4): vendor-table rows -> mechanical_review -> verdict.

Pure orchestration over injected seams (no I/O, no network, no model):

- R1 best_key: first candidate in table index order (matches
  lookup + shortlist order-kept; zero invention).
- R2 fires: row evidence split on "+" unioned across the sense's rows
  for the best key (shipped data only).
- R3 twin/ultra-short/exact inputs: all default off in v1; twin-suspect
  (vendor table carries >1 distinct sensekey for the sense) and
  ultra-short (deweighted gloss tokens < 3) senses route to DEFERRED
  (never approved/rejected; arbiter + operator still see them).
- R4 method->verdict map: ``LINK:*`` -> approved; ``MANUAL-NONE`` /
  ``quarantined-known-false`` -> rejected; ``JUDGE-PENDING`` /
  ``UNMAPPED`` / ``twin-pending`` -> deferred.

``mechanical_review`` behavior itself is untouched (doctests bind it).
"""

from __future__ import annotations

from factory.linking import linker as _linker


def _fires_for_key(rows, best_key):
    """Union of "+"-split evidence tokens across rows for ``best_key``."""
    fires = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        skey = row.get("wordnet_sensekey")
        skey = skey.strip() if isinstance(skey, str) else ""
        if not skey or skey != best_key:
            continue
        for tok in str(row.get("evidence") or "").split("+"):
            tok = tok.strip()
            if tok and tok not in seen:
                seen.add(tok)
                fires.append(tok)
    return fires


def _sense_rows(index, short_id, full_id):
    """Vendor-table rows for one sense (FULL then SHORT, index order)."""
    from factory.linking import lookup_link

    out = []
    for kid in (full_id, short_id):
        if not kid:
            continue
        for row in lookup_link(index or {}, kid) or []:
            if isinstance(row, dict):
                out.append(row)
    return out


def _is_ultra_short(definition):
    """True when the gloss carries < 3 deweighted tokens (R3)."""
    toks = _linker.norm_tokens(definition or "")
    return len(_linker.deweight_toks(set(toks))) < 3


def _is_twin_suspect(rows):
    """True when the vendor table carries >1 distinct sensekey (R3)."""
    keys = set()
    for row in rows or []:
        skey = (row or {}).get("wordnet_sensekey")
        skey = skey.strip() if isinstance(skey, str) else ""
        if skey and skey != "-":
            keys.add(skey)
    return len(keys) > 1


def map_verdict(method):
    """R4: mechanical method -> approved / rejected / deferred."""
    method = str(method or "")
    if method.startswith("LINK"):
        return "approved"
    if method in ("MANUAL-NONE", "quarantined-known-false"):
        return "rejected"
    return "deferred"


def run_mechanical(senses, index):
    """Run the mechanical step over sense-feed items; return records.

    ``senses`` are ``sense_feed.load_senses`` items
    (``sense_id``/``full_id`` via ``sense_id`` + feed join; the feed
    items carry ``sense_id`` only, so callers pass ``full_id`` through
    when known — absent full ids simply join on the short id).
    Each record: ``{sense_id, lemma, definition, best_key, method,
    evidence, verdict, deferred_reason}``.
    """
    out = []
    for item in senses or []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("sense_id") or "")
        full_id = str(item.get("full_id") or "")
        rows = _sense_rows(index or {}, sid, full_id)
        cands = [c for c in (item.get("candidates") or [])
                 if isinstance(c, dict)]
        best_key = str((cands[0].get("synset_id") if cands else "") or "")
        fires = _fires_for_key(rows, best_key) if best_key else []
        decision = _linker.mechanical_review(sid, best_key, fires)
        verdict = map_verdict(decision.get("method"))
        reason = ""
        if _is_twin_suspect(rows) or _is_ultra_short(
                item.get("definition")):
            if verdict in ("approved", "rejected"):
                verdict = "deferred"
                reason = "twin-suspect" if _is_twin_suspect(rows) \
                    else "ultra-short"
        out.append({
            "sense_id": sid,
            "lemma": str(item.get("lemma") or ""),
            "definition": str(item.get("definition") or ""),
            "best_key": best_key,
            "method": decision.get("method", ""),
            "evidence": decision.get("evidence", ""),
            "verdict": verdict,
            "deferred_reason": reason,
        })
    return out


def summarize(records):
    """``{approved, rejected, deferred, total}`` counts over records."""
    counts = {"approved": 0, "rejected": 0, "deferred": 0,
              "total": len(records or [])}
    for rec in records or []:
        verdict = (rec or {}).get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    return counts
