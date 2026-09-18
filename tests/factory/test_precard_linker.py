"""Linker witness tests (CI-executed; doctests in linker.py do not run in CI).

Mirrors the frozen REPORT_v0_5/v0_6/v0_7 witness rows: TRUE links stay
LINKed, FALSE rows park, and the shipped vendor table validates clean.
"""

import csv
import pathlib

from factory.precard import linker


TABLE = (pathlib.Path(__file__).resolve().parents[2]
         / "factory" / "precard" / "data" / "link_table.tsv")


def test_sa_move_only_overlap_never_fires():
    j, fires = linker.signal_sa(
        {"rumor", "move", "report", "hearsay"},
        {"run", "move", "flow", "stream"})
    assert (round(j, 2), fires) == (0.0, False)


def test_sb_cause_dead_under_cause_rule():
    assert linker.signal_sb(
        {"cause", "come", "go", "move"}, set(), {"stimulate"}) == []


def test_sb_bear_support_stays():
    assert linker.signal_sb(
        {"support", "hold"}, set(), {"hold", "carry", "bear"}) == ["hold"]


def test_match_exact_join():
    assert linker.match_exact(
        ["get%2:35:03::", "run%1:28:00::"], ["run%1:28:00::"]) == ["run%1:28:00::"]
    assert linker.match_exact(["a%1:01:00::"], ["b%1:02:00::"]) == []


def test_decide_true_link_stays():
    d = linker.decide(
        "en-light-en-noun-en:source_of_illumination",
        "light_source%1:06:00::", ["Sa:j=0.27", "Sb:source"],
        se_value=0.677, sa_words={"source"})
    assert (d["method"], d["flags"]) == ("LINK:2-sig", [])


def test_decide_single_signal_parks():
    d = linker.decide(
        "en-arrival-en-noun-X", "become%2:38:00::", ["Sa:j=0.27"])
    assert (d["sensekey"], d["method"]) == (
        "become%2:38:00::", "JUDGE-PENDING")


def test_decide_ultra_short_parks_with_best_cand():
    d = linker.decide(
        "en-mistake-en-noun-kjZERp8U", "mistake%1:04:00::",
        ["Sb:error,fault"], ultra_short=True)
    assert (d["method"], d["evidence"]) == (
        "JUDGE-PENDING", "short-gloss:Sb:error,fault")


def test_decide_twin_suppresses():
    d = linker.decide(
        "en-outside-en-adv-E7dgXPoq", "outside%4:02:00::", ["Sa:j=0.40"],
        is_twin=True, twin_cefr=("A1", "A2"))
    assert (d["method"], d["evidence"], d["flags"]) == (
        "twin-pending", "best-cand-twinned;tsv-cefr=A1,A2", ["twin-pending"])


def test_decide_quarantine_holds():
    d = linker.decide(
        "en-book-en-verb-hoaZwz7Y", "book%2:41:00::",
        ["Sa:j=0.33", "Sd:hyp=record"], se_value=0.437,
        sa_words={"record"})
    assert (d["method"], d["flags"]) == (
        "quarantined-known-false", ["quarantined-known-false"])


def test_decide_manual_none():
    d = linker.decide(
        "en-light-en-noun-en:Q12969754", "visible_radiation%1:19:00::",
        ["Sa:j=0.29", "Sb:radiation"],
        manual_none="owner-locked:E1")
    assert (d["sensekey"], d["method"], d["flags"]) == (
        "-", "MANUAL-NONE", ["manual-none"])


def test_shipped_table_validates_clean():
    with TABLE.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len(rows) == 141
    assert linker.validate_table_rows(rows) == []
    flagged = [r for r in rows if r["method"] in (
        "twin-pending", "quarantined-known-false", "MANUAL-NONE")]
    assert flagged
    assert all(not r["method"].startswith("LINK") for r in flagged)
