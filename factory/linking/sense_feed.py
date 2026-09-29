"""Shared screened→items feed (single source of truth, P2 extraction).

Moved verbatim out of ``factory/webui/batches.py`` (route-delete: the
old copies are deleted there) so the linking CLI and the console batch
builder join senses to mechanical candidates EXACTLY once:

- ``read_screened``: tolerant JSONL parse (bad lines skipped, missing
  file -> []), rows need a non-empty ``sense.sense_id``.
- ``load_link_index`` / ``candidates_for_ids``: read-only vendor-table
  join over FULL then SHORT id, deduped by synset; ``-`` sensekeys
  never become candidates; glosses stay honest empties (WordNet gloss
  resolution lives in the viewer/gallery layer).
- ``load_senses``: the composed feed both callers use.
"""

from __future__ import annotations

import json


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


def load_link_index(table_path=None):
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
    in index order.
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


def load_senses(screened_path, table_path=None):
    """Runner-shaped items for every screened row (oldest first)."""
    index = load_link_index(table_path)
    items = []
    for row in read_screened(screened_path):
        items.append({
            "sense_id": row["sense_id"],
            "lemma": row["lemma"],
            "definition": row["definition"],
            "example": row["example"],
            "tags": row["tags"],
            "candidates": candidates_for_ids(
                row["sense_id"], row["full_id"], index),
        })
    return items
