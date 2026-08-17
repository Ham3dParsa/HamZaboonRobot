"""Focused tests for the canonical plan-identity leaf (J-B6, R5/F5).

``config/plan_identity.py`` is the single source of truth for plan set
membership, premium tiering, learner-facing labels, and feature gating. These
tests pin its behavior and its invariants: no drift from the DB seed, rank
contiguity, monotonic feature inheritance, and the locked feature-gate map.
"""

import unittest

from config.plan_identity import (
    _PLANS,
    feature_audience,
    has_feature,
    is_premium,
    plan_label,
    valid_plans,
)
from services.db.plans import DEFAULT_PLANS


class PlanIdentityTests(unittest.TestCase):
    def test_valid_plans_matches_db_seed(self):
        """The identity registry must never drift from the DB seed: a new tier
        added to DEFAULT_PLANS without a matching identity entry is a bug."""
        self.assertEqual(valid_plans(), frozenset(DEFAULT_PLANS))

    def test_labels_match_db_seed_display_names(self):
        for code, spec in DEFAULT_PLANS.items():
            with self.subTest(plan=code):
                self.assertEqual(plan_label(code), spec[0])

    def test_ranks_are_contiguous_from_zero(self):
        """Ranks order tiers low->high with no gaps or duplicates. This is what
        makes feature inheritance (_FEATURE_MIN_RANK) well-defined."""
        ranks = sorted(int(entry["rank"]) for entry in _PLANS.values())
        self.assertEqual(ranks, list(range(len(_PLANS))))

    def test_premium_tiers_are_the_top_tiers(self):
        self.assertTrue(is_premium("silver"))
        self.assertTrue(is_premium("gold"))
        self.assertTrue(is_premium("emerald"))
        self.assertFalse(is_premium("free"))
        self.assertFalse(is_premium("bronze"))
        self.assertFalse(is_premium("unknown"))

    def test_pronounce_is_free_to_all(self):
        """Locked decision (owner, 2026-08-17): the 🔊 pronounce button is free
        for every plan (min_rank 0)."""
        for code in valid_plans():
            with self.subTest(plan=code):
                self.assertTrue(has_feature(code, "pronounce"))

    def test_card_modes_and_presentation_require_premium(self):
        """card_modes and presentation unlock at the premium boundary (silver+)."""
        for code in valid_plans():
            expected = is_premium(code)
            with self.subTest(plan=code):
                self.assertEqual(has_feature(code, "card_modes"), expected)
                self.assertEqual(has_feature(code, "presentation"), expected)

    def test_unknown_plan_and_feature_are_denied(self):
        """Fail-closed: an unknown plan or feature is never entitled."""
        self.assertFalse(has_feature("unknown", "card_modes"))
        self.assertFalse(has_feature("silver", "unknown_feature"))
        self.assertFalse(has_feature("unknown", "unknown_feature"))
        self.assertFalse(is_premium("unknown"))
        self.assertEqual(plan_label("unknown"), "unknown")

    def test_has_feature_is_monotonic_in_rank(self):
        """A higher-ranked plan never loses a feature a lower-ranked one has.

        ``granted`` must be exactly the trailing suffix of the rank-ascending
        order: a feature granted at rank r is granted at every rank >= r.
        """
        order = [
            code
            for code, _ in sorted(_PLANS.items(), key=lambda kv: kv[1]["rank"])
        ]
        for feature in ("pronounce", "card_modes", "presentation"):
            granted = [c for c in order if has_feature(c, feature)]
            self.assertEqual(
                granted,
                order[len(order) - len(granted):],
                f"feature '{feature}' is not a rank suffix (non-monotonic)",
            )

    def test_feature_audience_derives_from_live_gate(self):
        """Admin/help copy must mirror the live gate, not hardcoded tiers (#390).
        A free feature names every plan; a paid one names the entitled tiers in
        ascending rank order; an unknown feature yields an empty string."""
        self.assertEqual(feature_audience("pronounce"), "برای همه پلن‌ها")
        self.assertEqual(
            feature_audience("card_modes"),
            "برای پلن‌های نقره‌ای و طلایی و زمردی",
        )
        self.assertEqual(feature_audience("presentation"), feature_audience("card_modes"))
        self.assertEqual(feature_audience("unknown_feature"), "")


if __name__ == "__main__":
    unittest.main()