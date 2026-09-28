"""Dynamic provider manifest (ticket one): data-driven provider rows + N-key storage.

Single owner of the persisted provider manifest. Providers are DATA rows in
a JSON file, never Python edits: the stable store lives at the data-drive
path (``HAMZABAN_DATA_ROOT`` via ``factory.core.env_loader.data_root``)
with a safe repo-local fallback beside this module. First run seeds the
four core providers (avalai/google/openrouter/groq); deletions persist via
an explicit ``removed`` set so a removed default stays gone and is never
re-seeded.

Key storage is indexed and N-wide: ``{PROVIDER}_API_KEY_{N}`` (1-based).
Legacy group names map 1:1 (G1 -> 1, G2 -> 2) for compatibility. Each
provider row keeps its full ordered ``key_vars`` name list; values are
never stored here — :func:`ordered_key_values` resolves them in memory
only (process env -> factory env files -> operator store when given).

Secret rule: names and counts only ever leave this module. Values appear
only in the in-memory return of ``ordered_key_values`` (never logged,
never persisted, never embedded in errors).
"""

from __future__ import annotations

import ipaddress
import json
import os
import pathlib
import re
import time
import urllib.parse

MANIFEST_FILENAME = "provider_manifest.json"

PROTOCOLS = ("openai_compat", "gemini_rest")
ROUTES = ("direct", "tunnel")

#: Provider kinds (form-level concept, stored on the row): ``local``
#: (this machine only, keyless) vs ``cloud`` (internet service, keyed).
#: Kind decides which base_url hosts are acceptable — security by
#: construction for local rows (loopback-only ⇒ no SSRF surface).
KINDS = ("local", "cloud")

_NAME_RX = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_KEY_VAR_RX = re.compile(r"^[A-Z][A-Z0-9_]*_API_KEY(_[A-Z0-9]+)?$")

#: Canonical first-run seed (single owner — the registry reads it,
#: never a second copy). After seeding, the FILE is authoritative —
#: adding a provider is a data write, never a Python edit.
SEED_PROVIDERS = {
    "avalai": {
        "protocol": "openai_compat",
        "base_url": "https://api.avalai.ir/v1/chat/completions",
        "route": "direct",
        "key_vars": ["AVALAI_API_KEY_G1", "AVALAI_API_KEY_G2",
                     "AVALAI_API_KEY"],
        "request_extras": {
            "reasoning_effort": "low",
            "extra_body": {"reasoning_effort": "low"},
        },
    },
    "google": {
        "protocol": "gemini_rest",
        "base_url": None,
        "route": "tunnel",
        "key_vars": ["GOOGLE_API_KEY_G1", "GOOGLE_API_KEY_G2",
                     "GOOGLE_AI_API_KEY"],
        "request_extras": {},
    },
    "openrouter": {
        "protocol": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "route": "tunnel",
        "key_vars": ["OPENROUTER_API_KEY_G1", "OPENROUTER_API_KEY_G2",
                     "OPENROUTER_API_KEY", "OPENROUTER_API_KEY_2"],
        "request_extras": {},
    },
    "groq": {
        "protocol": "openai_compat",
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "route": "direct",
        "key_vars": ["GROQ_API_KEY_G1", "GROQ_API_KEY_G2", "GROQ_API_KEY"],
        "request_extras": {},
    },
}

#: Legacy group slot -> 1-based index (compatibility only).
LEGACY_GROUP_INDEX = {"G1": 1, "G2": 2}


def norm_name(name):
    """Canonical provider key: lowercase, stripped ("" when absent)."""
    return str(name or "").strip().lower()


def legacy_group_to_index(group):
    """Map a legacy group label (G1/G2, case-insensitive, bare 1/2) to index."""
    text = str(group or "").strip().upper()
    if text in LEGACY_GROUP_INDEX:
        return LEGACY_GROUP_INDEX[text]
    if text.isdigit() and int(text) >= 1:
        return int(text)
    if text.startswith("G") and text[1:].isdigit() and int(text[1:]) >= 1:
        return int(text[1:])
    return 1


def indexed_key_var(provider, index):
    """Convention key var NAME for (provider, 1-based index). Names only."""
    stem = re.sub(r"[^A-Z0-9]+", "_", str(provider or "").strip().upper())
    stem = stem.strip("_")
    if not stem:
        return ""
    try:
        idx = int(index)
    except (TypeError, ValueError, OverflowError):
        idx = 1
    if idx < 1:
        idx = 1
    return "%s_API_KEY_%d" % (stem, idx)


def _fallback_path():
    return str(pathlib.Path(__file__).resolve().parent / MANIFEST_FILENAME)


def manifest_primary_path():
    """Stable data-drive path (HAMZABAN_DATA_ROOT, else repo data/)."""
    try:
        from factory.core.env_loader import data_root
        root = data_root()
    except Exception:
        root = ""
    if not root:
        return _fallback_path()
    return str(pathlib.Path(str(root)) / MANIFEST_FILENAME)


def manifest_paths(explicit=None):
    """[primary, fallback] storage paths (explicit first when given)."""
    if explicit:
        return [str(explicit), _fallback_path()]
    primary = manifest_primary_path()
    fallback = _fallback_path()
    if primary == fallback:
        return [primary]
    return [primary, fallback]


def _base_host(base_url):
    """Lowercased hostname of a base_url ("" when unparsable)."""
    try:
        return (urllib.parse.urlsplit(str(base_url or "").strip())
                .hostname or "").lower()
    except ValueError:
        return ""


def is_loopback_host(host):
    """True for localhost names + loopback IPs (local-model scope)."""
    text = str(host or "").strip().lower()
    if not text:
        return False
    if text == "localhost" or text.endswith(".localhost"):
        return True
    try:
        return bool(ipaddress.ip_address(text).is_loopback)
    except ValueError:
        return False


def infer_kind(row):
    """Kind from the row's base_url (loopback → local, else cloud).

    Keyless service rows without a base (``gemini_rest`` style) infer
    ``cloud`` — they are keyed internet services, never local models.
    """
    host = _base_host((row or {}).get("base_url"))
    if host and is_loopback_host(host):
        return "local"
    return "cloud"


def base_host_allowed(base_url):
    """True when a provider base_url host is acceptable (SSRF guard).

    Literal IPs must be loopback (local models: LM Studio/Ollama) or
    globally routable; private/link-local/reserved literals are refused
    (no metadata/internal targets from this LAN-visible console).
    ``localhost`` names are always allowed; other DNS names pass here
    (no blocking DNS lookup in the request path — resolution-time
    rebinding stays a documented trusted-LAN-operator risk).
    """
    try:
        host = (urllib.parse.urlsplit(str(base_url or "").strip())
                .hostname or "")
    except ValueError:
        return False
    if not host:
        return False
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return True
    return bool(addr.is_loopback or addr.is_global)


def validate_row(name, row):
    """Validate a provider data row; (ok, error). Names only in errors."""
    want = norm_name(name)
    if not want or not _NAME_RX.match(want):
        return False, "provider name must be [a-z0-9_-] (got %r)" % (name,)
    if not isinstance(row, dict):
        return False, "provider row for %s must be an object" % want
    protocol = str(row.get("protocol") or "")
    if protocol not in PROTOCOLS:
        return False, "provider %s: protocol must be one of %s" % (
            want, "/".join(PROTOCOLS))
    route = str(row.get("route") or "")
    if route not in ROUTES:
        return False, "provider %s: route must be direct|tunnel" % want
    base_url = row.get("base_url")
    if base_url is not None and str(base_url).strip():
        text = str(base_url).strip()
        if not (text.startswith("https://") or text.startswith("http://")):
            return False, "provider %s: base_url must be http(s) or empty" % want
        if not base_host_allowed(text):
            return False, ("provider %s: base_url host is not allowed "
                           "(loopback, localhost, or public IP/hostname "
                           "only)" % want)
    kind = str(row.get("kind") or "").strip().lower() or infer_kind(row)
    if kind not in KINDS:
        return False, "provider %s: kind must be local|cloud" % want
    host = _base_host(base_url)
    if kind == "local":
        if protocol != "openai_compat":
            return False, ("provider %s: local kind needs the "
                           "openai_compat protocol" % want)
        if not host or not is_loopback_host(host):
            return False, ("provider %s: local kind accepts loopback/ "
                           "localhost endpoints only" % want)
        if str(row.get("route") or "") != "direct":
            return False, ("provider %s: local kind needs the direct "
                           "route" % want)
        # NOTE: key_vars stay ALLOWED on local rows (backward compatible):
        # loopback-only addressing already kills the SSRF class, and a
        # key reference is legitimately needed for key-gated listing.
        # The form simply sends none.
    else:
        if protocol == "openai_compat" and host:
            if not str(base_url).strip().startswith("https://"):
                return False, ("provider %s: cloud kind needs an https "
                               "base_url" % want)
            if is_loopback_host(host):
                return False, ("provider %s: cloud kind cannot point at "
                               "loopback (use kind local)" % want)
    key_vars = row.get("key_vars", [])
    if not isinstance(key_vars, (list, tuple)):
        return False, "provider %s: key_vars must be a list" % want
    for var in key_vars:
        if not isinstance(var, str) or not _KEY_VAR_RX.match(var.strip().upper()):
            return False, "provider %s: bad key var name" % want
    extras = row.get("request_extras", {})
    if not isinstance(extras, dict):
        return False, "provider %s: request_extras must be an object" % want
    return True, ""


class ProviderManifestManager:
    """Persistent dynamic provider manifest (JSON file, atomic writes).

    ``path`` injects the store file (tests pass tmp paths — never real
    env files). ``None`` resolves to the data-drive primary with a safe
    local fallback. Seeding happens on first load; ``removed`` pins
    deletions so defaults never resurrect.
    """

    def __init__(self, path=None):
        self._explicit = str(path) if path else ""
        self._paths = manifest_paths(self._explicit or None)
        self._providers = {}
        self._removed = set()
        self._loaded_path = ""
        self._loaded = False

    @property
    def store_path(self):
        """Path the manifest loaded from (or the primary when fresh)."""
        return self._loaded_path or self._paths[0]

    def _read_doc(self, path):
        try:
            with open(path, encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict):
            return None
        return doc

    @staticmethod
    def _quarantine_corrupt(path):
        """Rename an existing-but-unparseable file aside (best-effort).

        A corrupt manifest must never be silently reseeded over: one
        bad byte would wipe all custom rows plus the ``removed`` set.
        Moves ``path`` to ``<path>.corrupt.<ts>`` (original bytes kept)
        and returns True; missing/parseable/unmovable files return
        False without raising.
        """
        try:
            if not os.path.isfile(path):
                return False
            with open(path, encoding="utf-8") as handle:
                json.load(handle)
            return False
        except ValueError:
            pass  # corrupt JSON: quarantine below
        except OSError:
            return False
        try:
            stamp = int(time.time())
        except Exception:
            stamp = 0
        try:
            os.replace(path, "%s.corrupt.%d" % (path, stamp))
        except OSError:
            return False
        return True

    def _coerce_doc(self, doc):
        providers = {}
        removed = set()
        if isinstance(doc, dict):
            raw_providers = doc.get("providers") or {}
            if isinstance(raw_providers, dict):
                for name, row in raw_providers.items():
                    want = norm_name(name)
                    if not want or not isinstance(row, dict):
                        continue
                    ok, _ = validate_row(want, row)
                    if not ok:
                        continue
                    providers[want] = {
                        "protocol": str(row.get("protocol") or ""),
                        "base_url": row.get("base_url"),
                        "route": str(row.get("route") or "direct"),
                        "key_vars": [str(v).strip().upper()
                                     for v in (row.get("key_vars") or [])
                                     if str(v or "").strip()],
                        "request_extras": dict(row.get("request_extras") or {}),
                    }
            raw_removed = doc.get("removed") or []
            if isinstance(raw_removed, (list, tuple)):
                for name in raw_removed:
                    want = norm_name(name)
                    if want:
                        removed.add(want)
        return providers, removed

    def load(self):
        """Load (or seed) the manifest; returns the active provider dict."""
        for path in self._paths:
            doc = self._read_doc(path)
            if doc is None:
                self._quarantine_corrupt(path)
                continue
            providers, removed = self._coerce_doc(doc)
            self._providers = {k: v for k, v in providers.items()
                               if k not in removed}
            self._removed = set(removed)
            self._loaded_path = path
            self._loaded = True
            return dict(self._providers)
        # First run: seed core providers (never resurrect explicit removals,
        # of which there are none on a fresh store).
        self._providers = {k: dict(v, key_vars=list(v["key_vars"]))
                           for k, v in SEED_PROVIDERS.items()}
        self._removed = set()
        self._loaded_path = self._paths[0]
        self._loaded = True
        self.save()
        return dict(self._providers)

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()

    def save(self):
        """Atomic persist (primary first, fallback on failure). Names only."""
        doc = {
            "providers": self._providers,
            "removed": sorted(self._removed),
        }
        last_error = None
        for path in self._paths:
            try:
                parent = os.path.dirname(os.path.abspath(path))
                if parent:
                    os.makedirs(parent, exist_ok=True)
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(doc, handle, ensure_ascii=False, indent=1)
                os.replace(tmp, path)
                self._loaded_path = path
                return path
            except OSError as exc:
                last_error = exc
                continue
        raise OSError("cannot persist provider manifest: %s" % (last_error,))

    def provider_names(self):
        """Active provider names in manifest order (removed stay gone)."""
        self._ensure_loaded()
        return list(self._providers)

    def get(self, name):
        """Copy of one provider row, or None (fail-closed)."""
        self._ensure_loaded()
        row = self._providers.get(norm_name(name))
        if not isinstance(row, dict):
            return None
        return dict(row, key_vars=list(row.get("key_vars", [])))

    def is_removed(self, name):
        """True when a provider was explicitly deleted (stays gone)."""
        self._ensure_loaded()
        return norm_name(name) in self._removed

    def create(self, name, row):
        """Add a provider data row (kilo/local-studio validate as rows)."""
        self._ensure_loaded()
        want = norm_name(name)
        ok, error = validate_row(want, row or {})
        if not ok:
            raise ValueError(error)
        if want in self._providers:
            raise ValueError("provider exists: %s" % want)
        clean = {
            "protocol": str((row or {}).get("protocol") or ""),
            "base_url": (row or {}).get("base_url"),
            "route": str((row or {}).get("route") or "direct"),
            "key_vars": [str(v).strip().upper()
                         for v in ((row or {}).get("key_vars") or [])
                         if str(v or "").strip()],
            "request_extras": dict((row or {}).get("request_extras") or {}),
        }
        if not clean["key_vars"]:
            clean["key_vars"] = [indexed_key_var(want, 1)]
        self._providers[want] = clean
        self._removed.discard(want)
        self.save()
        return self.get(want)

    def delete(self, name):
        """Delete a provider (even defaults); True when something removed."""
        self._ensure_loaded()
        want = norm_name(name)
        if want not in self._providers and want not in self._removed:
            return False
        self._providers.pop(want, None)
        self._removed.add(want)
        self.save()
        return True

    def key_vars(self, name):
        """Full ordered key-var NAME list for a provider (names only)."""
        self._ensure_loaded()
        row = self._providers.get(norm_name(name))
        if not isinstance(row, dict):
            return []
        return [str(v) for v in (row.get("key_vars") or []) if str(v or "")]

    def key_count(self, name):
        """Exact active key-slot count for a provider."""
        return len(self.key_vars(name))

    def add_key(self, name, index=None, key_var=""):
        """Add a key slot at 1-based index (append when None); shifts up."""
        self._ensure_loaded()
        want = norm_name(name)
        row = self._providers.get(want)
        if not isinstance(row, dict):
            raise KeyError("unknown provider: %s" % want)
        var = str(key_var or "").strip().upper()
        if not var:
            var = indexed_key_var(want, (len(row.get("key_vars") or []) + 1
                                         if index is None else index))
        if not _KEY_VAR_RX.match(var):
            raise ValueError("bad key var name")
        slots = list(row.get("key_vars") or [])
        if var in slots:
            return list(slots)
        if index is None:
            slots.append(var)
        else:
            try:
                idx = int(index)
            except (TypeError, ValueError, OverflowError):
                raise ValueError("index must be a 1-based integer")
            if idx < 1 or idx > len(slots) + 1:
                raise ValueError("index out of range for %s" % want)
            slots.insert(idx - 1, var)
        row["key_vars"] = slots
        self.save()
        return list(slots)

    def delete_key(self, name, index):
        """Delete the key at 1-based index; higher indexes shift down."""
        self._ensure_loaded()
        want = norm_name(name)
        row = self._providers.get(want)
        if not isinstance(row, dict):
            raise KeyError("unknown provider: %s" % want)
        try:
            idx = int(index)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("index must be a 1-based integer")
        slots = list(row.get("key_vars") or [])
        if idx < 1 or idx > len(slots):
            raise ValueError("index out of range for %s" % want)
        removed_var = slots.pop(idx - 1)
        row["key_vars"] = slots
        self.save()
        return removed_var


def ordered_key_values(provider, *, manager=None, env_map=None,
                       file_paths=None, operator_store=None):
    """Full ordered key VALUES for a provider, in memory only.

    Order follows the manifest's ``key_vars`` list (N-wide). Each name
    resolves via explicit env map -> factory env files -> operator store.
    Empty slots resolve to "" and are dropped, so the return is the live
    rotation order (possibly shorter than the slot list). Values are
    never logged or persisted by this function.
    """
    mgr = manager
    if mgr is None:
        mgr = ProviderManifestManager()
    try:
        names = mgr.key_vars(provider)
    except Exception:
        names = []
    if not names:
        # Compatibility: convention pair (indexes 1..2) when the manifest
        # holds no row (should not happen once seeded, but keeps old
        # callers working against a fresh store).
        names = [indexed_key_var(provider, 1), indexed_key_var(provider, 2)]
    try:
        from factory.precard.provider_lease_policy import (
            resolve_key as _resolve)
    except Exception:
        _resolve = None
    values = []
    for var in names:
        if not var:
            continue
        hit = ""
        if env_map is not None:
            try:
                hit = env_map.get(var, "") or ""
            except AttributeError:
                hit = ""
        else:
            try:
                hit = os.environ.get(var, "") or ""
            except Exception:
                hit = ""
        if not hit and _resolve is not None:
            try:
                hit = _resolve(var, env_map=env_map,
                               file_paths=file_paths) or ""
            except Exception:
                hit = ""
        if not hit and operator_store:
            try:
                hit = operator_store.get(var, "") or ""
            except AttributeError:
                hit = ""
        if hit:
            values.append(hit)
    return values


__all__ = [
    "MANIFEST_FILENAME",
    "PROTOCOLS",
    "ROUTES",
    "SEED_PROVIDERS",
    "LEGACY_GROUP_INDEX",
    "ProviderManifestManager",
    "norm_name",
    "legacy_group_to_index",
    "indexed_key_var",
    "manifest_primary_path",
    "manifest_paths",
    "validate_row",
    "ordered_key_values",
]
