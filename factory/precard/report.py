"""Proof HTML report for a precard run (v1.4.1).

Reads <proof-dir>/precard.jsonl + dropped.log (+ optionally a run log
for judge-dropped proper nouns) and writes one self-contained HTML page
in the v141 shape: per-lemma h2, sense cards with topics/examples/level,
dropcards for dropped inputs.

Stdlib only (keeps the factory/precard self-containment rule).

Usage (from repo root):
    python -m factory.precard.report --proof-dir <dir> --sample <sample.json>
        [--limit 50] [--run-log run.log] [--name <name>] [--out <report.html>]
        [--title <title>]
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import OrderedDict
from pathlib import Path

__all__ = [
    "build_report",
    "load_order",
    "load_rows",
    "load_dropped",
    "render_card",
    "esc",
    "main",
]

CSS = (
    "body{font-family:Tahoma,sans-serif;max-width:1100px;margin:auto;"
    "padding:24px;background:#fafafa;color:#222}"
    ".en{font-family:Consolas,monospace;direction:ltr;"
    "unicode-bidi:embed;font-size:13px}"
    ".card{background:#fff;border:1px solid #ddd;border-radius:10px;"
    "padding:12px 16px;margin:10px 0}"
    ".row{margin-top:6px;font-size:14px}.lvl{color:#666;font-size:12px}"
    ".pair{display:flex;gap:10px}.pair>div{flex:1}"
    ".hl{background:#fff3cd;border-radius:4px;padding:0 3px}"
    ".dropcard{border-color:#e0a0a0}"
)

_PROPER_RE = re.compile(r"w:([A-Za-z]+):pick-proper-noun/([^\s,)]+)")


def esc(value):
    return html.escape(str(value), quote=False)


def load_order(sample_path, limit):
    sample = json.loads(Path(sample_path).read_text(encoding="utf-8"))
    items = sample if isinstance(sample, list) else sample.get("items", sample)
    order = []
    for item in items[:limit]:
        key = item.get("key") if isinstance(item, dict) else None
        if key and key not in order:
            order.append(key)
    return order


def load_rows(proof_dir):
    rows = OrderedDict()
    with open(Path(proof_dir) / "precard.jsonl", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rows.setdefault(rec["key"], []).append(rec)
    return rows


def load_dropped(proof_dir, run_log=None):
    dropped = OrderedDict()
    drop_path = Path(proof_dir) / "dropped.log"
    if drop_path.exists():
        for line in drop_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("===") or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) >= 3:
                dropped.setdefault(parts[0] + ":" + parts[1],
                                   ":".join(parts[2:]).strip())
    # Judge-dropped proper nouns are only logged in the run log.
    if run_log:
        log_path = Path(proof_dir) / run_log
        if log_path.exists():
            for match in _PROPER_RE.finditer(
                    log_path.read_text(encoding="utf-8")):
                dropped.setdefault("w:" + match.group(1),
                                   "pick-proper-noun/" + match.group(2))
    return dropped


def render_card(rec):
    topics = " ".join(
        "%s %.2f" % (entry["label"], entry["weight"])
        for entry in (rec.get("topic_vector") or []))
    examples = rec.get("dataset_examples") or []
    ex_html = "".join("<div class='en'>%s</div>" % esc(x) for x in examples)
    return (
        "<div class='card'><div class='row'>sense: %s</div>"
        "<div class='en'>%s</div>"
        "<div class='row'>topics: %s</div>"
        "<div class='row'>examples(%d): %s</div>"
        "<div class='lvl'>%s | cefr=%s | ipa=%s | id=%s</div></div>"
        % (esc(rec.get("sense_id", "")), esc(rec.get("en_def", "")),
           esc(topics), len(examples), ex_html or "—",
           esc(rec.get("pool_level", "")), esc(rec.get("sense_cefr", "")),
           esc(rec.get("ipa") or "—"), esc(rec.get("pre_card_id", ""))))


def build_report(proof_dir, sample_path, limit=50, run_log=None,
                  out_path=None, title=None, name=None):
    """Build the report; returns {"rows", "lemmas", "out"}."""
    proof = Path(proof_dir)
    if name and not title:
        title = "%s — precard v1.4.1 fan-out" % name
    title = title or ("%s — precard v1.4.1 fan-out" % proof.name)
    order = load_order(sample_path, limit)
    rows = load_rows(proof)
    dropped = load_dropped(proof, run_log)
    keys = [k for k in order if k in rows or k in dropped]
    keys += [k for k in list(rows) + list(dropped) if k not in keys]
    n_rows = sum(len(v) for v in rows.values())
    out = ["<!DOCTYPE html><html lang='fa' dir='rtl'><head>"
           "<meta charset='utf-8'><title>%s</title><style>%s</style>"
           "</head><body><h1>%s</h1><p>rows=%d lemmas=%d</p>"
           % (esc(title), CSS, esc(title), n_rows, len(keys))]
    for key in keys:
        label = rows[key][0]["text"] if key in rows else key.split(":", 1)[-1]
        out.append("<h2>%s <span class='en'>%s</span></h2>"
                   % (esc(label), esc(key)))
        for rec in rows.get(key, []):
            out.append(render_card(rec))
        if key in dropped:
            out.append("<div class='card dropcard'>dropped: %s</div>"
                       % esc(dropped[key]))
    out.append("</body></html>")
    dest = Path(out_path) if out_path else proof / ("%s.html" % name if name else "report.html")
    dest.write_text("".join(out), encoding="utf-8")
    return {"rows": n_rows, "lemmas": len(keys), "out": str(dest)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--proof-dir", required=True,
                    help="dir with precard.jsonl + dropped.log")
    ap.add_argument("--sample", required=True, help="sample json file")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--run-log", default=None,
                    help="run log filename inside proof-dir "
                         "(for judge-dropped proper nouns)")
    ap.add_argument("--out", default=None, help="report path "
                    "(default <proof-dir>/<name>.html with --name, "
                    "else <proof-dir>/report.html)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--name", default=None, help="report name: sets "
                    "default out to <proof-dir>/<name>.html and default "
                    "title to '<name> — precard v1.4.1 fan-out' "
                    "(explicit --out/--title win)")
    args = ap.parse_args(argv)
    precard_path = Path(args.proof_dir) / "precard.jsonl"
    if not precard_path.is_file():
        ap.error("missing precard.jsonl in proof-dir: %s" % args.proof_dir)
    if not Path(args.sample).is_file():
        ap.error("missing sample file: %s" % args.sample)
    stats = build_report(args.proof_dir, args.sample, args.limit,
                         args.run_log, args.out, args.title, args.name)
    print("wrote %(out)s rows=%(rows)d lemmas=%(lemmas)d" % stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
