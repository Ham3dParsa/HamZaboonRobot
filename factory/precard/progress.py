"""Stage names and progress files (sole owner inside factory/precard).

Real words everywhere: preprocess, inflection_review, anchor_rank,
sense_judge, topic_vectors, topic_label, enrich. On-disk filenames keep
their historic values so existing progress dirs resume untouched.
Legacy ids (s0..s5, the stage_glossary domain names, inflection/judge/
label) normalize here and are never written.
"""

from __future__ import annotations

import pathlib

STAGES = (
    "preprocess",
    "inflection_review",
    "anchor_rank",
    "sense_judge",
    "topic_vectors",
    "topic_label",
    "enrich",
)

FILES = {
    "preprocess": "preprocess.json",
    "inflection_review": "inflection-review.json",
    "anchor_rank": "anchor.json",
    "sense_judge": "sense-judge.json",
    "topic_vectors": "vectors.json",
    "topic_label": "topic-label.json",
    "enrich": "enrich.json",
}

# Legacy id -> new id. Covers the s-ids, the stage_glossary domain names,
# and the short legacy names. Unknown strings pass through (callers fail
# closed); None becomes "".
_LEGACY = {
    "s0": "preprocess",
    "s0b": "inflection_review",
    "s1": "anchor_rank",
    "s2": "sense_judge",
    "s3": "topic_vectors",
    "s4": "topic_label",
    "s5": "enrich",
    "inflection": "inflection_review",
    "inflection-review": "inflection_review",
    "anchor": "anchor_rank",
    "judge": "sense_judge",
    "sense-judge": "sense_judge",
    "davarie-mana": "sense_judge",
    "vectors": "topic_vectors",
    "label": "topic_label",
    "topic-label": "topic_label",
    "enrich": "enrich",
}

# Old on-disk filenames (read-shim only, never written) — including the
# intermediate v13 names.
_OLD_FILES = (
    "s0.json",
    "s0b.json",
    "s1.json",
    "s2.json",
    "s3.json",
    "s4.json",
    "s5.json",
    "inflection.json",
    "judge.json",
    "label.json",
)

TOPUP_NEW_NAME = "label_topup_cache.json"
TOPUP_OLD_NAME = "s4_topup_cache.json"


def normalize_stage(pick):
    """New stage id from any legacy id, domain name, or new id."""
    if pick is None:
        return ""
    if not isinstance(pick, str):
        return pick
    key = pick.strip().lower()
    if key in STAGES:
        return key
    return _LEGACY.get(key, key)


def display(stage):
    """Console/log display name: the id itself (real words, no tags)."""
    try:
        return normalize_stage(stage) or stage
    except Exception:
        return stage


def stage_file(progress_dir, stage):
    """Default (new) progress path for a stage."""
    return pathlib.Path(progress_dir) / FILES[normalize_stage(stage)]


def find_stage_file(progress_dir, stage):
    """Existing progress path (new name first, old names as fallback)."""
    new_path = stage_file(progress_dir, stage)
    try:
        if new_path.exists():
            return new_path
    except OSError:
        return new_path
    directory = pathlib.Path(progress_dir)
    for old in _OLD_FILES:
        candidate = directory / old
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return new_path
