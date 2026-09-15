"""Sample accounting audit (moved verbatim from the precard line).

Never-silent-drop invariant: every sample key resolves to >=1 precard
row or a structured drop verdict. Pure function, stdlib only.
"""

from __future__ import annotations

from factory.precard.progress import normalize_stage


def item_key(item):
    """Vendored from factory/pipeline/card_pilot (provenance: precard
    line R1-R6, 2026-09-14) — "w:"+text for words, "p:"+text for
    phrases. Copied so this package imports nothing project-owned.
    Pilot-line copy at card_pilot.item_key kept by design until T6
    (identity-141 R5)."""
    return ("w:" if item["kind"] == "word" else "p:") + item["text"]


def audit_sample_accounting(items, precards, states):
    """Keys with neither a precard row nor a structured drop (R2).

    v14.1 fail-closed accounting: every sample key must resolve to >=1
    precard row or a drop verdict in s0 (kept False), s1 ("dropped"),
    s0b (not kept), or the s2 proper-drop marker. Returns the sorted
    list of unaccounted keys ([] = nothing vanished silently).
    Hostile inputs fail open to [] (the audit never crashes a run —
    the caller logs a non-empty result loudly).
    """
    try:
        rows_of = precards if isinstance(precards, dict) else {}
        raw_states = states if isinstance(states, dict) else {}
        # States may arrive keyed by legacy ids (old progress) or new
        # ids — normalize once, then read only real words below.
        states = {}
        for stage_key, bucket in raw_states.items():
            try:
                norm_key = normalize_stage(stage_key)
            except Exception:
                continue
            states.setdefault(norm_key, bucket)
        missing = []
        for item in items or []:
            try:
                key = item_key(item)
            except Exception:
                continue
            rows = rows_of.get(key)
            if isinstance(rows, dict):
                rows = [rows]
            if rows:
                continue
            accounted = False
            try:
                s0 = (states.get("preprocess") or {}).get("done", {})
                if isinstance(s0.get(key), dict) \
                        and not s0[key].get("kept", True):
                    accounted = True
                s1 = (states.get("anchor_rank") or {}).get("done", {})
                if isinstance(s1.get(key), dict) and s1[key].get("dropped"):
                    accounted = True
                s0b = (states.get("inflection_review") or {}).get("done", {})
                if isinstance(s0b.get(key), dict) \
                        and not s0b[key].get("kept", True):
                    accounted = True
                s2 = (states.get("sense_judge") or {}).get("done", {})
                if isinstance(s2.get(key), dict) \
                        and s2[key].get("proper_drop"):
                    accounted = True
            except Exception:
                pass
            if not accounted:
                missing.append(key)
        return sorted(set(missing))
    except Exception:
        return []
