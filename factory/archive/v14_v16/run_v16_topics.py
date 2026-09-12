# v16 — full topic relabel with SIXTEEN labels + weight vectors (locked spec, plan-v14.md v16 + owner order 2026-09-03).
# One combined run (~63 calls): for EVERY sense (all 1676) fresh primary label (1..16) + weight vector (<=3, sum 1.0).
# Do NOT touch the frozen 13-label pack (factory/packs/en/topic_prototypes.json); the 16 labels live here only.
#
# THE 16 LABELS (exact strings, topic_id = position 1..16):
#  1 Daily Life & Home — everyday routines, household, clothing, time expressions.
#  2 Food & Drink — eating, cooking, food and drink items, and the act of eating/drinking.
#  3 Health & Body — body parts, illness, medicine, hygiene.
#  4 Work & Careers — jobs, offices, meetings, professional life.
#  5 Education & Exams — school, study, exams, learning.
#  6 Travel & Transportation — trips, vehicles, directions, movement of people/goods.
#  7 Society — community, traditions, social life, public affairs.
#  8 Arts & Culture — art, film, music, literature.
#  9 Animals & Living Beings — animals and other living creatures (even if edible: swimming fish = Animals, fish on table = Food).
# 10 Nature & Environment — plants, earth, air, water, weather, landscapes.
# 11 Science & Technology — science, computers, devices, inventions.
# 12 Business & Economy — money, trade, markets, finance.
# 13 Law & Politics — rules, government, crime, rights.
# 14 Sports & Leisure — games, sports, hobbies, free-time fun.
# 15 Emotions & Relationships — feelings, family, friendship, love.
# 16 Other / Abstract — abstract, grammatical, or otherwise unclassifiable meanings.
# TIE-BREAK (locked): living being->Animals even if edible; eating/cooking/food act->Food;
# exam/school/study->Education; job/meeting/office->Work; art/film/music/literature->Arts;
# community/tradition->Society.
#
# Transport: OpenCode Zen /responses, bare model ids (NO opencode/ prefix), browser UA, reasoning minimal.
# Chain: spark-1.3 -> 1.2 -> ling-3.0-flash-fin -> mimo-v2.5 -> nemotron-3.5-lightning.
# Batch 8 lemmas/call (~63 calls), sleep 2.5s, live tqdm (never pipe), resume JSON every batch.
# Any lemma failure -> deterministic single fallback: evp-domain (guideword-in-gloss match, mapped
# to 16 labels) else Other / Abstract @1.0, source deterministic-*, logged.
# Outputs: factory/fixtures/topic_labels-v16.json (same shape as v14c topic file, topic_source llm-v16)
#          factory/fixtures/topic_vectors-v16.json (same shape as v15 vectors file)
#          factory/fixtures/topic_migration_13_to_16.json (old label -> new label(s) rule, history comparison)
# Usage: dry-run: python factory/archive/v14_v16/run_v16_topics.py --dry-run --limit 8
#        smoke:    python factory/archive/v14_v16/run_v16_topics.py --lemmas rock,light,pass,flat,supporter,time,fish,fisherman
#        full:     python factory/archive/v14_v16/run_v16_topics.py
# Needs: factory/.env with OPENCODE_ZEN_API_KEY. Never prints keys, never stages .env.
# <SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE> — LOCKED in plan-v14.md v16
# (owner 2026-09-03) + explicit owner run order; factory-research scope, no prod code, no commit.
import argparse, json, pathlib, re, sys, time
import urllib.request
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # factory/ (moved under archive/v14_v16)
from factory.core.llm_json import extract_json, raise_for_auth, AuthError
FX = ROOT / "fixtures"
IN_RANKED = FX / "ranked_senses-v14c.json"
OUT_LABELS = FX / "topic_labels-v16.json"
OUT_VECTORS = FX / "topic_vectors-v16.json"
OUT_MIGRATION = FX / "topic_migration_13_to_16.json"
PROG = ROOT / "v16_progress.json"
ZEN_BASE = "https://opencode.ai/zen/v1"
MODELS = ["muse-spark-1.3-contributor-free", "muse-spark-1.2-contributor-free",
          "ling-3.0-flash-fin-free", "mimo-v2.5-free",
          "nemotron-3.5-lightning-free"]
BATCH = 8
SLEEP = 2.5
TOL = 0.01

LABELS16 = ["Daily Life & Home", "Food & Drink", "Health & Body", "Work & Careers",
            "Education & Exams", "Travel & Transportation", "Society", "Arts & Culture",
            "Animals & Living Beings", "Nature & Environment", "Science & Technology",
            "Business & Economy", "Law & Politics", "Sports & Leisure",
            "Emotions & Relationships", "Other / Abstract"]
ID2LABEL = {i + 1: lab for i, lab in enumerate(LABELS16)}
LABEL2ID = {lab: i + 1 for i, lab in enumerate(LABELS16)}

# 13 -> 16 default single mapping (history comparison + deterministic-evp fallback mapping).
MIGRATE_DEFAULT = {
    "Daily Life & Home": "Daily Life & Home",
    "Food & Drink": "Food & Drink",
    "Health & Body": "Health & Body",
    "Work & Education": None,  # split: see MIGRATION rule
    "Travel & Transportation": "Travel & Transportation",
    "Society & Culture": None,  # split: see MIGRATION rule
    "Nature & Environment": None,  # split: see MIGRATION rule
    "Science & Technology": "Science & Technology",
    "Business & Economy": "Business & Economy",
    "Law & Politics": "Law & Politics",
    "Sports & Leisure": "Sports & Leisure",
    "Emotions & Relationships": "Emotions & Relationships",
    "Other / Abstract": "Other / Abstract",
}

MIGRATION = {
    "Daily Life & Home": {"new": ["Daily Life & Home"], "rule": "identity (unchanged head)"},
    "Food & Drink": {"new": ["Food & Drink"], "rule": "identity (unchanged head)"},
    "Health & Body": {"new": ["Health & Body"], "rule": "identity (unchanged head)"},
    "Work & Education": {"new": ["Work & Careers", "Education & Exams"],
                         "rule": "split: job/meeting/office/professional life -> Work & Careers; exam/school/study/learning -> Education & Exams"},
    "Travel & Transportation": {"new": ["Travel & Transportation"], "rule": "identity (unchanged head)"},
    "Society & Culture": {"new": ["Society", "Arts & Culture"],
                          "rule": "split: community/tradition/social life -> Society; art/film/music/literature -> Arts & Culture"},
    "Nature & Environment": {"new": ["Animals & Living Beings", "Nature & Environment"],
                             "rule": "split: living beings/animals (even if edible) -> Animals & Living Beings; plants/earth/air/water/weather -> Nature & Environment"},
    "Science & Technology": {"new": ["Science & Technology"], "rule": "identity (unchanged head)"},
    "Business & Economy": {"new": ["Business & Economy"], "rule": "identity (unchanged head)"},
    "Law & Politics": {"new": ["Law & Politics"], "rule": "identity (unchanged head)"},
    "Sports & Leisure": {"new": ["Sports & Leisure"], "rule": "identity (unchanged head)"},
    "Emotions & Relationships": {"new": ["Emotions & Relationships"], "rule": "identity (unchanged head)"},
    "Other / Abstract": {"new": ["Other / Abstract"], "rule": "identity (unchanged head)"},
}

DEFS = ("1 Daily Life & Home: everyday routines, household, clothing, time. "
        "2 Food & Drink: eating, cooking, food/drink items and the act of eating. "
        "3 Health & Body: body parts, illness, medicine, hygiene. "
        "4 Work & Careers: jobs, offices, meetings, professional life. "
        "5 Education & Exams: school, study, exams, learning. "
        "6 Travel & Transportation: trips, vehicles, directions, movement. "
        "7 Society: community, traditions, social life, public affairs. "
        "8 Arts & Culture: art, film, music, literature. "
        "9 Animals & Living Beings: animals and living creatures, even if edible. "
        "10 Nature & Environment: plants, earth, air, water, weather, landscapes. "
        "11 Science & Technology: science, computers, devices, inventions. "
        "12 Business & Economy: money, trade, markets, finance. "
        "13 Law & Politics: rules, government, crime, rights. "
        "14 Sports & Leisure: games, sports, hobbies, free-time fun. "
        "15 Emotions & Relationships: feelings, family, friendship, love. "
        "16 Other / Abstract: abstract, grammatical, or unclassifiable meanings.")

TIEBREAK = ("TIE-BREAK (apply strictly): a living being -> Animals & Living Beings even if edible "
            "(a swimming fish = Animals, a fish on the table = Food & Drink); an eating/cooking/food act -> Food & Drink; "
            "exam/school/study -> Education & Exams; job/meeting/office -> Work & Careers; "
            "art/film/music/literature -> Arts & Culture; community/tradition -> Society.")

SYS = ("You are a lexicographer tagging English word senses with topics for Persian learners. "
       "Return ONLY raw JSON, no markdown fences, no commentary.")

USER_TMPL = (
    "For EACH sense below, pick ONE primary topic label (id 1..16) AND a weight vector of 1 to 3 "
    "labels (weights 0..1, summing to 1.0). The vector's top entry must be the primary label. "
    "Use 2+ topics only where the gloss genuinely spans topics; single-topic senses get one entry @1.0. "
    f"Labels (use EXACT strings, id = position): {DEFS} "
    f"{TIEBREAK} "
    f"Id map: {json.dumps(ID2LABEL)}. "
    'Output: {"results": [{"lemma": "...", "senses": [{"sense_id": "<exact sense id>", '
    '"topic_id": N, "topic_label": "<exact label>", "confidence": 0..1, '
    '"vector": [{"topic_id": N, "topic_label": "<exact label>", "weight": w}]}]}]}. '
    "Cover EVERY sense id from the input exactly once. Weights must sum to 1.0 (+-0.01). "
    "Input follows:\n")


def lemma_block(r):
    lines = [f"LEMMA {r['lemma']}:"]
    for s in r["ranked_senses"]:
        lines.append(f"- {s['sense_id']} {s.get('gloss', '')[:200]}")
    return "\n".join(lines)


_evp = json.loads((ROOT / "packs" / "en" / "evp_sense.json").read_text(encoding="utf-8"))["entries"]
_EVP_BY_LEMMA = {}
for _k, _v in _evp.items():
    _lem = _k.split("|")[0].lower()
    _EVP_BY_LEMMA.setdefault(_lem, []).append((_k, _v))


def evp_fallback_label(lemma, gloss):
    """Deterministic evp-domain single: entry of this lemma whose guideword occurs in gloss,
    mapped to 16 labels; else None (= caller falls back to Other)."""
    cands = _EVP_BY_LEMMA.get(lemma.lower(), [])
    gl = (gloss or "").lower()
    for _k, _v in cands:
        gw = (_v.get("guideword") or "").lower().replace("_", " ")
        dom = _v.get("domain", "Other / Abstract")
        if dom == "Other / Abstract":
            continue
        # Word-boundary match: raw substring lets guideword "art" hit "heart".
        if gw and re.search(r"\b" + re.escape(gw) + r"\b", gl):
            new = MIGRATE_DEFAULT.get(dom)
            if new:
                return new
    for _k, _v in cands:  # any non-Other domain entry, first hit
        dom = _v.get("domain", "Other / Abstract")
        if dom != "Other / Abstract":
            new = MIGRATE_DEFAULT.get(dom)
            if new:
                return new
    return None


def fallback_sense(lemma, s):
    lab = evp_fallback_label(lemma, s.get("gloss", "")) or "Other / Abstract"
    src = "deterministic-evp" if lab != "Other / Abstract" else "deterministic-other"
    return {"sense_id": s["sense_id"], "topic_id": LABEL2ID[lab], "topic_label": lab,
            "confidence": 0.9,
            "vector": [{"topic_id": LABEL2ID[lab], "topic_label": lab, "weight": 1.0}],
            "source": src}


def validate_senses(items, r):
    """Returns (ok, normalized). Normalizes: sorts vector desc, renormalizes, primary = top."""
    if not isinstance(items, list):
        return False, None
    input_ids = [s["sense_id"] for s in r["ranked_senses"]]
    if sorted(x.get("sense_id") for x in items if isinstance(x, dict)) != sorted(input_ids):
        return False, None
    if len(items) != len(input_ids):
        return False, None
    normed = []
    for x in items:
        tid, lab = x.get("topic_id"), x.get("topic_label")
        if not isinstance(tid, int) or tid not in ID2LABEL or ID2LABEL[tid] != lab:
            return False, None
        try:
            conf = float(x.get("confidence"))
        except (TypeError, ValueError):
            return False, None
        if not 0.0 <= conf <= 1.0:
            return False, None
        entries = x.get("vector")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 3:
            return False, None
        total = 0.0
        for e in entries:
            if not isinstance(e, dict):
                return False, None
            et, el = e.get("topic_id"), e.get("topic_label")
            if not isinstance(et, int) or et not in ID2LABEL or ID2LABEL[et] != el:
                return False, None
            try:
                w = float(e.get("weight"))
            except (TypeError, ValueError):
                return False, None
            if not 0.0 < w <= 1.0:
                return False, None
            total += w
        if abs(total - 1.0) > TOL:
            return False, None
        fixed = sorted(
            ({"topic_id": e["topic_id"], "topic_label": e["topic_label"],
              "weight": round(float(e["weight"]) / total, 4)} for e in entries),
            key=lambda d: -d["weight"])
        normed.append({"sense_id": x["sense_id"], "topic_id": fixed[0]["topic_id"],
                       "topic_label": fixed[0]["topic_label"], "confidence": conf,
                       "vector": fixed, "source": "judge"})
    return True, normed


def call_responses(api_key, model, user_text, timeout=180):
    body = json.dumps({"model": model, "input": [
        {"role": "system", "content": SYS}, {"role": "user", "content": user_text}],
        "reasoning": {"effort": "minimal"}, "max_output_tokens": 6000}).encode()
    req = urllib.request.Request(ZEN_BASE + "/responses", data=body,
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                                          "User-Agent": "HamZaban-factory/1.0 (research lexicon v16 topics)",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    parts = []
    for item in data.get("output", []):
        for c in item.get("content", []):
            if c.get("type") == "output_text":
                parts.append(c.get("text", ""))
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--lemmas", default="", help="comma-separated lemma filter (subset run)")
    a = ap.parse_args()
    ranked = json.loads(IN_RANKED.read_text(encoding="utf-8"))
    if a.lemmas:
        want = [w.strip() for w in a.lemmas.split(",") if w.strip()]
        missing = [w for w in want if w not in {r["lemma"] for r in ranked}]
        if missing:
            sys.exit(f"unknown lemmas: {missing}")
        ranked = [r for r in ranked if r["lemma"] in want]
        ranked.sort(key=lambda r: want.index(r["lemma"]))
    elif a.limit:
        ranked = ranked[:a.limit]
    if not a.dry_run:
        OUT_MIGRATION.write_text(json.dumps(MIGRATION, ensure_ascii=False, indent=1), encoding="utf-8")
    prog = json.loads(PROG.read_text(encoding="utf-8")) if PROG.exists() else {}
    done = prog.get("done_lemmas", {})
    failed = prog.get("failed_lemmas", [])
    calls = prog.get("model_calls", {})
    key = ""
    if not a.dry_run:
        from factory.core.env_loader import load_factory_env
        env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
        key = env["OPENCODE_ZEN_API_KEY"]
        if not key:
            sys.exit("no OPENCODE_ZEN_API_KEY in factory/.env")
    from tqdm.auto import tqdm
    for i in tqdm(range(0, len(ranked), BATCH), desc="v16 topics"):
        batch = ranked[i:i + BATCH]
        todo = [r for r in batch if r["lemma"] not in done]
        if not todo:
            pass
        elif a.dry_run:
            for r in todo:
                fb = [fallback_sense(r["lemma"], s) for s in r["ranked_senses"]]
                ok, normed = validate_senses(
                    [{k: x[k] for k in ("sense_id", "topic_id", "topic_label", "confidence", "vector")} for x in fb], r)
                assert ok, r["lemma"]
                done[r["lemma"]] = normed
        else:
            user_text = USER_TMPL + "\n\n".join(lemma_block(r) for r in todo)
            ok, data, used = False, None, ""
            for model in MODELS:
                for _ in range(2):
                    try:
                        data = extract_json(call_responses(key, model, user_text))
                        ok, used = True, model
                        break
                    except AuthError:
                        raise
                    except urllib.error.HTTPError as _he:
                        raise_for_auth(_he)
                    except Exception:
                        try:
                            data = extract_json(call_responses(
                                key, model, "Your last reply was not valid JSON. Re-send ONLY the JSON object.\n" + user_text))
                            ok, used = True, model
                            break
                        except AuthError:
                            raise
                        except urllib.error.HTTPError as _he2:
                            raise_for_auth(_he2)
                        except Exception:
                            time.sleep(5)
                if ok:
                    break
            if ok:
                calls[used] = calls.get(used, 0) + 1
                by_lemma = {x.get("lemma"): x for x in data.get("results", [])}
                for r in todo:
                    x = by_lemma.get(r["lemma"], {})
                    good, normed = validate_senses(x.get("senses"), r)
                    if good:
                        done[r["lemma"]] = normed
                    else:
                        done[r["lemma"]] = [fallback_sense(r["lemma"], s) for s in r["ranked_senses"]]
                        if r["lemma"] not in failed:
                            failed.append(r["lemma"])
            else:
                for r in todo:
                    done[r["lemma"]] = [fallback_sense(r["lemma"], s) for s in r["ranked_senses"]]
                    if r["lemma"] not in failed:
                        failed.append(r["lemma"])
            time.sleep(SLEEP)
            if not a.dry_run:
                PROG.write_text(json.dumps({"done_batches": i // BATCH + 1,
                                            "total_batches": (len(ranked) + BATCH - 1) // BATCH,
                                            "done_lemmas": done, "failed_lemmas": failed,
                                            "model_calls": calls}, ensure_ascii=False), encoding="utf-8")
    labels_out, vectors_out = [], []
    for r in ranked:
        vecs = []
        for s, x in zip(r["ranked_senses"], done[r["lemma"]]):
            assert x["sense_id"] == s["sense_id"]
            src = "llm-v16" if x["source"] == "judge" else x["source"]
            labels_out.append({"card_id": s["sense_id"], "lemma": r["lemma"], "sense_id": s["sense_id"],
                               "cefr": r["cefr"], "sense_cefr": s.get("sense_cefr"), "full_text": s.get("full_text"),
                               "tier": r["tier"], "topic_id": x["topic_id"], "topic_label": x["topic_label"],
                               "confidence": x["confidence"], "topic_source": src, "p": s.get("score")})
            vecs.append({"sense_id": x["sense_id"], "vector": x["vector"], "source": x["source"]})
        vectors_out.append({"lemma": r["lemma"], "vectors": vecs})
    if a.dry_run:
        print("dry-run: no files written")
        return
    OUT_LABELS.write_text(json.dumps(labels_out, ensure_ascii=False), encoding="utf-8")
    OUT_VECTORS.write_text(json.dumps(vectors_out, ensure_ascii=False), encoding="utf-8")
    n_multi = sum(1 for l in vectors_out for v in l["vectors"] if len(v["vector"]) > 1)
    print(f"v16: {len(ranked)} lemmas, {len(labels_out)} senses, multi={n_multi}, failed={len(failed)}, calls={calls}")
    if failed:
        print(f"failed lemmas: {failed}")


if __name__ == "__main__":
    main()
