# v16b — Other top-up: relabel ONLY the 552 v16 Other/Abstract senses (locked owner order 2026-09-03).
# Reuses v16 transport/batch/resume/validation pattern exactly. Stronger prompt only.
# Scope: factory-research, worktree only, no commit, no PR.
# Inputs: ranked_senses-v14c.json (gloss) + topic_labels-v16.json (552 Other ids) + topic_vectors-v16.json (keep vectors).
# Outputs: fixtures/topic_labels-v16b.json (full 1676: kept non-Other unchanged + relabeled Others, source llm-v16b)
#          fixtures/topic_vectors-v16b.json (full 1676 vectors, same rule)
#          v16b_progress.json (resume: done_lemmas with relabeled Other senses only, failed_lemmas, model_calls)
# Fallback per lemma: keep original v16 Other rows unchanged, logged in failed_lemmas.
# Validation: ids exact (subset), topic_id 1..16, label matches id, weights sum 1.0+-0.01, primary == vector top.
# Transport: Zen /responses, bare model ids, browser UA, reasoning minimal. Batch 8 lemmas, sleep 2.5s, live tqdm, resume every batch.
# Usage: dry-run: python -m factory.archive.v14_v16.run_v16b_topup.py --dry-run --limit 8
#        smoke:    python -m factory.archive.v14_v16.run_v16b_topup.py --lemmas rock,light,pass,flat
#        full:     python -m factory.archive.v14_v16.run_v16b_topup.py
import argparse, json, pathlib, re, sys, time
import urllib.request
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # factory/ (moved under archive/v14_v16)
from factory.core.llm_json import extract_json, raise_for_auth, AuthError
FX = ROOT / "fixtures"
IN_RANKED = FX / "ranked_senses-v14c.json"
IN_LABELS16 = FX / "topic_labels-v16.json"
IN_VECTORS16 = FX / "topic_vectors-v16.json"
OUT_LABELS = FX / "topic_labels-v16b.json"
OUT_VECTORS = FX / "topic_vectors-v16b.json"
PROG = ROOT / "v16b_progress.json"
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
    "IMPORTANT — Other / Abstract (id 16) is a LAST RESORT. Assign a real topic (1..15) wherever "
    "genuinely fitting, even if the fit is partial: express partial fit with a second/third label "
    "and weights (e.g. a theatre ticket = Arts & Culture 0.6 + Society 0.4; exam nerves = Education & Exams 0.6 "
    "+ Emotions & Relationships 0.4; a work outing = Work & Careers 0.5 + Society 0.5). "
    "MULTI-LABEL IS EXPLICITLY ALLOWED AND ENCOURAGED: use up to 3 labels with weights summing to 1.0 "
    "whenever a sense genuinely belongs to more than one head (e.g. rock music = Arts & Culture + Emotions & Relationships). "
    "Do NOT force-fit: genuinely abstract, grammatical, or otherwise unclassifiable senses stay Other / Abstract @1.0 "
    "(function words and vague placeholders such as about/always/anything/both/each, generic amount/time/degree words "
    "with no topical anchor). Single-topic senses get one entry @1.0. "
    f"Labels (use EXACT strings, id = position): {DEFS} "
    f"{TIEBREAK} "
    f"Id map: {json.dumps(ID2LABEL)}. "
    'Output: {"results": [{"lemma": "...", "senses": [{"sense_id": "<exact sense id>", '
    '"topic_id": N, "topic_label": "<exact label>", "confidence": 0..1, '
    '"vector": [{"topic_id": N, "topic_label": "<exact label>", "weight": w}]}]}]}. '
    "Cover EVERY sense id from the input exactly once. Weights must sum to 1.0 (+-0.01). "
    "Input follows:\n")


def lemma_block(lemma, senses):
    lines = [f"LEMMA {lemma}:"]
    for s in senses:
        lines.append(f"- {s['sense_id']} {s.get('gloss', '')[:200]}")
    return "\n".join(lines)


def validate_senses(items, want_ids):
    if not isinstance(items, list):
        return False, None
    if sorted(x.get("sense_id") for x in items if isinstance(x, dict)) != sorted(want_ids):
        return False, None
    if len(items) != len(want_ids):
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
                                          "User-Agent": "HamZaban-factory/1.0 (research lexicon v16b topup)",
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
    labels16 = json.loads(IN_LABELS16.read_text(encoding="utf-8"))
    vectors16 = json.loads(IN_VECTORS16.read_text(encoding="utf-8"))
    other_ids = {r["sense_id"] for r in labels16 if r["topic_id"] == 16}
    label_by_id = {r["sense_id"]: r for r in labels16}
    vec_by_lemma = {v["lemma"]: {x["sense_id"]: x for x in v["vectors"]} for v in vectors16}
    # todo: per lemma, only Other senses (with gloss from ranked)
    todo_lemmas = []
    for r in ranked:
        others = [s for s in r["ranked_senses"] if s["sense_id"] in other_ids]
        if others:
            todo_lemmas.append({"lemma": r["lemma"], "cefr": r.get("cefr"), "tier": r.get("tier"),
                                "senses": others})
    if a.lemmas:
        want = [w.strip() for w in a.lemmas.split(",") if w.strip()]
        todo_lemmas = [t for t in todo_lemmas if t["lemma"] in want]
        if not todo_lemmas:
            sys.exit(f"no Other-touching lemmas among: {want}")
    elif a.limit:
        todo_lemmas = todo_lemmas[:a.limit]
    todo_lemmas.sort(key=lambda t: t["lemma"])
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
    for i in tqdm(range(0, len(todo_lemmas), BATCH), desc="v16b topup"):
        batch = todo_lemmas[i:i + BATCH]
        todo = [t for t in batch if t["lemma"] not in done]
        if not todo:
            pass
        elif a.dry_run:
            for t in todo:
                # dry-run: keep Other (validates plumbing, no model)
                keep = []
                for s in t["senses"]:
                    old = label_by_id[s["sense_id"]]
                    keep.append({"sense_id": s["sense_id"], "topic_id": 16,
                                 "topic_label": "Other / Abstract", "confidence": 0.9,
                                 "vector": [{"topic_id": 16, "topic_label": "Other / Abstract", "weight": 1.0}],
                                 "source": "judge"})
                ok, normed = validate_senses(
                    [{k: x[k] for k in ("sense_id", "topic_id", "topic_label", "confidence", "vector")} for x in keep],
                    [s["sense_id"] for s in t["senses"]])
                assert ok, t["lemma"]
                done[t["lemma"]] = normed
        else:
            user_text = USER_TMPL + "\n\n".join(lemma_block(t["lemma"], t["senses"]) for t in todo)
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
                for t in todo:
                    x = by_lemma.get(t["lemma"], {})
                    good, normed = validate_senses(x.get("senses"), [s["sense_id"] for s in t["senses"]])
                    if good:
                        done[t["lemma"]] = normed
                    else:
                        done[t["lemma"]] = None  # sentinel: keep original v16 Other
                        if t["lemma"] not in failed:
                            failed.append(t["lemma"])
            else:
                for t in todo:
                    done[t["lemma"]] = None
                    if t["lemma"] not in failed:
                        failed.append(t["lemma"])
            time.sleep(SLEEP)
            if not a.dry_run:
                PROG.write_text(json.dumps({"done_batches": i // BATCH + 1,
                                            "total_batches": (len(todo_lemmas) + BATCH - 1) // BATCH,
                                            "done_lemmas": done, "failed_lemmas": failed,
                                            "model_calls": calls}, ensure_ascii=False), encoding="utf-8")
    # Merge: full 1676 rows. Non-Other kept byte-identical except file; Others replaced where relabeled.
    new_by_sense = {}
    for lemma, items in done.items():
        if items:
            for x in items:
                new_by_sense[x["sense_id"]] = x
    labels_out, vectors_out = [], []
    n_relabel = n_still_other = n_keep = 0
    # vectors: need per-lemma merge; build from ranked order
    vec_map_new = dict(new_by_sense)
    for r in ranked:
        vecs = []
        for s in r["ranked_senses"]:
            sid = s["sense_id"]
            if sid in vec_map_new:
                x = vec_map_new[sid]
                src = "llm-v16b"
                labels_out.append({"card_id": sid, "lemma": r["lemma"], "sense_id": sid,
                                   "cefr": r["cefr"], "sense_cefr": s.get("sense_cefr"), "full_text": s.get("full_text"),
                                   "tier": r["tier"], "topic_id": x["topic_id"], "topic_label": x["topic_label"],
                                   "confidence": x["confidence"], "topic_source": src, "p": s.get("score")})
                vecs.append({"sense_id": sid, "vector": x["vector"], "source": "judge-v16b"})
                n_relabel += 1
                if x["topic_id"] == 16:
                    n_still_other += 1
            else:
                old = label_by_id[sid]
                labels_out.append(dict(old))
                ov = vec_by_lemma[r["lemma"]][sid]
                vecs.append({"sense_id": sid, "vector": ov["vector"], "source": ov["source"]})
                if old["topic_id"] != 16:
                    n_keep += 1
                else:
                    # Other sense whose lemma failed validation -> kept Other
                    n_relabel += 0
                    n_still_other += 1
        vectors_out.append({"lemma": r["lemma"], "vectors": vecs})
    if a.dry_run:
        print("dry-run: no files written")
        return
    OUT_LABELS.write_text(json.dumps(labels_out, ensure_ascii=False), encoding="utf-8")
    OUT_VECTORS.write_text(json.dumps(vectors_out, ensure_ascii=False), encoding="utf-8")
    n_multi = sum(1 for l in vectors_out for v in l["vectors"] if len(v["vector"]) > 1)
    print(f"v16b: {len(todo_lemmas)} Other-lemmas, {len(labels_out)} senses, relabeled={n_relabel}, kept={n_keep}, still_other={n_still_other}, multi={n_multi}, failed={len(failed)}, calls={calls}")
    if failed:
        print(f"failed lemmas (kept v16 Other): {failed}")


if __name__ == "__main__":
    main()
