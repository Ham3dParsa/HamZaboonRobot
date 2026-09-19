# Linker changelog (condensation, 0.1 → 0.8)

Faithful condensation of `W:\hamzaban_data_factory\proof-linker\VERSIONS.md`
(top-level; the `v1\VERSIONS.md` file covers 0.5.x–0.8.x in finer detail).
Full reports, witness scripts and frozen runners stay on `W:` (READ-ONLY,
never imported) — this file speaks only: what changed, LINK precision,
LINK counts.

- **0.1 (frozen):** `linker.py` + `link_table.tsv` + `REPORT.md` +
  `CALIBRATION.md` — 16 links, **16/16 = 100%** LINK precision on 6 probes
  (interest, outside, call, hot, address, run), iter1–iter6. `linker_v1b.py`
  (iter7 Sd-dedupe) — **96.3%** (26/27 rows; only the `book/hoaZwz7Y`
  granularity miss left). Attach L8 on 42 rows; 5 inflection-miss EMPTYs.
  Verdict: NO-GO on Oxford-5000 sampling (inflection-blind selector, CEFR
  TSV 12/42).
- **0.2:** BUILD `linker_v0_2.py` = v1b byte-identical + inflection-aware
  example matching + in-file L8 attach. 16 probes (10 old + mistake, use,
  execution, get, well, catfish). `link_table_v0_2.tsv`: 688 rows
  (682 senses + 6 twin-inventory); 42/42 v1b LINK pairs intact, ZERO lost
  TRUEs; 122 new senses → **10 LINKs** (use 4, execution 2, get 2, well 1,
  catfish 1; mistake 0). Attach: 5/5 target EMPTYs fill. REPORT_v0_2:
  **10/10 new LINKs hand-judged CORRECT**. Verdict: GO on 0.2 goal.
- **0.3:** BUILD `linker_v0_3.py` = v0.2 byte-identical + 22 probes (+ lie,
  lead, light, fine, present, bear) + QUARANTINE emit-stage guard
  (`en-book-en-verb-hoaZwz7Y` → quarantined-known-false). Calibration
  tweaks used: 0. `link_table_v0_3.tsv`: 984 rows; 51/51 old-correct LINK
  pairs intact; 293 new senses → **21 LINK rows** (lie 3, lead 3, light 6,
  fine 0, present 3, bear 6). New-link precision **16/21 = 76.2%**.
  REPORT_v0_3 verdict: NO-GO on both bars (link < 90%).
- **0.4:** BUILD `linker_v0_4.py` = v0.3 byte-identical + 24 probes (+ spring,
  check) + Se embedding signal (all-MiniLM-L6-v2, `SE_CUT = 0.43`,
  diagnostic-only: zero decision changes). True v0.3 baseline 17/21 = 81.0%.
  `link_table_v0_4.tsv`: 1099 rows, 73/73 LINK pairs intact; spring 69
  senses → 6 LINKs, check 43 → 3 LINKs (8/9 judged TRUE). Eval15 pack
  (0.4.5–0.4.7): 725 senses → **LINK 50** / PENDING 210 / UNMAPPED 443 /
  twin 22; v0.3-vs-v0.4 zero method/sensekey mismatches (Se purely additive).
- **0.5:** BUILD `linker_v0_5.py` = v0.4 + FIX1 (ultra-short → JUDGE-PENDING)
  + FIX2 (`GENERIC_VERBS` deweight as Sa/Sb/Sc evidence; `hold` narrowed out)
  + FIX3 (`se_veto`, floor 0.35, single-family/generic-free/non-exact only).
  24-probe `link_table_v0_5.tsv`: 1100 rows — LOST 4 (3 named FALSEs +
  2 leniency casualties), GAINED 3 (incl. 1 new error, get-stimulate).
  New LINK precision **18/22 = 81.8%**. Eval15 (0.5.5–0.5.6): 730 rows,
  **LINK 49**. REPORT_v0_5 verdict: NO-GO on >90% (generic-word high-Se
  links inseparable without the judge leg; zero further tweaks recommended).
- **0.6:** BUILD `linker_v0_6.py` = v0.5 + cause-rule (`GENERIC_VERBS` +=
  `cause`). `link_table_v0_6.tsv`: 1100 rows — LOST 1 (IC5yKMhe
  stimulate-FALSE, intended), GAINED 1 (YLGk8-sY new strict-FALSE,
  exact-sensekey so veto-exempt). Zero lost TRUEs. Judged-24 precision
  **19/24 = 79.2% → 20/24 = 83.3%**. Judge leg ready (batch of 24,
  ~12.8k tokens, 0 calls made). Verdict: NO-GO on >90%.
- **0.7:** Judge-v2 packaging (Gemma-approved spec): discrete winner_index,
  two-pass ranks 4–6, N=3 iff 1-signal OR dSe<0.10 OR flip-family (16 VOTE /
  8 SINGLE). 132 calls (cap 90 breached, ~18.7 min). `integrate_v0_7.py` →
  `link_table_v0_7.tsv`: 1100 rows = **LINK 90** + PENDING 409 + UNMAPPED 550
  + twin 47 + quarantine 1 + MANUAL-NONE 3 (13 judge-v2 LINKs + 3 owner
  MANUAL-NONEs; lost == 2 intentional). REPORT_v0_7: strict-owner
  **22/24 = 91.7%**, extended **31/33 = 93.9%**. Verdict: GO. **This is the
  table that shipped into the repo** (`table.tsv` here).
- **0.8:** Judge-ops optimization (local gemma, budget locked at 2000;
  batching/compression/server-budget-350/0 all REJECTED; llama/granite/
  minicpm/spark/qwen bake-offs — none displace Gemma judge or ministral
  pre-screen). JOB5 rule: LINK on flip-family evidence is
   `provisional_consensus` (idx16). `REPORT_v0_8.md` verdict: NO-GO on
   'judge ops production-ready' (per-verdict reasoning cost unreduced).
- **Gallery 4.0.0 (2026-09-19):** flowtrace rewrite (S-flow RTL, verdict-first
  wires/badges, concordant tier, sticky toolbar+close, export redesign,
  certainty-language removal, candidate fallback, NFKC parity, None-crash
  guard, single-source vocab).
- **Gallery 4.1.0 (2026-09-19):** run version display (`viewer` + `data`
  labels, majority-never-wins), canonical-quorum counting, failed-vote hold
  (FAILED beats LINK on wires and status), per-record export with row_ref,
  support-quote fallbacks (never bare def), hermetic font embedding.
