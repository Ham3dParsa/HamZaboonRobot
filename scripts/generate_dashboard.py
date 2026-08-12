#!/usr/bin/env python3
"""Generate issues/project_status.html from project_status.json.

Usage:
  python scripts/generate_dashboard.py

The dashboard renders phase status, acceptance criteria, decision locks,
links to GitHub Issues, and includes interactive JS for search/filter/tabs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PROJECT_STATUS_PATH = BASE / "project_status.json"
HTML_PATH = BASE / "issues" / "project_status.html"

PHASE_BADGE: dict[str, str] = {
    "complete": "\U0001f7e2",
    "in-progress": "\U0001f7e1",
    "planned": "\U0001f535",
    "blocked": "\U0001f534",
    "deferred": "\u26aa",
}

DECISION_BADGE: dict[str, str] = {
    "locked": "\U0001f512",
    "proposed": "\U0001f4a1",
    "superseded": "\u267b\ufe0f",
    "rejected": "\u274c",
}

STATUS_LABEL: dict[str, str] = {
    "open": "Open",
    "partial": "Partial",
    "resolved": "Resolved",
    "accepted-risk": "Accepted",
    "obsolete": "Obsolete",
}

STATUS_COLOR: dict[str, str] = {
    "open": "#dc3545",
    "partial": "#fd7e14",
    "resolved": "#28a745",
    "accepted-risk": "#6f42c1",
    "obsolete": "#6c757d",
}

CSS = """
*,
*::before,
*::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

:root {
    --bg: #ffffff;
    --bg-secondary: #f6f8fa;
    --text: #24292f;
    --text-secondary: #57606a;
    --border: #d0d7de;
    --accent: #0969da;
    --accent-hover: #0550ae;
    --success: #1a7f37;
    --warning: #bf8700;
    --danger: #cf222e;
    --info: #0969da;
    --card-bg: #ffffff;
    --card-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.06);
    --nav-bg: #24292f;
    --nav-text: #f6f8fa;
    --nav-border: #454c54;
    --hover-bg: #eeeef0;
    --focus-ring: rgba(9, 105, 218, 0.3);
    --code-bg: #f6f8fa;
    --scrollbar-bg: #f6f8fa;
    --scrollbar-thumb: #c1c7cd;
}

[data-theme="dark"] {
    --bg: #0d1117;
    --bg-secondary: #161b22;
    --text: #c9d1d9;
    --text-secondary: #8b949e;
    --border: #30363d;
    --accent: #58a6ff;
    --accent-hover: #79c0ff;
    --success: #3fb950;
    --warning: #d29922;
    --danger: #f85149;
    --info: #58a6ff;
    --card-bg: #161b22;
    --card-shadow: 0 1px 3px rgba(0, 0, 0, 0.4), 0 1px 2px rgba(0, 0, 0, 0.3);
    --nav-bg: #161b22;
    --nav-text: #c9d1d9;
    --nav-border: #30363d;
    --hover-bg: #1c2128;
    --focus-ring: rgba(88, 166, 255, 0.3);
    --code-bg: #1c2128;
    --scrollbar-bg: #0d1117;
    --scrollbar-thumb: #30363d;
}

html {
    font-size: 16px;
    scroll-behavior: smooth;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100vh;
}

/* Navigation */
.nav-bar {
    background: var(--nav-bg);
    color: var(--nav-text);
    display: flex;
    align-items: center;
    gap: 0.25em;
    padding: 0 1.25em;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
    min-height: 52px;
}

.nav-title {
    font-weight: 700;
    font-size: 1.05em;
    white-space: nowrap;
    margin-right: 1em;
}

.nav-tabs {
    display: flex;
    gap: 0;
    flex: 1;
}

.nav-tab {
    padding: 0.6em 1.1em;
    border: none;
    background: transparent;
    color: var(--nav-text);
    cursor: pointer;
    font-size: 0.9em;
    opacity: 0.65;
    border-bottom: 2px solid transparent;
    transition: opacity 0.15s, border-color 0.15s;
    font-family: inherit;
    white-space: nowrap;
}

.nav-tab:hover {
    opacity: 0.9;
}

.nav-tab.active {
    opacity: 1;
    border-bottom-color: var(--accent);
}

#theme-toggle {
    background: transparent;
    border: 1px solid var(--nav-border);
    border-radius: 6px;
    color: var(--nav-text);
    cursor: pointer;
    font-size: 1.1em;
    padding: 0.35em 0.55em;
    line-height: 1;
    transition: background 0.15s;
}

#theme-toggle:hover {
    background: rgba(255, 255, 255, 0.1);
}

/* Main layout */
main {
    max-width: 1600px;
    margin: 0 auto;
    padding: 1.25em 1.25em 2em;
}

.tab-panel {
    display: none;
}

.tab-panel.active {
    display: block;
    animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
    from {
        opacity: 0;
        transform: translateY(4px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* Filter bar */
.filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75em;
    align-items: center;
    margin-bottom: 1.25em;
    padding: 0.75em 1em;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
}

.filter-bar input[type="search"] {
    flex: 1;
    min-width: 180px;
    padding: 0.5em 0.75em;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg);
    color: var(--text);
    font-size: 0.9em;
    font-family: inherit;
    outline: none;
    transition: border-color 0.15s, box-shadow 0.15s;
}

.filter-bar input[type="search"]:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--focus-ring);
}

.filter-bar select {
    padding: 0.5em 0.75em;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg);
    color: var(--text);
    font-size: 0.9em;
    font-family: inherit;
    outline: none;
    cursor: pointer;
}

.filter-bar select:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--focus-ring);
}

.filter-tabs {
    display: flex;
    gap: 2px;
    background: var(--border);
    border-radius: 6px;
    padding: 2px;
    overflow: hidden;
}

.filter-tab {
    padding: 0.35em 0.85em;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    font-size: 0.82em;
    font-weight: 500;
    font-family: inherit;
    transition: background 0.15s, color 0.15s;
    white-space: nowrap;
}

.filter-tab:hover {
    color: var(--text);
    background: var(--hover-bg);
}

.filter-tab.active {
    background: var(--bg);
    color: var(--text);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.results-count {
    font-size: 0.85em;
    color: var(--text-secondary);
    margin-left: auto;
}

/* Stat cards */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 0.75em;
    margin-bottom: 1.25em;
}

.stat-card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1em 0.75em;
    text-align: center;
    box-shadow: var(--card-shadow);
    cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s, border-color 0.15s;
}

.stat-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.12);
    border-color: var(--accent);
}

.stat-value {
    font-size: 2em;
    font-weight: 700;
    line-height: 1.2;
}

.stat-label {
    font-size: 0.8em;
    color: var(--text-secondary);
    margin-top: 0.25em;
}

/* Progress bar */
.progress-section {
    margin-bottom: 1.5em;
}

.progress-section h3 {
    font-size: 0.95em;
    font-weight: 600;
    margin-bottom: 0.5em;
    color: var(--text-secondary);
}

.progress-bar {
    display: flex;
    height: 10px;
    border-radius: 5px;
    overflow: hidden;
    background: var(--border);
}

.progress-done {
    background: var(--success);
    transition: width 0.4s ease;
}

.progress-wip {
    background: var(--warning);
    transition: width 0.4s ease;
}

.progress-todo {
    background: var(--border);
}

.progress-labels {
    display: flex;
    gap: 1.5em;
    margin-top: 0.4em;
    font-size: 0.82em;
    color: var(--text-secondary);
    flex-wrap: wrap;
}

.progress-labels span {
    display: flex;
    align-items: center;
    gap: 0.3em;
}

/* Phase list grid */
.phase-list {
    display: grid;
    grid-template-columns: 1fr;
    gap: 1em;
}

@media (min-width: 1200px) {
    .phase-list {
        grid-template-columns: repeat(2, 1fr);
    }
}

@media (min-width: 1600px) {
    .phase-list {
        grid-template-columns: repeat(3, 1fr);
    }
}

/* Phase card */
.phase-card {
    position: relative;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.25em;
    background: var(--card-bg);
    box-shadow: var(--card-shadow);
    border-left: 4px solid var(--status-color, var(--border));
    transition: border-color 0.15s;
}

.phase-card[data-status="complete"] {
    --status-color: var(--success);
}

.phase-card[data-status="in-progress"] {
    --status-color: var(--warning);
}

.phase-card[data-status="planned"] {
    --status-color: var(--info);
}

.phase-card[data-status="blocked"] {
    --status-color: var(--danger);
}

.phase-card[data-status="deferred"] {
    --status-color: var(--text-secondary);
}

.phase-header {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 0.5em;
    margin-bottom: 0.4em;
}

.phase-badge {
    font-size: 1.15em;
}

.phase-id {
    font-size: 0.75em;
    color: var(--text-secondary);
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
}

.phase-name {
    font-size: 1.1em;
    font-weight: 600;
}

.phase-status-tag {
    font-size: 0.72em;
    font-weight: 500;
    padding: 0.15em 0.55em;
    border-radius: 10px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    text-transform: capitalize;
    margin-left: auto;
}

.phase-objective {
    color: var(--text-secondary);
    font-size: 0.9em;
    margin-bottom: 0.5em;
    line-height: 1.5;
}

.phase-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 1em;
    font-size: 0.85em;
    color: var(--text-secondary);
    margin-bottom: 0.5em;
}

.phase-meta a {
    color: var(--accent);
    text-decoration: none;
}

.phase-meta a:hover {
    text-decoration: underline;
}

.phase-meta .dep-link {
    cursor: pointer;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 0.9em;
}

.issue-links {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.3em;
    font-size: 0.85em;
}

.issue-links a {
    color: var(--accent);
    text-decoration: none;
}

.issue-links a:hover {
    text-decoration: underline;
}

.issue-badge {
    display: inline-block;
    font-size: 0.75em;
    padding: 0.1em 0.4em;
    border-radius: 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    font-weight: 500;
}

.btn-gh-link {
    display: inline-flex;
    align-items: center;
    gap: 0.25em;
    font-size: 0.78em;
    padding: 0.2em 0.5em;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    text-decoration: none;
    cursor: pointer;
    font-family: inherit;
    transition: background 0.15s, color 0.15s;
}

.btn-gh-link:hover {
    background: var(--hover-bg);
    color: var(--accent);
    text-decoration: none;
}

/* Collapsible sections */
details.section-details {
    margin: 0.3em 0 0.1em;
    border-radius: 6px;
}

details.section-details summary {
    cursor: pointer;
    font-size: 0.82em;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 0.3em 0;
    user-select: none;
    display: flex;
    align-items: center;
    gap: 0.4em;
}

details.section-details summary:hover {
    color: var(--text);
}

details.section-details summary::marker {
    color: var(--text-secondary);
}

details.section-details summary .count {
    font-weight: 400;
    font-size: 0.9em;
    opacity: 0.7;
}

details.section-details ul {
    margin: 0.25em 0;
    padding-left: 1.5em;
}

details.section-details li {
    margin: 0.15em 0;
    font-size: 0.9em;
    line-height: 1.5;
}

/* Decision table */
.decision-table-wrapper {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--card-bg);
    box-shadow: var(--card-shadow);
}

.decision-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88em;
}

.decision-table th {
    text-align: left;
    padding: 0.65em 0.75em;
    background: var(--bg-secondary);
    border-bottom: 2px solid var(--border);
    font-weight: 600;
    font-size: 0.8em;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
    position: relative;
}

.decision-table th:hover {
    background: var(--hover-bg);
    color: var(--text);
}

.decision-table th .sort-icon {
    display: inline-block;
    margin-left: 0.3em;
    opacity: 0.3;
}

.decision-table th.sorted .sort-icon {
    opacity: 1;
    color: var(--accent);
}

.decision-table td {
    padding: 0.55em 0.75em;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
}

.decision-table tr:last-child td {
    border-bottom: none;
}

.decision-table tr:hover td {
    background: var(--hover-bg);
}

.dec-status-icon {
    font-size: 1.1em;
}

.dec-title {
    font-weight: 500;
}

.dec-id {
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 0.85em;
    color: var(--text-secondary);
}

.dec-summary {
    color: var(--text-secondary);
    font-size: 0.95em;
    max-width: 350px;
}

.dec-phase {
    font-size: 0.85em;
}

.dec-gh-link {
    color: var(--accent);
    text-decoration: none;
    font-size: 0.85em;
}

.dec-gh-link:hover {
    text-decoration: underline;
}

.dec-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3em;
    align-items: center;
}

.dec-actions .btn-gh-link {
    font-size: 0.78em;
}

/* Dependency chain visualization */
.dep-chain {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25em;
    padding: 1em;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-top: 0.75em;
}

.dep-node {
    display: flex;
    align-items: center;
    gap: 0.35em;
    padding: 0.4em 0.7em;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--card-bg);
    cursor: pointer;
    font-size: 0.82em;
    font-weight: 500;
    transition: background 0.15s, border-color 0.15s, transform 0.15s;
    white-space: nowrap;
}

.dep-node:hover {
    background: var(--hover-bg);
    border-color: var(--accent);
    transform: translateY(-1px);
}

.dep-node[data-status="complete"] {
    border-left: 3px solid var(--success);
}

.dep-node[data-status="in-progress"] {
    border-left: 3px solid var(--warning);
}

.dep-node[data-status="planned"] {
    border-left: 3px solid var(--info);
}

.dep-arrow {
    color: var(--text-secondary);
    font-size: 1.1em;
    padding: 0 0.15em;
    user-select: none;
}

/* Quick actions */
.quick-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5em;
    margin-bottom: 1.25em;
}

.quick-actions a {
    display: inline-flex;
    align-items: center;
    gap: 0.35em;
    padding: 0.45em 0.85em;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--card-bg);
    color: var(--text);
    text-decoration: none;
    font-size: 0.85em;
    transition: background 0.15s, border-color 0.15s;
}

.quick-actions a:hover {
    background: var(--hover-bg);
    border-color: var(--accent);
    color: var(--accent);
}

/* Footer */
.footer {
    margin-top: 2em;
    padding: 1.25em;
    border-top: 1px solid var(--border);
    font-size: 0.8em;
    color: var(--text-secondary);
    text-align: center;
    display: flex;
    flex-direction: column;
    gap: 0.3em;
}

.footer code {
    background: var(--code-bg);
    padding: 0.1em 0.3em;
    border-radius: 3px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 0.9em;
}

.no-results {
    text-align: center;
    padding: 2em;
    color: var(--text-secondary);
    font-size: 0.95em;
}

/* Section headings */
h2 {
    font-size: 1.35em;
    font-weight: 700;
    margin-bottom: 0.75em;
    color: var(--text);
}

h3 {
    font-size: 1.05em;
    font-weight: 600;
    margin-bottom: 0.5em;
    color: var(--text);
}

/* Scrollbar */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: var(--scrollbar-bg);
}

::-webkit-scrollbar-thumb {
    background: var(--scrollbar-thumb);
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--text-secondary);
}

/* Responsive */
@media (max-width: 768px) {
    .nav-bar {
        flex-wrap: wrap;
        padding: 0.5em 0.75em;
        gap: 0.25em;
    }

    .nav-title {
        font-size: 0.9em;
        margin-right: 0.5em;
    }

    .nav-tab {
        padding: 0.4em 0.6em;
        font-size: 0.82em;
    }

    main {
        padding: 0.75em;
    }

    .stats-grid {
        grid-template-columns: repeat(2, 1fr);
        gap: 0.5em;
    }

    .stat-value {
        font-size: 1.5em;
    }

    .filter-bar {
        flex-direction: column;
        align-items: stretch;
    }

    .filter-bar input[type="search"] {
        min-width: auto;
    }

    .filter-tabs {
        flex-wrap: wrap;
    }

    .phase-list {
        grid-template-columns: 1fr;
    }

    .phase-card {
        padding: 0.9em;
    }

    .decision-table {
        font-size: 0.8em;
    }

    .decision-table th,
    .decision-table td {
        padding: 0.4em 0.5em;
    }

    .dep-chain {
        gap: 0.2em;
        padding: 0.6em;
    }

    .dep-node {
        font-size: 0.75em;
        padding: 0.25em 0.4em;
    }

    .dep-arrow {
        font-size: 0.8em;
    }
}

@media (max-width: 480px) {
    .stats-grid {
        grid-template-columns: repeat(2, 1fr);
    }

    .nav-tabs {
        width: 100%;
        order: 3;
    }

    .phase-status-tag {
        margin-left: 0;
        width: 100%;
    }
}

/* Print */
@media print {
    .nav-bar {
        position: static;
    }

    #theme-toggle,
    .filter-bar {
        display: none;
    }

    .phase-card {
        break-inside: avoid;
        box-shadow: none;
    }
}
"""

JS = r"""
(function () {
    "use strict";

    var DATA = null;
    try {
        DATA = JSON.parse(document.getElementById("project-data").textContent);
    } catch (_) {
        console.error("Failed to parse project data");
        return;
    }

    var STATUS_BADGE = {
        complete: "\uD83D\uDFE2",
        "in-progress": "\uD83D\uDFE1",
        planned: "\uD83D\uDD35",
        blocked: "\uD83D\uDD34",
        deferred: "\u26AA",
    };

    var DECISION_BADGE = {
        locked: "\uD83D\uDD12",
        proposed: "\uD83D\uDCA1",
        superseded: "\u267B\uFE0F",
        rejected: "\u274C",
    };

    /* ----- Theme ----- */
    function initTheme() {
        var saved = localStorage.getItem("hamzaboon-theme");
        var prefers = window.matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light";
        var theme = saved || prefers;
        document.documentElement.setAttribute("data-theme", theme);
    }

    function toggleTheme() {
        var current = document.documentElement.getAttribute("data-theme");
        var next = current === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        localStorage.setItem("hamzaboon-theme", next);
    }

    /* ----- Tabs ----- */
    function switchTab(tabId) {
        document.querySelectorAll(".nav-tab").forEach(function (t) {
            t.classList.toggle("active", t.dataset.tab === tabId);
        });
        document.querySelectorAll(".tab-panel").forEach(function (p) {
            p.classList.toggle("active", p.id === "tab-" + tabId);
        });
        window.location.hash = tabId;
    }

    /* ----- Cross-tab navigation ----- */
    function navigateToTab(tabId, filterType, filterValue) {
        switchTab(tabId);
        if (tabId === "phases") {
            var filterTabs = document.querySelectorAll(".filter-tab");
            filterTabs.forEach(function (t) {
                t.classList.toggle("active", t.dataset.filter === filterValue);
            });
            applyPhaseFilters();
        } else if (tabId === "decisions") {
            var statusFilter = document.getElementById("decision-status-filter");
            if (statusFilter && filterValue) {
                statusFilter.value = filterValue;
            }
            applyDecisionFilters();
        }
    }

    /* ----- Phase search & filter ----- */
    function applyPhaseFilters() {
        var input = document.getElementById("search-input");
        var search = input ? input.value.toLowerCase() : "";
        var activeFilter = document.querySelector(".filter-tab.active");
        var filter = activeFilter ? activeFilter.dataset.filter : "all";
        var cards = document.querySelectorAll(".phase-card");
        var visible = 0;

        cards.forEach(function (card) {
            var status = card.dataset.status;
            var text = card.textContent.toLowerCase();
            var matchesSearch = !search || text.indexOf(search) !== -1;
            var matchesFilter =
                filter === "all" || status === filter;
            var show = matchesSearch && matchesFilter;
            card.style.display = show ? "" : "none";
            if (show) visible++;
        });

        var countEl = document.getElementById("results-count");
        if (countEl) countEl.textContent = visible + " / " + cards.length + " phases";
    }

    /* ----- Decision search & filter ----- */
    function applyDecisionFilters() {
        var input = document.getElementById("decisions-search");
        var search = input ? input.value.toLowerCase() : "";
        var statusFilter = document.getElementById("decision-status-filter");
        var filterVal = statusFilter ? statusFilter.value : "all";
        var rows = document.querySelectorAll(".decision-row");
        var visible = 0;

        rows.forEach(function (row) {
            var status = row.dataset.status;
            var text = row.textContent.toLowerCase();
            var matchesSearch = !search || text.indexOf(search) !== -1;
            var matchesFilter = filterVal === "all" || status === filterVal;
            var show = matchesSearch && matchesFilter;
            row.style.display = show ? "" : "none";
            if (show) visible++;
        });

        var countEl = document.getElementById("decisions-count");
        if (countEl) countEl.textContent = visible + " / " + rows.length + " decisions";
    }

    /* ----- Decision table sort ----- */
    function initDecisionSort() {
        var table = document.getElementById("decision-table");
        if (!table) return;
        var headers = table.querySelectorAll("th[data-sort]");
        var currentSort = { col: null, asc: true };

        function sortTable(col, asc) {
            var tbody = table.querySelector("tbody");
            var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
            var colIdx = Array.prototype.indexOf.call(
                headers[0].parentNode.children,
                table.querySelector('th[data-sort="' + col + '"]')
            );

            rows.sort(function (a, b) {
                var aVal = (a.children[colIdx]?.textContent || "").trim();
                var bVal = (b.children[colIdx]?.textContent || "").trim();
                if (col === "status") {
                    var order = ["locked", "proposed", "superseded", "rejected"];
                    return asc
                        ? order.indexOf(aVal) - order.indexOf(bVal)
                        : order.indexOf(bVal) - order.indexOf(aVal);
                }
                return asc
                    ? aVal.localeCompare(bVal)
                    : bVal.localeCompare(aVal);
            });

            rows.forEach(function (row) { tbody.appendChild(row); });

            headers.forEach(function (h) {
                h.classList.toggle("sorted", h.dataset.sort === col);
            });
        }

        headers.forEach(function (h) {
            h.addEventListener("click", function () {
                var col = h.dataset.sort;
                var asc =
                    currentSort.col === col ? !currentSort.asc : true;
                currentSort = { col: col, asc: asc };
                sortTable(col, asc);
            });
        });
    }

    /* ----- Summary dashboard ----- */
    function renderSummary() {
        var container = document.getElementById("summary-content");
        if (!container || !DATA) return;

        var phases = DATA.phases || [];
        var decisions = DATA.decisions || [];
        var counts = {
            complete: 0,
            "in-progress": 0,
            planned: 0,
            blocked: 0,
            deferred: 0,
        };
        phases.forEach(function (p) {
            counts[p.status] = (counts[p.status] || 0) + 1;
        });
        var decCounts = { locked: 0, proposed: 0, superseded: 0, rejected: 0 };
        decisions.forEach(function (d) {
            decCounts[d.status] = (decCounts[d.status] || 0) + 1;
        });

        var issueIds = new Set();
        phases.forEach(function (p) {
            (p.issue_ids || []).forEach(function (id) { issueIds.add(id); });
        });
        decisions.forEach(function (d) {
            (d.issue_ids || []).forEach(function (id) { issueIds.add(id); });
        });

        var html = "";

        /* Stat cards — clickable with cross-tab navigation */
        html += '<div class="stats-grid">';
        html +=
            '<div class="stat-card" style="border-top:3px solid var(--success)" onclick="navigateToTab(\'phases\',\'complete\')" title="Filter to completed phases">' +
            '<div class="stat-value">' +
            (counts.complete || 0) +
            '</div><div class="stat-label">\uD83D\uDFE2 Complete</div></div>';
        html +=
            '<div class="stat-card" style="border-top:3px solid var(--warning)" onclick="navigateToTab(\'phases\',\'in-progress\')" title="Filter to in-progress phases">' +
            '<div class="stat-value">' +
            (counts["in-progress"] || 0) +
            '</div><div class="stat-label">\uD83D\uDFE1 In Progress</div></div>';
        html +=
            '<div class="stat-card" style="border-top:3px solid var(--info)" onclick="navigateToTab(\'phases\',\'planned\')" title="Filter to planned phases">' +
            '<div class="stat-value">' +
            (counts.planned || 0) +
            '</div><div class="stat-label">\uD83D\uDD35 Planned</div></div>';
        html +=
            '<div class="stat-card" style="border-top:3px solid var(--border)" onclick="navigateToTab(\'phases\',\'all\')" title="Show all phases">' +
            '<div class="stat-value">' +
            (phases.length) +
            '</div><div class="stat-label">\uD83D\uDCCB Total Phases</div></div>';
        html += "</div>";

        /* More stats - decisions & issues */
        html += '<div class="stats-grid" style="margin-top:0.75em">';
        html +=
            '<div class="stat-card" style="border-top:3px solid var(--success)" onclick="navigateToTab(\'decisions\',\'locked\')" title="Filter to locked decisions">' +
            '<div class="stat-value">' +
            (decCounts.locked || 0) +
            '</div><div class="stat-label">\uD83D\uDD12 Locked</div></div>';
        html +=
            '<div class="stat-card" style="border-top:3px solid var(--warning)" onclick="navigateToTab(\'decisions\',\'proposed\')" title="Filter to proposed decisions">' +
            '<div class="stat-value">' +
            (decCounts.proposed || 0) +
            '</div><div class="stat-label">\uD83D\uDCA1 Proposed</div></div>';
        html +=
            '<div class="stat-card" style="border-top:3px solid var(--info)" onclick="window.open(\'https://github.com/Ham3dParsa/HamZaboonRobot/issues\',\'_blank\')" title="Open all issues on GitHub">' +
            '<div class="stat-value">' +
            issueIds.size +
            '</div><div class="stat-label">\u0023\uFE0F\u20E3 Linked Issues</div></div>';
        html +=
            '<div class="stat-card" style="border-top:3px solid #6f42c1" onclick="navigateToTab(\'decisions\')" title="Show all decisions">' +
            '<div class="stat-value">' +
            decisions.length +
            '</div><div class="stat-label">\uD83D\uDCDD Decisions</div></div>';
        html += "</div>";

        /* Quick actions */
        html +=
            '<div class="quick-actions"><a href="https://github.com/Ham3dParsa/HamZaboonRobot/issues" target="_blank" rel="noopener">\uD83D\uDCCD All Issues</a>';
        html +=
            '<a href="https://github.com/Ham3dParsa/HamZaboonRobot/issues/new" target="_blank" rel="noopener">\u2795 New Issue</a>';
        html +=
            '<a href="https://github.com/Ham3dParsa/HamZaboonRobot/projects" target="_blank" rel="noopener">\uD83D\uDCCA Projects</a></div>';

        /* Overall progress bar */
        var totalItems = 0,
            totalDone = 0,
            totalWip = 0;
        phases.forEach(function (p) {
            var d = (p.done || []).length;
            var w = (p.in_progress || []).length;
            var t = (p.todo || []).length;
            if (p.status === "complete") {
                totalDone += d + w + t;
                totalItems += d + w + t;
            } else {
                totalDone += d;
                totalWip += w;
                totalItems += d + w + t;
            }
        });

        html += '<div class="progress-section"><h3>Overall Progress</h3>';
        if (totalItems > 0) {
            var donePct = ((totalDone / totalItems) * 100).toFixed(0);
            var wipPct = ((totalWip / totalItems) * 100).toFixed(0);
            html += '<div class="progress-bar"><div class="progress-done" style="width:' +
                donePct + '%" title="Done: ' + totalDone +
                '"></div><div class="progress-wip" style="width:' + wipPct +
                '%" title="In progress: ' + totalWip + '"></div></div>';
            html += '<div class="progress-labels"><span>\u2705 Done: ' +
                totalDone + '</span><span>\U0001f504 In progress: ' +
                totalWip + '</span><span>\U0001f4dd Todo: ' +
                (totalItems - totalDone - totalWip) + '</span></div>';
        }
        html += "</div>";

        /* Dependency chain */
        html += '<div class="progress-section"><h3>Phase Dependency Flow</h3><div class="dep-chain">';
        phases.forEach(function (p, i) {
            var badge = STATUS_BADGE[p.status] || "\u26AA";
            html +=
                '<div class="dep-node" data-status="' +
                p.status +
                '" onclick="document.querySelector(\'.nav-tab[data-tab=phases]\')?.click();setTimeout(function(){var e=document.getElementById(\'' +
                p.id +
                "');if(e)e.scrollIntoView({behavior:'smooth'});},100)\">" +
                '<span class="dep-badge">' +
                badge +
                "</span>" +
                '<span class="dep-name">' +
                p.name +
                "</span></div>";
            if (i < phases.length - 1) {
                html += '<div class="dep-arrow">\u2192</div>';
            }
        });
        html += "</div></div>";

        container.innerHTML = html;
    }

    /* ----- Init ----- */
    document.addEventListener("DOMContentLoaded", function () {
        initTheme();

        var themeBtn = document.getElementById("theme-toggle");
        if (themeBtn) themeBtn.addEventListener("click", toggleTheme);

        /* Tab switching */
        document.querySelectorAll(".nav-tab").forEach(function (tab) {
            tab.addEventListener("click", function () {
                switchTab(tab.dataset.tab);
            });
        });

        /* Hash-based tab on load */
        var hashTab = window.location.hash.replace("#", "");
        if (hashTab && document.querySelector('.nav-tab[data-tab="' + hashTab + '"]')) {
            switchTab(hashTab);
        }

        /* Phase filter tabs */
        document.querySelectorAll(".filter-tab").forEach(function (tab) {
            tab.addEventListener("click", function () {
                document.querySelectorAll(".filter-tab").forEach(function (t) {
                    t.classList.remove("active");
                });
                tab.classList.add("active");
                applyPhaseFilters();
            });
        });

        /* Phase search */
        var searchInput = document.getElementById("search-input");
        if (searchInput) {
            searchInput.addEventListener("input", applyPhaseFilters);
        }

        /* Decision search */
        var decSearch = document.getElementById("decisions-search");
        if (decSearch) {
            decSearch.addEventListener("input", applyDecisionFilters);
        }

        /* Decision status filter */
        var decFilter = document.getElementById("decision-status-filter");
        if (decFilter) {
            decFilter.addEventListener("change", applyDecisionFilters);
        }

        /* Render summary */
        renderSummary();

        /* Init decision sort */
        initDecisionSort();

        /* Initial filter apply */
        applyPhaseFilters();
        applyDecisionFilters();
    });
})();
"""


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render() -> str:
    ps = json.loads(PROJECT_STATUS_PATH.read_text(encoding="utf-8"))
    phases: list[dict] = ps.get("phases", [])
    decisions: list[dict] = ps.get("decisions", [])
    # Scope the date to the last commit that touched project_status.json, not the
    # overall last commit. This keeps the committed html footer stable across
    # unrelated commits/merges and across days, so CI's `git diff --exit-code`
    # only flags a real project_status.json <-> html desync (issue #321).
    try:
        import subprocess
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ci", "--", str(PROJECT_STATUS_PATH.name)],
            capture_output=True, text=True, cwd=BASE
        )
        commit_date = result.stdout.strip().split()[0] if result.returncode == 0 and result.stdout.strip() else datetime.now(timezone.utc).date().isoformat()
    except Exception:
        commit_date = datetime.now(timezone.utc).date().isoformat()
    today = commit_date
    json_data = json.dumps(ps, ensure_ascii=False)

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "<title>HamZaboon \u2014 Project Status</title>",
        "<style>",
        CSS.strip(),
        "</style>",
        "</head>",
        "<body>",
        f'<script id="project-data" type="application/json">{json_data}</script>',
        _render_nav(),
        "<main>",
        _render_summary_section(),
        _render_phases_section(phases),
        _render_decisions_section(decisions),
        "</main>",
        _render_footer(today),
        "<script>",
        JS.strip(),
        "</script>",
        "</body>",
        "</html>",
    ]
    return "\n".join(parts)


def _render_nav() -> str:
    return """<nav class="nav-bar">
  <div class="nav-title">HamZaboon</div>
  <div class="nav-tabs">
    <button class="nav-tab active" data-tab="summary">Summary</button>
    <button class="nav-tab" data-tab="phases">Phases</button>
    <button class="nav-tab" data-tab="decisions">Decisions</button>
  </div>
  <button id="theme-toggle" aria-label="Toggle dark mode">\U0001f319</button>
</nav>"""


def _render_summary_section() -> str:
    return '<section id="tab-summary" class="tab-panel active"><div id="summary-content"><p style="color:var(--text-secondary)">Loading summary\u2026</p></div></section>'


def _render_phases_section(phases: list[dict]) -> str:
    parts = [
        '<section id="tab-phases" class="tab-panel">',
        '<div class="filter-bar">',
        '<input type="search" id="search-input" placeholder="Search phases, objectives, keywords\u2026" aria-label="Search phases">',
        '<div class="filter-tabs">',
        '<button class="filter-tab active" data-filter="all">All</button>',
        '<button class="filter-tab" data-filter="complete">Complete</button>',
        '<button class="filter-tab" data-filter="in-progress">In Progress</button>',
        '<button class="filter-tab" data-filter="planned">Planned</button>',
        "</div>",
        '<span class="results-count" id="results-count"></span>',
        "</div>",
        '<div id="phase-list" class="phase-list">',
    ]

    for phase in phases:
        parts.append(_render_phase_card(phase))

    parts.append('<div class="no-results" id="no-phase-results" style="display:none">No phases match your search or filter.</div>')
    parts.append("</div></section>")
    return "\n".join(parts)


def _render_phase_card(phase: dict) -> str:
    pid = esc(phase.get("id", ""))
    status = phase.get("status", "")
    badge = PHASE_BADGE.get(status, "\u26aa")
    name = esc(phase.get("name", ""))
    objective = esc(phase.get("objective", ""))
    deps: list[str] = phase.get("depends_on", [])

    parts = [
        f'<div class="phase-card" data-phase-id="{pid}" data-status="{status}" id="{pid}">'
    ]

    # Header
    parts.append(f'<div class="phase-header">')
    parts.append(f'<span class="phase-badge">{badge}</span>')
    parts.append(f'<span class="phase-id">{pid}</span>')
    parts.append(f'<span class="phase-name">{name}</span>')
    parts.append(f'<span class="phase-status-tag">{status}</span>')
    parts.append(f"</div>")

    # Objective
    if objective:
        parts.append(f'<div class="phase-objective">{objective}</div>')

    # Meta: deps + progress
    meta_parts = []
    if deps:
        dep_links = [f'<a href="#{esc(d)}" class="dep-link">\u2190 {esc(d)}</a>' for d in deps]
        meta_parts.append(f"Dependencies: {', '.join(dep_links)}")
    if meta_parts:
        parts.append(f'<div class="phase-meta">{"".join(meta_parts)}</div>')

    # Progress bar
    done_items = phase.get("done", [])
    wip_items = phase.get("in_progress", [])
    todo_items = phase.get("todo", [])
    total = len(done_items) + len(wip_items) + len(todo_items)
    if total > 0:
        if status == "complete":
            done_pct = 100.0
            wip_pct = 0.0
        else:
            done_pct = len(done_items) / total * 100
            wip_pct = len(wip_items) / total * 100
        parts.append(
            f'<div class="progress-bar">'
            f'<div class="progress-done" style="width:{done_pct:.0f}%" title="Done: {len(done_items)}"></div>'
            f'<div class="progress-wip" style="width:{wip_pct:.0f}%" title="In progress: {len(wip_items)}"></div>'
            f"</div>"
        )

    # Collapsible sections
    for section_name, field, default_open in [
        ("Done", "done", True),
        ("In progress", "in_progress", False),
        ("To-do", "todo", False),
    ]:
        items = phase.get(field, [])
        if items:
            open_attr = " open" if default_open else ""
            parts.append(
                f'<details class="section-details"{open_attr}>'
                f"<summary>{section_name} <span class=\"count\">({len(items)})</span></summary>"
                f"<ul>"
            )
            for item in items:
                parts.append(f"<li>{esc(item)}</li>")
            parts.append("</ul></details>")

    # Acceptance criteria
    criteria = phase.get("acceptance_criteria", [])
    if criteria:
        parts.append(
            f'<details class="section-details">'
            f"<summary>Acceptance Criteria <span class=\"count\">({len(criteria)})</span></summary>"
            f"<ul>"
        )
        for item in criteria:
            parts.append(f"<li>{esc(item)}</li>")
        parts.append("</ul></details>")

    # Issues and actions
    issue_ids: list[int] = phase.get("issue_ids", [])
    if issue_ids:
        links = []
        for issue_id in issue_ids:
            links.append(
                f'<a href="https://github.com/Ham3dParsa/HamZaboonRobot/issues/{issue_id}">#{issue_id}</a>'
            )
        parts.append(
            f'<div class="issue-links" style="margin-top:0.5em">'
            f'<span class="issue-badge">{len(issue_ids)} issues</span>'
            f"{' '.join(links)}"
            f'<a href="https://github.com/Ham3dParsa/HamZaboonRobot/issues/new?template=Blank+issue&labels=phase-{pid.replace("phase-", "")}" '
            f'class="btn-gh-link" target="_blank" rel="noopener">+ New Issue</a>'
            f"</div>"
        )
    else:
        parts.append(
            f'<div class="issue-links" style="margin-top:0.5em">'
            f'<span class="issue-badge">No tracked issues</span>'
            f'<a href="https://github.com/Ham3dParsa/HamZaboonRobot/issues/new?template=Blank+issue&labels=phase-{pid.replace("phase-", "")}" '
            f'class="btn-gh-link" target="_blank" rel="noopener">+ New Issue</a>'
            f"</div>"
        )

    parts.append("</div>")
    return "\n".join(parts)


def _render_decisions_section(decisions: list[dict]) -> str:
    parts = [
        '<section id="tab-decisions" class="tab-panel">',
        '<div class="filter-bar">',
        '<input type="search" id="decisions-search" placeholder="Search decisions\u2026" aria-label="Search decisions">',
        '<select id="decision-status-filter" aria-label="Filter by status">',
        '<option value="all">All statuses</option>',
        '<option value="locked">\U0001f512 Locked</option>',
        '<option value="proposed">\U0001f4a1 Proposed</option>',
        '<option value="superseded">\u267b\ufe0f Superseded</option>',
        '<option value="rejected">\u274c Rejected</option>',
        "</select>",
        '<span class="results-count" id="decisions-count"></span>',
        "</div>",
        '<div class="decision-table-wrapper">',
        '<table class="decision-table" id="decision-table">',
        "<thead><tr>",
        '<th data-sort="status">Status <span class="sort-icon">\u25b4</span></th>',
        '<th data-sort="title">Title <span class="sort-icon">\u25b4</span></th>',
        "<th>ID</th>",
        '<th data-sort="phase">Phase <span class="sort-icon">\u25b4</span></th>',
        "<th>Summary</th>",
        "<th>Issues</th>",
        "<th>Actions</th>",
        "</tr></thead><tbody>",
    ]

    for decision in decisions:
        parts.append(_render_decision_row(decision))

    parts.append("</tbody></table></div>")
    parts.append(
        '<div class="no-results" id="no-decision-results" style="display:none">No decisions match your search or filter.</div>'
    )
    parts.append("</section>")
    return "\n".join(parts)


def _render_decision_row(decision: dict) -> str:
    did = esc(decision.get("id", ""))
    title = esc(decision.get("title", ""))
    summary = esc(decision.get("summary", ""))
    status = decision.get("status", "")
    phase_id = decision.get("phase", "")
    phase_esc = esc(phase_id)
    badge = DECISION_BADGE.get(status, "\u2753")
    issue_ids: list[int] = decision.get("issue_ids", [])

    issue_links = []
    for issue_id in issue_ids:
        issue_links.append(
            f'<a href="https://github.com/Ham3dParsa/HamZaboonRobot/issues/{issue_id}" class="dec-gh-link">#{issue_id}</a>'
        )
    issues_html = " ".join(issue_links) if issue_links else '<span class="issue-badge">none</span>'

    # Action column: phase link + issues / new-issue button
    action_parts = [
        f'<a href="#{phase_esc}" class="btn-gh-link" title="Go to phase card">\U0001f4ce Phase</a>'
    ]
    if issue_ids:
        for issue_id in issue_ids:
            action_parts.append(
                f'<a href="https://github.com/Ham3dParsa/HamZaboonRobot/issues/{issue_id}" '
                f'class="dec-gh-link" title="Issue #{issue_id}">#{issue_id}</a>'
            )
    else:
        action_parts.append(
            f'<a href="https://github.com/Ham3dParsa/HamZaboonRobot/issues/new'
            f'?template=Blank+issue&amp;labels={did}" '
            f'class="btn-gh-link" target="_blank" rel="noopener" title="Create new issue">\u2795 New</a>'
        )
    actions_html = " ".join(action_parts)

    return (
        f'<tr class="decision-row" data-status="{status}" data-decision-id="{did}">'
        f'<td><span class="dec-status-icon">{badge}</span></td>'
        f'<td class="dec-title">{title}</td>'
        f'<td class="dec-id">{did}</td>'
        f'<td class="dec-phase">{phase_esc}</td>'
        f'<td class="dec-summary">{summary}</td>'
        f'<td>{issues_html}</td>'
        f'<td class="dec-actions">{actions_html}</td>'
        f"</tr>"
    )


def _render_footer(today: str) -> str:
    return (
        '<div class="footer">'
        f"<p>Generated on {today} from <code>project_status.json</code></p>"
        "<p>Issue detail lives on "
        '<a href="https://github.com/Ham3dParsa/HamZaboonRobot/issues">GitHub Issues</a>. '
        'Edit <code>project_status.json</code> and re-run <code>python scripts/generate_dashboard.py</code>.</p>'
        "</div>"
    )


def _generate() -> None:
    """Render and write the dashboard HTML."""
    content = render()
    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTML_PATH.write_text(content, encoding="utf-8")
    print(f"Generated {HTML_PATH}")


def _watch() -> None:
    """Poll project_status.json for changes and auto-regenerate."""
    last_mtime = os.path.getmtime(PROJECT_STATUS_PATH)
    print(f"[watch] Watching {PROJECT_STATUS_PATH.name} for changes...")
    while True:
        time.sleep(1)
        try:
            current_mtime = os.path.getmtime(PROJECT_STATUS_PATH)
            if current_mtime != last_mtime:
                last_mtime = current_mtime
                _generate()
        except Exception as exc:
            print(f"[watch] Error: {exc}", file=sys.stderr)


class _QuietHandler(SimpleHTTPRequestHandler):
    """HTTP request handler that suppresses access logs."""

    def log_message(self, fmt: str, *args: object) -> None:
        pass


def _serve() -> None:
    """Start a quiet HTTP server on port 8000."""
    host = "localhost"
    port = 8000
    server = HTTPServer((host, port), _QuietHandler)
    print(f"[serve] http://{host}:{port}/issues/project_status.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate project dashboard from project_status.json"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch project_status.json for changes and auto-regenerate",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve generated dashboard via HTTP on port 8000",
    )
    args = parser.parse_args()

    _generate()

    if args.watch and args.serve:
        wt = threading.Thread(target=_watch, daemon=True)
        wt.start()
        _serve()
    elif args.watch:
        _watch()
    elif args.serve:
        _serve()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
