"""Linker CLI coverage (OC must-fix on PR #770).

Hermetic: tmp_path mini tables only (never the 9500-row builds), no
network/model. In-process ``main(argv)`` + capsys (cli.main is
import-safe: argparse only, side effects behind ``__main__`` guard).
"""

import csv

import pytest

from factory.linker import cli
from factory.linker.cli import TABLE_FIELDNAMES, main

KID_APPLE = "en-apple-en-noun-AAAA1111"
KID_RUN = "en-run-en-verb-BBBB2222"
KID_BOOK = "en-book-en-verb-CCCC3333"

MINI_ROWS = [
    {
        "kaikki_sense_id": KID_APPLE,
        "wordnet_sensekey": "apple%1:13:00::",
        "method": "LINK:2-sig",
        "evidence": "Sa:j=0.50",
        "provenance": "unit-test",
    },
    {
        "kaikki_sense_id": KID_RUN,
        "wordnet_sensekey": "run%2:38:00::",
        "method": "twin-pending",
        "evidence": "best-cand-twinned;tsv-cefr=A1",
        "provenance": "unit-test",
    },
    {
        "kaikki_sense_id": KID_BOOK,
        "wordnet_sensekey": "-",
        "method": "MANUAL-NONE",
        "evidence": "owner-locked:E1",
        "provenance": "unit-test",
    },
]


def _write_table(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=TABLE_FIELDNAMES, delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def _write_wordlist(path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _read_rows(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def test_link_subset_keeps_matching_rows(tmp_path, capsys):
    table = _write_table(tmp_path / "mini.tsv", MINI_ROWS)
    words = _write_wordlist(tmp_path / "words.txt", [
        "apple",  # headword prefix match on KID_APPLE
        KID_RUN,  # exact kid match
        "zzz-no-such-word",
    ])
    out = str(tmp_path / "subset.tsv")

    rc = main(["link", "--words", words, "--out", out, "--table", table])

    assert rc == 0
    kept = _read_rows(out)
    assert {r["kaikki_sense_id"] for r in kept} == {KID_APPLE, KID_RUN}


def test_link_no_match_writes_header_only(tmp_path, capsys):
    table = _write_table(tmp_path / "mini.tsv", MINI_ROWS)
    words = _write_wordlist(tmp_path / "words.txt", ["zzz-no-such-word"])
    out = str(tmp_path / "subset.tsv")

    rc = main(["link", "--words", words, "--out", out, "--table", table])

    assert rc == 0
    assert _read_rows(out) == []
    with open(out, encoding="utf-8") as fh:
        assert fh.readline().strip().split("\t") == list(TABLE_FIELDNAMES)


def test_link_zero_kept_warns_on_stderr(tmp_path, capsys):
    table = _write_table(tmp_path / "mini.tsv", MINI_ROWS)
    words = _write_wordlist(tmp_path / "words.txt", ["zzz-no-such-word"])
    out = str(tmp_path / "subset.tsv")

    rc = main(["link", "--words", words, "--out", out,
               "--table", table, "--progress"])

    assert rc == 0
    err = capsys.readouterr().err
    assert "warning: 0 rows matched" in err
    assert "kept=0" in err


def test_lookup_hit_exits_zero_with_row(tmp_path, capsys):
    table = _write_table(tmp_path / "mini.tsv", MINI_ROWS)

    rc = main(["lookup", KID_APPLE, "--table", table])

    assert rc == 0
    out = capsys.readouterr().out
    assert KID_APPLE in out
    assert "apple%1:13:00::" in out


def test_lookup_miss_exits_one(tmp_path, capsys):
    table = _write_table(tmp_path / "mini.tsv", MINI_ROWS)

    rc = main(["lookup", "en-missing-en-noun-XXXX0000", "--table", table])

    assert rc == 1
    captured = capsys.readouterr()
    assert "no rows for" in captured.err
    assert captured.out == ""


def test_stats_counts_match_live_table(capsys):
    # Expected counts derived from a live read of the shipped table —
    # never a hardcoded competitor of the CLI's own aggregation.
    header, rows = cli.read_table(str(cli.DEFAULT_TABLE))
    assert header and len(rows) == 141
    linked = sum(1 for r in rows if r.get("method", "").startswith("LINK"))
    twins = sum(1 for r in rows if r.get("method") == "twin-pending")
    quarantined = sum(
        1 for r in rows if r.get("method") == "quarantined-known-false")
    manual_none = sum(1 for r in rows if r.get("method") == "MANUAL-NONE")
    assert (linked, twins, quarantined, manual_none) == (90, 47, 1, 3)

    rc = main(["stats", str(cli.DEFAULT_TABLE)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "rows=%d" % len(rows) in out
    assert "LINK: %d" % linked in out
    assert "twin-pending: %d" % twins in out
    assert "quarantined-known-false: %d" % quarantined in out
    assert "MANUAL-NONE: %d" % manual_none in out


def test_validate_ok_on_shipped_table(capsys):
    rc = main(["validate", str(cli.DEFAULT_TABLE)])

    assert rc == 0
    assert "OK:" in capsys.readouterr().out


def test_validate_fail_on_link_without_evidence(tmp_path, capsys):
    bad = dict(MINI_ROWS[0])
    bad["evidence"] = ""  # LINK rows must carry evidence
    table = _write_table(tmp_path / "bad.tsv", [bad])

    rc = main(["validate", table])

    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL:" in out
    assert "LINK without evidence" in out


def test_cli_module_import_safe_for_subprocess_fallback():
    # Contract: ``python -m factory.linker.cli`` must stay import-safe so
    # tests can prefer in-process main(); a subprocess fallback is only
    # justified if this ever regresses.
    assert callable(cli.main)
    assert callable(cli.build_parser)
    with pytest.raises(SystemExit):
        cli.main(["no-such-command"])
