# CONTRACT-linker — قرارداد زنده خط لینکر (append-only)

- Created: 2026-09-18. STATE: G1' LOCKED with C1-C4; R1–R8 (F3) locked earlier; T1–T5 locked earlier; G2/G4/G5 PENDING.
- Discipline: every future lock APPENDS a dated section below. Locked lines are never rewritten — only superseded by a newer dated section quoting the old one. Owner says "locked"/"proceed" per rule; blanket approvals invalid.

## LOCKED 2026-09-18 — G1' grade-once-at-build (owner: "locked")

**Rule:** example grading happens ONCE at table-build time (offline), using enrich's live predicate THEN; the winning example + source + grade-provenance are STORED in the row. At enrich runtime: pure lookup, zero grading, zero predicate injection, zero dual judges.
**Why:** dual-judge divergence (same sentence accepted in one slot, rejected in another, silently) is worse than any cost below.
**Cost accepted:** grading-rule change ⇒ table REBUILD + version bump (explicit, traceable). Transient cost: build does the grading (seconds: ~2000 senses / 2s measured).
**Evidence:** precard audit (enrich recomputes live per run) + linker audit (rows lack all attach fields) 2026-09-18.
**Owner Confirmation:** "بله" + ordered contract written now.

## LOCKED 2026-09-18 — C1 join key (owner: "locked")

**Rule:** join key is `(sense_id, gloss)` + stored TARGET lemma rows for xref-resolved picks (enrich.py:709 pattern). `lemma#idx` display ids stay untouched (enrich.py:464 int-parse). `sense_id` alone is NEVER a key (light double-occurrence precedent).
**Why:** file-order idx dies on Kaikki rebuild; xref picks carry the target lemma — joining on the wrong lemma enriches the wrong entry silently.

## LOCKED 2026-09-18 — C2 per-pick fan-out (owner: "locked")

**Rule:** the table covers secondary picks, not just rank-1 (s2 picks[] → per-pick rows with own pre_card_id). A table joined only to primaries drops live kept rows.
**Why:** pipeline grain is per-pick (pick_index/fanout_n); secondaries are real cards.

## LOCKED 2026-09-18 — C3 version pins (owner: "locked")

**Rule:** every row/pack carries dataset versions (Kaikki dump date, WordNet 3.0, TSV date, OEWN label). Keys without versions are invalid. Evidence: `ask%2:32:00` deleted in OEWN-2025.
**Why:** keys drift across dataset rebuilds; unversioned keys are time bombs.

## LOCKED 2026-09-18 — C4 winner-evidence separation (owner: "locked")

**Rule:** row `evidence` from deterministic signals describes CANDIDATES (often the loser — e.g. 4acunXz3's `Sd:hyp=move` belongs to 38:11, winner 38:00 had 0 fires) and must NEVER be cited as winner support. Winner authority lives in separate judge-quote fields.
**Why:** citing loser fires as support is the exact misread the audit caught.

## LOCKED 2026-09-18 — G2 KAIKKI-leg fallback (owner: "G2=A، قفل")

**Rule:** when `method=LINK*` but `synset is None` (hermetic CI, transient outage), attach emits the KAIKKI leg (kaikki example graded, `link_example_src="kaikki"`) with all `wn_*=""`. Never withhold a passing kaikki example because the WN side is missing.
**Why:** learner must not pay for a dictionary outage; hermetic runs must exercise the kaikki leg (else F4 coverage is blind + goldens understate LINK benefit).
**Cost accepted:** `linked` rows sometimes carry empty `wn_*`; every reader must handle `link_example_src="kaikki"`-on-LINK (documented, not silent).

## LOCKED 2026-09-18 — G3 link_cefr deferred (owner: "agreed")

**Rule:** NO `link_cefr` key ships until a repo-pinned per-sense CEFR source exists. CEFR stays single-sourced (`sense_cefr`, bridge-owned). Twin rows keep ONE row + `twin-pending` flag + both levels in evidence (no row duplication — duplicates break kid-uniqueness, risk double cards, and twins are temporary: exact links + Oxford resolve them).
**Why:** a 100%-empty 9th slot invites ad-hoc fills from unpinned dual-level pairs (second CEFR authority, violates R6/D-no-fake). Later landing = additive change with golden updates.
**Cost accepted:** readers built against 8 slots touch code again at landing.

## LOCKED 2026-09-18 — G4' two-level antonyms (owner: "قفل G4ʹ با همین صورت")

**Rule:** TABLE stores ALL antonyms with owner-lemma tags (`little@big`, `small@large`, `incorrect@correct` + `wrong@right` — nearness accepted, nuance tolerated). CARD displays + SRS-grades headword-lemma antonyms ONLY (single reference answer; empty honest when none).
**Why:** table preserves information (reviewable, future multi-answer SRS needs zero linker change); card needs one gradable answer — ambiguity breaks SRS scoring, not lexicography.
**Cost accepted:** table rows carry sibling-lemma antonyms (labeled, never displayed); display layer must filter by tag (not by presence).

## LOCKED 2026-09-18 — G5' split by certainty (owner: "قفل")

**Rule:** QUARANTINE (proven-false, hand-verified — today only book-hoaZwz7Y): `link_sensekey=""` total blackout; story lives in method/provenance + offline TSV history. UNDECIDED (twin-pending / JUDGE-NONE / JUDGE-REVIEW): key KEPT for debug + future re-link, but the SOLE consumption gate is `link_status` — guarded by an EXECUTABLE test (flagged-with-key row in → nothing out), never by paper contract.
**Why:** "proven wrong" applies only to quarantine; judge is ~90% not 100%, so NONE/twin keys are candidate intelligence, not poison — but only behind a tested gate.
**Cost accepted:** two code paths by certainty class; gate test must run in CI.

## LOCKED 2026-09-19 — F3 SignalQualityVeto mode (owner choice)

- SignalQualityVeto wires into enrich as LOG-ONLY/annotation until calibration lands: it records its would-fire verdict per row, NEVER blocks a direct LINK, NEVER routes. Flip to enforcing requires a new explicit lock after calibration numbers exist. (SplitVoteVeto by contrast enforces from day one: any non-3-0 → ESCALATE:HUMAN_QUEUE, never direct-link.)

<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>

F3 contract is LOCKED: R1–R8 + T1–T5 (prior) + v0.8 gate-core (LowRankZeroOverlapVeto / EvidenceGlossMismatchVeto+bailout / SplitVoteVeto-enforcing / SignalQualityVeto-log-only) + G1'/C1–C4/G2/G3/G4'/G5' unchanged. Proceed to implementation.

## ADOPTED 2026-09-19 — Domain vocabulary standard (owner-relayed Gemini, in-docs/in-logs/in-new-code effective immediately)

- Gate D / کلی داور → **LocalArbiterStage**; Gate A → **LowRankZeroOverlapVeto**; Gate B → **EvidenceGlossMismatchVeto**; 2-1 rule → **SplitVoteVeto** (all 2-1s); JUDGE-REVIEW label → **ESCALATE:HUMAN_QUEUE**.
- Scope: docs, logs, reports, NEW code use these names from now. Existing method strings in shipped tables/code migrate ONLY with F3 (mapping old→new recorded then) — no silent rename of data.
- Locked with it: SplitVoteVeto = no 2-1 verdict links directly, ever (→ESCALATE). Guarded-D batch = LocalArbiterStage runs.

## RECORDED 2026-09-18 — Oxford third leg (direction, NOT locked)

**Agreed boundaries (owner + agent):** Oxford joins as EVIDENCE + FIELDS leg, never as link target (no sensekeys there; WN keeps key graph + synonym/antonym network). (1) Topics: clue-only for disambiguation, never our labels (our 16 topics come only from our judge). (2) Keys: WE mint them by counting saved blocks (`interest_sng_4`), pinned to the saved copy; recount if Oxford edits. Block↔synset pairing via judge, same pairing work. (3) Coverage is gappy (many blocks cageless: no CEFR) → rule "if it speaks, it leads; if silent, nothing". (4) Copyright: levels/topics/selection free; verbatim text redistribution needs legal check (Kaikki-CC and WordNet-permissive have no such issue). Plain language only ("دانلود و ذخیره محلی", never jargon). Next: lock as G6 after G3–G5.

## Referenced prior locks (not reopened)

- R1–R8 F3 wiring (owner "Proceed" 2026-09-18): 7-col TSV + sidecar; ordinals; E1–E6; hop-6 kid read; WN→kaikki→EMPTY; link_cefr side slot; viewer DEFERRED; conjunctive bar.
- T1–T5 transfer (owner proceed): offline table + lookup; judge verdicts as data; repo-vendored table; flags as data + breaker; hermetic + errorwords bar.
- D-* product rules (plan-precard-quality-141.md): bridge-target 70%+, no-fake-label, sense-id-integrity, quorum pending, trial deferred, zen retired.
- D-no-fake-label restated for this line: no row ships a label below its evidence; UNMAPPED/NONE are verdicts, not failures.
Addendum 2026-09-20 (feat/row-surface-gate-ctx): gate_ctx row-surfacing locked — honest signals only at enrich call sites, rows carry gate_verdict/gate_fires/gate_reasons/signal_quality_would_fire(+reason), enrich stage aggregates gate counters, no backfill of legacy states, SignalQuality stays log-only (F3 lock stands).

## LOCKED 2026-09-20 — G6 Oxford bounds (owner: "locked")

**Rule:** Oxford joins as Domain/Topic Validator ONLY — never as an
independent candidate source (no Oxford-born candidates, no Oxford link
targets; the WordNet key graph + synonym/antonym network stays the sole
candidate authority).

1. **oxford-domain-prior:** fires ONLY on an exact Oxford↔Kaikki
   topic-tag match for the same sense. Near-matches, partial overlaps,
   and reworded equivalents do NOT fire.
2. **Register Mismatch Guard:** the guarded register set is exactly
   {archaic, historical, slang, vulgar, formal} — a WordNet candidate
   contradicting the sense's listed register is vetoed.
   Out-of-everyday-domain senses are stopped at pre-screen and NEVER
   reach the arbiter. Tags outside the listed set are ignored (no
   veto, no prior).
3. **No Proxy:** absent Oxford metadata fails OPEN — no synthetic
   values are ever invented to fill the gap (same preserve rule as the
   F3 gate-core: missing data never routes).
4. **TOPIC BOUNDARY (owner-locked):** Oxford signals are internal
   linker-assist features ONLY and MUST NEVER propagate as precard
   topic metadata or into learner-facing cards. The precard topic
   taxonomy stays independent (our topics come only from our judge —
   RECORDED 2026-09-18 §(1) stands).
**Loader explicitly deferred:** no Oxford data source is pinned, so no
loader ships; the changelog NO-GO stands until a source is locked.

## ADDENDUM 2026-09-20 — LocalArbiterStage implementation location (R3)

**Note:** LocalArbiterStage is the stage name; its implementation lives in
scratch judge-batch builders outside the repo (no repo class). Do not invent
a repo class for it.

## ADDENDUM 2026-09-20 — Ubiquitous language + metric formulas (R6)

**Ubiquitous language (locked scope: 5 nodes + 4 definitions):** the
canonical stage/gate vocabulary is LocalArbiterStage +
LowRankZeroOverlapVeto / EvidenceGlossMismatchVeto / SplitVoteVeto /
SignalQualityVeto (ADOPTED 2026-09-19 stands). Node/definition prose beyond
these locked names was not supplied in this lock — recorded here as scope
only, no new semantics invented.

**Metric formulas (exact denominators locked):**

- LINK_Retention denominator = 73 (LINK total post-R5)
- NONE_Containment denominator = 65 (NONE total post-R5)
- Arbiter_Consensus denominator = 15 (escapes)
- Queue_Integrity denominator = 15 (escapes)

Recorded inference (NOT locked prose — owner to confirm verbatim
numerators): LINK_Retention = retained-LINK / 73; NONE_Containment =
contained-NONE / 65; Arbiter_Consensus and Queue_Integrity are ratios over
the 15 escapes. Exact numerator semantics need owner verbatim; no formula
rewrite without a new explicit lock. Append-only; no prior section
rewritten.
