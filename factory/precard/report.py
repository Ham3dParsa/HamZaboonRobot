"""Proof HTML report for a precard run (v1.4.1 — Split Inspector).

Reads <proof-dir>/precard.jsonl + dropped.log (+ optionally a run log
for judge-dropped proper nouns) and writes a modern, self-contained
Split-Inspector HTML dashboard with telemetry and faceted filtering.

Stdlib only (keeps the factory/precard self-containment rule).

Usage (from repo root):
    python -m factory.precard.report --proof-dir <dir> --sample <sample.json>
        [--limit 50] [--run-log run.log] [--name <name>] [--out <report.html>]
        [--title <title>]
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import OrderedDict
from pathlib import Path

__all__ = [
    "build_report",
    "load_order",
    "load_rows",
    "load_dropped",
    "esc",
    "main",
]

_PROPER_RE = re.compile(r"w:([A-Za-z]+):pick-proper-noun/([^\s,)]+)")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
:root {
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-mono: "JetBrains Mono", "SF Mono", Consolas, monospace;

  /* LIGHT THEME */
  --bg-page: #f1f2f5;
  --bg-surface: #ffffff;
  --bg-surface-hover: #f8f9fa;
  --bg-surface-active: #eaebee;
  --border-subtle: #e2e4e9;
  --border-strong: #c8cbd2;

  --text-primary: #111317;
  --text-secondary: #4b515d;
  --text-muted: #838a97;

  --accent: #2563eb;
  --accent-soft: #eff6ff;

  --cefr-a: #059669; --cefr-a-bg: #ecfdf5; --cefr-a-b: #a7f3d0;
  --cefr-b: #0284c7; --cefr-b-bg: #f0f9ff; --cefr-b-b: #bae6fd;
  --cefr-c: #7c3aed; --cefr-c-bg: #f5f3ff; --cefr-c-b: #ddd6fe;

  --drop-text: #dc2626; --drop-bg: #fef2f2; --drop-b: #fecaca;
  --warn-text: #d97706; --warn-bg: #fffbeb; --warn-b: #fde68a;
  --info-text: #0284c7; --info-bg: #f0f9ff; --info-b: #bae6fd;

  --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --shadow-md: 0 4px 10px rgba(0,0,0,0.08);
}

[data-theme="dark"] {
  /* DARK THEME (Clean Neutral Zinc / Charcoal) */
  --bg-page: #121316;
  --bg-surface: #191a1f;
  --bg-surface-hover: #22232a;
  --bg-surface-active: #2b2d35;
  --border-subtle: #292b34;
  --border-strong: #3a3d4a;

  --text-primary: #f3f4f6;
  --text-secondary: #9da3af;
  --text-muted: #6b7280;

  --accent: #38bdf8;
  --accent-soft: #0369a133;

  --cefr-a: #34d399; --cefr-a-bg: #064e3b33; --cefr-a-b: #065f46;
  --cefr-b: #38bdf8; --cefr-b-bg: #0369a133; --cefr-b-b: #075985;
  --cefr-c: #c084fc; --cefr-c-bg: #581c8733; --cefr-c-b: #6b21a8;

  --drop-text: #f87171; --drop-bg: #450a0a33; --drop-b: #7f1d1d;
  --warn-text: #fbbf24; --warn-bg: #451a0333; --warn-b: #78350f;
  --info-text: #38bdf8; --info-bg: #0369a126; --info-b: #075985;

  --shadow-sm: 0 1px 3px rgba(0,0,0,0.5);
  --shadow-md: 0 4px 14px rgba(0,0,0,0.6);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-sans);
  background-color: var(--bg-page);
  color: var(--text-primary);
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  line-height: 1.5;
}

/* Guard against ultrawide display drift */
.app-shell {
  max-width: 1680px;
  width: 100%;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-left: 1px solid var(--border-subtle);
  border-right: 1px solid var(--border-subtle);
  box-shadow: 0 0 40px rgba(0,0,0,0.3);
}

.app-header {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  padding: 12px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
  gap: 16px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}
.brand h1 {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.3px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.brand-pill {
  font-family: var(--font-mono);
  font-size: 10px;
  background: var(--accent-soft);
  color: var(--accent);
  border: 1px solid var(--accent);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.stats-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-subtle);
  padding: 3px 8px;
  border-radius: 6px;
  color: var(--text-secondary);
}
.controls {
  display: flex;
  align-items: center;
  gap: 12px;
}
.shortcut-hint {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}
.kbd-key {
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 10px;
}
.theme-toggle-btn {
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  padding: 6px 12px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.15s ease;
}
.theme-toggle-btn:hover {
  background: var(--bg-surface-active);
  border-color: var(--border-strong);
}

.filter-bar {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  padding: 10px 24px;
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.search-input {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-family: var(--font-sans);
  width: 230px;
  outline: none;
  transition: border-color 0.15s;
}
.search-input:focus {
  border-color: var(--accent);
}
.select-filter {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-family: var(--font-sans);
  outline: none;
  cursor: pointer;
}
.filter-pills {
  display: flex;
  gap: 4px;
}
.pill-btn {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  font-family: var(--font-mono);
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.pill-count {
  opacity: 0.65;
  font-size: 10px;
}
.pill-btn.active {
  background: var(--text-primary);
  color: var(--bg-surface);
  border-color: var(--text-primary);
}
.pill-btn.active .pill-count {
  opacity: 0.9;
  font-weight: bold;
}

.split-workspace {
  display: grid;
  grid-template-columns: 320px 1fr;
  flex: 1;
  overflow: hidden;
}

.sidebar {
  background: var(--bg-surface);
  border-right: 1px solid var(--border-subtle);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.lemma-list-item {
  padding: 12px 18px;
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: background 0.1s;
}
.lemma-list-item:hover {
  background: var(--bg-surface-hover);
}
.lemma-list-item.selected {
  background: var(--bg-surface-active);
  border-left: 3px solid var(--accent);
}
.item-left {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.item-word {
  font-weight: 600;
  font-size: 14.5px;
  color: var(--text-primary);
}
.item-sub {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}
.item-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.detail-pane {
  background: var(--bg-page);
  overflow-y: auto;
  padding: 24px 32px 60px 32px;
}
.detail-content {
  max-width: 960px;
  margin: 0 auto;
}

.word-hero {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: var(--shadow-sm);
  flex-wrap: wrap;
  gap: 14px;
}
.hero-title-group {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
.hero-word {
  font-size: 28px;
  font-weight: 800;
  letter-spacing: -0.5px;
}
.hero-ipa {
  font-family: var(--font-mono);
  font-size: 16px;
  color: var(--text-muted);
}
.hero-key {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg-page);
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
}

.sense-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 20px 22px;
  margin-bottom: 18px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sense-topline {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 12px;
}
.topline-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sense-id-badge {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  background: var(--bg-surface-hover);
  color: var(--text-primary);
  border: 1px solid var(--border-strong);
  padding: 2px 8px;
  border-radius: 6px;
}
.cefr-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
}
.cefr-A1, .cefr-A2 { background: var(--cefr-a-bg); color: var(--cefr-a); border: 1px solid var(--cefr-a-b); }
.cefr-B1, .cefr-B2 { background: var(--cefr-b-bg); color: var(--cefr-b); border: 1px solid var(--cefr-b-b); }
.cefr-C1, .cefr-C2 { background: var(--cefr-c-bg); color: var(--cefr-c); border: 1px solid var(--cefr-c-b); }

.pos-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  padding: 2px 7px;
  border-radius: 5px;
}
.register-tag {
  font-size: 11px;
  font-style: italic;
  color: var(--warn-text);
  background: var(--warn-bg);
  border: 1px solid var(--warn-b);
  padding: 1px 6px;
  border-radius: 4px;
}

.topics-group {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.topic-pill {
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  padding: 2px 8px;
  border-radius: 5px;
  display: inline-flex;
  gap: 5px;
}
.topic-pill b {
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.sense-def {
  font-size: 16px;
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.55;
}

.examples-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.example-item {
  background: var(--bg-page);
  border-left: 3px solid var(--border-strong);
  padding: 8px 14px;
  border-radius: 0 6px 6px 0;
  font-size: 13.5px;
  color: var(--text-secondary);
  font-style: italic;
}
.no-examples-notice {
  font-size: 12px;
  font-style: italic;
  color: var(--warn-text);
  background: var(--warn-bg);
  border: 1px dashed var(--warn-b);
  padding: 8px 12px;
  border-radius: 6px;
}

.telemetry-box {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11px;
}
.telemetry-stages {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.stage-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
}
.stage-chip.model {
  background: var(--info-bg);
  border-color: var(--info-b);
  color: var(--info-text);
  font-weight: 600;
}
.stage-name {
  color: var(--text-muted);
}
.copy-btn {
  font-family: var(--font-mono);
  font-size: 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.copy-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
}

.sense-inspector-footer {
  padding-top: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  flex-wrap: wrap;
  gap: 8px;
}
.inspector-tags {
  display: flex;
  gap: 12px;
}

.dropped-hero {
  background: var(--drop-bg);
  border: 1px solid var(--drop-b);
  border-radius: 12px;
  padding: 40px 24px;
  text-align: center;
  margin-top: 20px;
}
.dropped-hero h2 {
  font-size: 26px;
  color: var(--drop-text);
  margin-bottom: 8px;
}
.dropped-reason-pill {
  font-family: var(--font-mono);
  font-size: 13px;
  background: var(--bg-surface);
  border: 1px solid var(--drop-b);
  color: var(--drop-text);
  padding: 6px 14px;
  border-radius: 8px;
  display: inline-block;
  margin-top: 12px;
}
</style>
</head>
<body>

<div class="app-shell">

  <header class="app-header">
    <div class="brand">
      <h1>Precard Studio <span class="brand-pill">v1.4.1</span></h1>
      <span class="stats-badge" id="statsCount">Loading...</span>
    </div>

    <div class="controls">
      <div class="shortcut-hint">
        <span class="kbd-key">Up</span><span class="kbd-key">Down</span> or <span class="kbd-key">J</span><span class="kbd-key">K</span> navigate
      </div>
      <button class="theme-toggle-btn" onclick="toggleTheme()">
        <span id="themeIcon">*</span> Theme
      </button>
    </div>
  </header>

  <div class="filter-bar">
    <input type="text" id="searchInput" class="search-input" placeholder="Search lemma or key... (press /)" oninput="applyFilters()">

    <div class="filter-pills" id="cefrPills">
      <button class="pill-btn active" data-cefr="ALL" onclick="filterCefr('ALL')">ALL <span class="pill-count" id="count-ALL"></span></button>
      <button class="pill-btn" data-cefr="A1" onclick="filterCefr('A1')">A1 <span class="pill-count" id="count-A1"></span></button>
      <button class="pill-btn" data-cefr="A2" onclick="filterCefr('A2')">A2 <span class="pill-count" id="count-A2"></span></button>
      <button class="pill-btn" data-cefr="B1" onclick="filterCefr('B1')">B1 <span class="pill-count" id="count-B1"></span></button>
      <button class="pill-btn" data-cefr="B2" onclick="filterCefr('B2')">B2 <span class="pill-count" id="count-B2"></span></button>
      <button class="pill-btn" data-cefr="C1" onclick="filterCefr('C1')">C1 <span class="pill-count" id="count-C1"></span></button>
      <button class="pill-btn" data-cefr="C2" onclick="filterCefr('C2')">C2 <span class="pill-count" id="count-C2"></span></button>
    </div>

    <select id="topicFilter" class="select-filter" onchange="applyFilters()">
      <option value="ALL">All Topics</option>
    </select>

    <select id="statusFilter" class="select-filter" onchange="applyFilters()">
      <option value="ALL">All Statuses</option>
      <option value="KEPT">Kept Only</option>
      <option value="DROPPED">Dropped Only</option>
      <option value="SYNTHETIC">Needs Synthetic Ex</option>
    </select>

    <select id="sortOrder" class="select-filter" onchange="applyFilters()" style="margin-left:auto;">
      <option value="DEFAULT">Original Order</option>
      <option value="ALPHA">A to Z</option>
      <option value="SENSES_DESC">Senses (High to Low)</option>
      <option value="CEFR_ASC">CEFR Level</option>
    </select>
  </div>

  <div class="split-workspace">
    <aside class="sidebar" id="sidebarList"></aside>
    <main class="detail-pane" id="detailPane">
      <div class="detail-content" id="detailContent">
        <div style="text-align:center; padding: 100px; color:var(--text-muted)">Select a word from the left list</div>
      </div>
    </main>
  </div>

</div>

<script>
const RAW_LEMMAS = __LEMMAS_JSON__;

let currentCefrFilter = "ALL";
let filteredList = [];
let selectedIndex = 0;

// Escape dynamic values before innerHTML interpolation (AI/dataset text).
function esc(s) {
  return String(s === undefined || s === null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

function initTopicsAndPillCounts() {
  const topicCounts = {};
  const cefrCounts = { "ALL": 0, "A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0, "C2": 0 };

  RAW_LEMMAS.forEach(l => {
    cefrCounts["ALL"]++;
    if (!l.dropped) {
      const lemmaCefrs = new Set();
      const lemmaTopics = new Set();
      l.senses.forEach(s => {
        // Effective level per sense: sense_cefr wins, pool_level is only
        // a fallback. Never count both (a B2 lemma with pool B1 must not
        // land in the B1 pill).
        const lv = s.sense_cefr || s.pool_level;
        if (lv) lemmaCefrs.add(lv);
        (s.topic_vector || []).forEach(t => lemmaTopics.add(t.label));
      });
      lemmaCefrs.forEach(c => {
        if (cefrCounts[c] !== undefined) cefrCounts[c]++;
      });
      lemmaTopics.forEach(t => {
        topicCounts[t] = (topicCounts[t] || 0) + 1;
      });
    }
  });

  for (const [lvl, count] of Object.entries(cefrCounts)) {
    const el = document.getElementById("count-" + lvl);
    if (el) el.textContent = "(" + count + ")";
  }

  const sel = document.getElementById("topicFilter");
  sel.innerHTML = "";
  const allOpt = document.createElement("option");
  allOpt.value = "ALL";
  allOpt.textContent = "All Topics (" + Object.keys(topicCounts).length + ")";
  sel.appendChild(allOpt);
  Object.keys(topicCounts).sort().forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t + " (" + topicCounts[t] + ")";
    sel.appendChild(opt);
  });
}

function filterCefr(level) {
  currentCefrFilter = level;
  document.querySelectorAll("#cefrPills .pill-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-cefr") === level);
  });
  applyFilters();
}

function applyFilters() {
  const q = document.getElementById("searchInput").value.trim().toLowerCase();
  const topic = document.getElementById("topicFilter").value;
  const status = document.getElementById("statusFilter").value;
  const sort = document.getElementById("sortOrder").value;

  filteredList = RAW_LEMMAS.filter(item => {
    if (q && !item.text.toLowerCase().includes(q) && !item.key.toLowerCase().includes(q)) {
      return false;
    }
    if (status === "KEPT" && item.dropped) return false;
    if (status === "DROPPED" && !item.dropped) return false;
    if (status === "SYNTHETIC") {
      const needsSynth = item.senses.some(s => s.example_synthetic_needed);
      if (!needsSynth) return false;
    }
    if (currentCefrFilter !== "ALL") {
      if (item.dropped) return false;
      const hasCefr = item.senses.some(s => (s.sense_cefr || s.pool_level) === currentCefrFilter);
      if (!hasCefr) return false;
    }
    if (topic !== "ALL") {
      if (item.dropped) return false;
      const hasTopic = item.senses.some(s => (s.topic_vector || []).some(t => t.label === topic));
      if (!hasTopic) return false;
    }
    return true;
  });

  if (sort === "ALPHA") {
    filteredList.sort((a, b) => a.text.localeCompare(b.text));
  } else if (sort === "SENSES_DESC") {
    filteredList.sort((a, b) => b.senses.length - a.senses.length);
  } else if (sort === "CEFR_ASC") {
    const rank = { "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6 };
    filteredList.sort((a, b) => {
      const firstA = a.senses[0] || {};
      const firstB = b.senses[0] || {};
      const ca = firstA.sense_cefr || a.pool_level || "";
      const cb = firstB.sense_cefr || b.pool_level || "";
      return (rank[ca] || 99) - (rank[cb] || 99);
    });
  }

  renderSidebar();
  if (filteredList.length > 0) {
    selectLemma(0);
  } else {
    document.getElementById("detailContent").innerHTML =
      '<div style="text-align:center; padding: 80px; color:var(--text-muted)">'
      + '<h3>No matching lemmas found</h3>'
      + '<p style="margin-top:6px; font-size:13px;">Try adjusting your filters or search query.</p>'
      + '</div>';
  }
}

function renderSidebar() {
  const sidebar = document.getElementById("sidebarList");
  sidebar.innerHTML = "";
  document.getElementById("statsCount").textContent = filteredList.length + " of " + RAW_LEMMAS.length + " lemmas";

  filteredList.forEach((item, idx) => {
    const el = document.createElement("div");
    el.className = "lemma-list-item" + (idx === selectedIndex ? " selected" : "");
    el.id = "lemma-item-" + idx;
    el.onclick = () => selectLemma(idx);

    let rightBadge = "";
    if (item.dropped) {
      rightBadge = '<span class="stats-badge" style="color:var(--drop-text); border-color:var(--drop-b);">DROP</span>';
    } else {
      const first = item.senses[0] || {};
      const topCefr = first.sense_cefr || item.pool_level;
      rightBadge =
        '<span class="cefr-tag cefr-' + esc(topCefr) + '">' + esc(topCefr) + '</span>'
        + '<span class="stats-badge">' + item.senses.length + '</span>';
    }

    let wordStyle = "";
    if (item.dropped) {
      wordStyle = ' style="text-decoration:line-through; opacity:0.6"';
    }
    el.innerHTML =
      '<div class="item-left">'
      + '<span class="item-word"' + wordStyle + '>' + esc(item.text) + '</span>'
      + '<span class="item-sub">' + esc(item.key) + '</span>'
      + '</div>'
      + '<div class="item-right">' + rightBadge + '</div>';
    sidebar.appendChild(el);
  });
}

function copyText(txt, btn) {
  navigator.clipboard.writeText(txt).then(() => {
    const old = btn.textContent;
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = old; }, 1500);
  });
}

// Copy buttons carry data-copy attributes (escaped at render); one
// delegated listener, no inline onclick interpolation.
document.getElementById("detailContent").addEventListener("click", (e) => {
  const b = e.target.closest ? e.target.closest("[data-copy]") : null;
  if (!b) return;
  copyText(b.getAttribute("data-copy"), b);
});

function selectLemma(index) {
  if (index < 0 || index >= filteredList.length) return;
  selectedIndex = index;
  document.querySelectorAll(".lemma-list-item").forEach((el, i) => {
    el.classList.toggle("selected", i === index);
  });

  const activeEl = document.getElementById("lemma-item-" + index);
  if (activeEl) {
    activeEl.scrollIntoView({ block: "nearest" });
  }

  const item = filteredList[index];
  const container = document.getElementById("detailContent");
  if (!item) return;

  document.getElementById("detailPane").scrollTop = 0;

  if (item.dropped) {
    container.innerHTML =
      '<div class="dropped-hero">'
      + '<h2>' + esc(item.text) + '</h2>'
      + '<div style="color:var(--text-muted); font-family:var(--font-mono); margin-top:4px;">' + esc(item.key) + '</div>'
      + '<div class="dropped-reason-pill">dropped: ' + esc(item.drop_reason) + '</div>'
      + '<p style="margin-top:16px; font-size:13px; color:var(--text-secondary)">This lemma was dropped during precard filtering stages.</p>'
      + '</div>';
    return;
  }

  const firstSense = item.senses[0] || {};
  let heroIpa = "";
  if (firstSense.ipa) {
    heroIpa = '<span class="hero-ipa">' + esc(firstSense.ipa) + '</span>';
  }

  const sensesHtml = item.senses.map(s => {
    const posList = (s.pos || []).map(p => '<span class="pos-tag">' + esc(p) + '</span>').join("");

    let regHtml = "";
    if (s.register && s.register !== "neutral") {
      regHtml += '<span class="register-tag">' + esc(s.register) + '</span>';
    }
    if (s.lexical_type && s.lexical_type !== "word") {
      regHtml += '<span class="register-tag">' + esc(s.lexical_type) + '</span>';
    }

    const topicsHtml = (s.topic_vector || []).map(t =>
      '<span class="topic-pill">' + esc(t.label) + ' <b>' + Number(t.weight).toFixed(2) + '</b></span>'
    ).join("");

    const exs = s.dataset_examples || [];
    let exsHtml = "";
    if (exs.length > 0) {
      exsHtml = '<div class="examples-block">' + exs.map(e => '<div class="example-item">&ldquo;' + esc(e) + '&rdquo;</div>').join("") + '</div>';
    } else if (s.example_synthetic_needed) {
      exsHtml = '<div class="no-examples-notice"> synthetic generation needed: ' + esc(s.example_fallback) + '</div>';
    } else {
      exsHtml = '<div style="font-size:12px; color:var(--text-muted); font-style:italic">No examples available</div>';
    }

    // Human-readable stage names (pipeline stage_calls keys are s-shaped).
    const sc = s.stage_calls || {};
    const chips = [];
    if (sc.s2) {
      chips.push('<span class="stage-chip model" title="sense_judge model"><span class="stage-name">sense_judge:</span> ' + esc(sc.s2) + '</span>');
    }
    if (sc.s3) {
      chips.push('<span class="stage-chip model" title="topic_vectors model"><span class="stage-name">topic_vectors:</span> ' + esc(sc.s3) + '</span>');
    }
    if (sc.s4) {
      chips.push('<span class="stage-chip" title="topic_label method, path: ' + esc(sc.s4_path || "") + '"><span class="stage-name">topic_label:</span> ' + esc(sc.s4) + ' (' + esc(sc.s4_path || "") + ')</span>');
    }
    if (sc.s5) {
      chips.push('<span class="stage-chip" title="enrich path"><span class="stage-name">enrich:</span> ' + esc(sc.s5) + '</span>');
    }

    return ''
      + '<article class="sense-card">'
      + '<div class="sense-topline">'
      + '<div class="topline-left">'
      + '<span class="sense-id-badge">' + esc(s.sense_id) + '</span>'
      + '<span class="cefr-tag cefr-' + esc(s.sense_cefr) + '">' + esc(s.sense_cefr) + '</span>'
      + (s.pool_level !== s.sense_cefr ? '<span class="stats-badge" title="Pool level: ' + esc(s.pool_level) + '">pool: ' + esc(s.pool_level) + '</span>' : "")
      + posList
      + regHtml
      + '</div>'
      + '<div class="topics-group">'
      + topicsHtml
      + '</div>'
      + '</div>'
      + '<div class="sense-def">' + esc(s.en_def) + '</div>'
      + exsHtml
      + '<div class="telemetry-box">'
      + '<div class="telemetry-stages">'
      + '<span style="color:var(--text-muted); font-family:var(--font-mono); font-weight:bold;">Pipeline:</span>'
      + chips.join("")
      + '</div>'
      + '<div style="display:flex; gap:6px; align-items:center;">'
      + '<button class="copy-btn" onclick="copyText(&#39;' + s.pre_card_id + '&#39;, this)">Copy ID</button>'
      + '<button class="copy-btn" onclick="copyText(&#39;' + s.sense_id + '&#39;, this)">Copy Sense</button>'
      + '</div>'
      + '</div>'
      + '<footer class="sense-inspector-footer">'
      + '<div class="inspector-tags">'
      + '<span>fallback: <code>' + esc(s.example_fallback) + '</code></span>'
      + '<span>cefr-src: <code>' + esc(s.sense_cefr_method) + '</code></span>'
      + '<span>ipa-src: <code>' + esc(s.ipa_src || "dataset") + '</code></span>'
      + '</div>'
      + '<span title="Precard Hash ID">hash: <code>' + esc(s.pre_card_id) + '</code></span>'
      + '</footer>'
      + '</article>';
  }).join("");

  container.innerHTML =
    '<div class="word-hero">'
    + '<div class="hero-title-group">'
    + '<span class="hero-word">' + esc(item.text) + '</span>'
    + heroIpa
    + '<span class="hero-key">' + esc(item.key) + '</span>'
    + '</div>'
    + '<span class="stats-badge" style="font-size:12px;">' + item.senses.length + ' sense(s) extracted</span>'
    + '</div>'
    + '<div class="senses-list">'
    + sensesHtml
    + '</div>';
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  document.getElementById("themeIcon").textContent = next === "dark" ? "*" : "o";
}

window.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") {
    if (e.key === "Escape") e.target.blur();
    return;
  }
  if (e.key === "ArrowDown" || e.key.toLowerCase() === "j") {
    e.preventDefault();
    if (selectedIndex < filteredList.length - 1) selectLemma(selectedIndex + 1);
  } else if (e.key === "ArrowUp" || e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (selectedIndex > 0) selectLemma(selectedIndex - 1);
  } else if (e.key === "/") {
    e.preventDefault();
    document.getElementById("searchInput").focus();
  }
});

initTopicsAndPillCounts();
applyFilters();
</script>
</body>
</html>
"""


def esc(value):
    return html.escape(str(value), quote=False)


def load_order(sample_path, limit):
    sample = json.loads(Path(sample_path).read_text(encoding="utf-8"))
    items = sample if isinstance(sample, list) else sample.get("items", sample)
    order = []
    for item in items[:limit]:
        key = item.get("key") if isinstance(item, dict) else None
        if key and key not in order:
            order.append(key)
    return order


def load_rows(proof_dir):
    rows = OrderedDict()
    with open(Path(proof_dir) / "precard.jsonl", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rows.setdefault(rec["key"], []).append(rec)
    return rows


def load_dropped(proof_dir, run_log=None):
    dropped = OrderedDict()
    drop_path = Path(proof_dir) / "dropped.log"
    if drop_path.exists():
        for line in drop_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("===") or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) >= 3:
                dropped.setdefault(parts[0] + ":" + parts[1],
                                   ":".join(parts[2:]).strip())
    # Judge-dropped proper nouns are only logged in the run log.
    if run_log:
        # run_log is a filename inside proof-dir: strip any directory
        # part so --run-log ../../x can never read outside it.
        log_path = Path(proof_dir) / Path(run_log).name
        if log_path.exists():
            for match in _PROPER_RE.finditer(
                    log_path.read_text(encoding="utf-8")):
                dropped.setdefault("w:" + match.group(1),
                                   "pick-proper-noun/" + match.group(2))
    return dropped


def build_report(proof_dir, sample_path, limit=50, run_log=None,
                 out_path=None, title=None, name=None):
    """Build the Split-Inspector report; returns {"rows", "lemmas", "out"}."""
    proof = Path(proof_dir)
    if name:
        # --name joins into proof-dir: strip directories so
        # --name ../../evil can never write outside it.
        name = Path(name).name
    if name and not out_path:
        out_path = str(proof / ("%s.html" % name))
    if name and not title:
        title = "%s — precard v1.4.1 inspector" % name
    title = title or ("%s — precard v1.4.1 inspector" % proof.name)
    order = load_order(sample_path, limit) if sample_path else []
    rows = load_rows(proof)
    dropped = load_dropped(proof, run_log)

    keys = [k for k in order if k in rows or k in dropped]
    keys += [k for k in list(rows) + list(dropped) if k not in keys]
    n_rows = sum(len(v) for v in rows.values())

    lemmas_data = []
    for key in keys:
        if key in rows:
            recs = rows[key]
            text = recs[0].get("text") or key.split(":", 1)[-1]
            pool_level = recs[0].get("pool_level") or "—"
            lemmas_data.append({
                "text": text,
                "key": key,
                "pool_level": pool_level,
                "dropped": False,
                "drop_reason": None,
                "senses": recs,
            })
        elif key in dropped:
            text = key.split(":", 1)[-1]
            lemmas_data.append({
                "text": text,
                "key": key,
                "pool_level": "—",
                "dropped": True,
                "drop_reason": dropped[key],
                "senses": [],
            })

    # Safe embed JSON in a script tag.
    json_blob = json.dumps(lemmas_data, ensure_ascii=False).replace(
        "</", "<\\/")
    page_html = HTML_TEMPLATE.replace("__TITLE__", esc(title)).replace(
        "__LEMMAS_JSON__", json_blob)

    dest = Path(out_path) if out_path else proof / "report.html"
    dest.write_text(page_html, encoding="utf-8")
    return {"rows": n_rows, "lemmas": len(keys), "out": str(dest)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--proof-dir", required=True,
                    help="dir with precard.jsonl + dropped.log")
    ap.add_argument("--sample", required=True, help="sample json file")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--run-log", default=None,
                    help="run log filename inside proof-dir "
                         "(for judge-dropped proper nouns)")
    ap.add_argument("--out", default=None, help="report path "
                    "(default <proof-dir>/<name>.html with --name, "
                    "else <proof-dir>/report.html)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--name", default=None, help="report name: sets "
                    "default out to <proof-dir>/<name>.html and default "
                    "title (explicit --out/--title win)")
    args = ap.parse_args(argv)
    precard_path = Path(args.proof_dir) / "precard.jsonl"
    if not precard_path.is_file():
        ap.error("missing precard.jsonl in proof-dir: %s" % args.proof_dir)
    if not Path(args.sample).is_file():
        ap.error("missing sample file: %s" % args.sample)
    stats = build_report(args.proof_dir, args.sample, args.limit,
                         args.run_log, args.out, args.title, args.name)
    print("wrote %(out)s rows=%(rows)d lemmas=%(lemmas)d" % stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
