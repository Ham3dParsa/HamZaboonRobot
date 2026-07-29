import unittest
import math
from services.fsrs_core import (
    compute_retrievability,
    compute_interval,
    initial_stability,
    initial_difficulty,
    update_difficulty,
    update_stability,
    short_term_stability,
    DSR_W,
    DSR_FACTOR,
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


if __name__ == "__main__":
    unittest.main()
