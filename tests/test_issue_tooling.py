import argparse
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_STATUS = Path("project_status.json")
DASHBOARD = Path("issues/project_status.html")
GENERATOR = Path("scripts/generate_dashboard.py")


class DashboardGeneratorTests(unittest.TestCase):
    """Tests for the generated project_status.html dashboard."""

    @classmethod
    def setUpClass(cls):
        cls.html = DASHBOARD.read_text(encoding="utf-8")
        cls.ps = json.loads(PROJECT_STATUS.read_text(encoding="utf-8"))

    def test_dashboard_is_generated_read_only_view(self):
        """Dashboard links to GitHub Issues and has no edit forms."""
        self.assertIn('<script id="project-data" type="application/json">', self.html)
        self.assertIn("project_status.json", self.html)
        self.assertIn("github.com/Ham3dParsa/HamZaboonRobot/issues", self.html)
        self.assertNotIn("<form", self.html)

    def test_dashboard_has_embedded_json_with_all_data(self):
        match = re.search(
            r'<script id="project-data" type="application/json">(.*?)</script>',
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        data = json.loads(match.group(1))
        self.assertIn("phases", data)
        self.assertIn("decisions", data)
        self.assertEqual(len(data["phases"]), 8)
        self.assertEqual(len(data["decisions"]), 10)

    def test_dashboard_has_all_phase_cards(self):
        cards = re.findall(r'<div class="phase-card"', self.html)
        self.assertEqual(len(cards), 8)

    def test_dashboard_has_all_decision_rows(self):
        rows = re.findall(r'<tr class="decision-row"', self.html)
        self.assertEqual(len(rows), 10)

    def test_every_phase_has_progress_bar(self):
        for match in re.finditer(
            r'<div class="phase-card" data-phase-id="([^"]+)"[^>]*>(.*?)</div>\s*</div>',
            self.html,
            re.DOTALL,
        ):
            card_content = match.group(2)
            self.assertIn(
                "progress-bar",
                card_content,
                f"Phase {match.group(1)} is missing progress bar",
            )

    def test_complete_phase_shows_100_percent_progress(self):
        """Complete phase cards force the progress bar to 100%."""
        for phase in self.ps["phases"]:
            if phase["status"] != "complete":
                continue
            pid = phase["id"]
            self.assertIn(
                f'style="width:100%"',
                self.html,
                f"Complete phase {pid} should show 100% progress, "
                f"but does not. Items: done={len(phase.get('done',[]))}, "
                f"wip={len(phase.get('in_progress',[]))}, "
                f"todo={len(phase.get('todo',[]))}",
            )

    def test_dashboard_has_filter_and_search_ui(self):
        self.assertIn('id="search-input"', self.html)
        self.assertIn("filter-tab", self.html)
        self.assertIn('id="results-count"', self.html)
        self.assertIn('id="decisions-search"', self.html)
        self.assertIn('id="decision-status-filter"', self.html)

    def test_dashboard_has_nav_tabs(self):
        self.assertIn('data-tab="summary"', self.html)
        self.assertIn('data-tab="phases"', self.html)
        self.assertIn('data-tab="decisions"', self.html)

    def test_dashboard_has_dependency_chain(self):
        self.assertIn("dep-chain", self.html)
        self.assertIn("Phase Dependency Flow", self.html)

    def test_dashboard_has_dark_mode_toggle(self):
        self.assertIn('id="theme-toggle"', self.html)
        self.assertIn("hamzaboon-theme", self.html)

    def test_dashboard_has_sortable_decision_table(self):
        self.assertIn('id="decision-table"', self.html)
        self.assertIn('data-sort="status"', self.html)
        self.assertIn('data-sort="title"', self.html)

    def test_dashboard_phase_cards_have_dependency_links(self):
        phases_with_deps = [p for p in self.ps["phases"] if p.get("depends_on")]
        dep_links = re.findall(r'<a href="#phase-\d+" class="dep-link">', self.html)
        total_deps = sum(len(p["depends_on"]) for p in phases_with_deps)
        self.assertEqual(len(dep_links), total_deps)

    def test_dashboard_phase_cards_have_new_issue_links(self):
        new_issue_links = re.findall(
            r'href="https://github\.com/Ham3dParsa/HamZaboonRobot/issues/new',
            self.html,
        )
        self.assertGreaterEqual(len(new_issue_links), 8)

    def test_dashboard_is_responsive(self):
        self.assertIn("@media (max-width: 768px)", self.html)
        self.assertIn("@media (max-width: 480px)", self.html)

    def test_dashboard_has_print_styles(self):
        self.assertIn("@media print", self.html)

    def test_dashboard_decision_rows_have_correct_ids(self):
        for dec in self.ps["decisions"]:
            self.assertIn(
                f'data-decision-id="{dec["id"]}"',
                self.html,
                f'Decision {dec["id"]} not found in dashboard',
            )

    def test_main_container_has_wide_max_width(self):
        """Dashboard layout uses 1600px max-width for 1440p displays."""
        self.assertIn("max-width: 1600px", self.html)

    def test_phase_list_is_css_grid(self):
        """Phase cards are arranged in a responsive grid."""
        self.assertIn('class="phase-list"', self.html)
        self.assertIn("grid-template-columns", self.html)

    def test_phase_grid_has_two_column_breakpoint(self):
        self.assertIn("grid-template-columns: repeat(2, 1fr)", self.html)

    def test_phase_grid_has_three_column_breakpoint(self):
        self.assertIn("grid-template-columns: repeat(3, 1fr)", self.html)

    def test_stat_cards_are_clickable(self):
        """All stat cards have onclick handlers for cross-tab navigation."""
        onclick_cards = re.findall(
            r'<div class="stat-card"[^>]*onclick="', self.html
        )
        self.assertGreaterEqual(len(onclick_cards), 8)

    def test_stat_cards_have_cursor_pointer(self):
        self.assertIn("cursor: pointer", self.html)

    def test_stat_card_complete_navigates_to_phases_tab(self):
        self.assertRegex(
            self.html,
            r"navigateToTab\(\\?'phases\\?',\\?'complete\\?'\)",
        )

    def test_stat_card_in_progress_navigates_to_phases_tab(self):
        self.assertRegex(
            self.html,
            r"navigateToTab\(\\?'phases\\?',\\?'in-progress\\?'\)",
        )

    def test_stat_card_planned_navigates_to_phases_tab(self):
        self.assertRegex(
            self.html,
            r"navigateToTab\(\\?'phases\\?',\\?'planned\\?'\)",
        )

    def test_stat_card_total_phases_navigates_to_phases_tab(self):
        self.assertRegex(
            self.html,
            r"navigateToTab\(\\?'phases\\?',\\?'all\\?'\)",
        )

    def test_stat_card_locked_navigates_to_decisions_tab(self):
        self.assertRegex(
            self.html,
            r"navigateToTab\(\\?'decisions\\?',\\?'locked\\?'\)",
        )

    def test_stat_card_proposed_navigates_to_decisions_tab(self):
        self.assertRegex(
            self.html,
            r"navigateToTab\(\\?'decisions\\?',\\?'proposed\\?'\)",
        )

    def test_stat_card_linked_issues_opens_github(self):
        self.assertRegex(
            self.html,
            r"window\.open\(\\?'https://github\.com/Ham3dParsa/HamZaboonRobot/issues\\?',\\?'_blank\\?'\)",
        )

    def test_stat_card_decisions_navigates_to_decisions_tab(self):
        self.assertRegex(
            self.html,
            r"navigateToTab\(\\?'decisions\\?'?\)",
        )

    def test_navigate_to_tab_function_exists(self):
        self.assertIn("function navigateToTab(tabId, filterType, filterValue)", self.html)

    def test_no_broken_label_links_in_decisions(self):
        """Decision action column no longer uses broken label%3A queries."""
        broken = re.findall(r'issues\?q=label%3Adecision-', self.html)
        self.assertEqual(
            len(broken), 0,
            "Found broken label%3A links in decision actions",
        )

    def test_decision_actions_have_phase_anchor(self):
        """Every decision row has an internal phase anchor link in actions."""
        phase_anchors = re.findall(
            r'<a href="#phase-\d+" class="btn-gh-link"[^>]*>📎 Phase</a>',
            self.html,
        )
        self.assertEqual(len(phase_anchors), 10)

    def test_decision_without_issues_has_new_issue_button(self):
        """Decisions with no issue_ids show a + New button in actions."""
        for dec in self.ps["decisions"]:
            if dec.get("issue_ids"):
                continue
            self.assertIn(
                f'labels={dec["id"]}',
                self.html,
                f"Decision {dec['id']} missing new-issue button with its label",
            )

    def test_decision_with_issues_has_issue_links_in_actions(self):
        """Decisions with issue_ids show issue links in the actions column."""
        for dec in self.ps["decisions"]:
            issue_ids = dec.get("issue_ids", [])
            if not issue_ids:
                continue
            for issue_id in issue_ids:
                self.assertIn(
                    f'issues/{issue_id}" class="dec-gh-link" title="Issue #{issue_id}">#{issue_id}</a>',
                    self.html,
                    f"Decision {dec['id']} missing issue #{issue_id} link in actions",
                )

    def test_decision_actions_column_has_dec_actions_class(self):
        dec_action_cols = self.html.count('class="dec-actions"')
        self.assertEqual(dec_action_cols, 10)


class GeneratorScriptTests(unittest.TestCase):
    """Tests for scripts/generate_dashboard.py CLI."""

    def test_script_imports_argparse(self):
        source = GENERATOR.read_text(encoding="utf-8")
        self.assertIn("import argparse", source)

    def test_script_defines_watch_argument(self):
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--help"],
            capture_output=True, text=True,
        )
        self.assertIn("--watch", result.stdout)
        self.assertIn("Watch project_status.json", result.stdout)

    def test_script_defines_serve_argument(self):
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--help"],
            capture_output=True, text=True,
        )
        self.assertIn("--serve", result.stdout)
        self.assertIn("Serve", result.stdout)

    def test_script_accepts_both_watch_and_serve(self):
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--watch", "--serve", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_watch_function_exists(self):
        source = GENERATOR.read_text(encoding="utf-8")
        self.assertIn("def _watch", source)

    def test_serve_function_exists(self):
        source = GENERATOR.read_text(encoding="utf-8")
        self.assertIn("def _serve", source)
        self.assertIn("HTTPServer", source)


if __name__ == "__main__":
    unittest.main()
