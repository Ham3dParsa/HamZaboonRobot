"""Precard run viewer: reads one precard run directory (precard.jsonl +
sample order + dropped.log + run.log) and writes one standalone viewer HTML.
Read-only, stdlib only.
"""

from __future__ import annotations

import argparse
import html
import json
import math
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
  color-scheme: light;
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
  color-scheme: dark;
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

/* Themed scrollbars: native <select> popups follow color-scheme for free.
   Sidebar + detail panes keep a 10px hit area with a thin visible thumb.
   Thumb uses --text-muted (not --border-strong) to hold >= 3:1 contrast
   against the pane surface in both themes. No new palette. */
.sidebar, .detail-pane {
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: var(--text-muted) transparent;
}
.sidebar::-webkit-scrollbar, .detail-pane::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
.sidebar::-webkit-scrollbar-track, .detail-pane::-webkit-scrollbar-track {
  background: transparent;
}
.sidebar::-webkit-scrollbar-thumb, .detail-pane::-webkit-scrollbar-thumb {
  background-color: var(--text-muted);
  border: 3px solid transparent;
  background-clip: content-box;
  border-radius: 8px;
}
.sidebar::-webkit-scrollbar-thumb:hover, .detail-pane::-webkit-scrollbar-thumb:hover {
  background-color: var(--text-secondary);
  border: 3px solid transparent;
  background-clip: content-box;
}

/* Header strip: always-visible lemma + precard totals (T4). */
.header-strip {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  padding: 6px 24px;
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
}
.header-strip b {
  color: var(--text-primary);
}
.hs-dim {
  color: var(--text-muted);
  font-size: 11px;
}
.hs-sep {
  color: var(--border-strong);
}

/* Distributions drawer under the filter bar: nine metric groups. */
.dist-drawer {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  padding: 6px 24px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.dist-drawer > summary {
  cursor: pointer;
  font-weight: 600;
  font-size: 12.5px;
  color: var(--text-primary);
  outline: none;
}
.dist-drawer > summary .dist-hint {
  font-weight: 400;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
}
.dist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 12px;
  padding: 10px 0 6px 0;
}
.dist-group {
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
}
.dist-group h3 {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.dist-group table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-mono);
  font-size: 11px;
}
.dist-group th, .dist-group td {
  text-align: left;
  padding: 2px 6px 2px 0;
  color: var(--text-secondary);
  vertical-align: top;
}
.dist-group th {
  color: var(--text-muted);
  font-weight: 600;
  border-bottom: 1px solid var(--border-subtle);
}
.dist-group td.num {
  text-align: right;
  color: var(--text-primary);
  white-space: nowrap;
}
.dist-note {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 6px;
  font-family: var(--font-sans);
}
.dist-kv {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
  margin: 2px 0;
}
.dist-kv b {
  color: var(--text-primary);
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

__HEADER_STRIP__

  <div class="filter-bar">
    <input type="text" id="searchInput" class="search-input" placeholder="Search lemma or key... (press /)" oninput="applyFilters()">

    <div class="filter-pills" id="cefrPills">
__CEFR_PILLS__
    </div>

    <select id="topicFilter" class="select-filter" onchange="applyFilters()"
      title="All Topics counts all lemmas (kept + dropped); each topic counts kept-only lemmas">
      <option value="ALL">All Topics</option>
    </select>

    <select id="statusFilter" class="select-filter" onchange="applyFilters()"
      title="Dropped lemmas carry no senses: Dropped Only combined with a CEFR, topic, style, method, or source filter matches nothing">
      <option value="ALL">All Statuses</option>
      <option value="KEPT">Kept Only</option>
      <option value="DROPPED">Dropped Only</option>
      <option value="SYNTHETIC">Needs Synthetic Ex</option>
    </select>

    <select id="registerFilter" class="select-filter" onchange="applyFilters()"
      title="All Styles counts all lemmas (kept + dropped); each style counts kept-only lemmas with any sense carrying it">
      <option value="ALL">All Styles</option>
    </select>

    <select id="methodFilter" class="select-filter" onchange="applyFilters()"
      title="All Methods counts all lemmas (kept + dropped); each method counts kept-only lemmas with any sense using it">
      <option value="ALL">All Methods</option>
    </select>

    <select id="sourceFilter" class="select-filter" onchange="applyFilters()"
      title="All Sources counts all lemmas (kept + dropped); each source counts kept-only lemmas with any sense from it">
      <option value="ALL">All Sources</option>
    </select>

    <select id="sortOrder" class="select-filter" onchange="applyFilters()" style="margin-left:auto;"
      title="CEFR Level sorts by each kept lemma's lowest sense CEFR (filter matches any sense)">
      <option value="DEFAULT">Original Order</option>
      <option value="ALPHA">A → Z</option>
      <option value="SENSES_DESC">Senses (High to Low)</option>
      <option value="CEFR_ASC">CEFR Level</option>
    </select>
  </div>

__DIST_DRAWER__

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
const STATS = __VIEWER_STATS__;
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
  const styleCounts = {};
  const methodCounts = {};
  const sourceCounts = {};
  const cefrCounts = { "ALL": 0, "A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0, "C2": 0 };

  RAW_LEMMAS.forEach(l => {
    cefrCounts["ALL"]++;
    if (!l.dropped) {
      // Find all unique CEFR levels present in this lemma
      const lemmaCefrs = new Set();
      const lemmaTopics = new Set();
      const lemmaStyles = new Set();
      const lemmaMethods = new Set();
      const lemmaSources = new Set();
      l.senses.forEach(s => {
        if (s.sense_cefr) lemmaCefrs.add(s.sense_cefr);
        if (s.pool_level) lemmaCefrs.add(s.pool_level);
        (s.topic_vector || []).forEach(t => lemmaTopics.add(t.label));
        if (s.register) lemmaStyles.add(`register:${s.register}`);
        if (s.lexical_type && s.lexical_type !== "word") lemmaStyles.add(`type:${s.lexical_type}`);
        lemmaMethods.add(s.sense_cefr_method || "(unknown)");
        lemmaSources.add(s.example_fallback || "(unknown)");
      });
      lemmaCefrs.forEach(c => {
        if (cefrCounts[c] !== undefined) cefrCounts[c]++;
      });
      lemmaTopics.forEach(t => {
        topicCounts[t] = (topicCounts[t] || 0) + 1;
      });
      lemmaStyles.forEach(v => {
        styleCounts[v] = (styleCounts[v] || 0) + 1;
      });
      lemmaMethods.forEach(v => {
        methodCounts[v] = (methodCounts[v] || 0) + 1;
      });
      lemmaSources.forEach(v => {
        sourceCounts[v] = (sourceCounts[v] || 0) + 1;
      });
    }
  });

  // Set CEFR pill counts + unit tooltips (label rule: ALL counts all
  // lemmas incl. dropped; each level counts kept-only lemmas, exists
  // semantics, so one lemma may count in 2 levels).
  const allPill = document.querySelector('#cefrPills .pill-btn[data-cefr="ALL"]');
  if (allPill) allPill.title = `ALL: all ${escapeHtml(STATS.lemmas_total)} lemmas (kept + dropped)`;
  for (const [lvl, count] of Object.entries(cefrCounts)) {
    const el = document.getElementById(`count-${lvl}`);
    if (el) el.textContent = `(${count})`;
    if (lvl !== "ALL") {
      const btn = document.querySelector(`#cefrPills .pill-btn[data-cefr="${lvl}"]`);
      if (btn) btn.title = `${escapeHtml(lvl)}: ${escapeHtml(count)} kept-only lemmas with any sense at ${escapeHtml(lvl)} (pool or sense CEFR; one lemma may count in 2 levels)`;
    }
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

  // Populate Styles dropdown with kept-only lemma counts (exists semantics).
  // Keys carry their field origin (register:informal vs type:colloquial)
  // so one combined select stays unambiguous.
  const styleSel = document.getElementById("registerFilter");
  styleSel.innerHTML = `<option value="ALL">All Styles (${RAW_LEMMAS.length})</option>`;
  Object.keys(styleCounts).sort().forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = `${v} (${styleCounts[v]} kept lemmas)`;
    opt.title = `${v}: ${styleCounts[v]} kept-only lemmas with any sense carrying it`;
    styleSel.appendChild(opt);
  });

  // Populate Method + Source dropdowns (kept-only, exists semantics)
  const methodSel = document.getElementById("methodFilter");
  methodSel.innerHTML = `<option value="ALL">All Methods (${RAW_LEMMAS.length})</option>`;
  Object.keys(methodCounts).sort().forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = `${v} (${methodCounts[v]} kept lemmas)`;
    opt.title = `${v}: ${methodCounts[v]} kept-only lemmas with any sense using it`;
    methodSel.appendChild(opt);
  });
  const sourceSel = document.getElementById("sourceFilter");
  sourceSel.innerHTML = `<option value="ALL">All Sources (${RAW_LEMMAS.length})</option>`;
  Object.keys(sourceCounts).sort().forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = `${v} (${sourceCounts[v]} kept lemmas)`;
    opt.title = `${v}: ${sourceCounts[v]} kept-only lemmas with any sense from it`;
    sourceSel.appendChild(opt);
  });
}

function filterCefr(level) {
  currentCefrFilter = level;
  document.querySelectorAll("#cefrPills .pill-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-cefr") === level);
  });
  applyFilters();
}

const CEFR_RANK = { "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6 };

// Lowest CEFR across all senses (pool fallback), consistent with the
// any-sense CEFR filter. senses[0]-only display/sort drifted from it.
function lowestCefrOf(item) {
  let best = null;
  let bestRank = 99;
  (item.senses || []).forEach(s => {
    [s.sense_cefr, s.pool_level, item.pool_level].forEach(lvl => {
      const r = CEFR_RANK[lvl] || 99;
      if (r < bestRank) { bestRank = r; best = lvl; }
    });
  });
  return best || item.pool_level || "—";
}

function applyFilters() {
  const q = document.getElementById("searchInput").value.trim().toLowerCase();
  const topic = document.getElementById("topicFilter").value;
  const status = document.getElementById("statusFilter").value;
  const style = document.getElementById("registerFilter").value;
  const method = document.getElementById("methodFilter").value;
  const source = document.getElementById("sourceFilter").value;
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
    if (style !== "ALL") {
      if (item.dropped) return false;
      const cut = style.indexOf(":");
      const field = style.slice(0, cut);
      const want = style.slice(cut + 1);
      const hasStyle = item.senses.some(s => field === "register" ? s.register === want : s.lexical_type === want);
      if (!hasStyle) return false;
    }
    if (method !== "ALL") {
      if (item.dropped) return false;
      const hasMethod = item.senses.some(s => (s.sense_cefr_method || "(unknown)") === method);
      if (!hasMethod) return false;
    }
    if (source !== "ALL") {
      if (item.dropped) return false;
      const hasSource = item.senses.some(s => (s.example_fallback || "(unknown)") === source);
      if (!hasSource) return false;
    }
    return true;
  });

  if (sort === "ALPHA") {
    filteredList.sort((a, b) => a.text.localeCompare(b.text));
  } else if (sort === "SENSES_DESC") {
    filteredList.sort((a, b) => b.senses.length - a.senses.length);
  } else if (sort === "CEFR_ASC") {
    filteredList.sort((a, b) => {
      return (CEFR_RANK[lowestCefrOf(a)] || 99) - (CEFR_RANK[lowestCefrOf(b)] || 99);
    });
  }

  renderSidebar();
  if (filteredList.length > 0) {
    selectLemma(0);
  } else {
    let hint = "Try adjusting your filters or search query.";
    if (status === "DROPPED" && (currentCefrFilter !== "ALL" || topic !== "ALL" || style !== "ALL" || method !== "ALL" || source !== "ALL")) {
      hint = `Dropped lemmas carry no senses, so a CEFR/topic/style/method/source filter never matches them. `
        + `Clear them to browse all ${STATS.lemmas_dropped} dropped lemmas.`;
    }
    document.getElementById("detailContent").innerHTML = `
      <div style="text-align:center; padding: 80px; color:var(--text-muted)">
        <h3>No matching lemmas found</h3>
        <p style="margin-top:6px; font-size:13px;">${escapeHtml(hint)}</p>
      </div>`;
  }
}

function renderSidebar() {
  const sidebar = document.getElementById("sidebarList");
  sidebar.innerHTML = "";
  const filteredPrecards = filteredList.reduce((n, item) => n + (item.dropped ? 0 : item.senses.length), 0);
  const statsEl = document.getElementById("statsCount");
  statsEl.textContent = `${escapeHtml(filteredList.length)} of ${escapeHtml(RAW_LEMMAS.length)} lemmas (filtered view, all) · ${escapeHtml(filteredPrecards)} precards (kept-only)`;
  statsEl.title = `Filtered view over all ${escapeHtml(STATS.lemmas_total)} lemmas (${escapeHtml(STATS.lemmas_kept)} kept, ${escapeHtml(STATS.lemmas_dropped)} dropped) and ${escapeHtml(STATS.precards_total)} precards (kept-only rows)`;

  filteredList.forEach((item, idx) => {
    const el = document.createElement("div");
    el.className = `lemma-list-item ${idx === selectedIndex ? "selected" : ""}`;
    el.id = `lemma-item-${idx}`;
    el.onclick = () => selectLemma(idx);

    let rightBadge = "";
    if (item.dropped) {
      rightBadge = `<span class="stats-badge" style="color:var(--drop-text); border-color:var(--drop-b);">DROP</span>`;
    } else {
      const lemmaCefr = lowestCefrOf(item);
      const nPrecards = item.senses.length;
      rightBadge = `
        <span class="cefr-tag cefr-${escapeHtml(lemmaCefr)}" title="lowest CEFR across senses (filter matches any sense)">${escapeHtml(lemmaCefr)}</span>
        <span class="stats-badge" title="${escapeHtml(nPrecards)} precards (kept-only senses)">${escapeHtml(nPrecards)} precards</span>
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
      <span class="topic-pill" title="topic label + weight 0..1">${escapeHtml(t.label)} <b>${t.weight.toFixed(2)}</b></span>
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
      <span class="stats-badge" style="font-size:12px;" title="${escapeHtml(item.senses.length)} kept-only precard rows for this lemma">${escapeHtml(item.senses.length)} precards</span>
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


_ENTRY_SUFFIX_RE = re.compile(r"\s\[entry=([^\]]+)\]\s*$")


def _split_entry_suffix(reason):
    """Strip a trailing " [entry=BAND]" (pipeline #730); (reason, band|None)."""
    text = str(reason or "")
    match = _ENTRY_SUFFIX_RE.search(text)
    if not match:
        return text.strip(), None
    band = match.group(1).strip() or None
    return text[:match.start()].rstrip(), band


def _drop_reason(value):
    """Reason string from a dropped-map value (dict {reason, entry_band}
    or legacy plain string; legacy strings are suffix-stripped too)."""
    if isinstance(value, dict):
        return value.get("reason") or ""
    reason, _band = _split_entry_suffix(value)
    return reason


def _drop_band(value):
    """Entry band from a dropped-map value (None for legacy lines)."""
    if isinstance(value, dict):
        return value.get("entry_band")
    _reason, band = _split_entry_suffix(value)
    return band


def _load_dropped(dropped_path, run_log_path=None):
    """Dropped map: key -> {"reason", "entry_band"}.

    The " [entry=BAND]" suffix is stripped at the reader so reason
    grouping (_reason_head) never sees it; the band rides along as a
    separate field for the later viewer pass (lemmas_data entry_band).
    Legacy suffix-less lines yield entry_band None.
    """
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
                reason, band = _split_entry_suffix(
                    ":".join(parts[2:]).strip())
                dropped.setdefault(parts[0] + ":" + parts[1],
                                   {"reason": reason, "entry_band": band})
    if run_log_path:
        try:
            log_text = Path(run_log_path).read_text(encoding="utf-8")
        except OSError:
            log_text = ""
        for match in _PROPER_RE.finditer(log_text):
            dropped.setdefault("w:" + match.group(1),
                               {"reason": "pick-proper-noun/" + match.group(2),
                                "entry_band": None})
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


_CEFR_LEVELS = tuple(CEFR_ORDER) + ("\u2014",)
_MISSING = "\u2014"
_UNKNOWN_METHOD = "(unknown)"


def _reason_head(reason):
    head = (reason or "").split(":")[0].split("/")[0].strip()
    return head or "(unknown)"


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def _median(values):
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _p90(values):
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def _sort_dist(dist):
    return dict(sorted(dist.items(), key=lambda kv: (-kv[1], kv[0])))


def _compute_stats(rows, dropped_map):
    """Distribution metrics from kept precard rows + drop reasons.

    Lemma-level counts use exists semantics (one lemma in two buckets
    counts in both, overlaps tallied separately); precard-level counts
    are row-level. Stdlib only; single dict embedded as STATS.
    """
    kept_keys = [k for k in rows]
    dropped_keys = [k for k in dropped_map if k not in rows]
    n_kept = len(kept_keys)
    n_dropped = len(dropped_keys)
    n_rows = sum(len(v) for v in rows.values())

    drops = {}
    for key in dropped_keys:
        head = _reason_head(_drop_reason(dropped_map[key]))
        drops[head] = drops.get(head, 0) + 1
    drops_by_reason = sorted(drops.items(), key=lambda kv: (-kv[1], kv[0]))

    per_lemma = [len(rows[k]) for k in kept_keys]
    hist = {"1": 0, "2": 0, "3": 0, "4+": 0}
    for n in per_lemma:
        hist["4+" if n >= 4 else str(n)] += 1

    cefr_lemma = {lvl: 0 for lvl in _CEFR_LEVELS}
    cefr_precard = {lvl: 0 for lvl in _CEFR_LEVELS}
    cefr_overlap = 0
    topic_lemma = {}
    topic_precard = {}
    topic_overlap = 0
    untagged_precards = 0
    synth_precards = 0
    synth_lemmas = 0
    mismatch_precards = 0
    mismatch_lemmas = 0
    method_precard = {}
    path_precard = {}
    source_precard = {}
    evidenced_rows = 0
    evidenced_mismatch = 0

    for key in kept_keys:
        lemma_cefrs = set()
        lemma_topics = set()
        lemma_synth = False
        lemma_mismatch = False
        for rec in rows[key]:
            if not isinstance(rec, dict):
                continue
            sense_cefr = rec.get("sense_cefr") or _MISSING
            pool = rec.get("pool_level") or _MISSING
            cefr_precard[sense_cefr] = cefr_precard.get(sense_cefr, 0) + 1
            lemma_cefrs.add(sense_cefr)
            lemma_cefrs.add(pool)
            labels = [t.get("label") for t in (rec.get("topic_vector") or [])
                      if isinstance(t, dict) and t.get("label")]
            if labels:
                for label in labels:
                    topic_precard[label] = topic_precard.get(label, 0) + 1
            else:
                untagged_precards += 1
            lemma_topics.update(labels)
            if rec.get("example_synthetic_needed"):
                synth_precards += 1
                lemma_synth = True
            method = rec.get("sense_cefr_method") or _UNKNOWN_METHOD
            method_precard[method] = method_precard.get(method, 0) + 1
            calls = rec.get("stage_calls")
            path = calls.get("s4_path") if isinstance(calls, dict) else None
            path = path or _UNKNOWN_METHOD
            path_precard[path] = path_precard.get(path, 0) + 1
            source = rec.get("example_fallback") or _UNKNOWN_METHOD
            source_precard[source] = source_precard.get(source, 0) + 1
            evidenced = method not in ("pool-fallback", _UNKNOWN_METHOD)
            if evidenced:
                evidenced_rows += 1
            if (sense_cefr != _MISSING and pool != _MISSING
                    and sense_cefr != pool):
                mismatch_precards += 1
                lemma_mismatch = True
                if evidenced:
                    evidenced_mismatch += 1
        for level in lemma_cefrs:
            cefr_lemma[level] = cefr_lemma.get(level, 0) + 1
        if len(lemma_cefrs) > 1:
            cefr_overlap += 1
        for label in lemma_topics:
            topic_lemma[label] = topic_lemma.get(label, 0) + 1
        if len(lemma_topics) > 1:
            topic_overlap += 1
        if lemma_synth:
            synth_lemmas += 1
        if lemma_mismatch:
            mismatch_lemmas += 1

    n_total = n_kept + n_dropped
    return {
        "lemmas_total": n_total,
        "lemmas_kept": n_kept,
        "lemmas_dropped": n_dropped,
        "precards_total": n_rows,
        "kept_rate_pct": round(100.0 * n_kept / n_total) if n_total else 0,
        "drops_by_reason": [[head, count] for head, count in drops_by_reason],
        "ppc": {
            "mean": round(sum(per_lemma) / len(per_lemma), 2) if per_lemma else 0,
            "median": _median(per_lemma),
            "p90": _p90(per_lemma),
            "hist": hist,
        },
        "cefr_lemma": cefr_lemma,
        "cefr_lemma_overlap": cefr_overlap,
        "cefr_precard": cefr_precard,
        "topic_lemma": dict(sorted(topic_lemma.items())),
        "topic_lemma_overlap": topic_overlap,
        "topic_precard": dict(sorted(topic_precard.items())),
        "untagged_precards": untagged_precards,
        "synthetic": {
            "precards": synth_precards,
            "precards_pct": _pct(synth_precards, n_rows),
            "lemmas": synth_lemmas,
            "lemmas_pct": _pct(synth_lemmas, n_kept),
        },
        "mismatch": {
            "precards": mismatch_precards,
            "precards_pct": _pct(mismatch_precards, n_rows),
            "lemmas": mismatch_lemmas,
            "evidenced_precards": evidenced_mismatch,
            "evidenced_denominator": evidenced_rows,
            "evidenced_pct": _pct(evidenced_mismatch, evidenced_rows),
        },
        "cefr_method": _sort_dist(method_precard),
        "topic_path": _sort_dist(path_precard),
        "example_source": _sort_dist(source_precard),
    }


def _header_strip(stats):
    if stats["drops_by_reason"]:
        drops_tip = "drops by reason (dropped.log): " + ", ".join(
            "%s: %d dropped lemmas" % (head, count)
            for head, count in stats["drops_by_reason"])
    else:
        drops_tip = "no drops recorded"
    return (
        '<div class="header-strip" id="headerStrip" title="%s">'
        '<span><b>%d</b> lemmas '
        '<span class="hs-dim">(all: <b>%d</b> kept, <b>%d</b> dropped)</span></span>'
        '<span class="hs-sep">\u00b7</span>'
        '<span><b>%d</b> precards '
        '<span class="hs-dim">(kept-only rows)</span></span>'
        '<span class="hs-sep">\u00b7</span>'
        '<span>kept rate <b>%d%%</b> '
        '<span class="hs-dim">(kept lemmas / all lemmas)</span></span>'
        "</div>" % (
            html.escape(drops_tip, quote=True),
            stats["lemmas_total"], stats["lemmas_kept"],
            stats["lemmas_dropped"], stats["precards_total"],
            stats["kept_rate_pct"]))


def _dist_table(headers, rows):
    head = "".join("<th>%s</th>" % _esc(h) for h in headers)
    body = "".join(
        "<tr>" + "".join(
            '<td class="num">%s</td>' % _esc(c) if i
            else "<td>%s</td>" % _esc(c)
            for i, c in enumerate(row)
        ) + "</tr>"
        for row in rows)
    return ("<table><thead><tr>%s</tr></thead>"
            "<tbody>%s</tbody></table>" % (head, body))


def _ordered_levels(*maps):
    levels = [lvl for lvl in _CEFR_LEVELS
              if any(m.get(lvl) for m in maps)]
    extras = sorted({k for m in maps for k in m} - set(_CEFR_LEVELS))
    return levels + extras


def _dist_drawer(stats):
    ppc = stats["ppc"]
    g1 = (
        "<h3>1 \u00b7 precards per kept lemma</h3>"
        '<p class="dist-kv">mean <b>%(mean)s</b> precards \u00b7 '
        "median <b>%(median)s</b> \u00b7 p90 <b>%(p90)s</b> "
        "(over %(n)d kept lemmas)</p>" % {
            "mean": ppc["mean"], "median": ppc["median"],
            "p90": ppc["p90"], "n": stats["lemmas_kept"]}
        + _dist_table(
            ("precards bucket", "kept lemmas"),
            [("1 precard", ppc["hist"]["1"]),
             ("2 precards", ppc["hist"]["2"]),
             ("3 precards", ppc["hist"]["3"]),
             ("4+ precards", ppc["hist"]["4+"])]))

    g2 = (
        "<h3>2 \u00b7 kept vs dropped</h3>"
        '<p class="dist-kv"><b>%(kept)d</b> kept lemmas \u00b7 '
        "<b>%(dropped)d</b> dropped lemmas \u00b7 kept rate "
        "<b>%(rate)d%%</b> (kept lemmas / all lemmas)</p>" % {
            "kept": stats["lemmas_kept"],
            "dropped": stats["lemmas_dropped"],
            "rate": stats["kept_rate_pct"]}
        + (_dist_table(
            ("drop reason (stage signal)", "dropped lemmas"),
            [(head, count) for head, count in stats["drops_by_reason"]])
            if stats["drops_by_reason"]
            else '<p class="dist-note">no drops recorded</p>'))

    levels = _ordered_levels(stats["cefr_lemma"], stats["cefr_precard"])
    g3 = (
        "<h3>3 \u00b7 senses by CEFR</h3>"
        + _dist_table(
            ("CEFR", "kept lemmas, lemma-level (exists)",
             "precards, row-level"),
            [(lvl, stats["cefr_lemma"].get(lvl, 0),
              stats["cefr_precard"].get(lvl, 0)) for lvl in levels])
        + '<p class="dist-note">lemma counts overlap: '
        "<b>%d</b> kept lemmas sit in 2+ CEFR buckets "
        "(sense_cefr \u222a pool_level); precard counts are row-level "
        "and never overlap.</p>" % stats["cefr_lemma_overlap"])

    labels = sorted(set(stats["topic_lemma"]) | set(stats["topic_precard"]),
                    key=lambda l: (-stats["topic_precard"].get(l, 0), l))
    g4 = (
        "<h3>4 \u00b7 senses by topic</h3>"
        + (_dist_table(
            ("topic", "kept lemmas, lemma-level (exists)",
             "precards, row-level"),
            [(label, stats["topic_lemma"].get(label, 0),
              stats["topic_precard"].get(label, 0)) for label in labels])
            if labels else '<p class="dist-note">no topic labels</p>')
        + '<p class="dist-note">lemma counts overlap: '
        "<b>%d</b> kept lemmas sit in 2+ topic buckets; "
        "<b>%d</b> precards carry no topic label.</p>" % (
            stats["topic_lemma_overlap"], stats["untagged_precards"]))

    synth = stats["synthetic"]
    g5 = (
        "<h3>5 \u00b7 synthetic examples needed</h3>"
        '<p class="dist-kv"><b>%(p)d</b> precards '
        "(%(pp)s%% of all precards) \u00b7 <b>%(m)d</b> kept lemmas "
        "(%(mp)s%% of kept lemmas)</p>" % {
            "p": synth["precards"], "pp": synth["precards_pct"],
            "m": synth["lemmas"], "mp": synth["lemmas_pct"]})

    mismatch = stats["mismatch"]
    g6 = (
        "<h3>6 \u00b7 pool-vs-sense CEFR mismatch</h3>"
        '<p class="dist-kv"><b>%(p)d</b> precards '
        "(%(pp)s%% of all precards) \u00b7 <b>%(m)d</b> kept lemmas "
        "with \u22651 mismatch</p>"
        '<p class="dist-kv">evidenced-only: <b>%(ep)d</b> precards '
        "(%(epp)s%% of %(ed)d evidenced precards)</p>"
        '<p class="dist-note">evidenced = sense_cefr_method other than '
        "pool-fallback or (unknown) (copied levels match by construction).</p>" % {
            "p": mismatch["precards"], "pp": mismatch["precards_pct"],
            "m": mismatch["lemmas"], "ep": mismatch["evidenced_precards"],
            "epp": mismatch["evidenced_pct"],
            "ed": mismatch["evidenced_denominator"]})

    g7 = (
        "<h3>7 \u00b7 CEFR provenance</h3>"
        + (_dist_table(
            ("CEFR method", "precards, row-level"),
            [(method, "%d precards (%s%%)" % (
                count, _pct(count, stats["precards_total"])))
             for method, count in stats["cefr_method"].items()])
            if stats["cefr_method"]
            else '<p class="dist-note">no rows</p>')
        + '<p class="dist-note">row-level sense_cefr_method; '
        "pool-fallback levels are copied from the pool.</p>")

    g8 = (
        "<h3>8 \u00b7 topic s4 paths</h3>"
        + (_dist_table(
            ("s4 path", "precards, row-level"),
            [(path, "%d precards (%s%%)" % (
                count, _pct(count, stats["precards_total"])))
             for path, count in stats["topic_path"].items()])
            if stats["topic_path"]
            else '<p class="dist-note">no rows</p>')
        + '<p class="dist-note">row-level stage_calls.s4_path.</p>')

    g9 = (
        "<h3>9 \u00b7 example sourcing</h3>"
        + (_dist_table(
            ("example source", "precards, row-level"),
            [(source, "%d precards (%s%%)" % (
                count, _pct(count, stats["precards_total"])))
             for source, count in stats["example_source"].items()])
            if stats["example_source"]
            else '<p class="dist-note">no rows</p>')
        + '<p class="dist-note">row-level example_fallback.</p>')

    return (
        '<details class="dist-drawer" id="distDrawer">'
        "<summary>Distributions "
        '<span class="dist-hint">nine metric groups \u00b7 lemma-level '
        "(exists, overlaps noted) vs precard-level (row-level) \u00b7 "
        "every number names its unit</span></summary>"
        '<div class="dist-grid">'
        + "".join('<section class="dist-group">%s</section>' % g
                   for g in (g1, g2, g3, g4, g5, g6, g7, g8, g9))
        + "</div></details>")


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
                "drop_reason": _drop_reason(dropped_map[key]),
                "entry_band": _drop_band(dropped_map[key]),
                "senses": [],
            })

    page = _HTML_TEMPLATE.replace(
        "__TITLE__", _esc(title or ("precard viewer \u2014 %s" % run_path.name)))
    page = page.replace("__LINE_VERSION__", _esc(_LINE_VERSION))
    page = page.replace("__CEFR_PILLS__", _cefr_pills())
    page = page.replace("__BANNERS__", _banners(warnings))
    stats = _compute_stats(rows, dropped_map)
    page = page.replace("__HEADER_STRIP__", _header_strip(stats))
    page = page.replace("__DIST_DRAWER__", _dist_drawer(stats))
    page = page.replace("__VIEWER_DATA__",
                        _neutralise(json.dumps(lemmas_data, ensure_ascii=False)))
    page = page.replace("__VIEWER_STATS__",
                        _neutralise(json.dumps(stats, ensure_ascii=False)))
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
