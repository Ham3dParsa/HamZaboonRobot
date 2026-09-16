"""Precard run viewer: reads one precard run directory (precard.jsonl +
sample order + dropped.log + run.log) and writes one standalone viewer HTML.
Read-only, stdlib only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import OrderedDict
from pathlib import Path

from factory.precard import __version__ as _LINE_VERSION
from factory.precard.accounting import item_key
from factory.precard.cefr import CEFR_ORDER
from factory.precard.pipeline import DEFAULT_OUT, DEFAULT_SAMPLE
from factory.precard.progress import normalize_stage
from factory.precard.topics import LABELS as _TOPIC_LABELS

_PROPER_RE = re.compile(r"w:([A-Za-z]+):pick-proper-noun/([^\s,)]+)")

_STAGE_IDS = ("s0", "s0b", "s1", "s2", "s3", "s4", "s5")

_HTML_TEMPLATE = """
<!DOCTYPE html>
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
.viewer-banner {
  background: var(--warn-bg);
  border: 1px solid var(--warn-b);
  color: var(--warn-text);
  font-size: 12px;
  padding: 6px 24px;
}
</style>
</head>
<body>

<div class="app-shell">
__BANNERS__

  <header class="app-header">
    <div class="brand">
      <h1>Precard Studio <span class="brand-pill">v__LINE_VERSION__</span></h1>
      <span class="stats-badge" id="statsCount">Loading...</span>
    </div>

    <div class="controls">
      <div class="shortcut-hint">
        <span class="kbd-key">↑</span><span class="kbd-key">↓</span> or <span class="kbd-key">J</span><span class="kbd-key">K</span> navigate
      </div>
      <button class="theme-toggle-btn" onclick="toggleTheme()">
        <span id="themeIcon">☀️</span> Theme
      </button>
    </div>
  </header>

  <div class="filter-bar">
    <input type="text" id="searchInput" class="search-input" placeholder="Search lemma or key... (press /)" oninput="applyFilters()">

    <div class="filter-pills" id="cefrPills">
__CEFR_PILLS__
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
      <option value="ALPHA">A → Z</option>
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
/*PRECARD_VIEWER_DATA_START*/
const RAW_LEMMAS = __VIEWER_DATA__;
/*PRECARD_VIEWER_DATA_END*/
const KNOWN_TOPICS = __KNOWN_TOPICS__;
const STAGE_NAMES = __STAGE_NAMES__;

let filteredList = [];
let selectedIndex = -1;
let currentCefrFilter = "ALL";

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function initTopicsAndPillCounts() {
  const topicCounts = {};
  const cefrCounts = { "ALL": 0, "A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0, "C2": 0 };

  RAW_LEMMAS.forEach(l => {
    cefrCounts["ALL"]++;
    if (!l.dropped) {
      // Find all unique CEFR levels present in this lemma
      const lemmaCefrs = new Set();
      const lemmaTopics = new Set();
      l.senses.forEach(s => {
        if (s.sense_cefr) lemmaCefrs.add(s.sense_cefr);
        if (s.pool_level) lemmaCefrs.add(s.pool_level);
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

  // Set CEFR pill counts
  for (const [lvl, count] of Object.entries(cefrCounts)) {
    const el = document.getElementById(`count-${lvl}`);
    if (el) el.textContent = `(${count})`;
  }

  // Populate Topics dropdown with counts
  const sel = document.getElementById("topicFilter");
  // ALL is a lemma count (total incl. dropped), matching CEFR ALL;
  // per-topic rows count kept lemmas (dropped never match a topic).
  sel.innerHTML = `<option value="ALL">All Topics (${RAW_LEMMAS.length})</option>`;
  KNOWN_TOPICS.filter(t => topicCounts[t] !== undefined).concat(Object.keys(topicCounts).filter(t => !KNOWN_TOPICS.includes(t)).sort()).forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = `${t} (${topicCounts[t]})`;
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
      const hasCefr = item.senses.some(s => s.sense_cefr === currentCefrFilter || s.pool_level === currentCefrFilter);
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
    const rank = { "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "—": 99 };
    filteredList.sort((a, b) => {
      const ca = a.senses[0]?.sense_cefr || a.pool_level || "—";
      const cb = b.senses[0]?.sense_cefr || b.pool_level || "—";
      return (rank[ca] || 99) - (rank[cb] || 99);
    });
  }

  renderSidebar();
  if (filteredList.length > 0) {
    selectLemma(0);
  } else {
    document.getElementById("detailContent").innerHTML = `
      <div style="text-align:center; padding: 80px; color:var(--text-muted)">
        <h3>No matching lemmas found</h3>
        <p style="margin-top:6px; font-size:13px;">Try adjusting your filters or search query.</p>
      </div>`;
  }
}

function renderSidebar() {
  const sidebar = document.getElementById("sidebarList");
  sidebar.innerHTML = "";
  document.getElementById("statsCount").textContent = `${filteredList.length} of ${RAW_LEMMAS.length} lemmas`;

  filteredList.forEach((item, idx) => {
    const el = document.createElement("div");
    el.className = `lemma-list-item ${idx === selectedIndex ? "selected" : ""}`;
    el.id = `lemma-item-${idx}`;
    el.onclick = () => selectLemma(idx);

    let rightBadge = "";
    if (item.dropped) {
      rightBadge = `<span class="stats-badge" style="color:var(--drop-text); border-color:var(--drop-b);">DROP</span>`;
    } else {
      const topCefr = item.senses[0]?.sense_cefr || item.pool_level;
      rightBadge = `
        <span class="cefr-tag cefr-${escapeHtml(topCefr)}">${escapeHtml(topCefr)}</span>
        <span class="stats-badge">${item.senses.length}</span>
      `;
    }

    el.innerHTML = `
      <div class="item-left">
        <span class="item-word" ${item.dropped ? 'style="text-decoration:line-through; opacity:0.6"' : ''}>${escapeHtml(item.text)}</span>
        <span class="item-sub">${escapeHtml(item.key)}</span>
      </div>
      <div class="item-right">${rightBadge}</div>
    `;
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

document.getElementById("detailContent").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-copy-text]");
  if (btn) copyText(btn.getAttribute("data-copy-text"), btn);
});

function selectLemma(index) {
  if (index < 0 || index >= filteredList.length) return;
  selectedIndex = index;
  document.querySelectorAll(".lemma-list-item").forEach((el, i) => {
    el.classList.toggle("selected", i === index);
  });

  const activeEl = document.getElementById(`lemma-item-${index}`);
  if (activeEl) {
    activeEl.scrollIntoView({ block: "nearest" });
  }

  const item = filteredList[index];
  const container = document.getElementById("detailContent");
  if (!item) return;

  document.getElementById("detailPane").scrollTop = 0;

  if (item.dropped) {
    container.innerHTML = `
      <div class="dropped-hero">
        <h2>${escapeHtml(item.text)}</h2>
        <div style="color:var(--text-muted); font-family:var(--font-mono); margin-top:4px;">${escapeHtml(item.key)}</div>
        <div class="dropped-reason-pill">dropped: ${escapeHtml(item.drop_reason)}</div>
        <p style="margin-top:16px; font-size:13px; color:var(--text-secondary)">This lemma was dropped during precard filtering stages.</p>
      </div>
    `;
    return;
  }

  const firstSense = item.senses[0] || {};
  const heroIpa = firstSense.ipa ? `<span class="hero-ipa">${escapeHtml(firstSense.ipa)}</span>` : "";

  let sensesHtml = item.senses.map(s => {
    const posList = (s.pos || []).map(p => `<span class="pos-tag">${escapeHtml(p)}</span>`).join("");

    let regHtml = "";
    if (s.register && s.register !== "neutral") {
      regHtml += `<span class="register-tag">${escapeHtml(s.register)}</span>`;
    }
    if (s.lexical_type && s.lexical_type !== "word") {
      regHtml += `<span class="register-tag">${escapeHtml(s.lexical_type)}</span>`;
    }

    const topicsHtml = (s.topic_vector || []).map(t => `
      <span class="topic-pill">${escapeHtml(t.label)} <b>${t.weight.toFixed(2)}</b></span>
    `).join("");

    const exs = s.dataset_examples || [];
    let exsHtml = "";
    if (exs.length > 0) {
      exsHtml = `<div class="examples-block">` + exs.map(e => `<div class="example-item">“${escapeHtml(e)}”</div>`).join("") + `</div>`;
    } else if (s.example_synthetic_needed) {
      exsHtml = `<div class="no-examples-notice">⚠️ No dataset examples — Flagged for synthetic generation (${escapeHtml(s.example_fallback)})</div>`;
    } else {
      exsHtml = `<div style="font-size:12px; color:var(--text-muted); font-style:italic">No examples available</div>`;
    }

    // Telemetry & Stage Calls Pipeline
    const sc = s.stage_calls || {};
    const s2Chip = sc.s2 ? `<span class="stage-chip model" title="${STAGE_NAMES.s2 || 's2'} disambiguation model"><span class="stage-name">s2:</span> ${escapeHtml(sc.s2)}</span>` : "";
    const s3Chip = sc.s3 ? `<span class="stage-chip model" title="${STAGE_NAMES.s3 || 's3'} model"><span class="stage-name">s3:</span> ${escapeHtml(sc.s3)}</span>` : "";
    const s4Chip = sc.s4 ? `<span class="stage-chip" title="${STAGE_NAMES.s4 || 's4'} path: ${escapeHtml(sc.s4_path || '')}"><span class="stage-name">s4:</span> ${escapeHtml(sc.s4)}</span>` : "";
    const s5Chip = sc.s5 ? `<span class="stage-chip"><span class="stage-name">s5:</span> ${escapeHtml(sc.s5)}</span>` : "";

    return `
      <article class="sense-card">
        <!-- ROW 1: SenseID | CEFR | POS | Topic -->
        <div class="sense-topline">
          <div class="topline-left">
            <span class="sense-id-badge">${escapeHtml(s.sense_id)}</span>
            <span class="cefr-tag cefr-${escapeHtml(s.sense_cefr)}">${escapeHtml(s.sense_cefr)}</span>
            ${s.pool_level !== s.sense_cefr ? `<span class="stats-badge" title="Pool level: ${escapeHtml(s.pool_level)}">pool: ${escapeHtml(s.pool_level)}</span>` : ""}
            ${posList}
            ${regHtml}
          </div>
          <div class="topics-group">
            ${topicsHtml}
          </div>
        </div>

        <!-- ROW 2: Definition -->
        <div class="sense-def">${escapeHtml(s.en_def)}</div>

        <!-- ROW 3: Examples -->
        ${exsHtml}

        <!-- ROW 4: Telemetry Pipeline Breakdown -->
        <div class="telemetry-box">
          <div class="telemetry-stages">
            <span style="color:var(--text-muted); font-family:var(--font-mono); font-weight:bold;">Pipeline:</span>
            ${s2Chip}
            ${s3Chip}
            ${s4Chip}
            ${s5Chip}
          </div>
          <div style="display:flex; gap:6px; align-items:center;">
            <button class="copy-btn" data-copy-text="${escapeHtml(s.pre_card_id)}">Copy ID</button>
            <button class="copy-btn" data-copy-text="${escapeHtml(s.sense_id)}">Copy Sense</button>
          </div>
        </div>

        <!-- Technical Details Footer -->
        <footer class="sense-inspector-footer">
          <div class="inspector-tags">
            <span>fallback: <code>${escapeHtml(s.example_fallback)}</code></span>
            <span>cefr-src: <code>${escapeHtml(s.sense_cefr_method)}</code></span>
            <span>ipa-src: <code>${escapeHtml(s.ipa_src || 'dataset')}</code></span>
          </div>
          <span title="Precard Hash ID">hash: <code>${escapeHtml(s.pre_card_id)}</code></span>
        </footer>
      </article>
    `;
  }).join("");

  container.innerHTML = `
    <div class="word-hero">
      <div class="hero-title-group">
        <span class="hero-word">${escapeHtml(item.text)}</span>
        ${heroIpa}
        <span class="hero-key">${escapeHtml(item.key)}</span>
      </div>
      <span class="stats-badge" style="font-size:12px;">${item.senses.length} sense(s) extracted</span>
    </div>
    <div class="senses-list">
      ${sensesHtml}
    </div>
  `;
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  document.getElementById("themeIcon").textContent = next === "dark" ? "🌙" : "☀️";
}

// Global Keyboard Navigation
window.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") {
    if (e.key === "Escape") e.target.blur();
    return;
  }
  if (e.key === "ArrowDown" || e.key === "j" || e.key === "J") {
    e.preventDefault();
    if (selectedIndex < filteredList.length - 1) selectLemma(selectedIndex + 1);
  } else if (e.key === "ArrowUp" || e.key === "k" || e.key === "K") {
    e.preventDefault();
    if (selectedIndex > 0) selectLemma(selectedIndex - 1);
  } else if (e.key === "/") {
    e.preventDefault();
    document.getElementById("searchInput").focus();
  }
});

// Initial Run
initTopicsAndPillCounts();
applyFilters();

</script>
</body>
</html>
"""


def _esc(value):
    return html.escape(str(value), quote=False)


def _default_run_dir():
    return Path(DEFAULT_OUT).parent


def _load_order(sample_path, limit):
    order = []
    if not sample_path:
        return order
    try:
        raw = Path(sample_path).read_text(encoding="utf-8")
    except OSError:
        return order
    try:
        sample = json.loads(raw)
    except ValueError:
        return order
    try:
        items = sample if isinstance(sample, list) else sample.get("items", [])
    except AttributeError:
        return order
    if isinstance(items, dict):
        items = items.get("items", [])
    try:
        seq = list(items) if not limit else list(items)[:limit]
    except TypeError:
        return order
    for item in seq:
        try:
            key = item_key(item)
        except Exception:
            key = item.get("key") if isinstance(item, dict) else None
        if key and key not in order:
            order.append(key)
    return order


def _load_rows(precard_path):
    rows = OrderedDict()
    if not precard_path:
        return rows
    try:
        handle = open(precard_path, encoding="utf-8")
    except OSError:
        return rows
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            key = rec.get("key") if isinstance(rec, dict) else None
            if not key:
                continue
            rows.setdefault(key, []).append(rec)
    return rows


def _load_dropped(dropped_path, run_log_path=None):
    dropped = OrderedDict()
    if dropped_path:
        try:
            text = Path(dropped_path).read_text(encoding="utf-8")
        except OSError:
            text = ""
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("===") or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) >= 3:
                dropped.setdefault(parts[0] + ":" + parts[1],
                                   ":".join(parts[2:]).strip())
    if run_log_path:
        try:
            log_text = Path(run_log_path).read_text(encoding="utf-8")
        except OSError:
            log_text = ""
        for match in _PROPER_RE.finditer(log_text):
            dropped.setdefault("w:" + match.group(1),
                               "pick-proper-noun/" + match.group(2))
    return dropped


def _cefr_pills():
    lines = ["      <button class=\"pill-btn active\" data-cefr=\"ALL\" "
             "onclick=\"filterCefr('ALL')\">ALL "
             "<span class=\"pill-count\" id=\"count-ALL\"></span></button>"]
    for level in CEFR_ORDER:
        lines.append("      <button class=\"pill-btn\" data-cefr=\"%s\" "
                     "onclick=\"filterCefr('%s')\">%s "
                     "<span class=\"pill-count\" id=\"count-%s\"></span></button>"
                     % (level, level, level, level))
    return "\n".join(lines)


def _banners(warnings):
    return "\n".join("    <div class=\"viewer-banner\">%s</div>" % _esc(w)
                      for w in warnings)


def _neutralise(text):
    return text.replace("</", "<\\/")


def _build(run_dir=None, precard=None, sample=None, dropped=None,
           run_log=None, limit=0, title=None):
    run_path = Path(run_dir) if run_dir else None
    if run_path is None:
        for cand in (precard, dropped, run_log):
            if cand:
                run_path = Path(cand).parent
                break
        if run_path is None:
            run_path = _default_run_dir()
    precard_path = Path(precard) if precard else run_path / "precard.jsonl"
    sample_path = Path(sample) if sample else (
        Path(DEFAULT_SAMPLE) if DEFAULT_SAMPLE else None)
    dropped_path = Path(dropped) if dropped else run_path / "dropped.log"
    run_log_path = Path(run_log) if run_log else run_path / "run.log"

    warnings = []
    order = _load_order(sample_path, limit)
    if sample_path is None or not sample_path.exists():
        warnings.append("sample order skipped (missing %s)" % sample_path)
    rows = _load_rows(precard_path)
    if not precard_path.exists():
        warnings.append("precard rows skipped (missing %s)" % precard_path)
    dropped_map = _load_dropped(dropped_path, run_log_path)
    if not dropped_path.exists():
        warnings.append("dropped list skipped (missing %s)" % dropped_path)
    if run_log_path is None or not run_log_path.exists():
        warnings.append("run-log scan skipped (missing %s)" % run_log_path)

    keys = [k for k in order if k in rows or k in dropped_map]
    seen = set(keys)
    for k in list(rows) + list(dropped_map):
        if k not in seen:
            seen.add(k)
            keys.append(k)
    n_rows = sum(len(v) for v in rows.values())

    lemmas_data = []
    for key in keys:
        if key in rows:
            recs = rows[key]
            first = recs[0] if isinstance(recs[0], dict) else {}
            text = first.get("text") or key.split(":", 1)[-1]
            pool_level = first.get("pool_level") or "\u2014"
            lemmas_data.append({
                "text": text,
                "key": key,
                "pool_level": pool_level,
                "dropped": False,
                "drop_reason": None,
                "senses": recs,
            })
        elif key in dropped_map:
            text = key.split(":", 1)[-1]
            lemmas_data.append({
                "text": text,
                "key": key,
                "pool_level": "\u2014",
                "dropped": True,
                "drop_reason": dropped_map[key],
                "senses": [],
            })

    page = _HTML_TEMPLATE.replace(
        "__TITLE__", _esc(title or ("precard viewer \u2014 %s" % run_path.name)))
    page = page.replace("__LINE_VERSION__", _esc(_LINE_VERSION))
    page = page.replace("__CEFR_PILLS__", _cefr_pills())
    page = page.replace("__BANNERS__", _banners(warnings))
    page = page.replace("__VIEWER_DATA__",
                        _neutralise(json.dumps(lemmas_data, ensure_ascii=False)))
    page = page.replace("__KNOWN_TOPICS__",
                        _neutralise(json.dumps(list(_TOPIC_LABELS),
                                               ensure_ascii=False)))
    page = page.replace("__STAGE_NAMES__",
                        _neutralise(json.dumps(
                            {sid: normalize_stage(sid) for sid in _STAGE_IDS},
                            ensure_ascii=False)))
    return page, {"rows": n_rows, "lemmas": len(keys)}


def build_html(run_dir=None, *, precard=None, sample=None, dropped=None,
               run_log=None, limit=0, title=None):
    """Return the standalone viewer HTML text for one precard run."""
    page, _stats = _build(run_dir, precard, sample, dropped, run_log,
                          limit, title)
    return page


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", default=str(_default_run_dir()),
                    help="run dir with precard.jsonl + dropped.log")
    ap.add_argument("--precard", default=None,
                    help="precard.jsonl path (default <run-dir>/precard.jsonl)")
    ap.add_argument("--sample", default=None,
                    help="sample json file (default pipeline DEFAULT_SAMPLE)")
    ap.add_argument("--dropped", default=None,
                    help="dropped.log path (default <run-dir>/dropped.log)")
    ap.add_argument("--run-log", default=None,
                    help="run log path (default <run-dir>/run.log)")
    ap.add_argument("--out", default=None,
                    help="viewer path (default <run-dir>/precard-viewer.html)")
    ap.add_argument("--limit", type=int, default=0,
                    help="max sample lemmas (0 = all)")
    ap.add_argument("--title", default=None,
                    help="page title (default 'precard viewer \u2014 <run-dir name>')")
    args = ap.parse_args(argv)
    page, stats = _build(args.run_dir, args.precard, args.sample,
                         args.dropped, args.run_log, args.limit, args.title)
    dest = Path(args.out) if args.out else Path(args.run_dir) / "precard-viewer.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page, encoding="utf-8")
    print("wrote %(out)s rows=%(rows)d lemmas=%(lemmas)d" % {
        "out": dest, "rows": stats["rows"], "lemmas": stats["lemmas"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
