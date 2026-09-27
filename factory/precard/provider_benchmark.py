"""Provider benchmark + gold evaluator (wave two, worker two).

Benchmark logic plus the gold evaluator ONLY. No transport, no
telemetry, no frontend, no server routes (web wiring is a later wave).

- Gold loader reads the calibration witness file through the existing
  default path (``factory.webui.server.DEFAULT_WITNESS_LABELS`` via
  the ``HAMZABAN_WITNESS_LABELS`` env var, explicit path first) with
  per-row field validation. Accepts the same shapes as the console
  reader: a list of ``{kid, ...}`` or ``{"rows": [...]}``. Verdict
  keys (``gemini_verdict``/``verdict``/``class``/``baseline``) and
  winner keys (``winner_sensekey``/``table_winner_sensekey``/
  ``target_synset``) match ``review_flags_for_sense`` exactly.
- ``ProviderBenchmark`` runs one sense or the full calibration set
  through the active provider presets (a Google preset versus a Kilo
  preset registered as DATA through the manifest manager — never a
  code row), collecting per-run latency (three decimals), input and
  output tokens, model verdict plus winner, and match against the
  expected verdict. Model invocation arrives as an injected
  ``invoke_fn``; without one the run parks with an error (live
  transport belongs to the sibling scope / a later wave — this module
  never performs it).
- Summary: total accuracy, mean latency, token totals per provider.

Secret rule: provider/key NAMES only. Key VALUES never enter this
module: ``invoke_fn`` receives ``(provider_name, sense)`` and returns
verdict/winner/tokens/latency — never key material. Results are plain
structured dicts (JSON-safe).
"""

from __future__ import annotations

import json
import os
import time

#: Verdict keys accepted from a witness row (same order as the console
#: ``review_flags_for_sense`` reader — first non-empty string wins).
GOLD_VERDICT_KEYS = ("gemini_verdict", "verdict", "class", "baseline")

#: Winner keys accepted from a witness row (same order as the console
#: reader — first non-empty string wins; empty when absent).
GOLD_WINNER_KEYS = ("winner_sensekey", "table_winner_sensekey",
                    "target_synset")

#: Default benchmark presets — NAMES only. Rows (protocol, base_url,
#: route, key vars) always resolve from the manifest manager; adding a
#: provider is a data write, never a code edit here.
DEFAULT_PROVIDERS = ("google", "kilo")

#: Env var name for the witness path (owned by factory.webui.server;
#: read here, with a literal fallback only when that module cannot be
#: imported).
WITNESS_LABELS_ENV_VAR = "HAMZABAN_WITNESS_LABELS"


def _normalize_providers(providers):
    """Provider name list from the caller's arg (never raises).

    A single string means one provider (``list("google")`` would
    split into chars — bogus unknown-provider entries); None means
    the defaults; anything else is listed as given (each entry is
    stripped + lowered at the call site).
    """
    if providers is None:
        return list(DEFAULT_PROVIDERS)
    if isinstance(providers, str):
        return [providers]
    return list(providers)


def default_witness_path(explicit=None):
    """Resolve the calibration witness path: explicit, else env, else default.

    The engine default lives in exactly one place
    (``factory.webui.server.DEFAULT_WITNESS_LABELS``) and is read
    lazily so importing this module stays light. Returns "" when
    nothing resolves (the loader raises, naming the miss).
    """
    hit = str(explicit or "").strip()
    if hit:
        return hit
    try:
        from factory.webui import server as _srv
        return str(_srv._configured_path(
            "", _srv.WITNESS_LABELS_ENV_VAR,
            _srv.DEFAULT_WITNESS_LABELS) or "")
    except Exception:
        return (os.environ.get(WITNESS_LABELS_ENV_VAR) or "").strip()


def _gold_entry(row):
    """Validate one witness row -> gold dict, or None when invalid.

    Requires a non-empty string ``kid`` and a non-empty verdict under
    one of GOLD_VERDICT_KEYS. The winner is optional (""). Anything
    else (non-dict, missing kid, missing verdict) is invalid.
    """
    if not isinstance(row, dict):
        return None
    kid = row.get("kid")
    if not (isinstance(kid, str) and kid.strip()):
        return None
    verdict = ""
    for key in GOLD_VERDICT_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            verdict = value.strip()
            break
    if not verdict:
        return None
    winner = ""
    for key in GOLD_WINNER_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            winner = value.strip()
            break
    return {"kid": kid.strip(), "expected_verdict": verdict,
            "expected_winner": winner}


def load_gold(path=None):
    """Load + validate the calibration witness file (secret-free).

    Returns ``{"path", "entries", "skipped", "total"}`` where entries
    are ``{kid, expected_verdict, expected_winner}`` dicts. Invalid
    rows are skipped and counted (never invented). Raises
    FileNotFoundError when the file is absent and ValueError when it
    is unreadable, corrupt, or the wrong top-level shape (list or
    ``{"rows": [...]}`` required).
    """
    resolved = default_witness_path(path)
    if not resolved:
        raise FileNotFoundError(
            "witness file: no path resolves (explicit, %s, or engine "
            "default)" % WITNESS_LABELS_ENV_VAR)
    try:
        with open(resolved, encoding="utf-8") as handle:
            blob = json.load(handle)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError(
            "witness file unreadable: %s" % resolved) from exc
    except ValueError as exc:
        raise ValueError(
            "witness file corrupt JSON: %s" % resolved) from exc
    raw = blob.get("rows") if isinstance(blob, dict) else blob
    if not isinstance(raw, list):
        raise ValueError(
            "witness shape: list or {rows:[...]} required "
            "(file: %s)" % resolved)
    entries, skipped = [], 0
    for row in raw:
        item = _gold_entry(row)
        if item is None:
            skipped += 1
            continue
        entries.append(item)
    return {"path": resolved, "entries": entries, "skipped": skipped,
            "total": len(raw)}


def _round3(value):
    """Finite float rounded to three decimals (0.0 when not a number)."""
    if isinstance(value, bool):
        return 0.0
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    if num != num or abs(num) == float("inf"):
        return 0.0
    return round(num, 3)


def _tokens(value):
    """Non-negative int token count (0 when absent or not a number)."""
    if isinstance(value, bool):
        return 0
    try:
        num = int(value)
    except (TypeError, ValueError):
        return 0
    return num if num > 0 else 0


class ProviderBenchmark:
    """Benchmark runner over active provider presets (gold evaluator).

    ``manager`` is a ``ProviderManifestManager`` (a default instance
    is built lazily when None — tests pass a tmp-path manager holding
    a DATA-registered kilo row). ``invoke_fn(provider_name, sense)``
    returns ``{verdict, winner, input_tokens, output_tokens,
    latency_s}`` (``model_verdict``/``model_winner`` spellings also
    accepted); it is the ONLY model seam, so tests inject fakes and no
    live call ever happens here. ``clock`` defaults to
    ``time.perf_counter`` and measures the invoke span only when the
    result carries no explicit ``latency_s``.
    """

    def __init__(self, *, manager=None, invoke_fn=None, clock=None):
        self._manager = manager
        self._cached_manager = None
        self._invoke = invoke_fn
        self._clock = clock if callable(clock) else time.perf_counter

    def _active_manager(self):
        if self._manager is not None:
            return self._manager
        if self._cached_manager is None:
            from factory.precard import provider_manifest as _manifest_mod
            self._cached_manager = _manifest_mod.ProviderManifestManager()
        return self._cached_manager

    def active_providers(self):
        """Active preset names from the manifest (removed stay gone)."""
        try:
            return list(self._active_manager().provider_names())
        except Exception:
            return []

    def _manifest_row(self, provider):
        try:
            return self._active_manager().get(provider)
        except Exception:
            return None

    def run_sense(self, sense, providers=None):
        """Run one gold sense across presets -> per-provider result list.

        Each result carries ``kid``, ``expected_verdict``,
        ``expected_winner``, ``provider``, ``latency_s`` (three
        decimals), ``input_tokens``, ``output_tokens``,
        ``model_verdict``, ``model_winner``, ``match`` (model verdict
        equals the expected verdict), and ``error`` (None on success).
        Unknown/removed providers and a missing ``invoke_fn`` park
        with an error entry instead of raising.
        """
        if not isinstance(sense, dict):
            raise ValueError("sense must be a gold dict with a kid")
        kid = sense.get("kid")
        if not (isinstance(kid, str) and kid.strip()):
            raise ValueError("sense must carry a non-empty kid")
        kid = kid.strip()
        expected_verdict = sense.get("expected_verdict", "")
        expected_verdict = (expected_verdict.strip()
                            if isinstance(expected_verdict, str) else "")
        expected_winner = sense.get("expected_winner", "")
        expected_winner = (expected_winner.strip()
                           if isinstance(expected_winner, str) else "")
        names = _normalize_providers(providers)
        results = []
        for name in names:
            want = str(name or "").strip().lower()
            base = {"kid": kid, "expected_verdict": expected_verdict,
                    "expected_winner": expected_winner, "provider": want,
                    "latency_s": 0.0, "input_tokens": 0,
                    "output_tokens": 0, "model_verdict": "",
                    "model_winner": "", "match": False, "error": None}
            if not want:
                base["error"] = "unknown provider (empty name)"
                results.append(base)
                continue
            if not isinstance(self._manifest_row(want), dict):
                base["error"] = (
                    "unknown provider: %s (not in active manifest)"
                    % want)
                results.append(base)
                continue
            if not callable(self._invoke):
                base["error"] = (
                    "no invoke_fn for %s (live transport is a later "
                    "wave)" % want)
                results.append(base)
                continue
            payload = {"kid": kid,
                       "expected_verdict": expected_verdict,
                       "expected_winner": expected_winner}
            try:
                start = self._clock()
                raw = self._invoke(want, dict(payload))
                measured = self._clock() - start
            except Exception as exc:
                base["error"] = "invoke failed for %s: %s" % (
                    want, type(exc).__name__)
                results.append(base)
                continue
            if not isinstance(raw, dict):
                base["error"] = (
                    "invoke returned non-dict for %s" % want)
                results.append(base)
                continue
            given = raw.get("latency_s")
            if isinstance(given, bool):
                given = None
            base["latency_s"] = (
                _round3(given) if isinstance(given, (int, float))
                else _round3(measured))
            verdict = raw.get("verdict", raw.get("model_verdict", ""))
            winner = raw.get("winner", raw.get("model_winner", ""))
            base["model_verdict"] = (verdict.strip()
                                     if isinstance(verdict, str) else "")
            base["model_winner"] = (winner.strip()
                                    if isinstance(winner, str) else "")
            base["input_tokens"] = _tokens(raw.get("input_tokens"))
            base["output_tokens"] = _tokens(raw.get("output_tokens"))
            base["match"] = bool(
                expected_verdict and base["model_verdict"]
                and base["model_verdict"] == expected_verdict)
            results.append(base)
        return results

    def run_all(self, senses=None, providers=None, sense_id=None,
                gold_path=None):
        """Run one sense or the full calibration set (secret-free dict).

        ``senses`` None loads the witness file (``gold_path`` or the
        engine default); ``sense_id`` narrows to one kid. Returns
        ``{"gold_path", "providers", "total_senses", "results",
        "summary", "note"}`` — JSON-safe, names only, never key
        values. Raises FileNotFoundError/ValueError only when the
        witness file itself cannot load.
        """
        names = _normalize_providers(providers)
        names = [str(n or "").strip().lower() for n in names]
        if senses is None:
            gold = load_gold(gold_path)
            senses = gold["entries"]
            resolved_path = gold["path"]
        else:
            senses = list(senses)
            resolved_path = str(gold_path or "")
        note = ""
        if sense_id is not None:
            want = str(sense_id or "").strip()
            senses = [s for s in senses
                      if isinstance(s, dict) and s.get("kid") == want]
            if not senses:
                note = "sense not found: %s" % want
        results = []
        for sense in senses:
            results.extend(self.run_sense(sense, names))
        return {"gold_path": resolved_path, "providers": list(names),
                "total_senses": len(senses), "results": results,
                "summary": summarize(results), "note": note}


def summarize(results):
    """Pure summary: accuracy, mean latency, per-provider token totals."""
    rows = list(results or [])
    runs = len(rows)
    matches = sum(1 for row in rows if isinstance(row, dict)
                  and row.get("match"))
    accuracy = round(matches / runs, 4) if runs else 0.0
    mean_latency = (round(sum(_round3((row or {}).get("latency_s", 0.0))
                              for row in rows) / runs, 3)
                    if runs else 0.0)
    per_provider = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("provider") or "")
        slot = per_provider.setdefault(name, {
            "runs": 0, "matches": 0, "accuracy": 0.0,
            "input_tokens": 0, "output_tokens": 0})
        slot["runs"] += 1
        if row.get("match"):
            slot["matches"] += 1
        slot["input_tokens"] += _tokens(row.get("input_tokens"))
        slot["output_tokens"] += _tokens(row.get("output_tokens"))
    for slot in per_provider.values():
        slot["accuracy"] = (round(slot["matches"] / slot["runs"], 4)
                            if slot["runs"] else 0.0)
    return {"total_runs": runs, "total_matches": matches,
            "accuracy": accuracy,
            "accuracy_pct": round(accuracy * 100.0, 2),
            "mean_latency_s": mean_latency,
            "tokens_per_provider": per_provider}


__all__ = [
    "GOLD_VERDICT_KEYS",
    "GOLD_WINNER_KEYS",
    "DEFAULT_PROVIDERS",
    "WITNESS_LABELS_ENV_VAR",
    "default_witness_path",
    "load_gold",
    "ProviderBenchmark",
    "summarize",
]
