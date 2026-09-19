"""Single rotation helper over the net leg policy (T-RUN-E).

Pure resolution of the walk every R6 leg repeats: ordered providers,
per-provider models, ring, target, key_var — plus the cooldown-walk
decision. Read-only over factory.precard.net policy (switch_plan /
leg_chain / target_for / norm_provider); no I/O, no network, no keys.

Legs (judge inflection_review/sense_judge, topics topic_label/
topic_vectors) keep prompt building, validation, telemetry, and terminal
semantics; they iterate the plan instead of recomputing it. No policy,
model, prompt, or cost change — byte-identical behavior by construction.
"""

from __future__ import annotations

from factory.precard import net as _net


def plan(leg, provider, base_models, rings, ring, key_var):
    """Resolve one leg's walk.

    Returns (base_provider, steps) where each step is a dict with
    provider / models / ring / target / key_var. ``base_models``
    (explicit per-leg override) wins only on the base provider; other
    providers walk their net-table chain. Providers without a ring are
    not attempted. Unknown legs raise via net policy (ValueError).
    """
    base_provider = _net.norm_provider(provider) or "avalai"
    # Raw provider goes to switch_plan (not the normalized base): net
    # normalizes internally, and for falsy input the empty walk (no
    # providers) is preserved exactly as the inline legs produced it.
    ordered = [p for p in _net.switch_plan(provider, leg)
               if p == base_provider
               or (rings is not None and p in rings)]
    steps = []
    for eff in ordered:
        models = (list(base_models)
                  if base_models is not None and eff == base_provider
                  else _net.leg_chain(eff, leg))
        steps.append({
            "provider": eff,
            "models": models,
            "ring": (rings or {}).get(eff) or ring,
            "target": _net.target_for(eff),
            "key_var": key_var if eff == base_provider else "",
        })
    return base_provider, steps


def cooldown_continues(ordered, eff_idx):
    """True when a cooled provider has a next provider to continue on.

    R6 rule: a free-leg cooldown moves to the next provider's chain;
    the last — or any paid — provider stops loud (the leg raises).
    """
    return eff_idx + 1 < len(ordered)
