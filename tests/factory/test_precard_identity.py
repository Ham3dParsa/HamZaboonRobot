"""Identity T1: the independent precard home speaks real words.

factory/precard owns its version, stage names, progress files, and the
accounting audit. No archive imports anywhere in the package (self
containment, enforced by test_no_archive_imports).
"""

import pathlib

from factory.precard import __version__
from factory.precard import accounting, progress


def test_version_is_145():
    assert __version__ == "1.4.5"


def test_stages_speak_real_words():
    assert progress.STAGES == (
        "preprocess", "inflection_review", "anchor_rank", "sense_judge",
        "topic_vectors", "topic_label", "enrich")


def test_files_keep_resume_compatible_names():
    assert progress.FILES == {
        "preprocess": "preprocess.json",
        "inflection_review": "inflection-review.json",
        "anchor_rank": "anchor.json",
        "sense_judge": "sense-judge.json",
        "topic_vectors": "vectors.json",
        "topic_label": "topic-label.json",
        "enrich": "enrich.json",
    }


def test_legacy_ids_still_normalize():
    assert progress.normalize_stage("s2") == "sense_judge"
    assert progress.normalize_stage("sense-judge") == "sense_judge"
    assert progress.normalize_stage("judge") == "sense_judge"
    assert progress.normalize_stage("s0b") == "inflection_review"
    assert progress.normalize_stage("bogus") == "bogus"


def test_accounting_lives_in_new_home():
    missing = accounting.audit_sample_accounting(
        [{"kind": "word", "text": "apple", "pool_level": "A1"}],
        {"w:apple": {"key": "w:apple"}},
        {"preprocess": {"done": {"w:apple": {"kept": True, "reason": None}},
                        "failed": []}})
    assert missing == []
    # Legacy-keyed states still account (old progress dirs).
    missing = accounting.audit_sample_accounting(
        [{"kind": "word", "text": "FEB", "pool_level": "B1"}],
        {},
        {"s0": {"done": {"w:FEB": {"kept": False, "reason": "g4-abbrev"}},
                "failed": ["w:FEB"]}})
    assert missing == []


def test_no_archive_imports():
    import ast

    package = pathlib.Path(progress.__file__).parent
    banned = ("factory.archive", "factory.pipeline", "factory.lexicon")
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            else:
                continue
            for mod in mods:
                assert not mod.startswith(banned), (path.name, mod)
