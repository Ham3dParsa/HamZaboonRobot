# v14 phase 1 (deterministic, no API keys) — contract R1/R2/R3-exact/R3b/R5 LOCKED 2026-09-03.
# Reads factory/packs/en (R5). Rebuilds uniq from raw Kaikki (threads tags/src_pos/evidence),
# EVP recall guard (R2/R10), new weights (R1), exact-dup merge with synset-single freq (R3/R3b),
# keyword topics (LLM refine = phase 2, needs keys). Run: python factory/run_v14_phase1.py
import json, collections, csv, gc, math, pathlib, re
import numpy as np, torch
from tqdm.auto import tqdm
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import AgglomerativeClustering

ROOT = pathlib.Path(__file__).resolve().parent
PACK = ROOT / "packs" / "en"
OUT = ROOT / "fixtures"
RAW = pathlib.Path("W:/hamzaban_data_factory/raw/filtered_500_kaikki.jsonl")
manifest = json.loads((PACK / "pack.json").read_text(encoding="utf-8"))
W = manifest["weights"]
LEVEL_CFG = {t: manifest["tiers"][t] for t in ("beginner", "intermediate", "advanced")}
CEFR_TO_TIER = {lab: t for t, c in LEVEL_CFG.items() for lab in c["labels"]}
CEFR_NUM = {k: i + 1 for i, k in enumerate(["A1", "A2", "B1", "B2", "C1", "C2"])}
lemmas = list(csv.DictReader(open(PACK / "lemmas.csv", encoding="utf-8")))
evp = json.loads((PACK / manifest["cefr"]["sense_table"]).read_text(encoding="utf-8"))
tatoeba = json.loads((PACK / manifest["enrich"]["example_pool"]).read_text(encoding="utf-8"))
tproto = json.loads((PACK / manifest["topic"]["file"]).read_text(encoding="utf-8"))
LABELS = tproto["labels"]
print(f"v14a phase1: {len(lemmas)} lemmas, weights={W}")

device = "cuda" if torch.cuda.is_available() else "cpu"
from sentence_transformers import SentenceTransformer
st = SentenceTransformer(manifest["embed"]["model_id"], device=device)
def embed(texts):
    return st.encode(texts, batch_size=64, normalize_embeddings=True, device=device, show_progress_bar=False)
import wordfreq as wf
from nltk.corpus import wordnet as wn

def build_full_sense_text(lemma, pos, sense):
    gloss = (sense.get("gloss") or "").strip() or lemma
    exs = []
    for ex in (sense.get("examples") or [])[:3]:
        t = ex.get("text") if isinstance(ex, dict) else str(ex)
        if (t or "").strip(): exs.append(t.strip())
    syns = []
    for s in (sense.get("synonyms") or [])[:5]:
        w = s.get("word") if isinstance(s, dict) else str(s)
        if (w or "").strip(): syns.append(w.strip().replace("_", " "))
    parts = [f"{lemma} [{pos}] {gloss}"]
    if exs: parts.append(" | Examples: " + " ; ".join(exs))
    if syns: parts.append(" | Synonyms: " + ", ".join(syns))
    full = "".join(parts)
    return full[:600].rsplit(" ", 1)[0] if len(full) > 600 else full

def sense_words(gloss, synonyms, lemma):
    words = [w for w in re.findall(r"[a-zA-Z']+", (gloss or "").lower()) if len(w) >= 3 and w != lemma.lower()]
    for s in synonyms or []:
        w = (s.get("word") if isinstance(s, dict) else str(s)) or ""
        words += [p for p in re.findall(r"[a-zA-Z']+", w.lower().replace("_", " ")) if len(p) >= 3]
    return words

def freq_per_sense(gloss, synonyms, lemma):
    words = sense_words(gloss, synonyms, lemma)
    if len(words) < 3: return None  # shrink to median later (R1)
    sc = [wf.zipf_frequency(w, "en") for w in words]
    sc = [s for s in sc if s > 0]
    return float(sum(sc) / len(sc)) if sc else None

VN = {"n": "noun", "v": "verb", "a": "adj", "s": "adj", "r": "adv"}
SLANG = {"slang", "vulgar", "derogatory", "offensive"}
OLD = {"obsolete", "archaic", "dated", "historical"}
def register_penalty(tags, gloss):
    t = set((tags or []))
    if t & SLANG: return 0.60
    g = (gloss or "").strip()
    if re.search(r"alternative [\w\-]+ form of|alternative spelling of|alternative name for", g.lower()): return 0.50  # alt-form stubs (global shape rule)
    if len(g.split()) == 1 and g[:1].isupper() and g[1:2].islower(): return 0.50
    if g in ("A surname.", "A place name.", "A surname.", "A given name."): return 0.50
    if t & OLD: return 0.80
    return 1.0

def asym2(lemma_cefr, sense_cefr):
    nl, ns = CEFR_NUM.get(lemma_cefr, 3), CEFR_NUM.get(sense_cefr, 3)
    if ns <= nl: f = 1.0
    else: f = max(0.25 - 0.15 * (ns - nl), 0.05)
    return f * (1.15 if sense_cefr == lemma_cefr else 1.0)

def zipf_to_cefr(z):
    for cut, lab in zip([5.2, 4.6, 4.0, 3.5, 3.0], ["A1", "A2", "B1", "B2", "C1"]):
        if z >= cut: return lab
    return "C2"

def tatoeba_hit(lemma, gloss, synonyms):
    pool = tatoeba.get(lemma.lower(), []) or tatoeba.get(lemma, [])
    if len(pool) < 5: return 0.5
    keys = set(w for w in re.findall(r"[a-zA-Z']+", (gloss or "").lower()) if len(w) >= 4)
    for s in synonyms or []:
        w = (s.get("word") if isinstance(s, dict) else str(s)) or ""
        keys.update(p for p in re.findall(r"[a-zA-Z']+", w.lower().replace("_", " ")) if len(p) >= 4)
    if not keys: return 0.0
    hits = sum(1 for sent in pool if any(k in sent.lower() for k in keys))
    return hits / len(pool)

# ---- load raw kaikki lines per lemma (read-only source) ----
raw_by_lemma = collections.defaultdict(list)
with open(RAW, encoding="utf-8") as fh:
    for line in fh:
        try: e = json.loads(line)
        except Exception: continue
        raw_by_lemma[(e.get("word") or "").lower()].append(e)

evp_entries = evp.get("entries", {})
evp_keys = list(evp_entries.keys())
evp_texts = [f"{k.split('|')[0]} [{k.split('|')[1] if '|' in k else ''}] {evp_entries[k].get('guideword','')} {evp_entries[k].get('domain','')}" for k in evp_keys]
evp_embs = embed(evp_texts) if evp_texts else None
topic_proto_embs = embed([tproto["prototypes"][l] for l in LABELS])

wn_cache = {}
def get_wn_pool(lemma):
    key = lemma.lower()
    if key in wn_cache: return wn_cache[key]
    try: syns = wn.synsets(lemma)
    except Exception: syns = []
    if not syns:
        wn_cache[key] = ([], [], None, []); return wn_cache[key]
    glosses = [s.definition() for s in syns]
    counts = []
    for s in syns:
        c = sum(l.count() for l in s.lemmas() if l.name().lower() == lemma.lower())
        counts.append(c if c > 0 else max([l.count() for l in s.lemmas()] + [0]) or 1)
    wn_cache[key] = (glosses, counts, embed(glosses), syns)
    return wn_cache[key]

THR_V, THR_O = manifest["dedup"]["thr_verb"], manifest["dedup"]["thr_other"]
uniq = []
for it in tqdm(lemmas, desc="v14a dedup+recall"):
    w, pos, lc = it["lemma"], it["pos"], it["cefr"]
    senses = []
    for e in raw_by_lemma.get(w.lower(), []):
        epos = (e.get("pos") or "").strip().lower()
        if epos == "name": continue  # R-design risk (e): proper-noun lines don't consume slots
        for s in e.get("senses", []):
            senses.append({"gloss": (s.get("glosses", [""])[0] if s.get("glosses") else ""),
                           "examples": s.get("examples", []), "synonyms": s.get("synonyms", []),
                           "tags": s.get("tags", []), "src_pos": epos})
    for syn in wn.synsets(w):
        senses.append({"gloss": syn.definition(), "examples": [{"text": e} for e in syn.examples()],
                       "synonyms": [{"word": l.name()} for l in syn.lemmas()],
                       "tags": [], "src_pos": VN.get(syn.pos(), syn.pos())})
    n_raw = len(senses)
    if not senses:
        uniq.append({"lemma": w, "pos": pos, "cefr": lc, "uniq_senses": []}); continue
    full_texts = [build_full_sense_text(w, pos, s) for s in senses]
    emb = embed(full_texts)
    thr = THR_V if pos == "verb" else THR_O  # POS-aware (actually applied, unlike v13)
    try:
        labels = AgglomerativeClustering(n_clusters=None, metric="precomputed",
                                         linkage="average", distance_threshold=1 - thr).fit_predict(1 - cosine_similarity(emb))
    except Exception:
        labels = list(range(len(senses)))
    clusters = collections.defaultdict(list)
    for i, lab in enumerate(labels): clusters[lab].append((i, senses[i]))
    us = []
    for lab, mem in clusters.items():
        _, best = max(mem, key=lambda x: len(x[1].get("gloss") or ""))
        mex = [ex for _, m in mem for ex in (m.get("examples") or [])][:3]
        asyn = [s for _, m in mem for s in (m.get("synonyms") or [])][:5]
        tags = sorted({t for _, m in mem for t in (m.get("tags") or [])})
        spos = collections.Counter(m.get("src_pos", "") for _, m in mem).most_common(1)[0][0]
        us.append({"sense_id": f"{w}#{lab}", "gloss": best["gloss"],
                   "full_text": build_full_sense_text(w, pos, best), "examples": mex,
                   "synonyms": asyn, "tags": tags, "src_pos": spos, "cluster_id": int(lab),
                   "n_ev": len(mex) + len(asyn)})
    cap = 14 if n_raw > 12 else 9
    pre_cap = list(us)
    if len(us) > cap:
        embs = embed([x["full_text"] for x in us])
        cent = embs.mean(axis=0, keepdims=True)
        sims = (embs @ cent.T).flatten()
        lens = np.array([len(t.split()) + 2 for t in [x["full_text"] for x in us]], dtype=float)
        cl = sims / np.log(lens)
        _, counts, wembs, _ = get_wn_pool(w)
        wsm = []
        if wembs is not None and len(counts):
            sim = embs @ wembs.T
            for i in range(len(us)):
                j = int(np.argmax(sim[i]))
                wsm.append(math.log(counts[j] + 0.5) if float(sim[i][j]) > 0.35 else math.log(1.5))
        else: wsm = [math.log(1.5)] * len(us)
        order = np.argsort([wsm[i] * 10 + cl[i] for i in range(len(us))])[::-1]
        us = [us[i] for i in order[:cap]]
    # R10 EVP recall guard: guideword with no match >0.60 among kept -> swap worst kept
    if evp_embs is not None:
        kept_ids = {x["sense_id"] for x in us}
        kembs = embed([x["full_text"] for x in us]) if us else np.zeros((0, 384))
        missing = []
        for k in evp_keys:
            if k.split("|")[0].lower() != w.lower(): continue
            v = evp_entries[k]
            q = embed([f"{w} [{k.split('|')[1] if '|' in k else ''}] {v.get('guideword','')} {v.get('domain','')}"])[0]
            best = float((kembs @ q).max()) if len(us) else 0.0
            if best <= 0.60: missing.append((k, v))
        if missing and us:
            scored = sorted(range(len(us)), key=lambda i: len(us[i]["full_text"]))
            for k, v in missing:
                cand = [s for s in pre_cap if s["sense_id"] not in kept_ids]
                if not cand: break
                q = embed([f"{w} [noun] {v.get('guideword','')} {v.get('domain','')}"])[0]
                cemb = embed([c["full_text"] for c in cand])
                bi = int(np.argmax(cemb @ q))
                victim = scored.pop(0)
                kept_ids.discard(us[victim]["sense_id"])
                us[victim] = cand[bi]; kept_ids.add(cand[bi]["sense_id"])
    uniq.append({"lemma": w, "pos": pos, "cefr": lc, "uniq_senses": us, "n_raw": n_raw, "cap": cap})
    del emb
    if device == "cuda": torch.cuda.empty_cache()
    gc.collect()
(OUT / "uniq_senses-v14a.json").write_text(json.dumps(uniq, ensure_ascii=False), encoding="utf-8")
print(f"uniq v14a: {len(uniq)} lemmas, {sum(len(x['uniq_senses']) for x in uniq)} senses")

# ---- ranking R1 + topics + R9 merge ----
all_full, pos_idx = [], []
for li, it in enumerate(uniq):
    for si, s in enumerate(it["uniq_senses"]):
        all_full.append(s.get("full_text") or build_full_sense_text(it["lemma"], it["pos"], s)); pos_idx.append((li, si))
all_embs = embed(all_full) if all_full else np.zeros((0, 384))
lidx = collections.defaultdict(list)
for ix, (li, si) in enumerate(pos_idx): lidx[li].append(ix)

def resolve_cefr(sense_emb, full_text):
    if evp_embs is not None and len(evp_keys):
        sims = (sense_emb.reshape(1, -1) @ evp_embs.T).flatten()
        j, best = int(np.argmax(sims)), float(sims.max())
        if best > 0.72:
            ent = evp_entries[evp_keys[j]]
            return ent.get("cefr", "B1"), ent.get("domain", "")
        if best > 0.60:
            ent = evp_entries[evp_keys[j]]
            return ent.get("cefr", "B1"), ent.get("domain", "")
    z = sum(wf.zipf_frequency(w, "en") for w in re.findall(r"[a-zA-Z']+", full_text.lower()) if len(w) >= 3) / max(1, len(re.findall(r"[a-zA-Z']+", full_text.lower())))
    return zipf_to_cefr(z), ""

ranked, debug_rows, topic_out = [], [], []
level_cards = collections.Counter()
for li, it in enumerate(tqdm(uniq, desc="v14a ranking R1")):
    lemma, pos, lc = it["lemma"], it["pos"], it.get("cefr", "A1")
    tier, cfg = CEFR_TO_TIER.get(lc, "beginner"), LEVEL_CFG[CEFR_TO_TIER.get(lc, "beginner")]
    C, Tau, Kmax = cfg["C"], cfg["Tau"], cfg["Kmax"]
    senses, n = it["uniq_senses"], len(it["uniq_senses"])
    if n == 0:
        ranked.append({"lemma": lemma, "cefr": lc, "tier": tier, "ranked_senses": []})
        debug_rows.append({"lemma": lemma, "cefr": lc, "tier": tier, "n": 0, "k": 0}); continue
    embs = all_embs[lidx[li]]
    cent = embs.mean(axis=0, keepdims=True)
    sims_c = (embs @ cent.T).flatten()
    fulls = [s.get("full_text") or build_full_sense_text(lemma, pos, s) for s in senses]
    lens = np.array([len(t.split()) + 2 for t in fulls], dtype=float)
    cl = sims_c / np.log(lens)
    def norm(a):
        a = np.array(a, dtype=float)
        return np.ones(len(a)) * 0.5 if a.max() - a.min() < 1e-9 else (a - a.min()) / (a.max() - a.min())
    cent_norm = norm(cl)
    _, counts, wembs, _ = get_wn_pool(lemma)
    if wembs is not None and len(counts):
        sim = embs @ wembs.T
        wn_vals = [math.log(counts[int(np.argmax(sim[i]))] + 0.5) if float(sim[i].max()) > 0.35 else math.log(1.5) for i in range(n)]
    else: wn_vals = [math.log(1.5)] * n
    wn_norm = norm(wn_vals)
    fraw = [freq_per_sense(s.get("gloss", ""), s.get("synonyms", []), lemma) for s in senses]
    med = float(np.median([x for x in fraw if x is not None])) if any(x is not None for x in fraw) else 3.0
    freq_norm = norm([x if x is not None else med for x in fraw])
    scefr_dom = [resolve_cefr(embs[i], fulls[i]) for i in range(n)]
    scefr = [d[0] for d in scefr_dom]
    closeness = [1 - abs(CEFR_NUM.get(lc, 3) - CEFR_NUM.get(sc, 3)) / 5.0 for sc in scefr]
    cefr_norm = norm(closeness)
    factors = np.array([asym2(lc, sc) for sc in scefr])
    cefr_asym = cefr_norm * factors
    that = [tatoeba_hit(lemma, s.get("gloss", ""), s.get("synonyms", [])) for s in senses]
    that_norm = norm(that)
    tinfo, tprior = [], []
    for i in range(n):
        dom = scefr_dom[i][1]
        if dom and dom in LABELS and dom != "Other / Abstract":
            tinfo.append((dom, 0.65, "evp-domain")); tprior.append(1.0); continue
        sims_t = (embs[i].reshape(1, -1) @ topic_proto_embs.T).flatten()
        j, best = int(np.argmax(sims_t)), float(sims_t.max())
        lab = LABELS[j] if best >= 0.50 else "Other / Abstract"
        tinfo.append((lab, best if best >= 0.50 else 0.50, "keyword" if best >= 0.50 else "keyword-other"))
        tprior.append(1.0 if lab != "Other / Abstract" else 0.92)
    topic_norm = norm(tprior)
    preg = np.array([register_penalty(s.get("tags", []), s.get("gloss", "")) for s in senses])
    ppos = np.array([0.70 if (s.get("src_pos") == "verb" and pos != "verb") else 1.0 for s in senses])
    p_raw = (W["w_freq"] * freq_norm + W["w_cefr"] * cefr_asym + W["w_wn"] * wn_norm
             + W["w_cent"] * cent_norm + W["w_topic"] * topic_norm + W["w_tatoeba"] * that_norm)
    p_raw = np.maximum(p_raw, 1e-6) * preg * ppos
    p = p_raw / p_raw.sum()
    order = np.argsort(-p, kind="stable")
    ps, s_sorted = p[order], [senses[i] for i in order]
    ti_sorted = [tinfo[i] for i in order]
    sc_sorted = [scefr[i] for i in order]
    ft_sorted = [fulls[i] for i in order]
    cum = np.cumsum(ps)
    k_ch = None
    for k in range(1, n + 1):
        if k > Kmax: break
        nxt = float(ps[k]) if k < n else 0.0
        if float(cum[k - 1]) >= C and (k == n or nxt < Tau):
            k_ch = k; break
    if k_ch is None:
        for k in range(1, min(n, Kmax) + 1):
            if float(cum[k - 1]) >= C:
                k_ch = k; break
        if k_ch is None: k_ch = min(n, Kmax)
    kept = list(zip(s_sorted[:k_ch], ps[:k_ch], ti_sorted[:k_ch], sc_sorted[:k_ch], ft_sorted[:k_ch]))
    # R9 exact-dup merge (R3b: max p, survivor examples only, merged_from recorded)
    seen, merged = {}, []
    for s, pv, ti, sc, ft in kept:
        key = " ".join((s.get("gloss") or "").lower().split()).rstrip(".")
        if key in seen:
            tgt = seen[key]
            if float(pv) > float(tgt["p"]):
                tgt.update({"sense_id": s["sense_id"], "gloss": s["gloss"], "full_text": ft,
                            "examples": s.get("examples", []), "p": round(float(pv), 4),
                            "sense_cefr": sc, "topic": ti})
            tgt["merged_from"].append(s["sense_id"])
            extra_syn = [x for x in (s.get("synonyms") or []) if x not in tgt["synonyms"]][: max(0, 5 - len(tgt["synonyms"]))]
            tgt["synonyms"] += extra_syn
        else:
            seen[key] = {"sense_id": s["sense_id"], "gloss": s["gloss"], "full_text": ft,
                         "p": round(float(pv), 4), "examples": s.get("examples", []),
                         "synonyms": list(s.get("synonyms", []))[:5], "sense_cefr": sc,
                         "topic": ti, "merged_from": []}
            merged.append(seen[key])
    merged.sort(key=lambda m: -m["p"])
    rs = []
    for idx, m in enumerate(merged):
        lab, conf, tsrc = m["topic"]
        tid = LABELS.index(lab) + 1 if lab in LABELS else 13
        rs.append({"sense_id": m["sense_id"], "gloss": m["gloss"], "full_text": m["full_text"],
                   "score": m["p"], "p_rank": idx + 1, "examples": m["examples"], "synonyms": m["synonyms"],
                   "topic_label": lab, "topic_confidence": round(float(conf), 3), "topic_id": tid,
                   "topic_source": tsrc,
                   "sense_cefr": m["sense_cefr"], "lemma_cefr": lc, "merged_from": m["merged_from"]})
        topic_out.append({"card_id": m["sense_id"], "lemma": lemma, "sense_id": m["sense_id"], "cefr": lc,
                          "sense_cefr": m["sense_cefr"], "full_text": m["full_text"], "tier": tier,
                          "topic_id": tid, "topic_label": lab, "confidence": round(float(conf), 3),
                          "topic_source": tsrc, "p": m["p"]})
    ranked.append({"lemma": lemma, "cefr": lc, "tier": tier, "ranked_senses": rs})
    level_cards[lc] += len(rs)
    debug_rows.append({"lemma": lemma, "cefr": lc, "tier": tier, "n": n, "k": k_ch,
                       "top1": rs[0]["sense_id"] if rs else None,
                       "top1_gloss": (rs[0]["gloss"] if rs else "")[:80],
                       "top1_cefr": rs[0]["sense_cefr"] if rs else None,
                       "top1_topic": rs[0]["topic_label"] if rs else None})
print(f"ranked v14a: {len(ranked)} lemmas, {sum(len(x['ranked_senses']) for x in ranked)} cards, per-CEFR {dict(sorted(level_cards.items()))}")
(OUT / "ranked_senses-v14a.json").write_text(json.dumps(ranked, ensure_ascii=False), encoding="utf-8")
(OUT / "ranked_senses-v14a.debug.json").write_text(json.dumps(debug_rows, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "topic_labels-v14a.json").write_text(json.dumps(topic_out, ensure_ascii=False, indent=2), encoding="utf-8")
oth = sum(1 for t in topic_out if t["topic_label"] == "Other / Abstract")
print(f"Other/topic rows: {oth}/{len(topic_out)} = {oth/max(1,len(topic_out))*100:.1f}%")
import collections as _c
print("topic sources:", dict(_c.Counter(t.get("topic_source", "?") for t in topic_out)))
probes = {}
for probe in ("rock", "light", "pass", "flat"):
    r = next(x for x in ranked if x["lemma"] == probe)
    probes[probe] = [{"sense_id": s["sense_id"], "gloss": (s["gloss"] or "")[:70], "score": s["score"],
                      "sense_cefr": s["sense_cefr"], "topic": s["topic_label"], "tsrc": s.get("topic_source"),
                      "merged_from": s.get("merged_from", [])} for s in r["ranked_senses"]]
    print(f"== {probe}: " + " | ".join(f"{s['sense_id']} [{s['sense_cefr']}/{s['topic_label']}] {s['gloss'][:45]}" for s in r["ranked_senses"][:5]))
(OUT / "probes-v14a.json").write_text(json.dumps(probes, ensure_ascii=False, indent=2), encoding="utf-8")