import unittest

from services.db.plans import validate_plan_consistency


class TestPlanConsistency(unittest.TestCase):
    def test_validate_plan_consistency_passes(self):
        # Should not raise on current DB seed / identity
        validate_plan_consistency()
