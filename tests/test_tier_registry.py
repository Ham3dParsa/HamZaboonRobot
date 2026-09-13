"""Order-parity tests for services/session/tier_registry.py (REF4-T5).

The registry is a read-only view over the ``due_words_for_user`` order
(``_row_priority_key`` in ``services/db/words.py``): it owns BOTH the build
iteration (``assembly.py:45-72``) and the refill iteration
(``srs_handler.py:692-722``) with zero logic change — no re-sort, no boundary
move, no internal ``today``. These tests prove the registry preserves input
order verbatim, tier1→tier2 priority, session_ids exclusion, max_nodes
capping, the tier-3 append point, and the SessionNode field mapping.
"""

from __future__ import annotations

import unittest


def _row(word_id: int, word: str) -> dict:
    return {"id": word_id, "word": word}


class TestTierRegistryParity(unittest.TestCase):
    def test_iter_preserves_due_order_verbatim_no_resort(self):
        from services.session.tier_registry import iter_tier_candidates

        due = [_row(3, "c"), _row(1, "a"), _row(2, "b")]
        got = list(iter_tier_candidates(due, []))
        self.assertEqual([r["id"] for r, _, _, _ in got], [3, 1, 2])

    def test_iter_tier1_before_tier2(self):
        from services.session.tier_registry import iter_tier_candidates

        due = [_row(1, "due1")]
        fe = [_row(2, "fe1")]
        got = list(iter_tier_candidates(due, fe))
        self.assertEqual(
            [(r["id"], tier) for r, _, tier, _ in got], [(1, 1), (2, 2)]
        )

    def test_iter_skips_session_ids_in_both_tiers(self):
        from services.session.tier_registry import iter_tier_candidates

        due = [_row(1, "due1"), _row(2, "due2")]
        fe = [_row(3, "fe1"), _row(4, "fe2")]
        got = list(iter_tier_candidates(due, fe, exclude_ids={1, 3}))
        self.assertEqual([r["id"] for r, _, _, _ in got], [2, 4])

    def test_iter_yields_refill_quadruple(self):
        from services.session.tier_registry import iter_tier_candidates

        due = [_row(7, "w")]
        (row, activity, tier, policy), *_ = iter_tier_candidates(due, [])
        self.assertEqual(row["id"], 7)
        self.assertEqual(activity, "srs_review")
        self.assertEqual(tier, 1)
        self.assertEqual(policy, "srs_review")

    def test_make_node_field_mapping_matches_build_and_refill(self):
        from services.session.tier_registry import make_tier_node

        node = make_tier_node(
            _row(9, "hello"), "srs_review", 1, "srs_review", 1, "en"
        )
        self.assertEqual(node.activity_type, "srs_review")
        self.assertEqual(node.source_tier, 1)
        self.assertEqual(node.card_data, {"word": "hello"})
        self.assertEqual(node.source_id, 9)
        self.assertEqual(
            node.activity_meta, {"user_id": 1, "target_lang": "en"}
        )
        self.assertEqual(node.grade_policy_ref, "srs_review")

    def test_build_caps_at_max_nodes_tier1_first(self):
        from services.session.tier_registry import build_tier12_nodes

        due = [_row(1, "a"), _row(2, "b"), _row(3, "c")]
        fe = [_row(4, "d")]
        nodes = build_tier12_nodes(1, "en", 2, due, fe)
        self.assertEqual([n.source_id for n in nodes], [1, 2])
        self.assertTrue(all(n.source_tier == 1 for n in nodes))

    def test_build_fills_tier2_after_tier1(self):
        from services.session.tier_registry import build_tier12_nodes

        due = [_row(1, "due1")]
        fe = [_row(2, "fe1"), _row(3, "fe2")]
        nodes = build_tier12_nodes(1, "en", 3, due, fe)
        self.assertEqual(
            [(n.source_id, n.source_tier) for n in nodes],
            [(1, 1), (2, 2), (3, 2)],
        )

    def test_next_returns_first_non_excluded_tier1_priority(self):
        from services.session.tier_registry import next_tier_node

        due = [_row(1, "due1"), _row(2, "due2")]
        fe = [_row(3, "fe1")]
        node = next_tier_node(1, "en", {1}, due, fe)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(node.source_id, 2)
        self.assertEqual(node.source_tier, 1)

    def test_next_falls_back_to_tier2_when_tier1_exhausted(self):
        from services.session.tier_registry import next_tier_node

        node = next_tier_node(1, "en", set(), [], [_row(5, "fe")])
        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(node.source_id, 5)
        self.assertEqual(node.source_tier, 2)

    def test_next_returns_none_when_queues_exhausted(self):
        from services.session.tier_registry import next_tier_node

        self.assertIsNone(next_tier_node(1, "en", {1}, [_row(1, "a")], []))
        self.assertIsNone(next_tier_node(1, "en", set(), [], []))

    def test_tier3_append_point_is_max_nodes_minus_built(self):
        from services.session.tier_registry import build_tier12_nodes

        nodes = build_tier12_nodes(1, "en", 5, [_row(1, "a")], [])
        remaining = 5 - len(nodes)
        self.assertEqual(remaining, 4)


if __name__ == "__main__":
    unittest.main()
