import unittest

from issues.validate import load_data, render_markdown, validate_issues


class IssueToolingTests(unittest.TestCase):
    def test_issue_registry_is_valid_and_has_unique_ids(self):
        issues = load_data()
        validate_issues(issues)
        self.assertEqual(len(issues), len({issue["id"] for issue in issues}))
        self.assertEqual({issue["status"] for issue in issues}, {
            "open",
            "partial",
            "resolved",
        })

    def test_markdown_export_contains_issue_statuses(self):
        markdown = render_markdown(load_data())
        self.assertIn("> Generated from `issues/issues.json`", markdown)
        self.assertIn("- Status: Resolved", markdown)
        self.assertIn("- Status: Partial", markdown)
        self.assertIn("- Status: Open", markdown)


if __name__ == "__main__":
    unittest.main()
