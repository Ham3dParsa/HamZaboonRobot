# v14 phase 3 — LLM judge (Stage B, locked R4). Outputs: ranked_senses-v14c.json + topic_labels-v14c.json
# Needs: factory/.env with OPENCODE_ZEN_API_KEY (OpenCode Zen, https://opencode.ai/zen/v1).
# Chain (bare API ids, NO opencode/ prefix): spark-1.3 -> spark-1.2 -> ling-3.0-flash-fin -> mimo-v2.5 -> nemotron-3.5-lightning.
# Transport: /responses, reasoning minimal (responses-only for muse-spark; chat 500s).
# Per lemma ONE call does both jobs: (a) pick beginner 2 / intermediate 3 / advanced 4 ids in judged order;
# (b) topic_label+confidence for every currently-Other sense (13 fixed labels from packs/en/topic_prototypes.json).
# Resume: v14_judge_progress.json. Batch: 8 lemmas/call. Sleep 2.5s.
# Any parse/validation failure -> deterministic fallback (score-rank top-N picks, topics stay Other), lemma logged. No placeholders.
# Dry run (no keys): python -m factory.archive.v14_v16.run_v14_phase3_judge.py --dry-run
import argparse, json, pathlib, re, sys, time
import urllib.request
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # factory/ (moved under archive/v14_v16)
from factory.core.llm_json import extract_json, raise_for_auth, AuthError
FX = ROOT / "fixtures"
IN_RANKED = FX / "ranked_senses-v14b.json"
OUT_RANKED = FX / "ranked_senses-v14c.json"
OUT_TOPICS = FX / "topic_labels-v14c.json"
PROG = ROOT / "v14_judge_progress.json"
ZEN_BASE = "https://opencode.ai/zen/v1"
MODELS = ["muse-spark-1.3-contributor-free", "muse-spark-1.2-contributor-free",
          "ling-3.0-flash-fin-free", "mimo-v2.5-free",
          "nemotron-3.5-lightning-free"]
BATCH = 8
SLEEP = 2.5
LEVEL_N = (("beginner", 2), ("intermediate", 3), ("advanced", 4))  # locked R4
# R40 v10 — S2 window expansion: judge input window 8-10 top candidates
# per high-sense lemma (parameterized cap); EVP_BOOST re-ranks senses
# lexically matching the pack evp guideword of that lemma.
JUDGE_WINDOW_CAP = 10
EVP_BOOST = 1.5
EVP_TABLE_PATH = ROOT / "packs" / "en" / "evp_sense.json"

LABELS = json.loads((ROOT / "packs" / "en" / "topic_prototypes.json").read_text(encoding="utf-8"))["labels"]
OTHER = "Other / Abstract"

SYS = ("You are a lexicographer choosing vocabulary senses for Persian learners of English. "
       "Return ONLY raw JSON, no markdown fences, no commentary.")

USER_TMPL = (
    "For EACH lemma below: (1) PICK the most useful senses per learner level as ORDERED id lists "
    "(most useful first): beginner 2 ids, intermediate 3 ids, advanced 4 ids. "
    "Prefer concrete everyday meanings for beginner, broader/academic/register-marked for advanced. "
    "If a lemma has fewer senses than a list needs, return all its ids in rank order. "
    "Every picked id MUST come from that lemma's sense list. "
    "(2) TOPIC: for each sense id flagged NEEDS_TOPIC assign one label + confidence 0-1. "
    f"Allowed labels (exact strings): {json.dumps(LABELS)}. "
    'Output: {"results": [{"lemma": "...", "picks": {"beginner": ["id", ...], "intermediate": [...], '
    '"advanced": [...]}, "topics": [{"id": "<sense id>", "label": "<one allowed label>", "confidence": 0.0}]}]}. '
    "Input follows:\n")


def load_evp_table(path=None):
    """R40: pack evp table {entry-key: {guideword...}}; missing -> {}."""
    try:
        raw = json.loads(pathlib.Path(
            path or EVP_TABLE_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return entries if isinstance(entries, dict) else {}


def evp_guide_tokens(lemma, evp_entries=None):
    """R40: guideword tokens for one lemma (split on _/non-alpha, lower)."""
    lemma = (lemma or "").strip().lower()
    if not lemma or not isinstance(evp_entries, dict):
        return set()
    tokens = set()
    for key in evp_entries:
        if not isinstance(key, str):
            continue
        parts = key.split("|")
        if not parts or parts[0].strip().lower() != lemma:
            continue
        guide = ""
        try:
            guide = str((evp_entries[key] or {}).get("guideword") or "")
        except Exception:
            guide = ""
        for tok in re.findall(r"[a-z]+", guide.lower()):
            if tok:
                tokens.add(tok)
    return tokens


def sense_gets_boost(gloss, guide_tokens):
    """R40: True when a guideword token occurs in the gloss (ci).

    F6: word-boundary match — a substring hit inside a longer word
    ("exam" in "example") must NOT boost.
    """
    if not guide_tokens:
        return False
    low = (gloss or "").lower()
    return any(tok and re.search(r"\b%s\b" % re.escape(tok), low)
               for tok in guide_tokens)


def boosted_ranked(ranked_senses, lemma, evp_entries=None):
    """R40: ranked senses sorted by score*EVP_BOOST (stable, no mutation)."""
    tokens = evp_guide_tokens(lemma, evp_entries)
    scored = []
    for order, sense in enumerate(ranked_senses or []):
        try:
            base = float(sense.get("score", 0))
        except (TypeError, ValueError):
            base = 0.0
        boosted = base * EVP_BOOST if sense_gets_boost(
            sense.get("gloss", ""), tokens) else base
        scored.append((boosted, order, sense))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [s for _, _, s in scored]


def select_judge_window(ranked_senses, lemma, cap=JUDGE_WINDOW_CAP,
                        evp_entries=None):
    """R40: top-cap senses after the EVP boost (score order, stable)."""
    try:
        cap = max(1, int(cap))
    except (TypeError, ValueError):
        cap = JUDGE_WINDOW_CAP
    return boosted_ranked(ranked_senses, lemma,
                          evp_entries)[:cap]


def _first_example_text(sense):
    """R40: first dataset example text of a sense ("" when none)."""
    for raw in (sense or {}).get("examples") or []:
        if isinstance(raw, dict):
            cand = raw.get("text")
        else:
            cand = raw
        if isinstance(cand, str) and cand.strip():
            return cand.strip()[:100]
    return ""


def lemma_block(r, cap=JUDGE_WINDOW_CAP, evp_entries=None):
    """R40: judge input block over the boosted top-cap window.

    Each line carries the gloss plus the first dataset example
    (gloss + first_example[:100]). Prompt shape and validation are
    otherwise identical to the locked R4 block.
    """
    lines = [f"LEMMA {r['lemma']} (learner level {r.get('cefr', '?')}):"]
    window = select_judge_window(r.get("ranked_senses") or [],
                                 r.get("lemma", ""), cap=cap,
                                 evp_entries=evp_entries)
    for s in window:
        flag = " NEEDS_TOPIC" if s.get("topic_label") == OTHER else ""
        line = (f"- {s['sense_id']} [{s.get('sense_cefr', '?')}] "
                f"sc={s.get('score', 0):.3f}{flag} "
                f"{s.get('gloss', '')[:180]}")
        example = _first_example_text(s)
        if example:
            line += f" || ex: {example}"
        lines.append(line)
    return "\n".join(lines)


def needs_topic(r):
    return [s["sense_id"] for s in r["ranked_senses"] if s.get("topic_label") == OTHER]


def deterministic_picks(r, evp_entries=None):
    """Fallback picks over the boosted window order (still validated)."""
    window = select_judge_window(r.get("ranked_senses") or [],
                                 r.get("lemma", ""), evp_entries=evp_entries)
    ids = [s["sense_id"] for s in window]
    if not ids:
        ids = [s["sense_id"] for s in sorted(
            r.get("ranked_senses") or [],
            key=lambda s: -s.get("score", 0))]
    return {lvl: ids[:min(n, len(ids))] for lvl, n in LEVEL_N}


def validate_picks(picks, input_ids):
    if not isinstance(picks, dict):
        return False
    for lvl, n in LEVEL_N:
        want = min(n, len(input_ids))
        lst = picks.get(lvl)
        if not isinstance(lst, list) or len(lst) != want:
            return False
        if any(i not in input_ids for i in lst) or len(set(lst)) != len(lst):
            return False
    return True


def validate_topics(topics, need_ids):
    if not isinstance(topics, list):
        return False
    got = {}
    for t in topics:
        if not isinstance(t, dict) or t.get("id") not in need_ids or t.get("id") in got:
            return False
        if t.get("label") not in LABELS:
            return False
        try:
            c = float(t.get("confidence"))
        except (TypeError, ValueError):
            return False
        if not 0.0 <= c <= 1.0:
            return False
        got[t["id"]] = (t["label"], c)
    return sorted(got) == sorted(need_ids)


def call_responses(api_key, model, user_text, timeout=180):
    body = json.dumps({"model": model, "input": [
        {"role": "system", "content": SYS}, {"role": "user", "content": user_text}],
        "reasoning": {"effort": "minimal"}, "max_output_tokens": 4000}).encode()
    req = urllib.request.Request(ZEN_BASE + "/responses", data=body,
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                                          "User-Agent": "HamZaban-factory/1.0 (research lexicon judge)",
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
    a = ap.parse_args()
    ranked = json.loads(IN_RANKED.read_text(encoding="utf-8"))
    if a.limit:
        ranked = ranked[:a.limit]
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
    out_all, topic_rows = [], []
    evp_entries = load_evp_table()
    from tqdm.auto import tqdm
    for i in tqdm(range(0, len(ranked), BATCH), desc="v14c judge"):
        batch = ranked[i:i + BATCH]
        todo = [r for r in batch if r["lemma"] not in done]
        if not todo:
            pass
        elif a.dry_run:
            for r in todo:
                ids = [s["sense_id"] for s in r["ranked_senses"]]
                # F5: the judge only ever sees the boosted window, so
                # validation is against window ids (full list fallback
                # keeps backward compat when the window is empty).
                window_ids = [s["sense_id"] for s in select_judge_window(
                    r.get("ranked_senses") or [], r.get("lemma", ""),
                    evp_entries=evp_entries)] or ids
                fake = {"picks": {lvl: window_ids[:min(n, len(window_ids))] for lvl, n in LEVEL_N},
                        "topics": [{"id": k, "label": OTHER, "confidence": 0.5} for k in needs_topic(r)]}
                assert validate_picks(fake["picks"], window_ids), r["lemma"]
                assert validate_topics(fake["topics"], needs_topic(r)), r["lemma"]
                done[r["lemma"]] = fake
        else:
            user_text = USER_TMPL + "\n\n".join(
                lemma_block(r, evp_entries=evp_entries) for r in todo)
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
                    ids = [s["sense_id"] for s in r["ranked_senses"]]
                    # F5: validate picks against the window the judge saw
                    # (full-list fallback preserves old callers/tests).
                    window_ids = [s["sense_id"] for s in select_judge_window(
                        r.get("ranked_senses") or [], r.get("lemma", ""),
                        evp_entries=evp_entries)] or ids
                    need = needs_topic(r)
                    x = by_lemma.get(r["lemma"], {})
                    if validate_picks(x.get("picks"), window_ids) and validate_topics(x.get("topics", []), need):
                        done[r["lemma"]] = {"picks": x["picks"], "topics": x["topics"]}
                    else:
                        done[r["lemma"]] = {"picks": deterministic_picks(
                            r, evp_entries=evp_entries), "topics": []}
                        failed.append(r["lemma"])
            else:
                for r in todo:
                    done[r["lemma"]] = {"picks": deterministic_picks(
                        r, evp_entries=evp_entries), "topics": []}
                    failed.append(r["lemma"])
            time.sleep(SLEEP)
            if not a.dry_run:
                PROG.write_text(json.dumps({"done_batches": i // BATCH + 1,
                                            "total_batches": (len(ranked) + BATCH - 1) // BATCH,
                                            "done_lemmas": done, "failed_lemmas": failed,
                                            "model_calls": calls}, ensure_ascii=False), encoding="utf-8")
        for r in batch:
            d = done[r["lemma"]]
            tmap = {t["id"]: t for t in d.get("topics", [])}
            senses = []
            for s in r["ranked_senses"]:
                s2 = dict(s)
                if s["sense_id"] in tmap:
                    s2["topic_label"] = tmap[s["sense_id"]]["label"]
                    s2["topic_confidence"] = tmap[s["sense_id"]]["confidence"]
                    s2["topic_source"] = "judge"
                senses.append(s2)
                topic_rows.append({"card_id": s["sense_id"], "lemma": r["lemma"], "sense_id": s["sense_id"],
                                   "cefr": r.get("cefr"), "sense_cefr": s.get("sense_cefr"),
                                   "full_text": s.get("full_text", ""), "tier": r.get("tier"),
                                   "topic_id": LABELS.index(s2["topic_label"]) + 1,
                                   "topic_label": s2["topic_label"],
                                   "confidence": s2.get("topic_confidence", 0.5),
                                   "topic_source": s2.get("topic_source", ""),
                                   "p": s.get("score", 0)})
            out_all.append({**r, "ranked_senses": senses, "picks": d["picks"],
                            "pick_source": "deterministic" if r["lemma"] in failed else "judge"})
    if a.dry_run:
        print("dry-run: no files written")
        return
    OUT_RANKED.write_text(json.dumps(out_all, ensure_ascii=False), encoding="utf-8")
    OUT_TOPICS.write_text(json.dumps(topic_rows, ensure_ascii=False), encoding="utf-8")
    judged = sum(1 for r in out_all if r["pick_source"] == "judge")
    print(f"v14c: {len(out_all)} lemmas, {sum(len(x['ranked_senses']) for x in out_all)} cards, "
          f"judged={judged}, failed={len(failed)}, calls={calls}")


if __name__ == "__main__":
    main()
