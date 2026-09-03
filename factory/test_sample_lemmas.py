"""Hermetic tests for factory/sample_lemmas.py (TICKET T2).

All fixtures (mini-dump + index + pack) are built inline in temp dirs.
Classification is driven by synthetic cefrj fallback entries only, so the
tests never depend on wordfreq data or the real W: dump.
"""

import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from sample_lemmas import LEVEL_ORDER, main

LEVELS = LEVEL_ORDER
QUOTA = 3
MIX = ",".join([str(QUOTA)] * 6)
CANDIDATES_PER_LEVEL = 6


def build_pack(pack_dir, pilot_rows, fallback):
    os.makedirs(pack_dir, exist_ok=True)
    with open(os.path.join(pack_dir, "evp_sense.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"_meta": {}, "entries": {}}))
    with open(os.path.join(pack_dir, "cefrj_pos.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"_meta": {}, "fallback": fallback}))
    with open(os.path.join(pack_dir, "pack.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"cefr": {"zipf_cutoffs": [5.2, 4.6, 4.0, 3.5, 3.0]}}))
    with open(os.path.join(pack_dir, "lemmas.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["lemma", "pos", "cefr"])
        writer.writerows(pilot_rows)


def build_dump_index(tmp, words):
    dump = os.path.join(tmp, "dump.jsonl")
    index = os.path.join(tmp, "index.jsonl")
    with open(dump, "wb") as dump_handle, open(index, "w", encoding="utf-8") as idx_handle:
        for word, pos in words:
            raw = (json.dumps({"word": word, "pos": pos, "senses": []},
                              ensure_ascii=False) + "\n").encode("utf-8")
            offset = dump_handle.tell()
            dump_handle.write(raw)
            idx_handle.write(json.dumps({"word": word, "pos": pos,
                                         "offset": offset, "length": len(raw)},
                                        ensure_ascii=False) + "\n")
    lookup = os.path.join(tmp, "lookup.json")
    with open(lookup, "w", encoding="utf-8") as handle:
        handle.write("{}")
    return dump, index, lookup


@pytest.fixture()
def env(tmp_path):
    pack = str(tmp_path / "pack")
    pilot_rows = [(f"Pilot{level}", "noun", level) for level in LEVELS]
    fallback = {}
    words = []
    for level in LEVELS:
        for num in range(CANDIDATES_PER_LEVEL):
            word = f"zzq_{level.lower()}_{num}"
            fallback[f"{word}|noun"] = level
            words.append((word, "noun"))
    words.append(("zzq_nonsense_nowhere", "noun"))  # no pack hit, zipf 0 -> skip
    build_pack(pack, pilot_rows, fallback)
    dump, index, lookup = build_dump_index(str(tmp_path), words)
    return {
        "pack": pack,
        "dump": dump,
        "index": index,
        "lookup": lookup,
        "out": str(tmp_path / "out.csv"),
        "progress": str(tmp_path / "progress.json"),
        "pilot_rows": pilot_rows,
    }


def base_argv(env, **overrides):
    argv = ["--lang", "en", "--dump", env["dump"], "--index", env["index"],
            "--lookup", env["lookup"], "--pack", env["pack"],
            "--out", env["out"], "--progress", env["progress"],
            "--mix", MIX, "--seed", "7", "--batch", "4"]
    for key, value in overrides.items():
        argv += [key, str(value)]
    return argv


def read_rows(out):
    with open(out, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_mix_quotas_exact(env):
    assert main(base_argv(env)) == 0
    rows = read_rows(env["out"])
    assert len(rows) == QUOTA * 6
    for level in LEVELS:
        assert sum(1 for row in rows if row["cefr"] == level) == QUOTA


def test_pilot_pinning_respected(env):
    assert main(base_argv(env)) == 0
    rows = read_rows(env["out"])
    by_lemma = {row["lemma"]: row for row in rows}
    for lemma, pos, cefr in env["pilot_rows"]:
        assert by_lemma[lemma]["cefr"] == cefr
        assert by_lemma[lemma]["pos"] == pos
    assert "zzq_nonsense_nowhere" not in by_lemma


def test_output_sorted_and_header(env):
    assert main(base_argv(env)) == 0
    with open(env["out"], "rb") as handle:
        raw = handle.read()
    assert b"\r" not in raw
    lines = raw.decode("utf-8").split("\n")
    assert lines[0] == "lemma,pos,cefr"
    rows = read_rows(env["out"])
    keys = [(LEVELS.index(row["cefr"]),
             f"{row['lemma'].strip().lower()}|{row['pos'].strip().lower()}")
            for row in rows]
    assert keys == sorted(keys)


def test_determinism_same_seed(env, tmp_path):
    assert main(base_argv(env)) == 0
    with open(env["out"], "rb") as handle:
        first = handle.read()
    out2 = str(tmp_path / "out2.csv")
    argv = base_argv(env)
    argv[argv.index("--out") + 1] = out2
    assert main(argv) == 0
    with open(out2, "rb") as handle:
        assert handle.read() == first


def test_different_seed_differs(env, tmp_path):
    assert main(base_argv(env)) == 0
    with open(env["out"], "rb") as handle:
        first = handle.read()
    for seed in range(8, 30):
        out = str(tmp_path / f"out{seed}.csv")
        argv = base_argv(env)
        argv[argv.index("--seed") + 1] = str(seed)
        argv[argv.index("--out") + 1] = out
        assert main(argv) == 0
        with open(out, "rb") as handle:
            if handle.read() != first:
                return
    raise AssertionError("seeds 8..29 all matched seed 7")


def test_dry_run_writes_nothing(env, capsys):
    out_dry = env["out"] + ".dry.csv"
    argv = base_argv(env) + ["--dry-run", "--limit", "10"]
    argv[argv.index("--out") + 1] = out_dry
    assert main(argv) == 0
    assert "dry-run" in capsys.readouterr().out
    assert not os.path.exists(out_dry)
    assert not os.path.exists(env["progress"])


def test_stale_progress_aborts(env):
    seen = {level: 0 for level in LEVELS}
    reservoirs = {level: [] for level in LEVELS}
    stat = os.stat(env["dump"])
    with open(env["progress"], "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "lang": "en", "seed": 7, "mix": MIX,
            "dump_size": stat.st_size + 1,  # stale on purpose
            "dump_mtime": stat.st_mtime, "lines_done": 0,
            "seen": seen, "reservoirs": reservoirs,
            "rng": [1, [0] * 625, None]}))
    with pytest.raises(SystemExit):
        main(base_argv(env))
    assert not os.path.exists(env["out"])


def test_resume_equals_fresh_run(env, tmp_path):
    assert main(base_argv(env)) == 0
    with open(env["out"], "rb") as handle:
        fresh = handle.read()
    assert os.path.exists(env["progress"]) is False  # completed run cleans up
    # Simulate an interrupted run: partial pass writes a checkpoint...
    out_part = str(tmp_path / "part.csv")
    argv = base_argv(env, **{"--limit": 10})
    argv[argv.index("--out") + 1] = out_part
    assert main(argv) == 0
    assert os.path.exists(env["progress"])
    os.unlink(out_part)
    # ...then resume to completion with identical output.
    out_resumed = str(tmp_path / "resumed.csv")
    argv = base_argv(env)
    argv[argv.index("--out") + 1] = out_resumed
    assert main(argv) == 0
    with open(out_resumed, "rb") as handle:
        assert handle.read() == fresh


def test_pilot_over_quota_aborts(env, tmp_path):
    pack = str(tmp_path / "pack_over")
    pilot_rows = [(f"Extra{i}", "noun", "A1") for i in range(QUOTA + 1)]
    fallback = {f"zzq_a1_{num}|noun": "A1" for num in range(3)}
    build_pack(pack, pilot_rows, fallback)
    argv = base_argv(env)
    argv[argv.index("--pack") + 1] = pack
    with pytest.raises(SystemExit):
        main(argv)
    assert not os.path.exists(env["out"])
