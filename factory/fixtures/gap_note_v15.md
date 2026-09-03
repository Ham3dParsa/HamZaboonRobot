# v15 gap note — weighted topic vectors (500-lemma pilot, 2026-09-03)

Input: ranked_senses-v14c.json (500 lemmas, 1676 cards) + 13 fixed labels.
Output: topic_vectors-v15.json — every sense has 1–3 topic labels with weights summing to 1.0.

Result: 101/1676 multi-topic (6.0%), 0 failed lemmas, 64 calls all muse-spark-1.3.
Weight sums all 1.0; ids match input per lemma.

Known gaps / non-gaps:
- 12 sense-id strings repeat WITHIN a lemma in v14c input (most, outside, cast) — pre-existing, untouched.
- Biggest primary drift Food & Drink −27 is correction of v14a keyword mislabels (fish, recycling, salmon-kiln, bracelet), verified by eye.
- 4000-scale run (R7) still needs owner sign-off per plan-v14.md phase 5.

Full counts: see factory/v15_EVIDENCE.md in the research worktree.
