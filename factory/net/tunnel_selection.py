"""Permanent provider-aware tunnel-selection seam (Wave 0 / T1 skeleton).

One module, one fix point: callers and tests cross the three-method seam
(select / prove / remember) plus exactly two adapters (SubscriptionSource,
ProviderProbe). Ping, dedup, latency ranking and cache writers stay internal
(T2/T3 own them). Paid-first ordering is recorded as a source tag only —
never subscription values. Batch/keep arrive as injected defaults with
override; the body never hardcodes them. The store is one file keyed by
provider (T2 implements it); rows carry id + timing only.
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

# Env names only (never values): the subscription/TTL/cache-path knobs this
# module may resolve. Values stay in the environment; tests use fakes + tmp
# files and never touch the real env.
SUB_URL_VAR = "EGRESS_SUB_URL"
SUB_URLS_VAR = "EGRESS_SUB_URLS"
CLEAN_TTL_VAR = "EGRESS_CLEAN_TTL"
CLEAN_CACHE_PATH_VAR = "EGRESS_CLEAN_CACHE_PATH"

# Injected numeric caps (defaults with override on the store ctor body):
# TTL window for one provider namespace; max rows kept per provider.
DEFAULT_TTL_SECONDS = 86400.0
DEFAULT_MAX_ROWS = 20

# Paid-first is recorded as a source tag only ("paid" vs anything else).
# Subscription values (URLs, tokens, keys) never enter rows or selections.
PAID_SOURCE_TAG = "paid"


class NoTunnelExit(Exception):
    """Honest park: no usable exit available. Never invent an exit."""


@dataclass(frozen=True)
class Selection:
    exit_id: str
    lease: Any = None
    whitelisted: bool = False
    served_from: str = ""


@dataclass(frozen=True)
class Proof:
    clean: list = field(default_factory=list)
    blocked: list = field(default_factory=list)
    unknown: list = field(default_factory=list)


class SubscriptionSource(ABC):
    """Subscription refresh adapter. Returns rows with id + source tag only."""

    @abstractmethod
    def refresh(self) -> list:
        """Refresh proxy subscriptions, deduped, paid-first. No values leak."""
        raise NotImplementedError


class ProviderProbe(ABC):
    """Per-provider probe shape behind one Proof contract."""

    @abstractmethod
    def probe(self, exit_id: str) -> str:
        """Return one of clean / blocked / unknown. Transport error=unknown."""
        raise NotImplementedError


class KeylessGoogleProbe(ProviderProbe):
    """Keyless Google probe shape (free check, never billed).

    ``check_fn(exit_id)`` executes the single keyless check and returns a
    verdict string (tests inject fakes — no network here). ``None`` reads
    as "unknown" (honest park, never invent a verdict). Transport
    exceptions map to "unknown", never "blocked". Carries no key
    material — name or value.
    """

    def __init__(self, check_fn: Any = None) -> None:
        if check_fn is not None and not callable(check_fn):
            raise TypeError("check_fn must be callable or None")
        self._check_fn = check_fn

    def probe(self, exit_id: str) -> str:
        if self._check_fn is None:
            return "unknown"
        try:
            verdict = self._check_fn(exit_id)
        except Exception:
            return "unknown"
        if verdict == "clean":
            return "clean"
        if verdict == "blocked":
            return "blocked"
        return "unknown"


class KeyedProviderProbe(ProviderProbe):
    """Keyed second-provider probe shape (key NAME only, never the value).

    Same verdict contract as :class:`KeylessGoogleProbe`; ``key_name`` is
    the key VAR NAME for receipts/diagnostics (secret values never enter
    this module). ``check_fn``/``None``/exception semantics match the
    keyless shape exactly — the two shapes differ only in key discipline.
    """

    def __init__(self, key_name: str = "", check_fn: Any = None) -> None:
        if not isinstance(key_name, str):
            raise TypeError("key_name must be a string (name only, never a value)")
        if check_fn is not None and not callable(check_fn):
            raise TypeError("check_fn must be callable or None")
        self.key_name = key_name
        self._check_fn = check_fn

    def probe(self, exit_id: str) -> str:
        if self._check_fn is None:
            return "unknown"
        try:
            verdict = self._check_fn(exit_id)
        except Exception:
            return "unknown"
        if verdict == "clean":
            return "clean"
        if verdict == "blocked":
            return "blocked"
        return "unknown"


def _row_id(row: Any) -> str:
    """Best-effort id extraction: Mapping id, .id attr, or bare string."""
    if isinstance(row, str):
        return row
    if isinstance(row, Mapping):
        value = row.get("id", "")
        return value if isinstance(value, str) else ""
    value = getattr(row, "id", "")
    return value if isinstance(value, str) else ""


def _row_source(row: Any) -> str:
    """Source tag only (paid vs rest). Never subscription values."""
    if isinstance(row, Mapping):
        value = row.get("source", "")
    else:
        value = getattr(row, "source", "")
    return value.lower() if isinstance(value, str) else ""


def dedup_rows(rows: list) -> list:
    """Collapse to first occurrence per non-empty id, order preserved."""
    seen: set[str] = set()
    out: list = []
    for row in rows or []:
        exit_id = _row_id(row)
        if not exit_id or exit_id in seen:
            continue
        seen.add(exit_id)
        out.append(row)
    return out


def order_paid_first(rows: list) -> list:
    """Stable paid-first partition on the source tag. No values inspected."""
    paid = [r for r in rows or [] if _row_source(r) == PAID_SOURCE_TAG]
    rest = [r for r in rows or [] if _row_source(r) != PAID_SOURCE_TAG]
    return paid + rest


def clean_ttl_from_env(default: float = DEFAULT_TTL_SECONDS) -> float:
    """TTL float from the EGRESS_CLEAN_TTL name; garbage falls back."""
    try:
        value = float(os.environ.get(CLEAN_TTL_VAR, "") or 0)
    except (TypeError, ValueError):
        return default
    if not (value > 0) or not (value < float("inf")):
        return default
    return value


def clean_cache_path_from_env(default: str = "") -> str:
    """Cache path from the EGRESS_CLEAN_CACHE_PATH name; never empty."""
    try:
        raw = (os.environ.get(CLEAN_CACHE_PATH_VAR, "") or "").strip()
    except AttributeError:
        raw = ""
    return raw or default


class ProviderCacheStore:
    """One cache file keyed by provider (never global, never one file each).

    Layout: one JSON object ``{provider: {"saved_at": float, "rows": [...]}}``.
    Cache rows carry id + timing only (source tags and subscription values
    are stripped on write). TTL and row caps are injected defaults with
    override; IO is best-effort (errors read as miss, writes never raise).
    """

    def __init__(
        self,
        path: Any,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        if not isinstance(path, (str, os.PathLike)):
            raise TypeError("path must be a string or path-like")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not isinstance(ttl_seconds, (int, float)) or not (
            ttl_seconds > 0 and ttl_seconds < float("inf")
        ):
            raise ValueError("ttl_seconds must be a finite positive number")
        if not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows < 1:
            raise ValueError("max_rows must be an int >= 1")
        self._path = str(path)
        self._clock = clock
        self._ttl = float(ttl_seconds)
        self._max_rows = max_rows

    @property
    def path(self) -> str:
        return self._path

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    @property
    def max_rows(self) -> int:
        return self._max_rows

    def _load(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def read(self, provider: str) -> list:
        if not isinstance(provider, str):
            raise TypeError("provider must be a string")
        if not provider:
            return []
        data = self._load()
        entry = data.get(provider)
        if not isinstance(entry, Mapping):
            return []
        saved_at = entry.get("saved_at")
        if not isinstance(saved_at, (int, float)):
            return []
        try:
            now = float(self._clock())
        except Exception:
            return []
        if now - float(saved_at) > self._ttl:
            return []
        rows = entry.get("rows")
        if not isinstance(rows, list):
            return []
        cleaned: list = []
        for row in rows:
            exit_id = _row_id(row)
            if not exit_id:
                continue
            latency = row.get("latency_ms", 0.0) if isinstance(row, Mapping) else 0.0
            try:
                latency_ms = float(latency)
            except (TypeError, ValueError):
                latency_ms = 0.0
            cleaned.append({"id": exit_id, "latency_ms": latency_ms})
        return cleaned

    def write(self, provider: str, rows: list) -> None:
        if not isinstance(provider, str):
            raise TypeError("provider must be a string")
        if not provider:
            return
        if not rows:
            return  # never-overwrite-with-empty: never touch the file
        cleaned: list = []
        seen: set[str] = set()
        for row in rows:
            exit_id = _row_id(row)
            if not exit_id or exit_id in seen:
                continue
            seen.add(exit_id)
            latency = row.get("latency_ms", 0.0) if isinstance(row, Mapping) else 0.0
            try:
                latency_ms = float(latency)
            except (TypeError, ValueError):
                latency_ms = 0.0
            cleaned.append({"id": exit_id, "latency_ms": latency_ms})
        if not cleaned:
            return
        cleaned = cleaned[: self._max_rows]
        try:
            data = self._load()
            try:
                saved_at = float(self._clock())
            except Exception:
                saved_at = 0.0
            data[provider] = {"saved_at": saved_at, "rows": cleaned}
            parent = os.path.dirname(os.path.abspath(self._path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp_path = self._path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            os.replace(tmp_path, self._path)
        except (OSError, ValueError, TypeError):
            return


class TunnelSelector:
    """Three-method seam. Constructor performs zero network/file/key access."""

    def __init__(
        self,
        *,
        subs: SubscriptionSource,
        probes: Mapping[str, ProviderProbe],
        store: Any,
        clock: Callable[[], float] = time.time,
        batch: int = 5,
        keep: int = 5,
        ping_budget: Any = None,
    ) -> None:
        if not isinstance(probes, Mapping):
            raise TypeError("probes must be a mapping of provider to probe")
        for provider, probe in probes.items():
            if not isinstance(probe, ProviderProbe):
                raise TypeError(
                    "probe for %r must implement ProviderProbe" % (provider,)
                )
        if not isinstance(batch, int) or not isinstance(keep, int):
            raise TypeError("batch and keep must be ints")
        self._subs = subs
        self._probes = dict(probes)
        self._store = store
        self._clock = clock
        self._batch = batch
        self._keep = keep
        self._ping_budget = ping_budget

    @property
    def batch(self) -> int:
        return self._batch

    @property
    def keep(self) -> int:
        return self._keep

    def select(self, provider: str) -> Selection:
        """Serve a fresh per-provider cache hit; else paid-first refresh.

        Cache hit: first row id, whitelisted, served_from cache, no refresh.
        Miss/stale: refresh subs, dedup + paid-first, serve the first id as
        a non-whitelisted subscription candidate. Empty everywhere raises
        NoTunnelExit. Never writes the cache (remember stabilizes) and never
        probes (T3 owns prove).
        """
        if not isinstance(provider, str):
            raise TypeError("provider must be a string")
        if not provider:
            raise NoTunnelExit(provider)
        try:
            cached = self._store.read(provider) or []
        except Exception:
            cached = []
        for row in cached:
            exit_id = _row_id(row)
            if exit_id:
                return Selection(
                    exit_id=exit_id,
                    lease=None,
                    whitelisted=True,
                    served_from="cache",
                )
        try:
            raw = self._subs.refresh()
        except Exception:
            raise NoTunnelExit(provider)
        ordered = order_paid_first(dedup_rows(list(raw or [])))
        for row in ordered:
            exit_id = _row_id(row)
            if exit_id:
                return Selection(
                    exit_id=exit_id,
                    lease=None,
                    whitelisted=False,
                    served_from="subscription",
                )
        raise NoTunnelExit(provider)

    def prove(self, provider: str, exits: list) -> Proof:
        """Batch loop (T3): at most `batch` probes per batch in priority order.

        Stops early once `keep` clean is met (even mid-batch). Transport
        errors map to unknown, never blocked. Reads nothing and writes
        nothing outside the injected probe: no store, no subscription
        refresh. Input order is the priority order.
        """
        probe = self._probes.get(provider)
        if probe is None:
            raise NoTunnelExit(provider)
        batch = self._batch
        keep = self._keep
        clean: list = []
        blocked: list = []
        unknown: list = []
        total = len(exits) if exits else 0
        if keep <= 0 or total == 0:
            return Proof(clean=clean, blocked=blocked, unknown=unknown)
        width = batch if batch > 0 else total
        idx = 0
        while idx < total and len(clean) < keep:
            for exit_id in exits[idx : idx + width]:
                if len(clean) >= keep:
                    break
                try:
                    verdict = probe.probe(exit_id)
                except Exception:
                    verdict = "unknown"
                if verdict == "clean":
                    clean.append(exit_id)
                elif verdict == "blocked":
                    blocked.append(exit_id)
                else:
                    unknown.append(exit_id)
            idx += width
        return Proof(clean=clean, blocked=blocked, unknown=unknown)

    def remember(self, provider: str, exit_id: str, latency_ms: float) -> None:
        """Best-effort stabilize hook. Empty input never touches the store.

        Upserts the exit at the front of its provider namespace (recency
        order), deduped by id; the store caps rows and strips everything but
        id + timing. IO errors never propagate.
        """
        if not isinstance(provider, str) or not isinstance(exit_id, str):
            raise TypeError("provider and exit_id must be strings")
        if not exit_id:
            return
        if not isinstance(latency_ms, (int, float)):
            raise TypeError("latency_ms must be numeric")
        try:
            row = {"id": exit_id, "latency_ms": float(latency_ms)}
        except (TypeError, ValueError):
            raise TypeError("latency_ms must be numeric")
        try:
            try:
                existing = self._store.read(provider) or []
            except Exception:
                existing = []
            merged = [row] + [r for r in existing if _row_id(r) != exit_id]
            self._store.write(provider, merged)
        except Exception:
            return
        return None
