"""P02 gallery build module (supervised arbitration, R6).

``gallery_sources(run_ref)`` locates the stored link-table TSV plus
verdicts/labels for a run id or explicit paths (current ``runs/`` +
history-shaped run dirs); ``build_gallery(run_ref)`` renders
``gallery.html`` next to the sources via the existing
``factory.linking.viewer.build_linker_gallery`` (cached: rebuild only
when a source is newer). Honest ``FileNotFoundError`` (farsi) when the
TSV is absent — rows are never faked. ``viewer.py`` stays untouched.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

#: Gallery output filename (always next to the sources).
GALLERY_FILENAME = "gallery.html"

#: Honest missing-source error (farsi, no invented rows).
_MISSING_TSV_FA = (
    "جدول پیوند (TSV) برای این اجرا پیدا نشد: %s — "
    "گالری بدون جدول ساخته نمی‌شود."
)


def _data_root(explicit=None):
    """Shared factory data root (explicit arg, else env, else "")."""
    hit = str(explicit or "").strip()
    if hit:
        return hit
    return (os.environ.get("HAMZABAN_DATA_ROOT") or "").strip()


def _project_root():
    return str(Path(__file__).resolve().parents[2])


def _first_hit(run_dir, patterns):
    """First existing match over glob patterns (sorted, stable)."""
    base = Path(str(run_dir))
    for pattern in patterns:
        try:
            hits = sorted(base.glob(pattern))
        except OSError:
            continue
        for hit in hits:
            try:
                if hit.is_file():
                    return str(hit)
            except OSError:
                continue
    return ""


def _resolve_run_dir(run_id, data_root):
    """Bare run id -> run dir (direct scan, no registry dependency)."""
    clean = str(run_id or "").strip()
    if not clean or clean != Path(clean).name:
        return ""
    root = _data_root(data_root)
    candidates = []
    if root:
        candidates.append(os.path.join(root, "webui", "linking_runs", clean))
        candidates.append(os.path.join(root, "proof-linker", clean))
    candidates.append(os.path.join(_project_root(), "factory", "webui",
                                   "runs", clean))
    for path in candidates:
        try:
            if os.path.isdir(path):
                return path
        except OSError:
            continue
    return ""


def gallery_sources(run_ref, data_root=None):
    """Locate stored sources for ``run_ref``.

    ``run_ref`` is a run-dir path, a TSV file path, a bare run id, or
    a dict with explicit paths (``tsv``/``verdicts``/``candidates``).
    Returns ``{run_dir, tsv, verdicts, candidates, labels, out_html}``
    (missing optional slots are ""). Raises ``FileNotFoundError``
    (farsi) when the TSV is absent.
    """
    tsv = verdicts = candidates = labels = run_dir = ""
    if isinstance(run_ref, dict):
        tsv = str(run_ref.get("tsv") or run_ref.get("table")
                  or run_ref.get("link_table") or "").strip()
        verdicts = str(run_ref.get("verdicts") or "").strip()
        candidates = str(run_ref.get("candidates") or "").strip()
        labels = str(run_ref.get("labels") or "").strip()
        run_dir = str(run_ref.get("run_dir") or "").strip()
        if tsv and not run_dir:
            run_dir = str(Path(tsv).parent)
    else:
        text = str(run_ref or "").strip()
        probe = Path(text) if text else Path("")
        is_file = False
        try:
            is_file = probe.is_file()
        except OSError:
            is_file = False
        if is_file and probe.suffix.lower() == ".tsv":
            tsv = str(probe)
            run_dir = str(probe.parent)
        else:
            is_dir = False
            try:
                is_dir = probe.is_dir()
            except OSError:
                is_dir = False
            if is_dir:
                run_dir = str(probe)
            elif text:
                run_dir = _resolve_run_dir(text, data_root)
                if not run_dir:
                    raise FileNotFoundError(_MISSING_TSV_FA % text)
    if run_dir and not tsv:
        tsv = _first_hit(run_dir, ("link_table*.tsv", "table*.tsv", "*.tsv"))
    if run_dir and not verdicts:
        verdicts = _first_hit(run_dir, ("*verdict*.json", "verdicts.json"))
    if run_dir and not candidates:
        candidates = _first_hit(run_dir, ("candidates*.json",))
    if run_dir and not labels:
        labels = _first_hit(run_dir, ("labels.jsonl",))
    if not tsv:
        raise FileNotFoundError(
            _MISSING_TSV_FA % (str(run_ref) if run_ref else run_dir))
    try:
        if not Path(tsv).is_file():
            raise FileNotFoundError(_MISSING_TSV_FA % tsv)
    except OSError:
        raise FileNotFoundError(_MISSING_TSV_FA % tsv)
    for slot in ("verdicts", "candidates", "labels"):
        val = {"verdicts": verdicts, "candidates": candidates,
               "labels": labels}[slot]
        if val:
            try:
                if not Path(val).is_file():
                    val = ""
            except OSError:
                val = ""
            if slot == "verdicts":
                verdicts = val
            elif slot == "candidates":
                candidates = val
            else:
                labels = val
    out_html = ""
    if isinstance(run_ref, dict):
        out_html = str(run_ref.get("out") or run_ref.get("out_html")
                       or "").strip()
    if not out_html and run_dir:
        out_html = str(Path(run_dir) / GALLERY_FILENAME)
    if not out_html:
        out_html = str(Path(tsv).parent / GALLERY_FILENAME)
    return {"run_dir": run_dir or str(Path(tsv).parent), "tsv": tsv,
            "verdicts": verdicts, "candidates": candidates,
            "labels": labels, "out_html": out_html}


def _load_rows(tsv_path):
    with open(str(tsv_path), encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _load_verdicts(verdicts_path):
    if not verdicts_path:
        return []
    text = str(verdicts_path)
    if text.endswith(".jsonl"):
        out = []
        try:
            with open(text, encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict):
                        out.append(rec)
        except OSError:
            return []
        return out
    try:
        with open(text, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    if isinstance(payload, dict):
        items = payload.get("verdicts", [])
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    return [v for v in items if isinstance(v, dict)]


def _load_candidates(candidates_path):
    if not candidates_path:
        return {}
    try:
        with open(str(candidates_path), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_mtimes(sources):
    mtimes = []
    for key in ("tsv", "verdicts", "candidates", "labels"):
        path = sources.get(key) or ""
        if not path:
            continue
        try:
            mtimes.append(os.path.getmtime(path))
        except OSError:
            continue
    return mtimes


def build_gallery(run_ref, data_root=None):
    """Build (or reuse cached) ``gallery.html`` for ``run_ref``.

    Returns the output path (str). Reuses the cached file when it is
    at least as new as every source; otherwise calls
    ``viewer.build_linker_gallery`` with the output next to the
    sources. Missing TSV raises ``FileNotFoundError`` (farsi).
    """
    from factory.linking.viewer import build_linker_gallery

    sources = gallery_sources(run_ref, data_root=data_root)
    out = sources["out_html"]
    try:
        out_mtime = os.path.getmtime(out)
    except OSError:
        out_mtime = -1.0
    if out_mtime >= 0:
        mtimes = _source_mtimes(sources)
        if mtimes and out_mtime >= max(mtimes):
            return out
    rows = _load_rows(sources["tsv"])
    verdicts = _load_verdicts(sources.get("verdicts") or "")
    candidates = _load_candidates(sources.get("candidates") or "")
    build_linker_gallery(rows, verdicts, out, candidates=candidates,
                         table_label=Path(sources["tsv"]).name)
    return out
