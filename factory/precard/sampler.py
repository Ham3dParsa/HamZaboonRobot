"""Quota sampler T0-v1: stratified row budgets from the T1 mix (pure, stdlib).

Pipeline position: AFTER deterministic filters, BEFORE card building.
Input = candidate precard-row dicts (any mapping with at least a level);
output = budgeted selection + machine-readable summary.

Provenance (measured 2026-09-16 on the v141 284-sample run):
- T1 mix (plan-v14-pools-multicard, band B): A1 276 / A2 448 / B1 753 /
  B2 700 / C1 438 / C2 385 (total 3000).
- Survival (kept fraction per level): A1 .88 / A2 .72 / B1 .58 /
  B2 .67 / C1 .67 / C2 .49.
- Fanout (rows per kept lemma): A1 2.98 / A2 2.79 / B1 2.92 /
  B2 2.29 / C1 2.68 / C2 2.0.
ALL numbers are PROVISIONAL — recalibrate after the first trial run.

Tag policy (locked owner directive 2026-09-16): the sampler core never
hardcodes a product decision about slang/colloquial/vulgar. Profiles
(`media` default / `clean`) set defaults; explicit --include-*/--exclude-*
flags always win. Dataset truth comes from anchor sets (imported, never
redefined); the slang set is profile policy owned HERE.
Rows without a "tags" field pass the tag policy untouched (documented
assumption — follow-up: emit sense tags on precard rows so the flags
bite on real pipeline data).
"""

from __future__ import annotations

import argparse
import json
import math
import sys

from factory.precard.anchor import OBSOLETE_TAGS, VULGAR_TAGS

LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")

# PROVISIONAL (see module docstring): target final rows per level.
QUOTA_MIX = {"A1": 276, "A2": 448, "B1": 753,
             "B2": 700, "C1": 438, "C2": 385}

# PROVISIONAL: kept fraction per level (drives reservoir sizing).
SURVIVAL = {"A1": 0.88, "A2": 0.72, "B1": 0.58,
            "B2": 0.67, "C1": 0.67, "C2": 0.49}

# Profile policy owned here (not dataset truth): informal-register tags
# the `clean` profile drops unless explicitly included.
SLANG_TAGS = frozenset({"slang", "colloquial"})

# PROVISIONAL scoring weights: bridge-method rank dominates, a dataset
# example is a smaller plus, zipf breaks the rest. Recalibrate later.
METHOD_SCORE = {"wn-single": 3, "wn-evp-gloss": 2,
                "pool-fallback": 1}
EXAMPLE_BONUS = 10
METHOD_SCALE = 100


def resolve_drop_tags(profile="media", include=(), exclude=()):
    """Effective drop-tag set: profile defaults, explicit flags win.

    `media` (default): drops only OBSOLETE_TAGS.
    `clean`: drops OBSOLETE_TAGS + VULGAR_TAGS + SLANG_TAGS.
    include/exclude: tag names force-kept / force-dropped.
    """
    drop = set(OBSOLETE_TAGS)
    if profile == "clean":
        drop |= set(VULGAR_TAGS) | set(SLANG_TAGS)
    elif profile != "media":
        raise ValueError("unknown profile: %r" % (profile,))
    drop |= {str(t or "").strip().casefold()
             for t in exclude if str(t or "").strip()}
    drop -= {str(t or "").strip().casefold()
             for t in include if str(t or "").strip()}
    return frozenset(drop)


def tag_drop_reason(tags, drop_tags):
    """First drop-tag hit (lowercased) or None. Missing tags -> None.

    Both sides are normalized: a direct caller passing uncasefolded
    drop_tags must not silently bypass the policy."""
    if tags is None:
        return None
    drop = {str(t or "").strip().casefold() for t in drop_tags or ()}
    hit = {str(t or "").strip().casefold() for t in tags} & drop
    return sorted(hit)[0] if hit else None


def row_level(row):
    """Stratum key: sense_cefr, else pool_level, else OTHER."""
    for field in ("sense_cefr", "pool_level"):
        level = str((row or {}).get(field) or "").strip().upper()
        if level in LEVELS:
            return level
    return "OTHER"


def score_row(row):
    """Deterministic quality score (higher = keep first)."""
    method = str((row or {}).get("sense_cefr_method") or "")
    score = METHOD_SCORE.get(method, 0) * METHOD_SCALE
    if (row or {}).get("dataset_examples"):
        score += EXAMPLE_BONUS
    try:
        zipf = float((row or {}).get("zipf", 0) or 0)
    except (TypeError, ValueError):
        zipf = 0.0
    if not math.isfinite(zipf):
        zipf = 0.0
    # Cap rationale: wordfreq zipf tops out near 8 in practice; the cap
    # keeps one extreme frequency from outweighing the method rank
    # (METHOD_SCALE 100). Recalibration must keep cap >> EXAMPLE_BONUS.
    return score + max(0.0, min(8.0, zipf))


def reservoir_need(quota, survival):
    """Upstream rows needed to net `quota` survivors (ceil)."""
    if survival <= 0:
        return quota
    return int(math.ceil(quota / survival))


def sample(rows, quotas=None, survival=None, drop_tags=frozenset(),
           other_quota=0):
    """Stratified budget selection.

    Filters (tag policy) run pre-reservoir; quotas apply post-filter on
    score order (score desc, key asc — fully deterministic, no RNG).
    Returns (selected, summary): summary reports per-level quota /
    candidates / selected / shortfall / reservoir_need plus drop counts
    by reason, so shortfalls are observable, never silent.
    """
    quotas = dict(QUOTA_MIX if quotas is None else quotas)
    survival = dict(SURVIVAL if survival is None else survival)
    drop_tags = frozenset(() if drop_tags is None else drop_tags)
    buckets = {level: [] for level in LEVELS}
    buckets["OTHER"] = []
    drops = {}
    for row in rows or []:
        reason = tag_drop_reason((row or {}).get("tags"), drop_tags)
        if reason is not None:
            drops["tag:" + reason] = drops.get("tag:" + reason, 0) + 1
            continue
        level = row_level(row)
        buckets[level].append(row)
    selected = []
    per_level = {}
    for level in LEVELS + ("OTHER",):
        cands = buckets[level]
        quota = quotas.get(level, 0) if level != "OTHER" else other_quota
        ordered = sorted(cands,
                         key=lambda r: (-score_row(r),
                                        str((r or {}).get("key", ""))))
        kept = ordered[:max(0, quota)]
        selected.extend(kept)
        surv = survival.get(level, 1.0) if level != "OTHER" else 1.0
        per_level[level] = {
            "quota": quota,
            "candidates": len(cands),
            "selected": len(kept),
            "shortfall": max(0, quota - len(kept)),
            "reservoir_need": reservoir_need(quota, surv),
        }
        if len(cands) > len(kept):
            drops["over-quota:" + level] = len(cands) - len(kept)
    summary = {"per_level": per_level, "drops": drops,
               "total_selected": len(selected)}
    return selected, summary


def parse_mix(text):
    """'276,448,753,700,438,385' -> {level: quota} (A1..C2 order)."""
    parts = [p.strip() for p in str(text or "").split(",")]
    if len(parts) != len(LEVELS):
        raise ValueError("mix needs %d comma values (got %r)"
                         % (len(LEVELS), text))
    try:
        values = [int(value) for value in parts]
    except ValueError:
        raise ValueError("mix values must be integers (got %r)"
                         % (text,))
    return {level: value for level, value in zip(LEVELS, values)}


def build_parser():
    parser = argparse.ArgumentParser(
        description="T0-v1 quota sampler: stratified row budgets.")
    parser.add_argument("--rows", required=True,
                        help="input candidate rows (.jsonl)")
    parser.add_argument("--out", required=True,
                        help="selected rows (.jsonl)")
    parser.add_argument("--mix", default=",".join(
        str(QUOTA_MIX[level]) for level in LEVELS),
        help="quotas A1..C2 (default: T1 mix)")
    parser.add_argument("--profile", default="media",
                        choices=("media", "clean"),
                        help="tag-policy profile (default: media)")
    parser.add_argument("--include-obsolete", action="store_true")
    parser.add_argument("--include-slang", action="store_true")
    parser.add_argument("--include-colloquial", action="store_true")
    parser.add_argument("--include-vulgar", action="store_true")
    parser.add_argument("--exclude-slang", action="store_true")
    parser.add_argument("--exclude-colloquial", action="store_true")
    parser.add_argument("--exclude-vulgar", action="store_true")
    parser.add_argument("--exclude-obsolete", action="store_true")
    parser.add_argument("--other-quota", type=int, default=0)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    include = set()
    exclude = set()
    if args.include_obsolete:
        include |= set(OBSOLETE_TAGS)
    if args.include_slang:
        include |= {"slang"}
    if args.include_colloquial:
        include |= {"colloquial"}
    if args.include_vulgar:
        include |= set(VULGAR_TAGS)
    if args.exclude_slang:
        exclude |= {"slang"}
    if args.exclude_colloquial:
        exclude |= {"colloquial"}
    if args.exclude_vulgar:
        exclude |= set(VULGAR_TAGS)
    if args.exclude_obsolete:
        exclude |= set(OBSOLETE_TAGS)
    drop_tags = resolve_drop_tags(args.profile, include, exclude)
    quotas = parse_mix(args.mix)
    try:
        with open(args.rows, encoding="utf-8") as handle:
            rows = []
            for lineno, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    parser.error("bad JSON on %s line %d"
                                 % (args.rows, lineno))
    except OSError as exc:
        parser.error("cannot read %s: %s" % (args.rows, exc))
    selected, summary = sample(rows, quotas=quotas, drop_tags=drop_tags,
                               other_quota=args.other_quota)
    summary["profile"] = args.profile
    summary["drop_tags"] = sorted(drop_tags)
    try:
        with open(args.out, "w", encoding="utf-8") as handle:
            for row in selected:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        parser.error("cannot write %s: %s" % (args.out, exc))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
