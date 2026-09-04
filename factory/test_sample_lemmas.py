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
from sample_lemmas import LEVEL_ORDER, classify, is_vowelless_allowlisted, load_pack, load_pilot, main, pack_has_cefr_hit, shape_verdict

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
            # Shape-clean on purpose (alpha, vowel, no digits/underscores):
            # the R5 shape filter intentionally drops digit/underscore rows.
            word = f"wobble{chr(97 + LEVELS.index(level))}{chr(97 + num)}"
            fallback[f"{word}|noun"] = level
            words.append((word, "noun"))
    words.append(("qxwzea", "noun"))  # no pack hit, zipf 0 -> skip
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
    assert "qxwzea" not in by_lemma


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


def test_resume_equals_fresh_run(env, tmp_path, capsys):
    assert main(base_argv(env)) == 0
    with open(env["out"], "rb") as handle:
        fresh = handle.read()
    fresh_counters = _counters_line(capsys.readouterr().out)
    assert os.path.exists(env["progress"]) is False  # completed run cleans up
    # Simulate an interrupted run: partial pass writes a checkpoint...
    out_part = str(tmp_path / "part.csv")
    argv = base_argv(env, **{"--limit": 10})
    argv[argv.index("--out") + 1] = out_part
    assert main(argv) == 0
    assert os.path.exists(env["progress"])
    os.unlink(out_part)
    capsys.readouterr()  # discard partial-run output; compare resume vs fresh only
    # ...then resume to completion with identical output AND counters.
    # Contract: a resumed run must report the same diagnostic counters as an
    # uninterrupted run (counters are checkpointed, not restarted at zero).
    out_resumed = str(tmp_path / "resumed.csv")
    argv = base_argv(env)
    argv[argv.index("--out") + 1] = out_resumed
    assert main(argv) == 0
    with open(out_resumed, "rb") as handle:
        assert handle.read() == fresh
    assert _counters_line(capsys.readouterr().out) == fresh_counters


def _counters_line(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("counters: "):
            return line
    raise AssertionError("counters line missing from sampler output")


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


def test_resume_corrupt_reservoir_aborts_loud(env):
    # A checkpoint reservoir record with an empty pos is unusable:
    # resume must fail closed with SystemExit naming the file, never a
    # bare ValueError traceback from lemma_key_for.
    seen = {level: 0 for level in LEVELS}
    reservoirs = {level: [] for level in LEVELS}
    reservoirs["A1"] = [["zzq_broken", "", "A1", 0, 10]]
    stat = os.stat(env["dump"])
    with open(env["progress"], "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "lang": "en", "seed": 7, "mix": MIX,
            "dump_size": stat.st_size, "dump_mtime": stat.st_mtime,
            "shape_v": 2, "lines_done": 0, "seen": seen, "counters": {},
            "reservoirs": reservoirs,
            "rng": [3, [0] * 625, None]}))
    with pytest.raises(SystemExit) as excinfo:
        main(base_argv(env))
    assert "progress" in str(excinfo.value).lower()
    assert "corrupt reservoir" in str(excinfo.value).lower()
    assert not os.path.exists(env["out"])


def test_resume_pre_r5_checkpoint_aborts_loud(env):
    # A checkpoint without a counters key (pre-R5 format) must fail closed
    # instead of silently resuming with zeroed diagnostic counters.
    seen = {level: 0 for level in LEVELS}
    reservoirs = {level: [] for level in LEVELS}
    stat = os.stat(env["dump"])
    with open(env["progress"], "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "lang": "en", "seed": 7, "mix": MIX,
            "dump_size": stat.st_size, "dump_mtime": stat.st_mtime,
            "shape_v": 2, "lines_done": 0, "seen": seen,
            "reservoirs": reservoirs,
            "rng": [3, [0] * 625, None]}))
    with pytest.raises(SystemExit) as excinfo:
        main(base_argv(env))
    assert "counters" in str(excinfo.value).lower()
    assert not os.path.exists(env["out"])


def test_resume_missing_shape_version_aborts_loud(env):
    # A pre-F2b checkpoint (no shape_v: allowed_vowelless backfilled 0,
    # dropped vowel-less keys pre-seeded as duplicates) must fail closed
    # instead of silently mixing shape rule regimes.
    from sample_lemmas import SHAPE_VERSION

    assert SHAPE_VERSION == 2
    seen = {level: 0 for level in LEVELS}
    reservoirs = {level: [] for level in LEVELS}
    stat = os.stat(env["dump"])
    with open(env["progress"], "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "lang": "en", "seed": 7, "mix": MIX,
            "dump_size": stat.st_size, "dump_mtime": stat.st_mtime,
            "lines_done": 0, "seen": seen,
            "counters": {"bad_index_lines": 0, "duplicates": 0,
                         "skipped_no_freq": 0, "skipped_shape": 0,
                         "allowed_vowelless": 0, "phrase_candidates": 0},
            "reservoirs": reservoirs,
            "rng": [3, [0] * 625, None]}))
    with pytest.raises(SystemExit) as excinfo:
        main(base_argv(env))
    assert "shape_v" in str(excinfo.value).lower()
    assert not os.path.exists(env["out"])


def test_resume_shape_version_mismatch_aborts_loud(env):
    # shape_v=1 (pre-F2b rules) against current v2: same fail-closed abort.
    seen = {level: 0 for level in LEVELS}
    reservoirs = {level: [] for level in LEVELS}
    stat = os.stat(env["dump"])
    with open(env["progress"], "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "lang": "en", "seed": 7, "mix": MIX,
            "dump_size": stat.st_size, "dump_mtime": stat.st_mtime,
            "shape_v": 1, "lines_done": 0, "seen": seen,
            "counters": {"bad_index_lines": 0, "duplicates": 0,
                         "skipped_no_freq": 0, "skipped_shape": 0,
                         "allowed_vowelless": 0, "phrase_candidates": 0},
            "reservoirs": reservoirs,
            "rng": [3, [0] * 625, None]}))
    with pytest.raises(SystemExit) as excinfo:
        main(base_argv(env))
    assert "shape_v" in str(excinfo.value).lower()
    assert not os.path.exists(env["out"])


def test_resume_new_checkpoint_counter_parity_with_allowlist(tmp_path, capsys):
    # A v2 checkpoint resumes with counter parity INCLUDING allowed_vowelless:
    # partial run, then resume, reports the same counters as a fresh run.
    pack = str(tmp_path / "pack")
    pilot_rows = [("PilotA1", "noun", "A1")]
    fallback = {"rhythm|noun": "A1", "wobbleaaa|noun": "A1"}
    build_pack(pack, pilot_rows, fallback)
    dump_dir = str(tmp_path / "d")
    os.makedirs(dump_dir, exist_ok=True)
    dump, index, lookup = build_dump_index(
        dump_dir, [("rhythm", "noun"), ("wobbleaaa", "noun")])
    out = str(tmp_path / "out.csv")
    progress = str(tmp_path / "progress.json")

    def argv_for(out_path, extra=()):
        return (["--lang", "en", "--dump", dump, "--index", index,
                 "--lookup", lookup, "--pack", pack,
                 "--out", out_path, "--progress", progress,
                 "--mix", "3,0,0,0,0,0", "--seed", "7", "--batch", "1"]
                + list(extra))

    assert main(argv_for(out)) == 0
    with open(out, "rb") as handle:
        fresh = handle.read()
    fresh_counters = _counters_line(capsys.readouterr().out)
    assert "'allowed_vowelless': 1" in fresh_counters
    out_part = str(tmp_path / "part.csv")
    assert main(argv_for(out_part, ["--limit", "1"])) == 0
    assert os.path.exists(progress)
    os.unlink(out_part)
    capsys.readouterr()
    out_resumed = str(tmp_path / "resumed.csv")
    assert main(argv_for(out_resumed)) == 0
    with open(out_resumed, "rb") as handle:
        assert handle.read() == fresh
    assert _counters_line(capsys.readouterr().out) == fresh_counters


def test_duplicate_pilot_row_skipped_keep_first(env, tmp_path, capsys):
    # Same lemma_key twice (differing only by case/whitespace/level):
    # keep-first wins, the dupe warns + counts as pilot_dupes, and the
    # per-level quotas stay exact.
    pack = str(tmp_path / "pack_dupe")
    pilot_rows = [(f"Pilot{level}", "noun", level) for level in LEVELS]
    pilot_rows.append(("  PILOTa1 ", "Noun", "C2"))  # dupe of PilotA1
    fallback = {}
    words = []
    for level in LEVELS:
        for num in range(CANDIDATES_PER_LEVEL):
            word = f"wobble{chr(97 + LEVELS.index(level))}{chr(97 + num)}"
            fallback[f"{word}|noun"] = level
            words.append((word, "noun"))
    build_pack(pack, pilot_rows, fallback)
    dump_dir = str(tmp_path / "d")
    os.makedirs(dump_dir, exist_ok=True)
    dump, index, lookup = build_dump_index(dump_dir, words)
    out = str(tmp_path / "out.csv")
    progress = str(tmp_path / "progress.json")
    argv = ["--lang", "en", "--dump", dump, "--index", index,
            "--lookup", lookup, "--pack", pack,
            "--out", out, "--progress", progress,
            "--mix", MIX, "--seed", "7", "--batch", "4"]
    rows, bad, dupes = load_pilot(pack)
    assert dupes == 1 and bad == 0
    assert sum(1 for row in rows if row[2] == "A1") == 1
    assert main(argv) == 0
    out_text = capsys.readouterr().out
    assert "duplicate pilot row" in out_text
    assert "'pilot_dupes': 1" in out_text
    with open(out, encoding="utf-8", newline="") as handle:
        got = list(csv.DictReader(handle))
    assert len(got) == QUOTA * 6
    for level in LEVELS:
        assert sum(1 for row in got if row["cefr"] == level) == QUOTA
    by_lemma = {row["lemma"]: row for row in got}
    assert by_lemma["PilotA1"]["cefr"] == "A1"  # first row kept, not C2


def test_classify_matches_legacy_scan(tmp_path, monkeypatch):
    # Differential test for the evp pre-index refactor: classify() must
    # return exactly what the old per-line startswith scan returned, over
    # a matrix of tricky keys (multi-sense, 2-segment, bare, bad level).
    import sys as _sys

    from registry import normalize_lemma, normalize_pos

    class _FakeWordfreq:
        @staticmethod
        def zipf_frequency(lemma, lang):
            return 0.0

    monkeypatch.setitem(_sys.modules, "wordfreq", _FakeWordfreq)
    pack = str(tmp_path / "pack")
    pilot_rows = [("PilotA1", "noun", "A1")]
    fallback = {"qx_zeta|noun": "B1"}
    build_pack(pack, pilot_rows, fallback)
    entries = {
        "qx_alpha|noun|s1": {"cefr": "B2"},
        "qx_alpha|noun|s2": {"cefr": "A2"},  # easiest wins
        "qx_alpha|verb|s1": {"cefr": "C1"},
        "qx_alpha|noun|s3": {"cefr": "Z9"},  # invalid level ignored
        "qx_beta|noun": {"cefr": "A1"},  # 2 segments: never a qualified hit
        "qx_gamma": {"cefr": "A1"},  # bare: never a hit
        "qx_delta|x|a|b": {"cefr": "B1"},  # 4 segments group fine
    }
    with open(os.path.join(pack, "evp_sense.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"_meta": {}, "entries": entries}))
    pack_data = load_pack(pack)

    def legacy(word, pos):
        try:
            lemma_norm = normalize_lemma(word)
        except (ValueError, TypeError):
            return None
        try:
            pos_norm = normalize_pos(pos)
        except (ValueError, TypeError):
            pos_norm = ""
        key = f"{lemma_norm}|{pos_norm}"
        hit = pack_data["cefrj_fallback"].get(key)
        if hit in LEVELS:
            return hit
        prefix = f"{lemma_norm}|{pos_norm}|" if pos_norm else f"{lemma_norm}|"
        best = None
        for entry_key, entry in pack_data["evp_entries"].items():
            if not entry_key.startswith(prefix):
                continue
            level = entry.get("cefr") if isinstance(entry, dict) else None
            if level not in LEVELS:
                continue
            if best is None or LEVELS.index(level) < LEVELS.index(best):
                best = level
        return best  # zipf stubbed to 0 above, so a miss is None either way

    words = ["qx_alpha", "qx_beta", "qx_gamma", "qx_delta", "qx_zeta",
             "qx_missing", "QX_ALPHA", "  qx_beta  "]
    poses = ["noun", "verb", "x", None, "", "NOUN", "  verb "]
    for word in words:
        for pos in poses:
            assert classify(word, pos, pack_data, "en") == legacy(word, pos), \
                (word, pos)
    assert classify("qx_alpha", "noun", pack_data, "en") == "A2"
    assert classify("qx_alpha", None, pack_data, "en") == "A2"
    assert classify("qx_beta", "noun", pack_data, "en") is None
    assert classify("qx_gamma", None, pack_data, "en") is None


def test_corrupt_pack_json_aborts_loud(env):
    with open(os.path.join(env["pack"], "pack.json"), "w", encoding="utf-8") as handle:
        handle.write("{not valid json")
    with pytest.raises(SystemExit) as excinfo:
        main(base_argv(env))
    assert "pack.json" in str(excinfo.value)
    assert not os.path.exists(env["out"])


def test_corrupt_cefrj_fallback_aborts_loud(env):
    # classify() indexes pack_data["cefrj_fallback"] directly, so load_pack()
    # must validate ONCE: a non-object fallback aborts naming the file
    # instead of a later KeyError/AttributeError traceback.
    with open(os.path.join(env["pack"], "cefrj_pos.json"), "w",
              encoding="utf-8") as handle:
        handle.write(json.dumps({"_meta": {}, "fallback": ["not", "an", "object"]}))
    with pytest.raises(SystemExit) as excinfo:
        main(base_argv(env))
    assert "cefrj_pos.json" in str(excinfo.value)
    assert not os.path.exists(env["out"])


def test_corrupt_evp_entries_aborts_loud(env):
    with open(os.path.join(env["pack"], "evp_sense.json"), "w",
              encoding="utf-8") as handle:
        handle.write(json.dumps({"_meta": {}, "entries": ["not", "an", "object"]}))
    with pytest.raises(SystemExit) as excinfo:
        main(base_argv(env))
    assert "evp_sense.json" in str(excinfo.value)
    assert not os.path.exists(env["out"])


def test_missing_cutoffs_warns_and_uses_default(env, capsys):
    with open(os.path.join(env["pack"], "pack.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"cefr": {}}))
    assert main(base_argv(env)) == 0
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "pack.json" in err and "zipf_cutoffs" in err
    rows = read_rows(env["out"])
    assert len(rows) == QUOTA * 6


def test_shape_verdict_matrix():
    # Every DROP class + keeps. A-list (April/about) keeps via the vowel
    # rule — no special-casing. "A. M. A." drops as period (DROP markers
    # win over phrase-routing); "all in all" routes to phrase.
    cases = {
        "-by": "drop:affix",
        "-got-": "drop:affix",
        "-our": "drop:affix",
        "2": "drop:digit",
        "3-1-3": "drop:digit",
        "catch22": "drop:digit",
        "'d": "drop:apostrophe",
        "don't": "drop:apostrophe",
        "x": "drop:single_char",
        "A. M. A.": "drop:period",
        "e.g.": "drop:period",
        "co-op": "drop:non_alpha",
        "rhythm": "drop:no_vowel",
        "all in all": "phrase",
        "hello": "keep",
        "April": "keep",
        "about": "keep",
        "wobbleaa": "keep",
    }
    for word, expected in cases.items():
        assert shape_verdict(word) == expected, word


def test_shape_filter_end_to_end(tmp_path, capsys):
    # Junk never reaches the CSV; phrases count separately and are also
    # excluded; quotas stay exact on the surviving clean candidates.
    # F2b intent: "rhythm" (vowel-less but pack-hit + frequent, zipf 4.05)
    # is allowlisted and competes for the reservoir; all other junk stays
    # dropped.
    pack = str(tmp_path / "pack")
    pilot_rows = [("PilotA1", "noun", "A1")]
    clean = [f"wobbleaa{chr(97 + num)}" for num in range(6)]
    junk = ["-by", "-got-", "2", "3-1-3", "'d", "x", "A. M. A.",
            "co-op", "rhythm"]
    phrases = ["all in all", "by and by"]
    fallback = {f"{word}|noun": "A1" for word in clean + junk + phrases}
    build_pack(pack, pilot_rows, fallback)
    dump_dir = str(tmp_path / "d")
    os.makedirs(dump_dir, exist_ok=True)
    words = [(word, "noun") for word in clean + junk + phrases]
    dump, index, lookup = build_dump_index(dump_dir, words)
    out = str(tmp_path / "out.csv")
    progress = str(tmp_path / "progress.json")
    argv = ["--lang", "en", "--dump", dump, "--index", index,
            "--lookup", lookup, "--pack", pack,
            "--out", out, "--progress", progress,
            "--mix", "4,0,0,0,0,0", "--seed", "7", "--batch", "4"]
    assert main(argv) == 0
    got = read_rows(out)
    by_lemma = {row["lemma"]: row for row in got}
    assert len(got) == 4  # 1 pilot + 3 top-up (clean + allowlisted rhythm)
    assert "PilotA1" in by_lemma
    for word in ["-by", "-got-", "2", "3-1-3", "'d", "x", "A. M. A.",
                 "co-op"] + phrases:
        assert word not in by_lemma
    text = capsys.readouterr().out
    assert "'skipped_shape': 8" in text
    assert "'allowed_vowelless': 1" in text
    assert "'phrase_candidates': 2" in text


def test_vowelless_allowlist_matrix(tmp_path, monkeypatch):
    # F2b allowlist matrix (hermetic: wordfreq stubbed so only the
    # named path can keep):
    # - pack-hit vowel-less kept even when rare (zipf 0);
    # - frequent vowel-less kept even without a pack hit;
    # - rare vowel-less junk (qxwzc, zipf 0, no hit) still dropped;
    # - affix still dropped even with a pack hit + high zipf.
    # ("qxwzea" has vowels e/a so it passes the pure shape gate and drops
    # later via no-freq; the vowel-less junk case here is "qxwzc".)
    import sys as _sys

    from sample_lemmas import FREQUENT_ZIPF_MIN

    assert FREQUENT_ZIPF_MIN == 3.0
    freq = {"by": 6.66, "qxwzb": 0.0, "qxwzc": 0.0, "-by": 6.0}

    class _FakeWordfreq:
        @staticmethod
        def zipf_frequency(lemma, lang):
            assert lang == "en"
            return freq.get(lemma, 0.0)

    monkeypatch.setitem(_sys.modules, "wordfreq", _FakeWordfreq)
    pack = str(tmp_path / "pack")
    build_pack(pack, [("PilotA1", "noun", "A1")],
               {"qxwzb|noun": "B1", "-by|noun": "A1"})
    pack_data = load_pack(pack)
    # Pure shape gate still flags vowel-less rows as no_vowel (allowlist
    # lives downstream, not in shape_verdict); qxwzea keeps (has e/a).
    assert shape_verdict("qxwzb") == "drop:no_vowel"
    assert shape_verdict("by") == "drop:no_vowel"
    assert shape_verdict("qxwzc") == "drop:no_vowel"
    assert shape_verdict("qxwzea") == "keep"
    assert shape_verdict("-by") == "drop:affix"
    # Allowlist verdicts.
    assert pack_has_cefr_hit("qxwzb", "noun", pack_data) is True
    assert is_vowelless_allowlisted("qxwzb", "noun", pack_data, "en") is True
    assert pack_has_cefr_hit("by", "noun", pack_data) is False
    assert is_vowelless_allowlisted("by", "noun", pack_data, "en") is True
    assert is_vowelless_allowlisted("qxwzc", "noun", pack_data, "en") is False
    # Affix class is never allowlisted (helper is only consulted for
    # drop:no_vowel rows).
    assert shape_verdict("-by") != "drop:no_vowel"


def test_vowelless_allowlist_end_to_end(tmp_path, monkeypatch, capsys):
    # Frequent vowel-less "by" (no pack hit) reaches the CSV via the
    # allowlist; rare vowel-less "qxwzc" (no hit, zipf 0) stays dropped.
    import sys as _sys

    class _FakeWordfreq:
        @staticmethod
        def zipf_frequency(lemma, lang):
            return {"by": 6.66}.get(lemma, 0.0)

    monkeypatch.setitem(_sys.modules, "wordfreq", _FakeWordfreq)
    pack = str(tmp_path / "pack")
    build_pack(pack, [("PilotA1", "noun", "A1")], {})
    dump_dir = str(tmp_path / "d")
    os.makedirs(dump_dir, exist_ok=True)
    dump, index, lookup = build_dump_index(
        dump_dir, [("by", "noun"), ("qxwzc", "noun")])
    out = str(tmp_path / "out.csv")
    progress = str(tmp_path / "progress.json")
    argv = ["--lang", "en", "--dump", dump, "--index", index,
            "--lookup", lookup, "--pack", pack,
            "--out", out, "--progress", progress,
            "--mix", "2,0,0,0,0,0", "--seed", "7", "--batch", "4"]
    assert main(argv) == 0
    by_lemma = {row["lemma"]: row for row in read_rows(out)}
    assert "by" in by_lemma
    assert "qxwzc" not in by_lemma
    text = capsys.readouterr().out
    assert "'allowed_vowelless': 1" in text
    assert "'skipped_shape': 1" in text


def test_pilot_exempt_from_shape_filter(tmp_path):
    # A pilot row that would DROP as an index row is still pinned.
    pack = str(tmp_path / "pack")
    pilot_rows = [("-by", "noun", "A1")]
    fallback = {"wobbleaaa|noun": "A1"}
    build_pack(pack, pilot_rows, fallback)
    dump_dir = str(tmp_path / "d")
    os.makedirs(dump_dir, exist_ok=True)
    dump, index, lookup = build_dump_index(dump_dir, [("wobbleaaa", "noun")])
    out = str(tmp_path / "out.csv")
    progress = str(tmp_path / "progress.json")
    argv = ["--lang", "en", "--dump", dump, "--index", index,
            "--lookup", lookup, "--pack", pack,
            "--out", out, "--progress", progress,
            "--mix", "2,0,0,0,0,0", "--seed", "7", "--batch", "4"]
    assert main(argv) == 0
    by_lemma = {row["lemma"]: row for row in read_rows(out)}
    assert by_lemma["-by"]["cefr"] == "A1"


def test_dry_run_shape_counters_untouched(tmp_path):
    # --dry-run reports shape/phrase counters and writes nothing.
    pack = str(tmp_path / "pack")
    pilot_rows = [("PilotA1", "noun", "A1")]
    fallback = {"wobbleaaa|noun": "A1", "-by|noun": "A1",
                "all in all|noun": "A1"}
    build_pack(pack, pilot_rows, fallback)
    dump_dir = str(tmp_path / "d")
    os.makedirs(dump_dir, exist_ok=True)
    words = [("wobbleaaa", "noun"), ("-by", "noun"), ("all in all", "noun")]
    dump, index, lookup = build_dump_index(dump_dir, words)
    out = str(tmp_path / "out.csv")
    progress = str(tmp_path / "progress.json")
    argv = ["--lang", "en", "--dump", dump, "--index", index,
            "--lookup", lookup, "--pack", pack,
            "--out", out, "--progress", progress,
            "--mix", "2,0,0,0,0,0", "--seed", "7", "--batch", "4",
            "--dry-run"]
    assert main(argv) == 0
    assert not os.path.exists(out)
    assert not os.path.exists(progress)


def test_classify_empty_pack_no_keyerror(monkeypatch):
    # classify() must not KeyError on hand-built dicts (load_pack stays
    # the validating contract): {} pack returns None (no fallback hit,
    # wordfreq stubbed to 0 so the zipf branch misses too).
    import sys as _sys

    class _FakeWordfreq:
        @staticmethod
        def zipf_frequency(lemma, lang):
            return 0.0

    monkeypatch.setitem(_sys.modules, "wordfreq", _FakeWordfreq)
    assert classify("wobbleaaa", "noun", {}, "en") is None
