"""AWL coverage vs the 10k pool + vowel-less recall audit (TICKET F3).

Reads ``awl_families.json`` (see factory/fetch_awl.py) and the pool
``factory/packs/en/lemmas_10k.csv``, normalizes BOTH sides with the single
source of truth ``registry.normalize_lemma`` (this file defines no
normalizer), and reports:

(a) % of AWL families with >=1 member in the pool (overall + per-CEFR of
    the matching pool row, easiest level wins on multi-match);
(b) % of pool rows that are AWL members;
(c) vowel-less recall audit: streams the Kaikki offset index ONCE and counts
    single-token alphabetic vowel-less words that have a pack CEFR hit
    (CEFR-J fallback or EVP entry = strict real-word signal), plus what the
    sampler's real keep rule (classify: pack or wordfreq zipf) would have
    kept, per-level — i.e. how much recall the R5 ``drop:no_vowel`` gate
    cost. Shows pack-hit samples + top frequent samples.

Writes a Markdown report (default W:/hamzaban_data_factory/reports/) and
prints a summary to stdout. Reads only — never writes to the pool or index.

Usage:
    python factory/awl_coverage.py --lang en [--awl PATH] [--pool PATH]
        [--index PATH] [--pack DIR] [--report PATH]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from registry import normalize_lemma  # noqa: E402  (single source)
from sample_lemmas import (LEVEL_ORDER, LEVEL_RANK, classify, load_pack,  # noqa: E402
                           pack_has_cefr_hit)

VOWELS = frozenset("aeiouAEIOU")
SAMPLE_N = 20
SAMPLE_CAP = 2000  # stored-sample cap; counters keep running past it
# Audit-only frequent floor (NOT the sampler keep rule): zipf >= 4.0 means
# genuinely common (B1+ frequency), not tail junk. Deliberately stricter
# than the sampler's keep-rule floor FREQUENT_ZIPF_MIN = 3.0 (strict >) in
# factory/sample_lemmas.py: the keep rule is lenient (never drop a real
# word) while this audit is stringent (only flag clear recall cost).
AUDIT_FREQUENT_ZIPF = 4.0

DEFAULT_AWL_TEMPLATE = "W:/hamzaban_data_factory/raw/awl_families.json"
DEFAULT_INDEX_TEMPLATE = "W:/hamzaban_data_factory/raw/kaikki-{lang}-index.jsonl"
DEFAULT_REPORT_TEMPLATE = "W:/hamzaban_data_factory/reports/awl_coverage_10k.md"


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def default_pool(lang: str) -> str:
    return os.path.join(script_dir(), "packs", lang, "lemmas_10k.csv")


def default_pack(lang: str) -> str:
    return os.path.join(script_dir(), "packs", lang)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AWL coverage vs pool.")
    parser.add_argument("--lang", default="en", help="language key (default en)")
    parser.add_argument("--awl", default=None, help="awl_families.json path")
    parser.add_argument("--pool", default=None, help="lemmas_10k.csv path")
    parser.add_argument("--index", default=None, help="kaikki offset index path")
    parser.add_argument("--pack", default=None, help="language pack dir")
    parser.add_argument("--report", default=None, help="output Markdown report path")
    args = parser.parse_args(argv)
    if args.awl is None:
        args.awl = DEFAULT_AWL_TEMPLATE
    if args.pool is None:
        args.pool = default_pool(args.lang)
    if args.index is None:
        args.index = DEFAULT_INDEX_TEMPLATE.format(lang=args.lang)
    if args.pack is None:
        args.pack = default_pack(args.lang)
    if args.report is None:
        args.report = DEFAULT_REPORT_TEMPLATE
    return args


def load_awl(path: str) -> tuple[dict[str, list[str]], dict]:
    """AWL families as {norm_family: [norm_members]} + metadata (pure logic)."""
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    families = payload.get("families", payload)
    normed: dict[str, list[str]] = {}
    for head, members in families.items():
        try:
            norm_head = normalize_lemma(head)
        except (ValueError, TypeError):
            continue
        norm_members: list[str] = []
        for member in members:
            try:
                norm = normalize_lemma(member)
            except (ValueError, TypeError):
                continue
            if norm not in norm_members:
                norm_members.append(norm)
        if norm_members and norm_head not in normed:
            normed[norm_head] = norm_members
    meta = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    return normed, meta


def load_pool(path: str) -> tuple[list[tuple[str, str, str]], dict[str, str]]:
    """Pool rows + {norm_lemma: easiest CEFR} (pure logic over CSV rows)."""
    rows: list[tuple[str, str, str]] = []
    easiest: dict[str, str] = {}
    with open(path, encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            try:
                norm = normalize_lemma(record["lemma"])
            except (ValueError, TypeError, KeyError):
                continue
            cefr = record.get("cefr")
            if cefr not in LEVEL_RANK:
                continue
            rows.append((record["lemma"], record.get("pos", ""), cefr))
            if norm not in easiest or LEVEL_RANK[cefr] < LEVEL_RANK[easiest[norm]]:
                easiest[norm] = cefr
    return rows, easiest


def family_coverage(families: dict[str, list[str]],
                    pool_easiest: dict[str, str]) -> tuple[dict, dict[str, int]]:
    """(a) per-family hit + per-CEFR split of matched families (pure)."""
    hits = 0
    per_cefr: dict[str, int] = {level: 0 for level in LEVEL_ORDER}
    for members in families.values():
        levels = [pool_easiest[m] for m in members if m in pool_easiest]
        if not levels:
            continue
        hits += 1
        per_cefr[min(levels, key=lambda lv: LEVEL_RANK[lv])] += 1
    summary = {"families": len(families), "hit": hits,
               "miss": len(families) - hits,
               "pct": 100.0 * hits / len(families) if families else 0.0}
    return summary, per_cefr


def pool_awl_fraction(rows: list[tuple[str, str, str]],
                      member_norms: set[str]) -> dict:
    """(b) pool rows that are AWL members (pure; normalization reused)."""
    hits = 0
    for lemma, _pos, _cefr in rows:
        try:
            if normalize_lemma(lemma) in member_norms:
                hits += 1
        except (ValueError, TypeError):
            continue
    return {"rows": len(rows), "awl_rows": hits,
            "pct": 100.0 * hits / len(rows) if rows else 0.0}


def is_vowelless_word(word: object) -> bool:
    """Single-token alphabetic word with no vowel (mirrors R5 no_vowel gate)."""
    return (isinstance(word, str) and len(word.strip()) >= 2
            and word.strip().isalpha()
            and not any(ch in VOWELS for ch in word.strip()))


def vowelless_audit(index_path: str, pack_data: dict, lang: str) -> dict:
    """(c) stream the index ONCE; quantify what `drop:no_vowel` costs.

    Returns dict with: scanned lines, total vowel-less alpha rows, pack-hit
    count + samples (real-word signal), classify()-keep per-level
    distribution (pack or zipf — the sampler's real keep rule), and the
    frequent subset (zipf >= 4.0) with top samples. Pure sampler logic is
    reused (classify/zipf), never redefined.
    """
    out = {"scanned": 0, "vowelless_rows": 0, "pack_real": 0,
           "pack_samples": [], "kept_levels": {lv: 0 for lv in LEVEL_ORDER},
           "kept_unique": 0, "frequent": []}
    seen_kept: set[str] = set()
    pack_hit_lemmas: set[str] = set()
    frequent_all: list[tuple[str, str, float]] = []
    with open(index_path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            out["scanned"] += 1
            word = entry.get("word")
            if not is_vowelless_word(word):
                continue
            out["vowelless_rows"] += 1
            pos = entry.get("pos")
            # Single source: pack-hit test lives in sample_lemmas
            # (pack_has_cefr_hit); counted per unique lemma (not per index
            # row) so one word with N POS rows cannot inflate pack_real.
            if pack_has_cefr_hit(word, pos, pack_data):
                try:
                    pack_norm = normalize_lemma(word)
                except (ValueError, TypeError):
                    pack_norm = None
                if pack_norm is not None and pack_norm not in pack_hit_lemmas:
                    pack_hit_lemmas.add(pack_norm)
                    if len(out["pack_samples"]) < SAMPLE_CAP:
                        out["pack_samples"].append(word.strip())
            try:
                norm = normalize_lemma(word)
            except (ValueError, TypeError):
                continue
            if norm in seen_kept:
                continue
            seen_kept.add(norm)
            level = classify(word, pos, pack_data, lang)
            if level is None:
                continue
            out["kept_levels"][level] += 1
            # Lazy wordfreq (same convention as sampler): CI/bot envs may not
            # have it installed; missing library means no frequent-list.
            try:
                from wordfreq import zipf_frequency
            except ImportError:
                continue
            z = zipf_frequency(norm, lang)
            if z >= AUDIT_FREQUENT_ZIPF:
                frequent_all.append((norm, level, round(z, 2)))
    out["kept_unique"] = sum(out["kept_levels"].values())
    out["pack_real"] = len(pack_hit_lemmas)
    out["pack_samples"] = sorted(set(out["pack_samples"]))[:SAMPLE_N]
    frequent_all.sort(key=lambda item: -item[2])
    out["frequent"] = frequent_all[:SAMPLE_N]
    out["frequent_n"] = len(frequent_all)
    return out


def decide_verdict(family_pct: float, pack_real: int, frequent_n: int) -> str:
    if frequent_n >= 20 or pack_real >= 100:
        vowel = ("ADJUST vowel rule (allowlist pack-hit + frequent vowel-less "
                 "words; keep the gate — it blocks mostly initialism junk)")
    elif frequent_n > 0 or pack_real > 0:
        vowel = "PROCEED with allowlist follow-up (vowel-gate cost is small)"
    else:
        vowel = "PROCEED (no vowel-gate recall cost)"
    extra = " + NEEDS exam lists (AWL coverage < 40%)" if family_pct < 40.0 else ""
    return vowel + extra


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    families, meta = load_awl(args.awl)
    rows, pool_easiest = load_pool(args.pool)
    member_norms = {m for members in families.values() for m in members}
    fam_summary, per_cefr = family_coverage(families, pool_easiest)
    pool_summary = pool_awl_fraction(rows, member_norms)
    pack_data = load_pack(args.pack)
    audit = vowelless_audit(args.index, pack_data, args.lang)
    verdict = decide_verdict(fam_summary["pct"], audit["pack_real"],
                             audit["frequent_n"])

    lines = [
        "# AWL coverage vs 10k pool (TICKET F3)",
        "",
        f"- AWL source: {meta.get('source_url', args.awl)} "
        f"(fetched {meta.get('date', 'n/a')}, {fam_summary['families']} families)",
        f"- Pool: `{args.pool}` ({pool_summary['rows']} rows)",
        f"- Index scanned: `{args.index}` ({audit['scanned']} lines)",
        "",
        "## (a) AWL families with >=1 member in pool",
        "",
        f"- **{fam_summary['hit']}/{fam_summary['families']} "
        f"({fam_summary['pct']:.1f}%)**, miss={fam_summary['miss']}",
        "",
        "| CEFR | matched families |",
        "|---|---|",
    ]
    lines += [f"| {level} | {per_cefr[level]} |" for level in LEVEL_ORDER]
    lines += [
        "",
        "## (b) Pool rows that are AWL members",
        "",
        f"- **{pool_summary['awl_rows']}/{pool_summary['rows']} "
        f"({pool_summary['pct']:.1f}%)**",
        "",
        "## (c) Vowel-less recall audit (R5 `drop:no_vowel` cost)",
        "",
        f"- Single-token alphabetic vowel-less index rows: "
        f"**{audit['vowelless_rows']}**",
        f"- …with a pack CEFR hit (strict real-word signal): "
        f"**{audit['pack_real']}**",
        f"- …that classify() would keep (pack or zipf, unique lemmas): "
        f"**{audit['kept_unique']}** {audit['kept_levels']}",
        f"- …thereof frequent (zipf >= {AUDIT_FREQUENT_ZIPF}, genuine recall cost): "
        f"**{audit['frequent_n']}**",
        f"- Pack-hit sample ({len(audit['pack_samples'])} shown): "
        + (", ".join(f"`{s}`" for s in audit["pack_samples"])
           if audit["pack_samples"] else "—"),
        f"- Frequent sample (top {len(audit['frequent'])} by zipf): "
        + (", ".join(f"`{w}` ({lv}, {z})" for w, lv, z in audit["frequent"])
           if audit["frequent"] else "—"),
        "",
        f"## Verdict: {verdict}",
        "",
    ]
    parent = os.path.dirname(os.path.abspath(args.report))
    os.makedirs(parent, exist_ok=True)
    tmp = args.report + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines))
    os.replace(tmp, args.report)

    print(f"AWL family coverage: {fam_summary['hit']}/{fam_summary['families']} "
          f"({fam_summary['pct']:.1f}%)")
    print(f"  per-CEFR: {per_cefr}")
    print(f"Pool AWL fraction: {pool_summary['awl_rows']}/{pool_summary['rows']} "
          f"({pool_summary['pct']:.1f}%)")
    print(f"Vowel-less rows: {audit['vowelless_rows']} "
          f"(scanned {audit['scanned']} index lines)")
    print(f"  pack-hit real words: {audit['pack_real']} "
          f"({', '.join(audit['pack_samples'][:5]) if audit['pack_samples'] else '—'})")
    print(f"  classify-keep (unique): {audit['kept_unique']} {audit['kept_levels']}")
    print(f"  frequent (zipf>={AUDIT_FREQUENT_ZIPF}): {audit['frequent_n']} "
          f"({', '.join(w for w, _, _ in audit['frequent'][:8])})")
    print(f"Verdict: {verdict}")
    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
