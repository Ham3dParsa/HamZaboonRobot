"""AI preset registry, fallback state, and hourly usage."""

import datetime as _dt

from services.db.schema import get_conn, transaction, _utc_now
from services.db.settings import get_bool_setting, get_setting
from services.ai.ai_presets import resolve_api_key
from services.ai import preset_fields as _pf
from services.db.key_crypto import encrypt_for_storage


def get_presets() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM ai_presets ORDER BY name").fetchall()
    return [dict(row) for row in rows]


def get_preset(name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ai_presets WHERE name=?", (name,)).fetchone()
    return dict(row) if row else None


class NoActivePresetError(Exception):
    """Raised when no enabled preset exists to serve as the active AI preset."""


def get_active_preset_name() -> str:
    if get_bool_setting("ai_fallback_active", False):
        return get_setting("ai_fallback_preset", "") or (_first_enabled_name() or "")
    return get_setting("ai_primary_preset", "") or (_first_enabled_name() or "")


def get_active_preset() -> dict:
    """Return the active preset, raising rather than returning {} when none exists.

    No silent empty dict: callers that cannot fall back must surface the
    absence of an enabled preset as an explicit error (R10).
    """
    name = get_active_preset_name()
    preset = get_preset(name)
    if preset and _pf.resolve(preset, "enabled"):
        return preset
    name = _first_enabled_name()
    preset = get_preset(name)
    if preset and _pf.resolve(preset, "enabled"):
        return preset
    raise NoActivePresetError("no enabled AI preset available")


def set_preset(
    name: str,
    base_url: str = _pf.write_default("base_url"),
    model: str = _pf.write_default("model"),
    api_key: str = _pf.write_default("api_key"),
    daily_batch_size: int = _pf.write_default("daily_batch_size"),
    max_concurrency: int = _pf.write_default("max_concurrency"),
    max_rpm: int = _pf.write_default("max_rpm"),
    max_tpm: int = _pf.write_default("max_tpm"),
    max_daily_req: int = _pf.write_default("max_daily_req"),
    timeout_seconds: float = _pf.write_default("timeout_seconds"),
    temperature: float = _pf.write_default("temperature"),
    max_output_tokens: int = _pf.write_default("max_output_tokens"),
    is_emergency: int = _pf.write_default("is_emergency"),
    priority: int | None = None,
    enabled: int | None = None,
    input_cost_per_million: float | None = _pf.write_default("input_cost_per_million"),
    output_cost_per_million: float | None = _pf.write_default("output_cost_per_million"),
    in_fallback_chain: int = _pf.write_default("in_fallback_chain"),
    group_label: str = _pf.write_default("group_label"),
    *,
    previous_name: str | None = None,
    remove_orphaned_group_key: bool = False,
):
    with transaction() as conn:
        source_name = previous_name or name
        previous = conn.execute(
            "SELECT group_label FROM ai_presets WHERE name=?", (source_name,)
        ).fetchone()
        if previous_name and previous_name != name:
            collision = conn.execute(
                "SELECT 1 FROM ai_presets WHERE name=?", (name,)
            ).fetchone()
            if collision:
                raise ValueError(f"preset name already exists: {name}")
        # Encrypt at the write seam: an unchanged edit passes the token that
        # is already at rest (encrypt_for_storage is idempotent on Fernet
        # tokens), while a new plaintext key is encrypted before storing.
        stored_key = encrypt_for_storage(api_key)
        # On conflict, only overwrite priority/enabled when the caller
        # explicitly passes them (None = preserve the existing stored value,
        # so partial edits can't silently reset a preset's chain position or
        # re-enable a disabled preset). New rows use 0 / disabled-by-default.
        conflict_sets = [
            "base_url=excluded.base_url",
            "model=excluded.model",
            "api_key=excluded.api_key",
            "daily_batch_size=excluded.daily_batch_size",
            "max_concurrency=excluded.max_concurrency",
            "max_rpm=excluded.max_rpm",
            "max_tpm=excluded.max_tpm",
            "max_daily_req=excluded.max_daily_req",
            "timeout_seconds=excluded.timeout_seconds",
            "temperature=excluded.temperature",
            "max_output_tokens=excluded.max_output_tokens",
            "is_emergency=excluded.is_emergency",
            "in_fallback_chain=excluded.in_fallback_chain",
            "group_label=excluded.group_label",
        ]
        if priority is not None:
            conflict_sets.append("priority=excluded.priority")
        if enabled is not None:
            conflict_sets.append("enabled=excluded.enabled")
        if input_cost_per_million is not None:
            conflict_sets.append("input_cost_per_million=excluded.input_cost_per_million")
        if output_cost_per_million is not None:
            conflict_sets.append("output_cost_per_million=excluded.output_cost_per_million")
        conn.execute(
            "INSERT INTO ai_presets(name, base_url, model, api_key, daily_batch_size, max_concurrency, max_rpm, max_tpm, max_daily_req, timeout_seconds, temperature, max_output_tokens, is_emergency, priority, enabled, input_cost_per_million, output_cost_per_million, in_fallback_chain, group_label) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            f"ON CONFLICT(name) DO UPDATE SET {', '.join(conflict_sets)}",
            (
                name,
                base_url,
                model,
                stored_key,
                daily_batch_size,
                max_concurrency,
                max_rpm,
                max_tpm,
                max_daily_req,
                timeout_seconds,
                temperature,
                max_output_tokens,
                is_emergency,
                0 if priority is None else priority,
                1 if enabled is None else enabled,
                input_cost_per_million,
                output_cost_per_million,
                in_fallback_chain,
                group_label,
            ),
        )
        if previous_name and previous_name != name:
            conn.execute("DELETE FROM ai_presets WHERE name=?", (previous_name,))
        old_label = previous["group_label"] if previous else ""
        if remove_orphaned_group_key and old_label and old_label != group_label:
            remaining_member = conn.execute(
                "SELECT 1 FROM ai_presets WHERE group_label=? LIMIT 1",
                (old_label,),
            ).fetchone()
            if not remaining_member:
                conn.execute(
                    "DELETE FROM preset_groups WHERE group_label=?", (old_label,)
                )


def set_preset_api_key_batch(names: list[str], new_key: str):
    stored_key = encrypt_for_storage(new_key)
    with transaction() as conn:
        placeholders = ",".join("?" for _ in names)
        conn.execute(
            f"UPDATE ai_presets SET api_key=? WHERE name IN ({placeholders})",
            (stored_key, *names),
        )


def set_preset_group_label_batch(names: list[str], label: str):
    with transaction() as conn:
        placeholders = ",".join("?" for _ in names)
        conn.execute(
            f"UPDATE ai_presets SET group_label=? WHERE name IN ({placeholders})",
            (label, *names),
        )


def get_group_labels() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT group_label, COUNT(*) as count FROM ai_presets "
            "WHERE group_label != '' AND group_label IS NOT NULL "
            "GROUP BY group_label ORDER BY count DESC"
        ).fetchall()
        return [{"label": r["group_label"], "count": r["count"]} for r in rows]


def rename_group_label(old_label: str, new_label: str):
    if old_label == new_label:
        return
    with transaction() as conn:
        conn.execute(
            "UPDATE ai_presets SET group_label=? WHERE group_label=?",
            (new_label, old_label),
        )
        # Keep any shared group key consistent with the renamed label.
        # If the target label already owns a key, it wins (merge, keep target's
        # key); otherwise the source key carries over. Never crash on the PK.
        conn.execute(
            "INSERT OR IGNORE INTO preset_groups(group_label, api_key) "
            "SELECT ?, api_key FROM preset_groups WHERE group_label=?",
            (new_label, old_label),
        )
        conn.execute(
            "DELETE FROM preset_groups WHERE group_label=?",
            (old_label,),
        )


def clear_group_label(label: str):
    with transaction() as conn:
        conn.execute(
            "UPDATE ai_presets SET group_label='' WHERE group_label=?",
            (label,),
        )
        # Remove the now-orphaned shared group key (no preset references it).
        conn.execute(
            "DELETE FROM preset_groups WHERE group_label=?",
            (label,),
        )


# ---------- Group Shared Keys ----------

def set_group_key(label: str, api_key: str):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO preset_groups(group_label, api_key) VALUES (?, ?) "
            "ON CONFLICT(group_label) DO UPDATE SET api_key=excluded.api_key",
            (label, encrypt_for_storage(api_key)),
        )


def get_group_key(label: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT api_key FROM preset_groups WHERE group_label=?", (label,)
        ).fetchone()
    return row["api_key"] if row else None


def delete_group_key(label: str):
    with transaction() as conn:
        conn.execute("DELETE FROM preset_groups WHERE group_label=?", (label,))


def resolve_preset_key(preset: dict) -> str:
    """Resolve a preset's effective API key to a real plaintext value.

    Precedence: the preset's own `api_key` (if non-empty), else the shared key
    of its `group_label` (if the group has one), else empty. The chosen stored
    value is Fernet ciphertext (Phase 5) and is decrypted by `resolve_api_key`.
    Fail-closed: returns ``''`` if no key exists, the master key is missing, or
    the stored token cannot be decrypted. Backward-compatible: when a preset
    owns its key and no group key exists, this returns the same value as
    `resolve_api_key(preset)`.
    """
    raw = preset.get("api_key", "") or ""
    if not raw:
        label = preset.get("group_label", "") or ""
        if label:
            raw = get_group_key(label) or ""
    return resolve_api_key(raw)


def delete_preset(name: str) -> bool:
    with transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM ai_presets WHERE name=?", (name,)
        )
        conn.execute(
            "UPDATE settings SET value='' WHERE key='ai_fallback_preset' AND value=?",
            (name,),
        )
        conn.execute(
            "UPDATE settings SET value='' WHERE key='ai_primary_preset' AND value=?",
            (name,),
        )
        return cursor.rowcount > 0


def clone_preset(name: str, new_name: str) -> str:
    """Clone an existing preset to a new name, copying all fields except name.

    Raises ValueError if the source is missing or the target name already
    exists. The clone inherits the source's enabled/priority state so it can
    never start routing without an explicit owner choice.
    """
    src = get_preset(name)
    if not src:
        raise ValueError(f"source preset not found: {name}")
    if get_preset(new_name) is not None:
        raise ValueError(f"preset name already exists: {new_name}")
    field_names = (
        "base_url", "model", "api_key", "daily_batch_size", "max_concurrency",
        "max_rpm", "max_tpm", "max_daily_req", "timeout_seconds", "temperature",
        "max_output_tokens", "is_emergency", "priority", "enabled",
        "input_cost_per_million", "output_cost_per_million", "in_fallback_chain",
        "group_label",
    )
    with transaction() as conn:
        placeholders = ", ".join("?" for _ in field_names)
        columns = ", ".join(field_names)
        values = [src.get(f) for f in field_names]
        conn.execute(
            f"INSERT INTO ai_presets(name, {columns}) VALUES (?, {placeholders})",
            (new_name, *values),
        )
    return new_name


def activate_preset(name: str) -> bool:
    preset = get_preset(name)
    if not preset:
        return False
    with transaction() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_primary_preset", name),
        )
        if preset.get("base_url"):
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_base_url", preset["base_url"]),
            )
        if preset.get("model"):
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_model", preset["model"]),
            )
        if preset.get("api_key"):
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_api_key", preset["api_key"]),
            )
    return True


# ---------- Preset Cost ----------

def get_preset_cost(preset_name: str) -> dict:
    preset = get_preset(preset_name)
    if not preset:
        return {"input_cost_per_million": None, "output_cost_per_million": None}
    return {
        "input_cost_per_million": preset.get("input_cost_per_million"),
        "output_cost_per_million": preset.get("output_cost_per_million"),
    }


# ---------- Fallback State Management ----------

def set_fallback_active(active: bool, fallback_preset: str | None = None):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_fallback_active", "true" if active else "false"),
        )
        if active:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_fallback_since", _utc_now().isoformat()),
            )
            if fallback_preset:
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("ai_fallback_preset", fallback_preset),
                )
        else:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_fallback_since", ""),
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_consecutive_failures", "0"),
            )


def increment_consecutive_failures() -> int:
    with transaction() as conn:
        current = int(get_setting("ai_consecutive_failures", "0")) + 1
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_consecutive_failures", str(current)),
        )
        return current


def reset_consecutive_failures():
    with transaction() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_consecutive_failures", "0"),
        )


def _first_enabled_name() -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM ai_presets WHERE enabled=1 AND is_emergency=0 ORDER BY priority ASC, name ASC LIMIT 1"
        ).fetchone()
    return row["name"] if row else None


def get_fallback_status() -> dict:
    return {
        "fallback_active": get_bool_setting("ai_fallback_active", False),
        "primary_preset": get_setting("ai_primary_preset", _first_enabled_name()),
        "fallback_preset": get_setting("ai_fallback_preset", "") or (_first_enabled_name() or ""),
        "fallback_since": get_setting("ai_fallback_since", ""),
        "consecutive_failures": int(get_setting("ai_consecutive_failures", "0")),
    }


# ---------- Preset Hourly Usage ----------

def get_hourly_usage(preset_name: str, hours_back: int = 24) -> tuple[int, int]:
    cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours_back)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(request_count), 0) req, COALESCE(SUM(token_count), 0) tok "
            "FROM preset_hourly_usage WHERE preset_name=? AND hour_bucket >= ?",
            (preset_name, cutoff[:13]),
        ).fetchone()
    return (row["req"], row["tok"])


def get_hourly_usage_many(names: list[str], hours_back: int = 24) -> dict[str, tuple[int, int]]:
    """Return the 24h usage for many presets in one query (BOT-3, N+1 fix).

    Reduces the per-preset ``get_hourly_usage`` loop on the AI hot path to a
    single batched read. Presets with no rows report ``(0, 0)``. The existing
    single-preset ``get_hourly_usage`` is unchanged for other callers.
    """
    if not names:
        return {}
    cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours_back)).isoformat()
    placeholders = ",".join("?" for _ in names)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT preset_name, "
            "COALESCE(SUM(request_count), 0) AS req, "
            "COALESCE(SUM(token_count), 0) AS tok "
            "FROM preset_hourly_usage "
            f"WHERE preset_name IN ({placeholders}) AND hour_bucket >= ? "
            "GROUP BY preset_name",
            (*names, cutoff[:13]),
        ).fetchall()
    result: dict[str, tuple[int, int]] = {name: (0, 0) for name in names}
    for row in rows:
        result[row["preset_name"]] = (row["req"], row["tok"])
    return result


def prune_preset_hourly_usage(hours_back: int = 24):
    """Delete preset_hourly_usage rows older than a rolling window (R13).

    Keeping only the last `hours_back` hours bounds the RPD accounting so stale
    rows never hold the per-preset daily cap open or closed wrongly.
    """
    cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours_back)).isoformat()
    with transaction() as conn:
        conn.execute(
            "DELETE FROM preset_hourly_usage WHERE hour_bucket < ?",
            (cutoff[:13],),
        )


def increment_hourly_usage(preset_name: str, hour_bucket: str, req_count: int = 1, token_count: int = 0):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO preset_hourly_usage(preset_name, hour_bucket, request_count, token_count) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(preset_name, hour_bucket) DO UPDATE SET "
            "request_count=request_count+excluded.request_count, "
            "token_count=token_count+excluded.token_count",
            (preset_name, hour_bucket, req_count, token_count),
        )


# ---------- Preset Management ----------

def get_enabled_presets_ordered() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_presets WHERE enabled=1 ORDER BY is_emergency ASC, priority ASC, name ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_fallback_chain_presets() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_presets WHERE enabled=1 AND in_fallback_chain=1 "
            "ORDER BY is_emergency ASC, priority ASC, name ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def reindex_preset_priority(name: str, target_rank: int, group_is_emergency: bool):
    target_idx = target_rank - 1
    with transaction() as conn:
        rows = conn.execute(
            "SELECT name, priority FROM ai_presets "
            "WHERE enabled=1 AND is_emergency=? AND in_fallback_chain=1 "
            "ORDER BY priority ASC, name ASC",
            (1 if group_is_emergency else 0,),
        ).fetchall()

        count = len(rows)
        if not (1 <= target_rank <= count):
            raise ValueError(f"target_rank {target_rank} out of range [1, {count}]")

        names = [r["name"] for r in rows]
        current_idx = names.index(name) if name in names else -1
        if current_idx == -1:
            raise ValueError(f"preset {name} not found in group")
        if current_idx == target_idx:
            return

        item = rows.pop(current_idx)
        rows.insert(target_idx, item)

        for i, row in enumerate(rows):
            conn.execute(
                "UPDATE ai_presets SET priority=? WHERE name=?",
                (i, row["name"]),
            )


def set_preset_priority(name: str, priority: int):
    with transaction() as conn:
        conn.execute("UPDATE ai_presets SET priority=? WHERE name=?", (priority, name))


def set_preset_enabled(name: str, enabled: bool):
    want = 1 if enabled else 0
    with transaction() as conn:
        if not enabled:
            # Only refuse when disabling would leave the target as the sole
            # remaining enabled preset. Exclude the target itself so a no-op
            # disable (already disabled / nonexistent) never faults.
            remaining = conn.execute(
                "SELECT COUNT(*) AS c FROM ai_presets WHERE enabled=1 AND name != ?",
                (name,),
            ).fetchone()["c"]
            if remaining <= 0:
                raise ValueError("cannot disable the last enabled preset")
        conn.execute("UPDATE ai_presets SET enabled=? WHERE name=?", (want, name))


def set_preset_emergency(name: str, is_emergency: bool):
    with transaction() as conn:
        conn.execute("UPDATE ai_presets SET is_emergency=? WHERE name=?", (1 if is_emergency else 0, name))


def insert_preset_at_rank(name: str, target_rank: int, *, as_emergency: bool = False):
    """Place an existing preset so it occupies ``target_rank`` among the enabled
    normal (non-emergency) in-fallback-chain presets, densifying the group.

    Used by the R14 create flow so "top"/"bottom"/manual-value always yield the
    intended fallback-chain position with dense priorities (0,1,2,...). The
    preset row MUST already exist (the caller creates it first via ``set_preset``);
    this function only renumbers the existing enabled normal group so the target
    preset ends up at exactly ``target_rank`` (0-based). The target may be
    disabled at insert time; it is still placed at the requested rank so enabling
    it later routes it there.
    Emergency rows are never renumbered here.
    """
    with transaction() as conn:
        rows = conn.execute(
            "SELECT name FROM ai_presets "
            "WHERE enabled=1 AND is_emergency=? AND in_fallback_chain=1 "
            "ORDER BY priority ASC, name ASC",
            (1 if as_emergency else 0,),
        ).fetchall()
        names = [r["name"] for r in rows if r["name"] != name]
        count = len(names)
        if not (0 <= target_rank <= count):
            raise ValueError(f"target_rank {target_rank} out of range [0, {count}]")

        names.insert(target_rank, name)
        for i, n in enumerate(names):
            conn.execute(
                "UPDATE ai_presets SET priority=? WHERE name=?",
                (i, n),
            )
