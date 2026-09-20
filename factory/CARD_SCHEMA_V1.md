# Factory Card Schema v1 (FROZEN 2026-09-16)

Upstream contract for everything downstream: the bot DB migration
(`saved_words`), the pool reader, word-query pool-first (#550), and the
quality gates. Frozen by owner lock; break only via a new dated lock entry
in `ROADMAP.md`, never by silent drift.

Status of the two identity tracks at freeze time: sense IDs in the old
pipeline are unstable (`{word}#{label}` — see
`factory/archive/v14_v16/DESIGN-registry-B.md`); v1 mandates the stable
content-addressed scheme from `factory/archive/v14_v16/DESIGN-registry-A.md`.

## 1. Identity (frozen)

| Key | Type | Rule |
|---|---|---|
| `card_id` | TEXT, PRIMARY KEY | Stable, content-addressed: `{lemma_key}::g{sha1(norm_gloss)[:10]}`. Never reused, never rewritten. |
| `lemma_key` | TEXT | `{norm_lemma}\|{norm_pos}` (NFKC-lower, collapsed whitespace; case-collapsing intentional, display form preserved separately). |
| `legacy_sense_id` | TEXT NULL, UNIQUE where not null | Old unstable id (`Miss#21`, `April#0`) kept for traceability/migration only. New rows MUST NOT mint legacy-style ids. |
| `sense_id` | TEXT, NOT NULL | == `card_id` for sense-level cards (one row per sense). The sense IS the card. |

## 2. Quality gates per card (frozen — L2)

Every served card MUST carry all of:

| Key | Type | Rule |
|---|---|---|
| `cefr` | TEXT, NOT NULL | Sense-level CEFR (A1–C2), judged for THIS sense, not the word. |
| `topics` | JSON array of TEXT, NOT NULL, non-empty | Topic labels matching THIS sense. |
| `examples` | exactly 2 + exactly 2 translations | Each example must exemplify THIS sense (validated, not whole-word). |
| `fa_meaning` | TEXT, NOT NULL | Persian gloss of THIS sense. |

Optional-but-validated when present: `synonyms[]`, `antonyms[]`
(sense-scoped; see issue #408), `phonetic` (structured `{...}`).

## 3. Classification (frozen)

| Key | Type | Rule |
|---|---|---|
| `card_type` | TEXT, NOT NULL | Enum: `word` \| `phrase` \| `acronym` (extend only by lock). |
| `pos` | TEXT NULL | Part of speech (`noun/verb/adj/adv`, mapped via existing VN table). Optional at v1. |
| `pack_id` | TEXT NULL | **Reserved, no beta content.** Column exists so packs (e.g. TOEFL) need no re-freeze; Beta-1 ships general vocabulary only. |

## 4. Explicitly OUT of v1 (not frozen, not required)

- Pool storage engine choice (registry.db vs JSONL pool files) — MS-1 implementation detail.
- Coverage thresholds per CEFR×Topic cell (tracked by #590 heatmap).
- Bot-side migration shape (new `saved_words` columns vs JSON contract read) — MUST be derived from this doc in MS-1, not invented.
- Any pack content, leaderboards, quizzes, social (post-beta).

## 5. Bot-side gap this freeze exposes (for MS-1)

Current `saved_words` DDL (`services/db/schema.py`) has NO
`sense_id / cefr / topics / card_type / pack_id` columns — the card payload
is opaque `card_data TEXT`. MS-1 must add the migration + reader; the column
names MUST match §1–§3 (single source of truth).

## 6. Pack scope clarification (R-acro, locked 2026-09-20 — additive, §1–§3 frozen lines untouched)

Downstream-reader check 2026-09-20 (`pack_id|origin_pack_id|
pack_memberships` over `factory/ services/ handlers/ config/ bot.py`):
zero `.py` readers — `pack_id` appears only in this doc (§3 `pack_id`,
§5 gap list). No rename of shipped columns is needed; the meaning is
clarified here without renaming:

- `pack_id` (§3) / precard-row `origin_pack_id` (`factory.precard.
  pipeline._build_precard_row`) both mean the ORIGIN pack — the pack
  that introduced the card. A card keeps its origin pack id for life;
  playlist assignment beyond origin lives in `pack_memberships.jsonl`,
  never in a renamed column.
- `pack_memberships.jsonl` (emitted beside the pack-build `--out`
  when `--pack-id` is given, via `build_pack_memberships` +
  `write_pack_memberships`): one row per emitted card —
  `{card_id (= pre_card_id), pack_id, priority (int display order,
  0-based over emitted rows), section (opaque pack-side string,
  e.g. "Unit 1"), added_at (UTC `%Y-%m-%dT%H:%M:%SZ`)}`.
- FSRS INVARIANT (locked): packs are playlists. FSRS state lives on
  `(user_id, card_id)`; pack membership NEVER affects scheduling,
  ordering for review, or due-state. No bot-DB pack tables/handlers
  ship with this change (out of scope by lock).
