# v14 phase 2 — LLM merge (Stage A, locked R3/R3b). Output: ranked_senses-v14b.json
# Needs: factory/.env with OPENCODE_ZEN_API_KEY (OpenCode Zen, https://opencode.ai/zen/v1).
# Chain (all Zen, free): spark-1.3 -> spark-1.2 -> ling-3.0-flash-fin -> mimo-v2.5 -> nemotron-3.5-lightning.
# Transport: /responses, reasoning minimal (responses-only for muse-spark; chat 500s).
# Resume: v14_merge_progress.json. Batch: 8 lemmas/call. Fallback per lemma: singleton clusters.
# Dry run (no keys): python factory/run_v14_phase2_merge.py --dry-run
import argparse, json, pathlib, re, sys, time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
FX = ROOT / "fixtures"
OUT_RANKED = FX / "ranked_senses-v14b.json"
PROG = ROOT / "v14_merge_progress.json"
ZEN_BASE = "https://opencode.ai/zen/v1"
MODELS = ["muse-spark-1.3-contributor-free", "muse-spark-1.2-contributor-free",
          "ling-3.0-flash-fin-free", "mimo-v2.5-free",
          "nemotron-3.5-lightning-free"]
BATCH = 8
SLEEP = 2.5

SYS = ("You are a lexicographer merging duplicate dictionary senses for Persian learners of English. "
       "Return ONLY raw JSON, no markdown fences, no commentary.")
USER_TMPL = (
    "For EACH lemma below, group sense ids with the SAME core meaning into one cluster. "
    "MERGE iff paraphrases of one meaning (same definition in different words, e.g. identical glosses). "
    "KEEP SEPARATE iff different nuance, register, transitivity, count/mass use, POS, or proper-noun/slang vs common sense "
    "(never merge a proper-noun sense with a common sense). "
    "Every input sense id must appear in EXACTLY ONE cluster. "
    'Output: {"results": [{"lemma": "...", "clusters": [{"rep_hint": "<one input id>", "members": ["<ids>"], '
    '"reason": "<max 8 words>", "drop_examples": ["<example text that does NOT illustrate rep_hint meaning>"]}]}]}. '
    "drop_examples lists member examples that do NOT fit the cluster meaning (they will be discarded). "
    "Input follows:\n")

def lemma_block(r):
    lines = [f"LEMMA {r['lemma']} (learner level {r.get('cefr','?')}):"]
    for s in r["ranked_senses"]:
        ex = " | ".join((e if isinstance(e, str) else e.get("text", ""))[:120] for e in (s.get("examples") or [])[:2])
        sy = ", ".join((w if isinstance(w, str) else w.get("word", "")) for w in (s.get("synonyms") or [])[:5])
        lines.append(f"- {s['sense_id']} [{s.get('sense_cefr','?')}] {s.get('gloss','')[:200]}"
                     + (f" || ex: {ex}" if ex else "") + (f" || syn: {sy}" if sy else ""))
    return "\n".join(lines)

def call_responses(api_key, model, user_text, timeout=120):
    body = json.dumps({"model": model, "input": [
        {"role": "system", "content": SYS}, {"role": "user", "content": user_text}],
        "reasoning": {"effort": "minimal"}, "max_output_tokens": 4000}).encode()
    req = urllib.request.Request(ZEN_BASE + "/responses", data=body,
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                                          "User-Agent": "HamZaban-factory/1.0 (research lexicon merge)",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    parts = []
    for item in data.get("output", []):
        for c in item.get("content", []):
            if c.get("type") == "output_text": parts.append(c.get("text", ""))
    return "".join(parts)

def extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m: raise ValueError("no JSON object")
    return json.loads(m.group(0))

def validate(clusters, input_ids):
    seen = []
    for c in clusters:
        if c.get("rep_hint") not in c.get("members", []): return False
        seen += c.get("members", [])
    return sorted(seen) == sorted(input_ids)

def apply_merge(ranked_entry, clusters):
    by_id = {s["sense_id"]: s for s in ranked_entry["ranked_senses"]}
    out = []
    for c in clusters:
        members = [by_id[i] for i in c["members"] if i in by_id]
        if not members: continue
        rep = max(members, key=lambda s: s.get("score", 0))  # deterministic: highest score (R3b)
        drop = set(c.get("drop_examples", []) or [])
        merged_from = [s["sense_id"] for s in members if s["sense_id"] != rep["sense_id"]]
        ex = [e for e in (rep.get("examples") or [])
              if (e if isinstance(e, str) else e.get("text", "")) not in drop]
        syn = list(dict.fromkeys([(w if isinstance(w, str) else w.get("word", ""))
                                  for s in members for w in (s.get("synonyms") or [])]))[:5]
        out.append({**rep, "examples": ex, "synonyms": syn,
                    "merged_from": sorted(set(rep.get("merged_from", [])) | set(merged_from))})
    out.sort(key=lambda s: -s.get("score", 0))
    for i, s in enumerate(out): s["p_rank"] = i + 1
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    ranked = json.loads((FX / "ranked_senses-v14a.json").read_text(encoding="utf-8"))
    if a.limit: ranked = ranked[:a.limit]
    prog = json.loads(PROG.read_text(encoding="utf-8")) if PROG.exists() else {}
    done = prog.get("done_lemmas", {})
    failed = prog.get("failed_lemmas", [])
    key = ""
    if not a.dry_run:
        import sys as _s
        _s.path.insert(0, str(ROOT))
        from env_loader import load_factory_env
        env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
        key = env["OPENCODE_ZEN_API_KEY"]
        if not key: sys.exit("no OPENCODE_ZEN_API_KEY in factory/.env")
    merged_total, new_cards = 0, 0
    out_all = []
    from tqdm.auto import tqdm
    for i in tqdm(range(0, len(ranked), BATCH), desc="v14b merge"):
        batch = ranked[i:i + BATCH]
        todo = [r for r in batch if r["lemma"] not in done]
        if not todo:
            out_all += [dict(r, ranked_senses=done[r["lemma"]]) for r in batch]; continue
        if a.dry_run:
            for r in todo:
                prompt = USER_TMPL + "\n\n".join(lemma_block(x) for x in [r])
                ids = [s["sense_id"] for s in r["ranked_senses"]]
                fake = {"results": [{"lemma": r["lemma"],
                                     "clusters": [{"rep_hint": k, "members": [k], "reason": "dry", "drop_examples": []} for k in ids]}]}
                assert validate(fake["results"][0]["clusters"], ids), r["lemma"]
                done[r["lemma"]] = apply_merge(r, fake["results"][0]["clusters"])
            out_all += [dict(r, ranked_senses=done[r["lemma"]]) for r in batch]
            continue
        user_text = USER_TMPL + "\n\n".join(lemma_block(r) for r in todo)
        ok, data = False, None
        for model in MODELS:
            for attempt in range(2):
                try:
                    data = extract_json(call_responses(key, model, user_text))
                    ok = True; break
                except Exception:
                    try:
                        data = extract_json(call_responses(key, model, "Your last reply was not valid JSON. Re-send ONLY the JSON object.\n" + user_text))
                        ok = True; break
                    except Exception: time.sleep(5)
            if ok: break
        if ok:
            by_lemma = {x.get("lemma"): x.get("clusters", []) for x in data.get("results", [])}
            for r in todo:
                ids = [s["sense_id"] for s in r["ranked_senses"]]
                cl = by_lemma.get(r["lemma"], [])
                if cl and validate(cl, ids):
                    done[r["lemma"]] = apply_merge(r, cl)
                    merged_total += sum(1 for s in done[r["lemma"]] if s.get("merged_from"))
                else:
                    done[r["lemma"]] = r["ranked_senses"]; failed.append(r["lemma"])
        else:
            for r in todo:
                done[r["lemma"]] = r["ranked_senses"]; failed.append(r["lemma"])
        time.sleep(SLEEP)
        PROG.write_text(json.dumps({"done_batches": i // BATCH + 1,
                                    "total_batches": (len(ranked) + BATCH - 1) // BATCH,
                                    "done_lemmas": done, "failed_lemmas": failed,
                                    "merged_cards": merged_total}, ensure_ascii=False), encoding="utf-8")
        out_all += [dict(r, ranked_senses=done[r["lemma"]]) for r in batch]
    OUT_RANKED.write_text(json.dumps(out_all, ensure_ascii=False), encoding="utf-8")
    print(f"v14b: {len(out_all)} lemmas, {sum(len(x['ranked_senses']) for x in out_all)} cards, merged={merged_total}, failed={len(failed)}")

if __name__ == "__main__":
    main()
