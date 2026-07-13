import unittest

from issues.validate import VALID_STATUSES, load_data, render_markdown, validate_issues


class IssueToolingTests(unittest.TestCase):
    def test_issue_registry_is_valid_and_has_unique_ids(self):
        issues = load_data()
        validate_issues(issues)
        self.assertEqual(len(issues), len({issue["id"] for issue in issues}))
        statuses = {issue["status"] for issue in issues}
        self.assertLessEqual(statuses, VALID_STATUSES)
        self.assertIn("open", statuses)
        self.assertIn("resolved", statuses)

    def test_markdown_export_contains_issue_statuses(self):
        markdown = render_markdown(load_data())
        self.assertIn("> Generated from `issues/issues.json`", markdown)
        self.assertIn("- Status: Resolved", markdown)
        self.assertIn("- Status: Open", markdown)
        self.assertIn("- Status: Accepted risk", markdown)

    def test_issue_registry_allows_optional_phase_values(self):
        issues = load_data()
        phases = {issue.get("phase") for issue in issues if issue.get("phase")}
        self.assertTrue(phases.issubset({"phase-1", "phase-2", "phase-3", "phase-4", "phase-6"}))


if __name__ == "__main__":
    unittest.main()
