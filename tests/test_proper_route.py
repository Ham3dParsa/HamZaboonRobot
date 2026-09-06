"""Hermetic tests for post-S2 proper-noun routing (precard_pipeline).

No network, no W:, no real keys: stub kaikki index/read_entry, stub
judge/topic transports, injected zipf. Each stub lemma carries a common
anchor sense (file-idx 0, noun/adj row — S1 anchors here, never proper)
plus a proper sense (file-idx 1, name row) that the stub judge picks.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "factory"))
import precard_pipeline  # noqa: E402
from precard_pipeline import main as precard_main  # noqa: E402
from precard_pipeline import s2_proper_route  # noqa: E402

LONG_EX = ("She eats a fresh red apple every single morning "
           "with her family")


def _rows(pairs, ipa="/x/"):
    """Index rows in file order from [(pos, gloss)] pairs."""
    return [{"pos": pos,
             "entry": {"pos": pos, "sounds": [{"ipa": ipa}],
                       "senses": [{"glosses": [gloss], "tags": [],
                                   "examples": [{"text": LONG_EX}]}]}}
            for pos, gloss in pairs]


def make_index():
    return {
        "pacific": _rows([
            ("noun", "a calm and peaceful manner"),
            ("name", "the Pacific Ocean, the largest ocean on earth")]),
        "city": _rows([
            ("noun", "a large town"),
            ("name", "Manchester City FC, a football club")]),
        "easter": _rows([
            ("noun", "coming from the east"),
            ("name", "an English surname")]),
        "march": _rows([
            ("noun", "a steady forward walk"),
            ("name", "the third month of the year")]),
        "spanish": _rows([
            ("adj", "relating to Spain"),
            ("name", "the Spanish language")]),
        "xanadu": _rows([
            ("noun", "a place of great beauty"),
            ("name", "Xanadu, a country in the old tales")]),
        "zorp": _rows([
            ("noun", "a small green stone"),
            ("name", "Zorp, a legendary hero of the old tales")]),
        "plain": _rows([
            ("noun", "a round fruit"),
            ("noun", "a sweet dessert")]),
        "yen": _rows([
            ("noun", "a sharp bite"),
            ("name", "a unit of currency used in Japan")]),
        "festivus": _rows([
            ("noun", "a pole dance"),
            ("name", "a secular festival in December")]),
        "steamer": _rows([
            ("noun", "a cooking pot"),
            ("name", "an abandoned steamer near the driver")]),
    }


def read_entry(row):
    return row["entry"]


def item(text, pool="A1"):
    return {"kind": "word", "text": text, "pos": "noun",
            "pool_level": pool}


ZIPFS = {"xanadu": 2.0}


def zipf_fn(text):
    return ZIPFS.get((text or "").strip().lower(), 5.0)


def pick_second_judge(api_key, model, user_text):
    """S2-shape reply: #1 sense when present, else the first candidate."""
    keys, cands, cur = [], {}, None
    for line in user_text.splitlines():
        hit = re.match(r"^KEY (\S+)", line)
        if hit:
            cur = hit.group(1)
            keys.append(cur)
            cands[cur] = []
        pick = re.match(r"^- (\S+#\d+)", line)
        if pick and cur:
            cands[cur].append(pick.group(1))
    out = []
    for key in keys:
        ids = cands[key]
        pick = next((i for i in ids if i.endswith("#1")),
                    ids[0] if ids else "")
        out.append({"key": key, "pick": pick})
    return json.dumps({"results": out})


def fake_topics(api_key, model, user_text):
    """v15-shape reply: every sense -> Other / Abstract @1.0."""
    lemmas, cur = {}, None
    for line in user_text.splitlines():
        hit = re.match(r"^LEMMA (.+):$", line)
        if hit:
            cur = hit.group(1)
            lemmas[cur] = []
        pick = re.match(r"^- (\S+)", line)
        if pick and cur is not None:
            lemmas[cur].append(pick.group(1))
    return json.dumps({"results": [
        {"lemma": lemma,
         "vectors": [{"sense_id": sid,
                      "vector": [{"topic_id": 16,
                                  "topic_label": "Other / Abstract",
                                  "weight": 1.0}]}
                     for sid in sids]}
        for lemma, sids in lemmas.items()]})


def run_all(tmp_path, texts, prog=None, pools=None):
    """Run the full pipeline on stub lemmas; return (rc, rows, progdir)."""
    pools = pools or {}
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(
        [item(t, pools.get(t, "C2" if t == "xanadu" else "A1"))
         for t in texts]), encoding="utf-8")
    out = str(tmp_path / "precard.jsonl")
    progdir = prog or str(tmp_path / "prog")
    rc = precard_main(
        ["--sample", str(sample), "--out", out,
         "--progress-dir", progdir],
        _judge_transport=pick_second_judge, _topic_transport=fake_topics,
        _assign_transport=None, _inflect_transport=None,
        _sleep_fn=lambda s: None,
        _index=make_index(), _read_entry=read_entry, _tatoeba={},
        _zipf_fn=zipf_fn)
    assert rc == 0
    with open(out, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    return rc, {r["key"]: r for r in rows}, progdir


def s2_state(progdir):
    with open(os.path.join(progdir, "s2.json"),
              encoding="utf-8") as handle:
        return json.load(handle)


def test_geo_pick_routes_to_proper_pool(tmp_path):
    _, rows, _ = run_all(tmp_path, ["pacific"])
    assert rows["w:pacific"]["proper_route"] == "geo"
    assert rows["w:pacific"]["sense_id"] == "pacific#1"


def test_org_guard_drops_club(tmp_path):
    _, rows, prog = run_all(tmp_path, ["city"])
    assert "w:city" not in rows
    done = s2_state(prog)["done"]
    assert done["w:city"]["proper_drop"] == "pick-proper-noun/org-guard"
    assert done["w:city"]["proper_route"] == ""


def test_person_guard_drops_surname(tmp_path):
    _, rows, prog = run_all(tmp_path, ["easter"])
    assert "w:easter" not in rows
    done = s2_state(prog)["done"]
    assert done["w:easter"]["proper_drop"] == "pick-proper-noun/person-name"


def test_month_and_language_route(tmp_path):
    _, rows, _ = run_all(tmp_path, ["march", "spanish"])
    assert rows["w:march"]["proper_route"] == "time"
    assert rows["w:spanish"]["proper_route"] == "language"


def test_zipf_low_proper_drops(tmp_path):
    # xanadu rides C2 (S0 floor 1.5 keeps zipf 2.0) but the proper-route
    # floor is 2.5, so it drops here — never silently.
    _, rows, prog = run_all(tmp_path, ["xanadu"])
    assert "w:xanadu" not in rows
    done = s2_state(prog)["done"]
    assert done["w:xanadu"]["proper_drop"].startswith(
        "pick-proper-noun/zipf-low")


def test_no_class_proper_drops(tmp_path):
    _, rows, prog = run_all(tmp_path, ["zorp"])
    assert "w:zorp" not in rows
    done = s2_state(prog)["done"]
    assert done["w:zorp"]["proper_drop"] == "pick-proper-noun/no-class"


def test_common_pick_continues_without_marker(tmp_path):
    _, rows, prog = run_all(tmp_path, ["plain"])
    assert "proper_route" not in rows["w:plain"]
    done = s2_state(prog)["done"]
    assert done["w:plain"]["proper_route"] == ""
    assert done["w:plain"]["proper_drop"] == ""


def test_resume_is_idempotent(tmp_path):
    texts = ["pacific", "city", "easter", "march", "spanish",
             "xanadu", "zorp", "plain"]
    _, rows1, prog = run_all(tmp_path, texts)
    before = s2_state(prog)["done"]
    _, rows2, _ = run_all(tmp_path, texts, prog=prog)
    assert rows1 == rows2
    after = s2_state(prog)["done"]
    assert before == after
    assert after["w:pacific"]["proper_route"] == "geo"
    assert after["w:city"]["proper_drop"] == "pick-proper-noun/org-guard"


def test_unit_zipf_unknown_drops():
    index = make_index()
    pick = {"sense_id": "pacific#1",
            "gloss": "the Pacific Ocean, the largest ocean on earth"}
    verdict = s2_proper_route(
        item("pacific"), pick, {"anchor_pos": "noun"},
        index, read_entry, zipf_fn=lambda t: None)
    assert verdict == {"routed": False, "proper_route": "",
                       "reason": "pick-proper-noun/zipf-unknown"}


def test_unit_anchor_proper_passes_through():
    index = make_index()
    pick = {"sense_id": "pacific#1",
            "gloss": "the Pacific Ocean, the largest ocean on earth"}
    verdict = s2_proper_route(
        item("pacific"), pick, {"anchor_pos": "name"},
        index, read_entry, zipf_fn=zipf_fn)
    assert verdict == {"routed": False, "proper_route": "",
                       "reason": None}


def test_unit_empty_pick_passes_through():
    index = make_index()
    verdict = s2_proper_route(
        item("pacific"), {"sense_id": "", "gloss": ""},
        {"anchor_pos": "noun"}, index, read_entry, zipf_fn=zipf_fn)
    assert verdict == {"routed": False, "proper_route": "",
                       "reason": None}

def test_money_and_holiday_classes_route():
    from precard_pipeline import classify_proper_gloss
    assert classify_proper_gloss(
        "A unit of currency used in Japan.")[0] == "money"
    assert classify_proper_gloss(
        "A Christian festival celebrating birth.")[0] == "holiday"
    # Substring traps must not fire (word boundaries).
    assert classify_proper_gloss(
        "Abandoned steamer near the driver.")[0] in (None, "no-class")

def test_money_and_holiday_classes_route(tmp_path):
    _, rows, _ = run_all(tmp_path, ["yen", "festivus"])
    assert rows["w:yen"]["proper_route"] == "money"
    assert rows["w:festivus"]["proper_route"] == "holiday"


def test_substring_traps_do_not_route(tmp_path):
    # Word boundaries: abandoned/steamer/driver must not fire band/team/river.
    _, rows, prog = run_all(tmp_path, ["steamer"])
    assert "w:steamer" not in rows
    done = s2_state(prog)["done"]
    assert done["w:steamer"]["proper_drop"] == "pick-proper-noun/no-class"
