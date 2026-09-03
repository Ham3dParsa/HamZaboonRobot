# v15 — weighted topic vectors (locked spec, see plan-v14.md v15 + CONTEXT-v14).
# For EVERY sense (all 1676): up to 3 topic labels from the 13 fixed labels, weights sum 1.0.
# Primary = current v14c label in most cases; model may reorder with justification in weights.
# Transport: OpenCode Zen /responses, bare model ids (NO opencode/ prefix), browser UA, reasoning minimal.
# Batch 8 lemmas/call (~63 calls), sleep 2.5s, live tqdm, resume JSON after every batch.
# Any lemma failure -> fallback: current single v14c label @1.0, source deterministic, logged.
# Output: factory/fixtures/topic_vectors-v15.json
# Usage: dry-run: python factory/run_v15_topics.py --dry-run --limit 8
#        smoke:    python factory/run_v15_topics.py --limit 8
#        full:     python factory/run_v15_topics.py
# Needs: factory/.env with OPENCODE_ZEN_API_KEY. Never prints keys, never stages .env.
import argparse, json, pathlib, re, sys, time
import urllib.request
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from llm_json import extract_json, raise_for_auth, AuthError
FX = ROOT / "fixtures"
IN_RANKED = FX / "ranked_senses-v14c.json"
OUT_VECTORS = FX / "topic_vectors-v15.json"
PROG = ROOT / "v15_progress.json"
ZEN_BASE = "https://opencode.ai/zen/v1"
MODELS = ["muse-spark-1.3-contributor-free", "muse-spark-1.2-contributor-free",
          "ling-3.0-flash-fin-free", "mimo-v2.5-free",
          "nemotron-3.5-lightning-free"]
BATCH = 8
SLEEP = 2.5
TOL = 0.01

_proto = json.loads((ROOT / "packs" / "en" / "topic_prototypes.json").read_text(encoding="utf-8"))
LABELS = _proto["labels"]
ID2LABEL = {i + 1: lab for i, lab in enumerate(LABELS)}
LABEL2ID = {lab: i + 1 for i, lab in enumerate(LABELS)}

SYS = ("You are a lexicographer tagging English word senses with topic weights for Persian learners. "
       "Return ONLY raw JSON, no markdown fences, no commentary.")

USER_TMPL = (
    "For EACH sense below, assign 1 to 3 topic labels with weights (numbers 0..1) summing to 1.0. "
    "The CURRENT label is usually the primary topic — keep it first with the largest weight UNLESS "
    "the gloss genuinely spans another topic (e.g. rock music = Society & Culture + Emotions & Relationships; "
    "a flat tire on a trip = Travel & Transportation + Daily Life & Home). "
    "Use 2+ topics only where genuinely mixed; single-topic senses get one entry with weight 1.0. "
    f"Allowed labels with ids (use EXACT strings): {json.dumps(ID2LABEL)}. "
    'Output: {"results": [{"lemma": "...", "vectors": [{"sense_id": "<exact sense id>", '
    '"vector": [{"topic_id": N, "topic_label": "<exact allowed label>", "weight": w}]}]}]}. '
    "Cover EVERY sense id from the input exactly once. Weights must sum to 1.0 (±0.01). "
    "Input follows:\n")


def lemma_block(r):
    lines = [f"LEMMA {r['lemma']}:"]
    for s in r["ranked_senses"]:
        lab = s.get("topic_label", "Other / Abstract")
        lines.append(f"- {s['sense_id']} [current: {lab}] {s.get('gloss', '')[:200]}")
    return "\n".join(lines)


def fallback_vectors(r):
    vecs = []
    for s in r["ranked_senses"]:
        lab = s.get("topic_label", "Other / Abstract")
        vecs.append({"sense_id": s["sense_id"],
                     "vector": [{"topic_id": LABEL2ID[lab], "topic_label": lab, "weight": 1.0}],
                     "source": "deterministic"})
    return vecs


def validate_vectors(vecs, r):
    """Returns (ok, normalized_vecs). Renormalizes weights within tolerance."""
    if not isinstance(vecs, list):
        return False, None
    input_ids = [s["sense_id"] for s in r["ranked_senses"]]
    if sorted(v.get("sense_id") for v in vecs if isinstance(v, dict)) != sorted(input_ids):
        return False, None
    if len(vecs) != len(input_ids):
        return False, None
    normed = []
    for v in vecs:
        entries = v.get("vector")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 3:
            return False, None
        total = 0.0
        for e in entries:
            if not isinstance(e, dict):
                return False, None
            tid = e.get("topic_id")
            lab = e.get("topic_label")
            if not isinstance(tid, int) or tid not in ID2LABEL or ID2LABEL[tid] != lab:
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
        fixed = [{"topic_id": e["topic_id"], "topic_label": e["topic_label"],
                  "weight": round(float(e["weight"]) / total, 4)} for e in entries]
        normed.append({"sense_id": v["sense_id"], "vector": fixed, "source": "judge"})
    return True, normed


def call_responses(api_key, model, user_text, timeout=180):
    body = json.dumps({"model": model, "input": [
        {"role": "system", "content": SYS}, {"role": "user", "content": user_text}],
        "reasoning": {"effort": "minimal"}, "max_output_tokens": 4000}).encode()
    req = urllib.request.Request(ZEN_BASE + "/responses", data=body,
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                                          "User-Agent": "HamZaban-factory/1.0 (research lexicon v15 topics)",
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
        want = {w.strip() for w in a.lemmas.split(",") if w.strip()}
        ranked = [r for r in ranked if r["lemma"] in want]
        missing = want - {r["lemma"] for r in ranked}
        if missing:
            sys.exit(f"unknown lemmas: {sorted(missing)}")
    elif a.limit:
        ranked = ranked[:a.limit]
    prog = json.loads(PROG.read_text(encoding="utf-8")) if PROG.exists() else {}
    done = prog.get("done_lemmas", {})
    failed = prog.get("failed_lemmas", [])
    calls = prog.get("model_calls", {})
    key = ""
    if not a.dry_run:
        sys.path.insert(0, str(ROOT))
        from env_loader import load_factory_env
        env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
        key = env["OPENCODE_ZEN_API_KEY"]
        if not key:
            sys.exit("no OPENCODE_ZEN_API_KEY in factory/.env")
    from tqdm.auto import tqdm
    for i in tqdm(range(0, len(ranked), BATCH), desc="v15 topics"):
        batch = ranked[i:i + BATCH]
        todo = [r for r in batch if r["lemma"] not in done]
        if not todo:
            pass
        elif a.dry_run:
            for r in todo:
                vecs = fallback_vectors(r)
                ok, normed = validate_vectors(
                    [{"sense_id": v["sense_id"], "vector": v["vector"]} for v in vecs], r)
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
                    good, normed = validate_vectors(x.get("vectors"), r)
                    if good:
                        done[r["lemma"]] = normed
                    else:
                        done[r["lemma"]] = fallback_vectors(r)
                        if r["lemma"] not in failed:
                            failed.append(r["lemma"])
            else:
                for r in todo:
                    done[r["lemma"]] = fallback_vectors(r)
                    if r["lemma"] not in failed:
                        failed.append(r["lemma"])
            time.sleep(SLEEP)
            PROG.write_text(json.dumps({"done_batches": i // BATCH + 1,
                                        "total_batches": (len(ranked) + BATCH - 1) // BATCH,
                                        "done_lemmas": done, "failed_lemmas": failed,
                                        "model_calls": calls}, ensure_ascii=False), encoding="utf-8")
    out_all = [{"lemma": r["lemma"], "vectors": done[r["lemma"]]} for r in ranked]
    OUT_VECTORS.write_text(json.dumps(out_all, ensure_ascii=False), encoding="utf-8")
    n_senses = sum(len(x["vectors"]) for x in out_all)
    n_multi = sum(1 for x in out_all for v in x["vectors"] if len(v["vector"]) > 1)
    print(f"v15: {len(out_all)} lemmas, {n_senses} senses, multi={n_multi}, failed={len(failed)}, calls={calls}")


if __name__ == "__main__":
    main()
