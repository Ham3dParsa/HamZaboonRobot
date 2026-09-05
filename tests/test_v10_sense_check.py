"""Hermetic v10 sense-check tests (LOCKED R38-R41).

No network, no real pools/indexes: kaikki rows are inline stubs,
zipf lookups are injected, the judge EVP table is an inline dict.
Factory-only: card_pilot (R38/R39/R41), precard S1 window (R39),
run_v14_phase3_judge window+boost (R40).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "factory"))
import card_pilot
from card_pilot import (
    candidate_bucket_cap,
    fa_alpha_check,
    generate_card,
    score_senses,
    select_candidate_window,
    sense_coherence_check,
    sense_report,
    top_sense_candidates,
)
import run_v14_phase3_judge as judge

NOFREQ = lambda w: None  # noqa: E731 — neutral freq tie-breaker


def _rows(gloss_list, pos="noun", tags_list=None):
    """One index row per gloss (each its own entry — file order = idx)."""
    rows = []
    for pos_i, gloss in enumerate(gloss_list):
        tags = (tags_list[pos_i] if tags_list else []) or []
        rows.append({"pos": pos if isinstance(pos, str) else pos[pos_i],
                     "entry": {"pos": pos if isinstance(pos, str)
                               else pos[pos_i],
                               "sounds": [],
                               "senses": [{"glosses": [gloss],
                                           "tags": list(tags),
                                           "examples": []}]}})
    return rows


def read_entry(row):
    return row["entry"]


# ---------------- R38: file-index decay pre-score ----------------

def _kiss_entries():
    return _rows([
        "to touch with the lips as a sign of love",
        "to kiss someone with love and affection",
        "a kiss expressing love",
        "A mark X used to show a kiss in writing",
        "Initialism of Keep It Simple Stupid",
        "A surname.",
    ])


def test_r38_kiss_love_top_xmark_acronym_surname_bottom():
    scored = score_senses("kiss", _kiss_entries(), "verb", read_entry,
                          zipf_fn=NOFREQ)
    order = [idx for _, idx, _, _, _ in scored]
    assert order[:3] == [0, 1, 2]  # love senses top
    assert order[-1] == 5  # surname penalized + deepest decay
    assert order[-2] == 4  # acronym above surname only
    assert order[3] == 3  # X-mark above acronym/surname, below love


def test_r38_bank_top_is_file_order_financial():
    entries = _rows([
        "a financial institution where money is kept",
        "the land along the side of a river",
        "a bench for rowers in a boat",
        "to tilt an aircraft sideways",
    ])
    scored = score_senses("bank", entries, "noun", read_entry,
                          zipf_fn=NOFREQ)
    assert scored[0][1] == 0
    assert scored[0][4] == "a financial institution where money is kept"


def test_r38_freq_only_breaks_close_ties():
    glosses = (["clean filler sense about everyday matters here"] * 14
               + ["zzz qqq xxx obscure thing here",
                  "aaa bbb ccc common thing here"])
    entries = _rows(glosses)

    def common_fn(word):
        return 6.0 if word in ("aaa", "bbb", "ccc", "common") else 1.0

    scored = score_senses("w", entries, "noun", read_entry,
                          zipf_fn=common_fn)
    rank = {idx: pos for pos, (_, idx, _, _, _) in enumerate(scored)}
    # Decay diff between idx14/idx15 is < 0.05, so freq promotes idx15.
    assert rank[15] < rank[14]
    tied = score_senses("w", entries, "noun", read_entry, zipf_fn=NOFREQ)
    rank_tie = {idx: pos for pos, (_, idx, _, _, _) in enumerate(tied)}
    assert rank_tie[14] < rank_tie[15]  # neutral freq keeps file order


def test_r38_archaic_demoted_outside_top5():
    glosses = [
        "a short musical sound",
        "a written reminder",
        "a coin of small value",
        "to notice something quickly",
        "a chapternote in a book",
        "an archaic term for a mark",
    ]
    tags = [[], [], [], [], [], ["archaic"]]
    scored = score_senses("note", _rows(glosses, tags_list=tags), "noun",
                          read_entry, zipf_fn=NOFREQ)
    top5 = [idx for _, idx, _, _, _ in scored[:5]]
    assert 5 not in top5  # archaic 0.80 * decay loses to 5 clean senses


def test_sense_report_kiss_bank_note():
    index = {
        "kiss": _kiss_entries(),
        "bank": _rows([
            "a financial institution where money is kept",
            "the land along the side of a river",
            "a bench for rowers in a boat",
        ]),
        "note": _rows(
            ["a short musical sound", "a written reminder",
             "a coin of small value", "to notice something quickly",
             "a chapternote in a book", "an archaic term for a mark"],
            tags_list=[[], [], [], [], [], ["archaic"]]),
    }
    report = sense_report(
        [{"text": "kiss", "pos": "verb", "pool_level": "A1"},
         {"text": "bank", "pos": "noun", "pool_level": "A1"},
         {"text": "note", "pos": "noun", "pool_level": "B1"}],
        index, read_entry, k=5, zipf_fn=NOFREQ)
    kiss, bank, note = (r["top"] for r in report)
    assert [c["sense_id"] for c in kiss[:3]] == [
        "kiss#0", "kiss#1", "kiss#2"]
    assert bank[0]["sense_id"] == "bank#0"
    assert "note#5" not in [c["sense_id"] for c in note[:5]]


# ---------------- R39: tiered bucketing ----------------

def _twelve_nouns():
    return _rows(["clean noun gloss number %d here today" % i
                  for i in range(12)])


def test_r39_bucket_boundaries_a1_vs_upper():
    scored = score_senses("w", _twelve_nouns(), "noun", read_entry,
                          zipf_fn=NOFREQ)
    assert candidate_bucket_cap("A1") == 6
    assert candidate_bucket_cap("A2") == 6
    assert candidate_bucket_cap("B1") == 10
    a1 = select_candidate_window(scored, "noun", "A1")
    assert {t[1] for t in a1} <= set(range(6)) and len(a1) == 6
    b1 = select_candidate_window(scored, "noun", "B1")
    assert {t[1] for t in b1} <= set(range(10)) and len(b1) == 10


def test_r39_pos_coverage_pulls_missing_pos():
    entries = _rows(["clean noun gloss number %d here today" % i
                     for i in range(6)], pos="noun") + _rows(
        ["to verb gloss number %d here today" % i for i in range(2)],
        pos="verb")
    scored = score_senses("w", entries, "noun", read_entry, zipf_fn=NOFREQ)
    window = select_candidate_window(scored, "noun", "A1")
    poses = {(t[2] or {}).get("pos") for t in window}
    assert "verb" in poses  # at least one candidate per POS present
    assert len(window) == 7  # 6-bucket + 1 pulled verb


def test_r39_fallback_to_higher_when_no_pos_match():
    entries = _rows(["clean noun gloss number %d here today" % i
                     for i in range(6)], pos="noun") + _rows(
        ["to tilt an aircraft sideways always", "to bank money daily now"],
        pos="verb")
    scored = score_senses("w", entries, "verb", read_entry, zipf_fn=NOFREQ)
    window = select_candidate_window(scored, "verb", "A1")
    assert max(t[1] for t in window) > 5  # went higher for the verb match
    # Pilot shortlist rides the same window.
    cands = top_sense_candidates("w", entries, "verb", read_entry, k=3,
                                 zipf_fn=NOFREQ, pool_level="A1")
    assert len(cands) == 3


def test_r39_s1_window_is_judge_width():
    from precard_pipeline import s1_rank_item
    index = {"bank": _twelve_nouns()}
    item = {"kind": "word", "text": "bank", "pos": "noun",
            "pool_level": "B1"}
    ranked = s1_rank_item(item, index, read_entry)
    assert len(ranked["candidates"]) == 10  # S2 judge width, not top-3
    assert ranked["top"]["sense_id"] == ranked["candidates"][0]["sense_id"]


# ---------------- R40: judge window + examples + EVP boost ----------------

def _judge_sense(sid, gloss, score, example=""):
    return {"sense_id": sid, "gloss": gloss, "score": score,
            "sense_cefr": "B1", "topic_label": "Other / Abstract",
            "examples": [{"text": example}] if example else []}


def test_r40_block_contains_first_example():
    r = {"lemma": "bank", "cefr": "B1",
         "ranked_senses": [
             _judge_sense("bank#0", "a financial institution", 0.5,
                          "He deposited money at the bank yesterday morning."),
             _judge_sense("bank#1", "river side", 0.4)]}
    block = judge.lemma_block(r)
    assert "|| ex: He deposited money at the bank yesterday morning." in block
    assert "river side" in block  # senses without examples still listed


def test_r40_evp_boost_reorders():
    r = {"lemma": "pass", "cefr": "B1",
         "ranked_senses": [
             _judge_sense("pass#0", "a mountain gap between hills", 0.5),
             _judge_sense("pass#1", "to succeed in an exam", 0.4)]}
    evp = {"pass|verb|exam_success": {"guideword": "exam",
                                      "cefr": "B1",
                                      "domain": "Work & Education"}}
    plain = [s["sense_id"] for s in judge.select_judge_window(
        r["ranked_senses"], "pass")]
    assert plain == ["pass#0", "pass#1"]
    boosted = [s["sense_id"] for s in judge.select_judge_window(
        r["ranked_senses"], "pass", evp_entries=evp)]
    assert boosted == ["pass#1", "pass#0"]  # 0.4*1.5=0.6 beats 0.5
    assert judge.EVP_BOOST == 1.5


def test_r40_cap_raised_and_validation_passes():
    senses = [_judge_sense("w#%d" % i, "clean gloss number %d here" % i,
                           1.0 / (i + 1)) for i in range(12)]
    r = {"lemma": "w", "cefr": "A1", "ranked_senses": senses}
    block = judge.lemma_block(r)
    assert len(block.splitlines()) == 1 + judge.JUDGE_WINDOW_CAP == 11
    window = judge.select_judge_window(senses, "w")
    assert len(window) == 10
    picks = judge.deterministic_picks(r)
    assert judge.validate_picks(
        picks, [s["sense_id"] for s in senses]) is True
    need = judge.needs_topic(r)
    topics = [{"id": k, "label": "Other / Abstract", "confidence": 0.5}
              for k in need]
    assert judge.validate_topics(topics, need) is True


# ---------------- R41: fa-alpha + sense coherence ----------------

CLEAN_CARD = {
    "word": "resilient",
    "phonetic": "rɪˈzɪl.jənt",
    "fa_meaning": "تاب‌آور",
    "fa_explanation": "کسی که پس از سختی به حالت عادی برمی‌گردد.",
    "synonyms": ["tough", "hardy"],
    "antonyms": ["fragile"],
    "examples": ["She is a resilient student studying daily here.",
                 "Resilient trees grow strong after every storm."],
    "example_translations": ["او دانش‌آموز تاب‌آوری است که هر روز در اینجا درس می‌خواند.",
                             "درختان تاب‌آور پس از هر طوفان قوی رشد می‌کنند."],
    "grammar_tip": "صفت است.",
}


def test_r41_fa_alpha_fuerte_and_diacritics_fail_clean_passes():
    assert fa_alpha_check(dict(
        CLEAN_CARD, fa_meaning="تاب‌آور fuerte")) is False
    assert fa_alpha_check(dict(
        CLEAN_CARD, fa_explanation="متن فارسی niño")) is False
    assert fa_alpha_check(dict(
        CLEAN_CARD,
        example_translations=["متن فارسی", "متن straße فارسی"])) is False
    assert fa_alpha_check(CLEAN_CARD) is True
    assert fa_alpha_check(dict(CLEAN_CARD, fa_meaning="تلویزیون TV"),
                          allowed_terms=["TV"]) is True
    assert fa_alpha_check(dict(CLEAN_CARD, fa_meaning="تلویزیون TV"),
                          ) is False  # allowlist empty by default


def test_r41_coherence_xmark_rejected_coherent_passes():
    xmark = "A written X mark used instead of a signature"
    kissing_card = dict(
        CLEAN_CARD, word="kiss",
        examples=["They were kissing under the mistletoe today.",
                  "She gave him a kissing greeting yesterday."],
        example_translations=["آن‌ها امروز زیر دارواش همدیگر را بوسیدند.",
                              "او دیروز با بوسه به او سلام کرد."],
        synonyms=["hug"], fa_meaning="علامت ضربدر",
        fa_explanation="نشانه‌ای نوشتاری به‌جای امضا.")
    assert sense_coherence_check(xmark, kissing_card) is False
    love = "to touch with the lips as a sign of love"
    loving_card = dict(
        kissing_card,
        examples=["They kiss to show their love daily.",
                  "She gave him a loving kiss yesterday."],
        synonyms=["kiss"])
    assert sense_coherence_check(love, loving_card) is True
    assert sense_coherence_check("", kissing_card) is True  # fail-open


def test_r41_generate_card_rejects_without_regen():
    # NOTE: "TV" (2 Latin chars) passes the R7 fa-dominant loanword
    # leniency (<=3) so the card reaches the R41 fa-alpha hard gate;
    # the bare "fuerte" variant is covered directly in
    # test_r41_fa_alpha_fuerte_and_diacritics_fail_clean_passes (it trips
    # fa-dominant first, which is the specified gate order).
    bad_alpha = dict(CLEAN_CARD, fa_meaning="تاب‌آور TV")

    def transport_alpha(api_key, model, system, user):
        return json.dumps(bad_alpha)

    rec = generate_card({"kind": "word", "text": "resilient",
                         "pool_level": "B2",
                         "en_def": "tough resilience after hard times"},
                        "key", transport=transport_alpha, model_calls={})
    assert rec["valid"] is False
    assert rec["reason"] == "fa-alpha"
    assert rec.get("regen") is False

    incoherent = dict(
        CLEAN_CARD, word="kiss",
        examples=["They kiss to show their love every day.",
                  "She gave him a sweet kiss yesterday."],
        example_translations=["آن‌ها برای نشان دادن عشقشان هر روز همدیگر را می‌بوسند.",
                              "او دیروز با یک بوسه شیرین به او سلام کرد."],
        synonyms=["hug"], fa_meaning="علامت ضربدر",
        fa_explanation="نشانه‌ای نوشتاری به‌جای امضا.")

    def transport_incoherent(api_key, model, system, user):
        return json.dumps(incoherent)

    rec2 = generate_card(
        {"kind": "word", "text": "kiss", "pool_level": "A1",
         "en_def": "A written X mark used instead of a signature"},
        "key", transport=transport_incoherent, model_calls={})
    assert rec2["valid"] is False
    assert rec2["reason"] == "sense-incoherence"
    assert rec2.get("regen") is False

def test_judge_window_cap_matches_owner_module():
    from run_v14_phase3_judge import JUDGE_WINDOW_CAP as OWNER_CAP
    assert card_pilot.JUDGE_WINDOW_CAP == OWNER_CAP == 10
