"""Proof test for factory/registry.py (DESIGN-B §5 proof ideas, stdlib only).

Covers (plain asserts, `python factory/test_registry_proof.py`):
  (a) import twice -> counts identical, no dupes
      (GROUP BY pre_card_id HAVING COUNT(*) > 1 is empty);
  (b) overlapping re-import with 20 shuffled duplicate lemmas -> zero new rows;
  (c) new language 'de' with 3 fake lemmas -> 'en' untouched, 'de' separate;
  (d) batch claim / complete / stale-lease cycle.

Runs against a TEMP copy (tempfile). Never touches factory/registry.db.
"""

import json
import os
import random
import re
import sqlite3
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
from factory import registry as R  # noqa: E402

FX = os.path.join(_HERE, "fixtures")


def q(db, sql, params=()):
    con = sqlite3.connect(db)
    try:
        con.row_factory = sqlite3.Row
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def snap(db, lang="en"):
    return R.stats(db, lang)


def main():
    tmp = tempfile.mkdtemp(prefix="regproof-")
    db = os.path.join(tmp, "registry.db")

    # (a) import twice -> identical counts, no dupes.
    first = R.migrate_v14(db, FX)
    second = R.migrate_v14(db, FX)
    assert first == second, (first, second)
    dupes = q(db, "SELECT pre_card_id, COUNT(*) c FROM precards"
                  " GROUP BY lang, pre_card_id HAVING c > 1")
    assert dupes == [], dupes
    print("PASS (a) import-twice idempotent:", json.dumps(first))

    # (b) 20 shuffled duplicate lemmas -> zero new rows.
    before = snap(db)
    uniq = json.load(open(os.path.join(FX, "uniq_senses-v14a.json"),
                          encoding="utf-8"))
    ra = json.load(open(os.path.join(FX, "ranked_senses-v14a.json"),
                        encoding="utf-8"))
    by_lc = {(r["lemma"], r["cefr"]): r for r in ra}
    sample = random.Random(0).sample(uniq, 20)
    new_rows = 0
    for u in sample:
        R.upsert_lemma(db, "en", u["lemma"], u["pos"], cefr=u.get("cefr"),
                       stages={"deduped": True},
                       pack_version="v14a", code_hash="legacy-import")
        r = by_lc[(u["lemma"], u["cefr"])]
        lk = R.lemma_key_for(u["lemma"], u["pos"])
        for s in r["ranked_senses"]:
            if R.add_precard(db, "en", lk, s["gloss"],
                             sense_cefr=s.get("sense_cefr"),
                             legacy_id=s.get("sense_id"),
                             created_run="import-v14a"):
                new_rows += 1
    assert new_rows == 0, new_rows
    assert snap(db) == before, (snap(db), before)
    print("PASS (b) 20 shuffled dupes -> 0 new rows")

    # (c) new language 'de' isolated from 'en'.
    en_before = snap(db, "en")
    R.register_language(db, "de", "v14a-test")
    for lemma, pos in [("Apfel", "noun"), ("laufen", "verb"), ("schnell", "adverb")]:
        lk = R.upsert_lemma(db, "de", lemma, pos, cefr="A1",
                            raw_hash="fake", stages={"deduped": True},
                            pack_version="v14a-test", code_hash="proof")
        assert R.add_precard(db, "de", lk, "fake gloss %s" % lemma,
                             legacy_id="%s#0" % lemma) is True
    assert snap(db, "en") == en_before, (snap(db, "en"), en_before)
    de = snap(db, "de")
    assert (de["lemmas"], de["precards_total"], de["active"]) == (3, 3, 3), de
    assert sorted(R.get_pending(db, "de")) == sorted(
        r["pre_card_id"] for r in q(
            db, "SELECT pre_card_id FROM precards WHERE lang='de'"))
    # fingerprint helper: match -> reuse, any drift -> reprocess.
    assert R.fingerprint(db, "de", R.lemma_key_for("Apfel", "noun"),
                         "v14a-test", "proof", "fake") == "reuse"
    assert R.fingerprint(db, "de", R.lemma_key_for("Apfel", "noun"),
                         "v14a-test", "proof", "other") == "reprocess"
    assert R.fingerprint(db, "de", R.lemma_key_for("Apfel", "noun"),
                         "v14b", "proof", "fake") == "reprocess"
    assert R.fingerprint(db, "en", "nope|noun", "v14a",
                         "legacy-import", "x") == "reprocess"
    print("PASS (c) de isolated (3/3/3), en untouched, fingerprint ok")

    # (d) batch claim / complete / stale-lease cycle.
    t1 = R.claim_batch(db, "en", 10)
    assert re.fullmatch(r"FINAL-en-\d{8}-\d{2,}", t1), t1
    items = [r["pre_card_id"] for r in q(
        db, "SELECT pre_card_id FROM batch_items WHERE ticket=?", (t1,))]
    assert len(items) == 10, len(items)
    for pid in items[:3]:
        assert R.complete_batch_item(db, t1, pid, "final-%s" % pid) is True
    assert snap(db, "en")["converted"] == 3
    # double-complete / double-convert refused.
    assert R.complete_batch_item(db, t1, items[0], "final-other") is False
    assert R.mark_converted(db, "en", items[0], "final-other") is False
    # fresh lease -> no requeue; backdated lease -> requeue 7, done kept.
    assert R.requeue_stale(db, t1) == 0
    con = sqlite3.connect(db)
    try:
        prog = json.loads(con.execute(
            "SELECT progress FROM batches WHERE ticket=?",
            (t1,)).fetchone()[0])
        prog["leased_at"] = "2020-01-01T00:00:00+00:00"
        con.execute("UPDATE batches SET progress=? WHERE ticket=?",
                    (json.dumps(prog), t1))
        con.commit()
    finally:
        con.close()
    assert R.requeue_stale(db, t1) == 7
    left = {r["pre_card_id"]: r["status"] for r in q(
        db, "SELECT pre_card_id, status FROM batch_items WHERE ticket=?",
        (t1,))}
    assert sum(1 for s in left.values() if s == "done") == 3
    assert sum(1 for s in left.values() if s == "queued") == 7
    # reclaim: seq bumps, all 7 re-queued items claimed, never double-claimed.
    t2 = R.claim_batch(db, "en", 10)
    assert t2 != t1 and t2.rsplit("-", 1)[0] == t1.rsplit("-", 1)[0], (t1, t2)
    t2items = [r["pre_card_id"] for r in q(
        db, "SELECT pre_card_id FROM batch_items WHERE ticket=?", (t2,))]
    assert set(items[3:]) <= set(t2items)
    clash = q(db, "SELECT pre_card_id FROM batch_items"
                  " WHERE status='claimed' GROUP BY pre_card_id HAVING COUNT(*) > 1")
    assert clash == [], clash
    assert R.complete_batch_item(db, t2, items[3], "final-%s" % items[3]) is True
    assert snap(db, "en")["converted"] == 4
    print("PASS (d) batch cycle: %s -> %s, converted=4, no double-claim" % (t1, t2))

    print("ALL PROOF TESTS PASS on", db)


if __name__ == "__main__":
    main()
