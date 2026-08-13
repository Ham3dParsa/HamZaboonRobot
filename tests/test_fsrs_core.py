import unittest
import math
from types import MappingProxyType
from services.fsrs_core import (
    compute_retrievability,
    compute_interval,
    initial_stability,
    initial_stability_first_exposure,
    initial_difficulty,
    update_difficulty,
    update_stability,
    short_term_stability,
    DSR_W,
    DSR_FACTOR,
    FIRST_EXPOSURE_STABILITY,
    FSRSConfig,
    DEFAULT_FSRS_CONFIG,
)


class TestRetrievability(unittest.TestCase):
    def test_at_stability_equals_desired_retention(self):
        r = compute_retrievability(10.0, 10.0)
        self.assertAlmostEqual(r, 0.9, places=4)

    def test_zero_elapsed_returns_one(self):
        r = compute_retrievability(0.0, 10.0)
        self.assertAlmostEqual(r, 1.0, places=6)

    def test_decays_over_time(self):
        r1 = compute_retrievability(1.0, 10.0)
        r2 = compute_retrievability(10.0, 10.0)
        self.assertGreater(r1, r2)

    def test_low_stability_decays_faster(self):
        r_short = compute_retrievability(5.0, 1.0)
        r_long = compute_retrievability(5.0, 30.0)
        self.assertLess(r_short, r_long)

    def test_floor_stability_prevents_division_by_zero(self):
        r = compute_retrievability(100.0, 0.001)
        self.assertGreater(r, 0.0)


class TestComputeInterval(unittest.TestCase):
    def test_at_default_retention_equals_stability(self):
        i = compute_interval(30.0, 0.9)
        self.assertAlmostEqual(i, 30.0, delta=0.5)

    def test_higher_retention_shorter_interval(self):
        i_high = compute_interval(30.0, 0.95)
        i_low = compute_interval(30.0, 0.8)
        self.assertLess(i_high, i_low)

    def test_zero_stability_returns_positive(self):
        i = compute_interval(0.0)
        self.assertGreater(i, 0.0)


class TestInitialStability(unittest.TestCase):
    def test_again_equals_w0(self):
        self.assertAlmostEqual(initial_stability(1), DSR_W["w0"])

    def test_hard_equals_w1(self):
        self.assertAlmostEqual(initial_stability(2), DSR_W["w1"])

    def test_good_equals_w2(self):
        self.assertAlmostEqual(initial_stability(3), DSR_W["w2"])

    def test_easy_equals_w3(self):
        self.assertAlmostEqual(initial_stability(4), DSR_W["w3"])

    def test_invalid_grade_raises_key_error(self):
        with self.assertRaises(KeyError):
            initial_stability(5)


class TestInitialDifficulty(unittest.TestCase):
    def test_again_equality_w4(self):
        d = initial_difficulty(1)
        self.assertAlmostEqual(d, DSR_W["w4"])

    def test_clamped_to_range(self):
        for grade in [1, 2, 3, 4]:
            d = initial_difficulty(grade)
            self.assertGreaterEqual(d, 1.0)
            self.assertLessEqual(d, 10.0)

    def test_increasing_grade_decreases_difficulty(self):
        d1 = initial_difficulty(1)
        d2 = initial_difficulty(2)
        d3 = initial_difficulty(3)
        d4 = initial_difficulty(4)
        self.assertGreater(d1, d2)
        self.assertGreater(d2, d3)
        self.assertGreater(d3, d4)


class TestUpdateDifficulty(unittest.TestCase):
    def test_good_keeps_similar(self):
        d = update_difficulty(5.0, 3)
        self.assertAlmostEqual(d, 5.0, delta=0.5)

    def test_again_increases(self):
        d = update_difficulty(5.0, 1)
        self.assertGreater(d, 5.0)

    def test_easy_decreases(self):
        d = update_difficulty(5.0, 4)
        self.assertLess(d, 5.0)

    def test_clamped_to_range(self):
        for grade in [1, 2, 3, 4]:
            d = update_difficulty(5.0, grade)
            self.assertGreaterEqual(d, 1.0)
            self.assertLessEqual(d, 10.0)


class TestUpdateStability(unittest.TestCase):
    def setUp(self):
        self.s = 10.0
        self.r = compute_retrievability(5.0, self.s)

    def test_again_capped_at_prior_stability(self):
        s_new = update_stability(5.0, self.s, self.r, 1)
        self.assertLessEqual(s_new, self.s)

    def test_hard_good_easy_monotonic(self):
        s_hard = update_stability(5.0, self.s, self.r, 2)
        s_good = update_stability(5.0, self.s, self.r, 3)
        s_easy = update_stability(5.0, self.s, self.r, 4)
        self.assertLess(s_hard, s_good)
        self.assertLess(s_good, s_easy)

    def test_passing_grades_never_decrease(self):
        for grade in [2, 3, 4]:
            s_new = update_stability(5.0, self.s, self.r, grade)
            self.assertGreaterEqual(s_new, self.s)

    def test_again_returns_positive(self):
        s_new = update_stability(5.0, self.s, self.r, 1)
        self.assertGreater(s_new, 0.0)

    def test_again_low_r_gives_higher_stability(self):
        r_low = compute_retrievability(30.0, self.s)
        r_high = compute_retrievability(1.0, self.s)
        s_low = update_stability(5.0, self.s, r_low, 1)
        s_high = update_stability(5.0, self.s, r_high, 1)
        self.assertGreater(s_low, s_high)

    def test_hard_penalty_less_than_good(self):
        r = compute_retrievability(1.0, self.s)
        s_hard = update_stability(5.0, self.s, r, 2)
        s_good = update_stability(5.0, self.s, r, 3)
        self.assertLess(s_hard, s_good)


class TestShortTermStability(unittest.TestCase):
    def test_again_decreases(self):
        s_new = short_term_stability(10.0, 1)
        self.assertLess(s_new, 10.0)

    def test_hard_may_decrease(self):
        s_new = short_term_stability(10.0, 2)
        self.assertLess(s_new, 10.0)

    def test_good_or_easy_never_decrease(self):
        for grade in [3, 4]:
            s_new = short_term_stability(10.0, grade)
            self.assertGreaterEqual(s_new, 10.0)


class TestConstants(unittest.TestCase):
    def test_factor_positive(self):
        self.assertGreater(DSR_FACTOR, 0.0)

    def test_w20_in_range(self):
        self.assertGreaterEqual(DSR_W["w20"], 0.1)
        self.assertLessEqual(DSR_W["w20"], 0.8)


class TestFirstExposureStability(unittest.TestCase):
    def test_again_equals_0_212(self):
        self.assertAlmostEqual(FIRST_EXPOSURE_STABILITY[1], 0.212)

    def test_hard_equals_1_5(self):
        self.assertAlmostEqual(FIRST_EXPOSURE_STABILITY[2], 1.5)

    def test_good_equals_3_0(self):
        self.assertAlmostEqual(FIRST_EXPOSURE_STABILITY[3], 3.0)

    def test_easy_equals_12_0(self):
        self.assertAlmostEqual(FIRST_EXPOSURE_STABILITY[4], 12.0)

    def test_is_mappingproxy(self):
        self.assertIsInstance(FIRST_EXPOSURE_STABILITY, MappingProxyType)

    def test_immutable(self):
        with self.assertRaises(TypeError):
            FIRST_EXPOSURE_STABILITY[1] = 99.0


class TestInitialStabilityFirstExposure(unittest.TestCase):
    def test_again_returns_correct(self):
        self.assertAlmostEqual(initial_stability_first_exposure(1), 0.212)

    def test_hard_returns_correct(self):
        self.assertAlmostEqual(initial_stability_first_exposure(2), 1.5)

    def test_good_returns_correct(self):
        self.assertAlmostEqual(initial_stability_first_exposure(3), 3.0)

    def test_easy_returns_correct(self):
        self.assertAlmostEqual(initial_stability_first_exposure(4), 12.0)

    def test_invalid_grade_raises_key_error(self):
        with self.assertRaises(KeyError):
            initial_stability_first_exposure(5)

    def test_uses_config_injection(self):
        custom_stability = {1: 0.5, 2: 2.0, 3: 4.0, 4: 15.0}
        cfg = FSRSConfig(first_exposure_stability=MappingProxyType(custom_stability))
        self.assertAlmostEqual(initial_stability_first_exposure(1, config=cfg), 0.5)


class TestFSRSConfig(unittest.TestCase):
    def test_default_config_w_is_mappingproxy(self):
        self.assertIsInstance(DEFAULT_FSRS_CONFIG.w, MappingProxyType)

    def test_default_config_first_exposure_stability_is_mappingproxy(self):
        self.assertIsInstance(DEFAULT_FSRS_CONFIG.first_exposure_stability, MappingProxyType)

    def test_frozen_dataclass_prevents_attribute_mutation(self):
        with self.assertRaises(AttributeError):
            DEFAULT_FSRS_CONFIG.desired_retention = 0.8

    def test_mappingproxy_prevents_dict_mutation(self):
        with self.assertRaises(TypeError):
            DEFAULT_FSRS_CONFIG.w["w3"] = 99.0

    def test_custom_w_via_construction(self):
        custom_w = {**DSR_W, "w3": 50.0}
        cfg = FSRSConfig(w=MappingProxyType(custom_w))
        self.assertAlmostEqual(cfg.w["w3"], 50.0)

    def test_custom_config_affects_interval(self):
        custom_w = {**DSR_W, "w3": 50.0}
        cfg = FSRSConfig(w=MappingProxyType(custom_w))
        s = initial_stability(4, config=cfg)
        self.assertAlmostEqual(s, 50.0)
        i = compute_interval(s, 0.9, config=cfg)
        self.assertAlmostEqual(i, 50.0, delta=1.0)

    def test_maximum_interval_caps_compute_interval(self):
        cfg = FSRSConfig(maximum_interval=7)
        i = compute_interval(365.0, 0.9, config=cfg)
        self.assertLessEqual(i, 7.0)

    def test_maximum_interval_does_not_affect_short_intervals(self):
        cfg = FSRSConfig(maximum_interval=7)
        i = compute_interval(5.0, 0.9, config=cfg)
        self.assertAlmostEqual(i, 5.0, delta=0.5)

    def test_config_name_default(self):
        self.assertEqual(DEFAULT_FSRS_CONFIG.name, "default")

    def test_config_enable_short_term_default(self):
        self.assertTrue(DEFAULT_FSRS_CONFIG.enable_short_term)

    def test_config_from_custom_w_alters_retrievability(self):
        """Change w20 from 0.1542 to 0.3; at R(S=10, t=1) values diverge."""
        cfg = FSRSConfig(w=MappingProxyType({**DSR_W, "w20": 0.3}))
        r_default = compute_retrievability(1.0, 10.0)
        r_custom = compute_retrievability(1.0, 10.0, config=cfg)
        self.assertNotAlmostEqual(r_default, r_custom, places=4)


class TestComputeIntervalWithConfig(unittest.TestCase):
    def test_verification_identity(self):
        """Phase 0.7 verification: compute_interval(S=30, r=0.9) == 30.0"""
        i = compute_interval(30.0, 0.9)
        self.assertAlmostEqual(i, 30.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
