"""Render a standalone card-gallery HTML for a factory run.

Takes a gallery-rows JSON file (a list of dicts with the same shape as the
``CARDS`` sample embedded in ``card_gallery.html``) and injects it between
the ``GALLERY_DATA_START``/``GALLERY_DATA_END`` markers of the template,
writing a self-contained HTML file that opens with a double-click (no server).

Row schema (only ``word`` is required; everything else gets a safe default):
    word, kind, status_ok, error_msg, cefr, sense_id, anchor_def, topic,
    model, ipa, fa_meaning, fa_explanation, en_def, examples[],
    example_translations[], synonyms[], antonyms[], grammar_tip,
    diff_rows[{label, pre, op, fin}], gates[{name, status, pass}], raw_json.

Source: card_pilot complete-card records (``cards.jsonl``) reshaped to the
above rows. The reshaping exporter is deliberately deferred until the
completion line stabilizes — this script stays decoupled behind rows JSON.

Usage (from repo root):
    python -m factory.pipeline.render_gallery --data <rows.json> --out <run.html>
"""

import argparse
import json
import re
import sys
from pathlib import Path

TEMPLATE_NAME = "card_gallery.html"
START_MARKER = "/*GALLERY_DATA_START*/"
END_MARKER = "/*GALLERY_DATA_END*/"

# Defaults keep every template tab (learner + audit) working when a run
# does not provide that field.
ROW_DEFAULTS = {
    "kind": "واژه",
    "status_ok": True,
    "error_msg": "",
    "cefr": "A1",
    "sense_id": "",
    "anchor_def": "",
    "topic": "",
    "model": "",
    "ipa": "",
    "fa_meaning": "",
    "fa_explanation": "",
    "en_def": "",
    "examples": [],
    "example_translations": [],
    "synonyms": [],
    "antonyms": [],
    "grammar_tip": "",
    "diff_rows": [],
    "gates": [],
    "raw_json": {},
}


def normalize_rows(rows):
    if not isinstance(rows, list):
        raise ValueError("data file must contain a JSON list of row objects")
    normalized = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {i} is not an object")
        if not row.get("word"):
            raise ValueError(f"row {i} is missing required key 'word'")
        merged = dict(ROW_DEFAULTS)
        merged.update(row)
        merged["id"] = i
        normalized.append(merged)
    return normalized


def render(template_path, rows):
    template = Path(template_path).read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL
    )
    if len(pattern.findall(template)) != 1:
        raise ValueError("template must contain exactly one GALLERY_DATA block")
    payload = START_MARKER + json.dumps(rows, ensure_ascii=False) + END_MARKER
    return pattern.sub(lambda _: payload, template)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render a card-gallery HTML run.")
    parser.add_argument("--data", required=True, help="gallery-rows JSON file")
    parser.add_argument("--out", required=True, help="output HTML path (caller-chosen)")
    parser.add_argument(
        "--template",
        default=str(Path(__file__).with_name(TEMPLATE_NAME)),
        help="template HTML (default: card_gallery.html next to this script)",
    )
    args = parser.parse_args(argv)

    rows = normalize_rows(json.loads(Path(args.data).read_text(encoding="utf-8-sig")))
    html = render(args.template, rows)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    ok = sum(1 for r in rows if r["status_ok"])
    print(f"gallery: {len(rows)} cards ({ok} ok, {len(rows) - ok} error) -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
