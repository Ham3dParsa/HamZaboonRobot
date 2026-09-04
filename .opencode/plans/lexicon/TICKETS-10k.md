# TICKETS — 10k sampling (3000 EN lemmas, checkpointed)

Contract: plan-10k-sampling.md (LOCKED 2026-09-04). Branch: research/lexicon-5k.
Cross-language rule: every ticket must keep `lang` a parameter, never hardcoded `en`.

| Ticket | Title | Skills | State | Evidence |
|---|---|---|---|---|
| T0 | Sampler interface: 2 parallel designs, pick one | codebase-design (design-twice) | complete | A + offset-index file locked by owner |
| T1 | Downloader + verify (~3GB Kaikki English-words to W:) | general | complete | aa013ca + 82836b0; 3,212,282,689 B, 1,487,639 lines, 0 bad (independent verify) |
| T2 | Seeded checkpointed sampler -> lemmas.csv (3000) + determinism test | tdd-enforcement | review-fixed, production run next | 3f2e78e + 3554f30; reviewer 3 findings fixed (replay dedup, pilot-quota fail-closed, progress-kept-on-truncate) + found+fixed own checkpoint-lifecycle bug |
| T1b | Offset-index builder (lemma -> file offset, JSON on W:, reusable per lang) | general | complete | dbe5552; reviewer 0 findings; index 108MB + lookup 39MB, 1,351,588 lemmas, 31.5s |

## Dataset audit (owner order 03:18, night quota, total cap 10GB)
- kaikki-en-words.jsonl 3.06GB ✅ fresh; eng_sentences.tsv.bz2 24MB ✅ present; tatoeba pools ✅ on W: (regenerable); EVP/CEFR-J/prototypes ✅ in git pack; wordfreq ✅ cached locally.
- Raw total 3.18GB. NOTHING else mandatory for v16 reproduction — no further downloads. Other-language Tatoeba deferred (not v16-relevant).
| T3 | Evidence: per-level counts, pilot overlap, pack.json bump, report | general | complete | 984535c; 3000 rows / 2999 unique keys, mix exact, overlap 499 unique + 1 dupe-skipped (cast|verb keep-first), spot-check 0 mismatch; lemmas_10k pointer UNWIRED from pack.json pending owner quality review (affix/digit/multiword rows; csv kept as evidence only); QUALITY FLAG (owner decision needed): A1 contains affix/digit rows ('d, -by, -got-, -our, 2) — no filter applied without approval; downstream pos=name exclusion may drop some (e.g. Zerbe) |
| T4 | Full validation + PR | hamzaban-validation, pre-commit-gate, git-protocol | pending | PR URL + CI |
| T5 | PR comment cycle to mergeable | kilo-ci-loop | pending | mergeable state |

## Rules
- After each implementation ticket: hamzaban-reviewer (0 confirmed findings or fix + re-verify) before next ticket.
- Persist findings after each ticket (this file + plan file + W: reports as needed).
- Every phase stoppable/resumable: progress files + seeded determinism.
- Issues: #550 updated on phase completions (pool prerequisite for cache pipeline).

## T0 designs
- (pending subagent results)
