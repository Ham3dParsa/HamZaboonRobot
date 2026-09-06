---
name: contract-showcase
description: Present, defend, or explain a contract/proposal/design decision for owner review as a standalone Persian RTL HTML decision document with read-state tracking and per-rule lock toggles. Load when owner asks to "unslop" a debate or needs an owner-readable decision doc.
license: MIT
compatibility: opencode
metadata:
  category: workflow
author: Ham3dParsa
author_url: https://github.com/Ham3dParsa
---
# Contract Showcase Skill

## When to load
- User asks to present, defend, or explain a contract / proposal / design decision for owner review
- User says "unslop" about a debate, wants tangible scenarios with trade-offs, or needs a decision document the (non-developer) owner can actually read
- After a contract lock draft exists and the owner must pick rules one by one

## What it builds
A single standalone Persian RTL HTML decision document (lives wherever the owner opens it — reports dir or drive), with this anatomy per rule:
1. **مسئله** (amber box) — why a decision is needed at all; technical terms explained inline where they appear, never assumed.
2. **سناریو** (teal box) — one realistic story with concrete names/numbers showing what happens in practice under the chosen option.
3. **جدول گزینه‌ها** — chosen vs rejected, each with the concrete price of being wrong (not abstract "better/worse").
4. **Q&A annex under its own rule** (indigo dashed box, bidirectional links) — owner questions answered where they belong, never in a detached appendix. Each annex carries a date stamp; calibration claims cite the real test (sample size + numbers), never "verified" without evidence.

## Document mechanics (all required)
- **Sticky single-line nav** with anchor links to every rule + annex; `scroll-margin-top` so anchors never hide under the bar; horizontal scroll on mobile.
- **Per-section read state**: خواندم / نیمه / نخواندم buttons under every section, persisted in `localStorage` (per-machine memory, no backend). A dynamic "fresh/unread" box at top rebuilds itself from those states — never a hardcoded "what's new" list. Unread sections get a ● dot in the nav.
- **Floating ▲ ▼ buttons** appearing after scroll, for jump to top/bottom.
- **Vazirmatn** with Tahoma fallback; distinct role color per box type; decision tables with green/red verdict side-bars; English terms as `ltr` pills.
- **Evidence rule**: every empirical claim (counts, scores, distributions) names its source (file, sample size, date). A test with n=2 positives says so openly and does not lock thresholds — it locks the metric family and records the calibration as pending.

## Completion criteria
- Owner can answer "what is new since I last read" in under 30 seconds (fresh box + nav dots).
- Owner can rule on each numbered option without asking what a term means (inline explanations, one realistic scenario each).
- No sentence rewrites the locked contract — the showcase explains and defends; the contract file stays the single source of truth.

## Sequencing (optional — ask when complex)
This skill may run standalone for simple explanations. When the matter is
complex (multiple rules, owner must pick options, code will follow), ask the
owner via the question tool whether to pair with `contract-lock-gate`:
draft → showcase → per-rule pick → lock. Never assume the pairing.

## Canonical sample
`sample-minimal.html` in this folder is the structural template: required ids
(`rN`, `q-N`, `fresh`, `freshlist`, `gotop`, `gobot`), required classes
(`prob`, `sc`, `qa`, `pick`, `drop`, `en`, `readctl`, `stamp`), and the
read-state + nav + jump-button script. Build every showcase from it; do not
link a past report as the template (reports rot, the sample is the contract).

## Handoff back to the agent (mandatory part of the pattern)
Browser memory is owner-local and invisible to the agent — locks mean nothing
until they cross into chat. Every showcase therefore includes:
- A **copy-status button** in the fresh box (`📋 کپی وضعیت برای ارسال`):
  copies `READ: {...} / LOCK: {...}` JSON to clipboard (with prompt() fallback).
- The agent's standing instruction: when the owner pastes it, parse it fully,
  read back the understanding for confirmation, and persist locks into the
  contract file (git) + the relevant issue threads. Chat is the bridge;
  the file is the memory.

## Lock state (per-rule, owner-driven)
Every rule heading carries a lock toggle (🔓 قفل کن / 🔒 قفل شد), persisted in
`localStorage` under a separate namespaced key (`<doc-key>-lock`). Locked
rules get a green edge; a progress line (`🔒 n از m بند قفل شده`) lives in the
fresh box. Lock is NEVER set by the agent — only by the owner's click (or an
explicit "قفل شد" in chat, which the agent then mirrors). A rule whose annex
is later superseded is manually unlocked by the agent with a باطل‌شده mark.

## Acceptance checklist (soft-hard: all boxes ticked before delivery)
- [ ] Every rule has مسئله + سناریوی واقعی + جدول انتخاب/رد با قیمت اشتباه.
- [ ] Every empirical claim carries a stamp: [Jalali date | Gregorian date | commit | issue].
- [ ] Every Q&A sits under its own rule with bidirectional links (rule→annex, annex→rule).
- [ ] Every annex has a date stamp; superseded annexes are marked باطل‌شده+date, never deleted.
- [ ] Fresh box is dynamic (built from read-state buttons), never a hardcoded list.
- [ ] localStorage key is namespaced per document (`showcase-read-<title>`), never a fixed global.
- [ ] Sticky nav links every section; anchors clear the bar; no horizontal overflow at 390px.
- [ ] No term unexplained; no threshold locked on n<30 evidence (lock metric family, record calibration pending).
- [ ] Lock toggles on every rule; progress line in fresh box; nothing pre-locked by the agent.
- [ ] Copy-status button present; handoff instruction (paste → parse → persist) followed.

## Lifecycle & ticket sync
- Each annex stamp: `[1405-06-15 شمسی | 2026-09-06 | commit:<sha> | issue:#NNN]` —
  Jalali for the owner, Gregorian+commit for the machine, issue for the thread.
- When a rule changes: old annex stays, marked باطل‌شده with date + link to the
  replacing annex. History is never rewritten.
- When a rule maps to an issue, the annex links it (`#NNN` form only — never
  hardcoded numbers); the agent posts the decision back to that issue thread,
  so chat and tracker agree.
