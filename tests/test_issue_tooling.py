import unittest
from pathlib import Path

from issues.validate import (
    VALID_CATEGORIES,
    VALID_PHASES,
    VALID_STATUSES,
    load_data,
    load_project_status,
    render_markdown,
    validate_issues,
)


class IssueToolingTests(unittest.TestCase):
    def test_issue_registry_is_valid_and_has_unique_ids(self):
        issues = load_data()
        validate_issues(issues, load_project_status())
        self.assertEqual(len(issues), len({issue["id"] for issue in issues}))
        statuses = {issue["status"] for issue in issues}
        self.assertLessEqual(statuses, VALID_STATUSES)
        self.assertIn("open", statuses)
        self.assertIn("resolved", statuses)
        self.assertTrue({issue["category"] for issue in issues}.issubset(VALID_CATEGORIES))

    def test_markdown_export_contains_issue_statuses(self):
        markdown = render_markdown(load_data())
        self.assertIn("> Generated from `issues/issues.json`", markdown)
        self.assertIn("- Status: Resolved", markdown)
        self.assertIn("- Status: Open", markdown)
        self.assertIn("- Status: Accepted risk", markdown)

    def test_project_status_assigns_every_issue_to_one_phase(self):
        issues = load_data()
        project_status = load_project_status()
        validate_issues(issues, project_status)
        phases = {issue["phase"] for issue in issues}
        self.assertTrue(phases.issubset(VALID_PHASES))
        assigned = [
            issue_id
            for phase in project_status["phases"]
            for issue_id in phase["issue_ids"]
        ]
        self.assertEqual(sorted(assigned), sorted(issue["id"] for issue in issues))

    def test_dashboard_is_read_only_and_has_generated_markers(self):
        dashboard = Path("issues/project_status.html").read_text(encoding="utf-8")
        self.assertIn("BEGIN GENERATED PROJECT STATUS DATA", dashboard)
        self.assertIn("BEGIN GENERATED ISSUE DATA", dashboard)
        self.assertNotIn("localStorage", dashboard)


if __name__ == "__main__":
    unittest.main()
