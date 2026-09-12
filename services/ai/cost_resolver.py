"""Cost resolution + client pool-key helpers for the AI hot path (REF5-T5).

Owns the chain/cost read pattern ONLY:
- ``resolve_costs``: preset-dict-first -> global profile fallback, verbatim
  from ``telemetry._log_llm_request`` (the preset came from the chain/active
  read, so no re-query; the profile read is TTL-cached + invalidatable).
- ``client_pool_key``: pure pooling identity
  ``(name, base_url, model, timeout, proxy, generation)`` — carries NO key
  material and is never logged (plaintext-key caching is forbidden).

Explicit NON-GOAL (rejected-deferred, valid outcome): NO name/group-key
cache. Caching resolved plaintext keys would pin stale credentials across
the 7 key-mutation seams without invalidation + switching tests:
``set_preset`` (api_key write), ``set_preset_api_key_batch``,
``set_group_key``, ``delete_group_key``, ``set_preset_group_label_batch``
(label move across groups), ``delete_preset``/``clone_preset`` (row
lifecycle), and enable/priority/chain edits that change which preset a name
resolves to. Until per-seam invalidation + switching tests land, key
resolution stays uncached via ``db.resolve_preset_key`` (fail-closed).
"""

from __future__ import annotations

from typing import Any


def resolve_costs(
    preset: dict[str, Any] | None,
    profile: dict[str, float],
) -> tuple[float, float, float]:
    """Return ``(input_per_m, output_per_m, usd_to_toman_rate)``.

    Preset-dict-first: a non-None per-million value on the preset row wins;
    otherwise the global profile value applies. ``preset=None`` resolves fully
    from the profile. Pure (no I/O, no logging, no key material).
    """
    if preset:
        input_cost = preset.get("input_cost_per_million")
        output_cost = preset.get("output_cost_per_million")
    else:
        input_cost = None
        output_cost = None
    input_per_m = input_cost if input_cost is not None else profile["input_cost_usd_per_million"]
    output_per_m = output_cost if output_cost is not None else profile["output_cost_usd_per_million"]
    return (input_per_m, output_per_m, profile["usd_to_toman_rate"])


def client_pool_key(
    preset: dict[str, Any],
    *,
    proxy: str | None = None,
    generation: int = 0,
) -> tuple[str, str, str, Any, str, int]:
    """Return the client-pool identity for a preset (no key material).

    ``(name, base_url, model, timeout, proxy, generation)``: any preset edit
    to the pooled surface changes the key, so an edited preset never reuses a
    pooled client built from stale values. ``proxy`` defaults to the
    env-driven ``AI_PROXY_URL`` (lazy import keeps this module side-effect
    free); ``generation`` is an explicit bust token (default 0) for a future
    preset-version column. ``api_key``/``group_label`` are deliberately
    excluded — pooling must never key on or retain secrets.
    """
    if proxy is None:
        from config import AI_PROXY_URL as _proxy

        proxy = _proxy
    return (
        str(preset.get("name", "")),
        str(preset.get("base_url", "")),
        str(preset.get("model", "")),
        preset.get("timeout_seconds", ""),
        str(proxy or ""),
        int(generation),
    )
