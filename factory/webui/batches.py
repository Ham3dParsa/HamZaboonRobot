"""Operator-supervised arbitration batch export builder (P01).

Builds copy-paste arbitration batches from a screened JSONL export plus
mechanical vendor-table candidates. New module only — routes are mounted
by the coordinator (server.py untouched here).

Frozen contracts (see ``.opencode/plans/factory/plan-supervised-arbitration.md``):

- Batch item: ``{sense_id, lemma, definition, example, tags[],
  candidates:[{synset_id, definition, example, tags[]}]}``.
- Answer sheet (JSON): ``{model, prompt_hash,
  verdicts:[{sense_id, verdict:link|none, target_synset|null}]}``.
- Batch store: ``<data_root>/webui/batches/<id>/`` with ``batch.json``
  (meta), ``batch.md`` (markdown carrier), ``batch.json-data`` (full
  items JSON), ``answers/`` (empty dir; P04 import fills it).
- ``sha256(supervised_prompt_v1.txt)`` = ``prompt_hash``.

Sourcing rules (read-only callers, never modified here):

- Screened JSONL: tolerant parse (bad lines skipped, never crash), same
  shape as ``export_screened`` writes (``{lemma, sense:{sense_id, id,
  glosses/gloss, examples, tags}}``). ``sense_id`` (SHORT queue id) is
  the canonical batch identity; ``sense.id`` (FULL kaikki id) only
  feeds the vendor-table join.
- Candidates: ``factory.linking`` ``build_link_index``/``lookup_link``
  over the shipped vendor table (via ``cli.read_table``). The vendor
  table carries NO glosses, so candidate ``definition``/``example`` are
  honest empties and ``tags`` is ``[]`` — WordNet gloss resolution
  stays in the viewer/gallery layer (P02). Rows with a blank or ``-``
  (MANUAL-NONE marker) sensekey are never candidates. Dedup by
  ``synset_id``, index order kept.
- Judged set: ``sense_id`` s already in ``labels.jsonl`` (via
  ``labels.load_labels``) plus ``sense_id`` s in non-cancelled batches.
  Oldest-unjudged-first = screened file order minus the judged set.
- R4 anti-rework: a new build is refused while any non-cancelled batch
  exists (``VALIDATION-active-batch``); ``cancel_batch`` releases its
  ids back to the queue. Statuses in this phase: ``exported`` /
  ``cancelled`` only (P04 adds the rest; any non-cancelled status
  counts as active).
- Size clamp 10-50, default 25 (``VALIDATION-size``); empty eligible
  queue (``VALIDATION-empty-queue``). A non-empty queue shorter than
  the requested size exports what exists (no padding, never invented).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field

PROMPT_VERSION = "v1"
PROMPT_FILENAME = "supervised_prompt_v1.txt"

MIN_SIZE = 10
MAX_SIZE = 50
DEFAULT_SIZE = 25


@dataclass
class BatchRecord:
    """One arbitration batch (in-memory; ``save_batch`` persists it)."""

    id: str
    size: int
    status: str
    prompt_version: str
    prompt_hash: str
    created_at: str
    items: list = field(default_factory=list)


def prompt_path():
    """Absolute path of the versioned system-prompt file."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, PROMPT_FILENAME)


def prompt_hash():
    """sha256 hex over the prompt file bytes (= frozen ``prompt_hash``)."""
    with open(prompt_path(), "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _resolve_root(data_root=None):
    if isinstance(data_root, str) and data_root.strip():
        return data_root.strip()
    from factory.core.env_loader import data_root as _root

    return _root()


def batches_dir(data_root=None):
    """``<data_root>/webui/batches`` (created on save, never on read)."""
    return os.path.join(_resolve_root(data_root), "webui", "batches")


def default_labels_path(data_root=None):
    """``<data_root>/webui/labels.jsonl`` (mirrors server.labels_path)."""
    return os.path.join(_resolve_root(data_root), "webui", "labels.jsonl")


def default_table_path():
    """Shipped vendor table (single source: ``factory/linking``)."""
    from factory.linking import cli as _cli

    return str(_cli.DEFAULT_TABLE)


def _first_gloss(sense):
    if not isinstance(sense, dict):
        return ""
    for cand in sense.get("glosses") or []:
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    gloss = sense.get("gloss")
    return gloss.strip() if isinstance(gloss, str) and gloss.strip() else ""


def _first_example(sense):
    if not isinstance(sense, dict):
        return ""
    for item in sense.get("examples") or []:
        text = item.get("text") if isinstance(item, dict) else item
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def _clean_tags(raw):
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for tag in raw:
        text = str(tag or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def read_screened(screened_path):
    """Screened senses in file order (tolerant parse, bad lines skipped).

    Returns ``[{lemma, sense_id, full_id, definition, example, tags}]``.
    Rows without a non-empty ``sense.sense_id`` are skipped (never
    invented). Missing file -> ``[]``.
    """
    rows = []
    try:
        handle = open(str(screened_path), encoding="utf-8")
    except OSError:
        return rows
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            sense = rec.get("sense")
            if not isinstance(sense, dict):
                continue
            sid = sense.get("sense_id")
            if not (isinstance(sid, str) and sid.strip()):
                continue
            full = sense.get("id")
            rows.append({
                "lemma": str(rec.get("lemma") or ""),
                "sense_id": sid.strip(),
                "full_id": full.strip() if isinstance(full, str)
                and full.strip() else "",
                "definition": _first_gloss(sense),
                "example": _first_example(sense),
                "tags": _clean_tags(sense.get("tags")),
            })
    return rows


def _load_link_index(table_path=None):
    """Vendor-table index (read-only); missing table -> empty index."""
    from factory.linking import build_link_index
    from factory.linking import cli as _cli

    path = table_path or default_table_path()
    try:
        _header, rows = _cli.read_table(path)
    except OSError:
        return {}
    return build_link_index(rows or [])


def candidates_for_ids(short_id, full_id, index):
    """Mechanical candidates for one sense (pure join, never fabricated).

    Looks up both the FULL kaikki id and the SHORT queue id (direct-hit
    pass-through, mirroring the console join), dedups by ``synset_id``
    in index order. See module docstring for the honest-empty fields.
    """
    from factory.linking import lookup_link

    out = []
    seen = set()
    for kid in (full_id, short_id):
        if not kid:
            continue
        for row in lookup_link(index, kid) or []:
            if not isinstance(row, dict):
                continue
            skey = row.get("wordnet_sensekey")
            skey = skey.strip() if isinstance(skey, str) else ""
            if not skey or skey == "-" or skey in seen:
                continue
            seen.add(skey)
            out.append({"synset_id": skey, "definition": "",
                        "example": "", "tags": []})
    return out


def judged_ids(labels_path=None, data_root=None):
    """``sense_id`` s already judged (labels store + non-cancelled batches)."""
    from factory.webui import labels as _labels

    seen = set()
    store = labels_path or default_labels_path(data_root)
    for rec in _labels.load_labels(store):
        sid = rec.get("sense_id")
        if isinstance(sid, str) and sid.strip():
            seen.add(sid.strip())
    base = batches_dir(data_root)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return seen
    for name in names:
        meta_path = os.path.join(base, name, "batch.json")
        try:
            with open(meta_path, encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        if str(meta.get("status") or "") == "cancelled":
            continue
        for sid in meta.get("sense_ids") or []:
            if isinstance(sid, str) and sid.strip():
                seen.add(sid.strip())
    return seen


#: Terminal batch states: never block a new build, never re-openable.
#: Everything else (exported/in_review/...) is live and blocks rebuilds.
TERMINAL_STATUSES = frozenset({"imported", "cancelled"})


def active_batches(data_root=None):
    """Metas of all live (non-terminal) batches (oldest first)."""
    out = []
    base = batches_dir(data_root)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        meta_path = os.path.join(base, name, "batch.json")
        try:
            with open(meta_path, encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and str(meta.get("status") or "") \
                not in TERMINAL_STATUSES:
            out.append(meta)
    return out


def _check_size(size):
    if size is None:
        return DEFAULT_SIZE
    if isinstance(size, bool) or not isinstance(size, int):
        raise ValueError("VALIDATION-size: size must be an int in %d-%d"
                         % (MIN_SIZE, MAX_SIZE))
    if size < MIN_SIZE or size > MAX_SIZE:
        raise ValueError("VALIDATION-size: size must be in %d-%d (got %d)"
                         % (MIN_SIZE, MAX_SIZE, size))
    return size


def _new_id():
    stamp = datetime.datetime.now(datetime.timezone.utc)
    return "%s-%s" % (stamp.strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:6])


def build_batch(screened_path, size=DEFAULT_SIZE, table_path=None,
                labels_path=None, data_root=None):
    """Build the next oldest-unjudged-first batch (no disk writes).

    Raises ``ValueError`` with a ``VALIDATION-*`` message on bad size,
    an active (non-cancelled) batch, or an empty eligible queue.
    """
    want = _check_size(size)
    if active_batches(data_root):
        raise ValueError("VALIDATION-active-batch: cancel the active batch "
                         "before exporting a new one (anti-rework)")
    rows = read_screened(screened_path)
    done = judged_ids(labels_path, data_root)
    queue = [row for row in rows if row["sense_id"] not in done]
    if not queue:
        raise ValueError("VALIDATION-empty-queue: no unjudged senses in %s"
                         % (screened_path,))
    index = _load_link_index(table_path)
    items = []
    for row in queue[:want]:
        items.append({
            "sense_id": row["sense_id"],
            "lemma": row["lemma"],
            "definition": row["definition"],
            "example": row["example"],
            "tags": row["tags"],
            "candidates": candidates_for_ids(
                row["sense_id"], row["full_id"], index),
        })
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return BatchRecord(
        id=_new_id(),
        size=want,
        status="exported",
        prompt_version=PROMPT_VERSION,
        prompt_hash=prompt_hash(),
        created_at=stamp,
        items=items,
    )


def render_json(batch):
    """Full batch payload as a JSON string (round-trips ``items``)."""
    return json.dumps({
        "id": batch.id,
        "size": batch.size,
        "status": batch.status,
        "prompt_version": batch.prompt_version,
        "prompt_hash": batch.prompt_hash,
        "created_at": batch.created_at,
        "items": batch.items,
    }, ensure_ascii=False, indent=1)


def render_markdown(batch):
    """Markdown carrier: copy-paste prompt block + items + answer template."""
    try:
        with open(prompt_path(), encoding="utf-8") as handle:
            prompt_text = handle.read().strip()
    except OSError:
        prompt_text = ""
    lines = []
    lines.append("# Supervised arbitration batch %s" % batch.id)
    lines.append("")
    lines.append("prompt_version: %s" % batch.prompt_version)
    lines.append("prompt_hash: %s" % batch.prompt_hash)
    lines.append("created_at: %s" % batch.created_at)
    lines.append("size: %d" % batch.size)
    lines.append("")
    lines.append("## System prompt (copy into the AI chat first)")
    lines.append("")
    lines.append("```text")
    lines.append(prompt_text)
    lines.append("```")
    lines.append("")
    lines.append("## Items (%d)" % len(batch.items))
    for pos, item in enumerate(batch.items, 1):
        lines.append("")
        lines.append("### %d. %s — %s" % (pos, item.get("sense_id", ""),
                                          item.get("lemma", "")))
        if item.get("definition"):
            lines.append("definition: %s" % item["definition"])
        if item.get("example"):
            lines.append("example: %s" % item["example"])
        tags = item.get("tags") or []
        if tags:
            lines.append("tags: %s" % ", ".join(tags))
        cands = item.get("candidates") or []
        if cands:
            lines.append("candidates:")
            for cand in cands:
                lines.append("- %s" % cand.get("synset_id", ""))
                if cand.get("definition"):
                    lines.append("  definition: %s" % cand["definition"])
                if cand.get("example"):
                    lines.append("  example: %s" % cand["example"])
        else:
            lines.append("candidates: (none — verdict must be none)")
    lines.append("")
    lines.append("## Answer sheet template (reply with EXACTLY this JSON shape)")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps({
        "model": "<your model name>",
        "prompt_hash": batch.prompt_hash,
        "verdicts": [{"sense_id": item.get("sense_id", ""),
                      "verdict": "link|none",
                      "target_synset": "<synset_id or null>"}
                     for item in batch.items],
    }, ensure_ascii=False, indent=1))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def batch_dir(batch_id, data_root=None):
    """``<data_root>/webui/batches/<id>`` (never created by reads)."""
    return os.path.join(batches_dir(data_root), str(batch_id))


def save_batch(batch, data_root=None):
    """Persist a built batch (meta + md + items JSON + empty answers/)."""
    base = batch_dir(batch.id, data_root)
    os.makedirs(os.path.join(base, "answers"), exist_ok=True)
    meta = {
        "id": batch.id,
        "size": batch.size,
        "status": batch.status,
        "prompt_version": batch.prompt_version,
        "prompt_hash": batch.prompt_hash,
        "created_at": batch.created_at,
        "sense_ids": [item.get("sense_id", "") for item in batch.items],
        "answered": 0,
        "approved": 0,
    }
    with open(os.path.join(base, "batch.json"), "w",
              encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=1)
    with open(os.path.join(base, "batch.md"), "w",
              encoding="utf-8") as handle:
        handle.write(render_markdown(batch))
    with open(os.path.join(base, "batch.json-data"), "w",
              encoding="utf-8") as handle:
        handle.write(render_json(batch))
    return batch


def list_batches(data_root=None):
    """``[{id, size, status, answered, approved, created_at}]`` (oldest first)."""
    out = []
    base = batches_dir(data_root)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        meta_path = os.path.join(base, name, "batch.json")
        try:
            with open(meta_path, encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or not meta.get("id"):
            continue
        out.append({
            "id": meta.get("id"),
            "size": meta.get("size"),
            "status": meta.get("status"),
            "answered": meta.get("answered", 0),
            "approved": meta.get("approved", 0),
            "created_at": meta.get("created_at"),
        })
    return out


def cancel_batch(batch_id, data_root=None):
    """Mark a batch ``cancelled`` (releases its ids to the queue).

    Refuses ``imported`` batches (W3: the audit trail is locked once
    labels are final — rejected ids already returned to the queue at
    approve time, so no cancel is needed to re-export them).
    """
    base = batch_dir(batch_id, data_root)
    meta_path = os.path.join(base, "batch.json")
    try:
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
    except OSError:
        raise ValueError("VALIDATION-unknown-batch: no batch %s" % (batch_id,))
    except ValueError:
        raise ValueError("VALIDATION-unknown-batch: no batch %s" % (batch_id,))
    if not isinstance(meta, dict) or not meta.get("id"):
        raise ValueError("VALIDATION-unknown-batch: no batch %s" % (batch_id,))
    if str(meta.get("status") or "") == "imported":
        raise ValueError("VALIDATION-imported-final: batch %s is already "
                         "imported; its audit trail is locked (rejected ids "
                         "returned to the queue at approve time)"
                         % (batch_id,))
    meta["status"] = "cancelled"
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=1)
    data_path = os.path.join(base, "batch.json-data")
    try:
        with open(data_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            payload["status"] = "cancelled"
            with open(data_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=1)
    except (OSError, ValueError):
        pass
    return meta
