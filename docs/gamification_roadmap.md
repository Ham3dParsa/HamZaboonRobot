# Gamification & Engagement Roadmap (نقشه راه گیمیفیکیشن و تعاملات آینده)

> Status: Non-canonical ideation document. This is a brainstorm reference extracted from a strategic discussion (see [Claude Chat](https://claude.ai/chat/03464fdd-304a-4e14-9ca3-19d968f1686b)), not a locked roadmap commitment. No item here has passed the Contract-Lock Gate (AGENTS.md §2.4) or been added to ROADMAP.md. Nothing here should be treated as scheduled work until it is formally promoted.

---

## Reading Guide (نحوه مطالعه این سند)

This document is a **strategic reference, not a spec**. Because these features are **not imminent**, the details below (data dependencies, success metrics, UX sketches) reflect **our current best understanding at the time of writing** — the repo will evolve, so treat every implementation detail as **provisional and re-verifiable**, not as locked rules. Before any item is promoted to real work, it must be re-checked against the codebase and pass the Contract-Lock Gate (AGENTS.md §2.4).

---

## Philosophy (مزیت رقابتی و رویکرد آموزشی)

**HamZaboon is not just a teacher — it is a language companion.**

Gamification here must **use actual cognitive data (FSRS parameters) rather than random dopamine hits**. The single most important differentiator against both **Duolingo** (which gamifies engagement but not memory) and **Anki** (which exposes raw FSRS math but no motivation) is our ability to make a learner's **real memory retention visible and motivating**.

Every engagement feature below is grounded in one principle: *reward learning that actually sticks, not learning that merely looks active.*

### Design invariants (stable beliefs)

These hold regardless of how the repo changes:

- **Educational content is never paywalled** — coins and cosmetics only ever sit on top of learning, never gate it.
- **Every "reward" maps to a real FSRS signal** (difficulty, stability, retention, due count) — never to arbitrary activity.
- **Zero unexpected AI spend** — features must either reuse stored data or declare their marginal token cost up front.
- **The learner always sees *why*:** an alert, a plant, or a streak must trace back to a real memory fact.

---

## Phase 1: Immediate / Near-term (Relying on existing FSRS & Telegram UI)

These features are **lowest risk** — they reuse the FSRS engine and the current Telegram UI we already ship, with no new storage surface required.

### 1.1 Forgetting Alerts (کلمات در خطر فراموشی)

- **What it is:** Use DSR data to warn users: *"You have 5 words that will be forgotten this week if not reviewed."*
- **Why it matters:** Creates **scientific urgency** — the alert is a prediction from memory math, not a guilt trip. It is the fastest way to make FSRS value visible to a non-technical learner.
- **UX sketch:** A daily summary message listing the most at-risk saved words with a tap-to-review action per word.
- **Provisional data dependency:** reads the `saved_words` retention / DSR-derived forget-risk signal already produced by the FSRS path. Exact query is re-verifiable at build time.
- **Success metric:** % of alert recipients who open a review session that day vs. baseline; reduction in words that actually lapse.
- **Open questions:** how many words to surface (5 feels right but unvalidated); push vs. only on-open; opt-out behavior.

### 1.2 Shareable Weekly Wrap-up (جمعبندی هفتگی)

- **What it is:** A **Spotify-style static card** summarizing words learned and current streak.
- **Why it matters:** A **zero-CAC organic marketing tool** — learners share their progress and bring new users for free.
- **UX sketch:** A single shareable image (learned words, streak, best day, a "you remembered X" stat) with a native share button; generated once per week.
- **Provisional data dependency:** aggregate over recent reviews/learned cards + streak state — all already persisted.
- **Success metric:** share rate per weekly delivery; new-user signups attributable to shares (if trackable without invasive analytics).
- **Open questions:** whether image generation costs matter at scale; which stats are motivating vs. noise; cadence (weekly vs. monthly).

### 1.3 "Just 3 Minutes" Mode (مرور سریع ۳ دقیقهای)

- **What it is:** A dedicated button that **strictly pulls from the Tier1 (Due) queue** for users with low time.
- **Why it matters:** Removes the **friction of starting a full session** — the #1 reason learners abandon.
- **UX sketch:** A low-commitment entry point that runs only as many due cards as fit in 3 minutes, then stops cleanly with a "come back tomorrow" note.
- **Provisional data dependency:** reuses the existing Tier1 due-queue selection logic from the session assembler — no new data needed.
- **Success metric:** session-start rate among users who chose 3-min mode; completion rate; whether it grows into full sessions.
- **Open questions:** how "3 minutes" is estimated (card-count heuristic vs. pacing model); behavior when the queue is empty.

### Why these three first

- **Forgetting Alerts** prove the FSRS value proposition immediately — turning dry retention math into a reason to open the app.
- **Weekly Wrap-up** is pure organic growth with no paid acquisition and no new AI spend.
- **"Just 3 Minutes" Mode** converts "I have no time" into "I have 3 minutes," lowering the activation barrier to a daily habit.

---

## Phase 2: Mid-term (Premium Features, MiniQuiz & Internal Economy)

These features layer an **internal economy** and **quiz surface** on top of data we already generate. They introduce their first new persistent state, so they carry more schema risk than Phase 1.

### 2.1 Coin Economy (اقتصاد سکه)

- **What it is:** Convert **`retention_events` points** (1 / 3 / 6 / 10) into a **soft currency**.
- **Why it matters:** Turns memory success into a tangible, motivating reward loop.
- **Rules:**
  - **Strictly reserved** for **streak-savers** or **cosmetic upgrades**.
  - **Core learning remains ad/coin-free** — educational content is never paywalled.
  - **Premium plans get a multiplier** (e.g., **2x coins**) as a reward for paying users.
- **UX sketch:** A coin balance shown in the main menu; spend flows for a streak-saver (restore a broken streak) or cosmetic (theme / badge).
- **Provisional data dependency:** a new coin ledger derived from `retention_events`; the spend targets (streak-saver, cosmetics) presume a streak mechanism and a cosmetic store that **do not exist yet** and must be scoped. **Note:** the `retention_events` source this economy builds on does **not exist yet** — it is created by [#84](https://github.com/Ham3dParsa/HamZaboonRobot/issues/84) (phase-6, open). Coin Economy therefore depends on #84 being implemented first.
- **Success metric:** coin balance growth correlates with review consistency; streak-saver used but not abused; no learner-facing content becomes coin-gated.
- **Open questions:** economy balance (earn vs. spend rates); anti-abuse of streak-savers; whether Premium multiplier is flat or tiered; what cosmetics exist initially.

> **Guardrail:** Coins must never gate access to educational material. They are a reward and personalization layer, not a paywall.

### 2.2 Semantic Explorer (کاوشگر معنا)

- **What it is:** **4-choice quizzes** using **synonyms / antonyms generated from the user's existing saved cards**.
- **Why it matters:** Turns passive saved-word storage into an active recall surface that reinforces semantic connections — **without new AI cost**.
- **UX sketch:** A mini-quiz surfaced after a session or on demand: "Which of these is a synonym of X?" built from the learner's own words.
- **Provisional data dependency:** relies on synonym/antonym data generated at card-creation time; **this relationship must be verified** — if the current generation flow does not emit synonyms, a limited generation step (and its cost) must be scoped before this is viable.
- **Success metric:** quiz completion and accuracy; uplift in retention of words touched by the quiz.
- **Open questions:** data availability of synonyms; distractor selection quality; quiz placement/cadence.

---

## Phase 3: Long-term (Telegram Mini App / Rich UI era)

These features **require the real-time responsiveness of a Telegram Mini App (TMA)** — they cannot run smoothly on plain message-based UI. This phase implies a **front-end migration**, which is itself a major scoped decision.

### 3.1 Golden Minute (دقیقهی طلایی)

- **What it is:** A **60-second speed-run of due cards**.
- **Why it matters:** The fixed, tight timebox requires **sub-second UI transitions**, which only a TMA can deliver. Converts review from "another session" into a **fun, bounded challenge**.
- **UX sketch:** A full-screen countdown racing through due cards with a final score tied to FSRS outcomes (not raw clicks).
- **Provisional data dependency:** same due-queue as normal review; the "score" should map to real retention to honor the design invariants.
- **Success metric:** repeat usage of the challenge; whether it lifts daily review frequency.
- **Open questions:** scoring fairness; difficulty scaling; how it coexists with the main session flow.

### 3.2 Word Garden (باغچه واژگان)

- **What it is:** Visualizing progress using **existing FSRS data**.
- **Why it matters:** Gives learners a **living, emotional representation of their memory** — the core differentiator made visible, at **zero AI cost** (pure UI rendering over `saved_words`).

| FSRS Parameter | Visual Mapping |
| --- | --- |
| **Difficulty** | The plant's **health / need for water** |
| **Stability** | The plant's **growth / height** |

- **UX sketch:** A garden grid where each plant is a saved word; watering (reviewing) keeps it healthy; neglect makes it wilt — mirroring real forgetting.
- **Provisional data dependency:** reads `saved_words` FSRS fields only. No new backend state; the schema of those fields is re-verifiable at build time.
- **Success metric:** returning visits to the garden; a visible connection between garden health and review behavior.
- **Open questions:** visual rendering approach inside a TMA; performance with large word counts; whether garden state adds any write (e.g., user-planted placement).

---

## Phase 4: Future / Social (Requires Strict Scope Expansion)

> **WARNING BADGE**

Social features, leaderboards, and groups are currently **STRICTLY OUT OF SCOPE** per **AGENTS.md §9 (Product Scope Guardrails)**.

### 4.1 Study Buddy (همراه مطالعه)

Two users **link their streaks**. If one breaks, **both get notified**.

### ⚠️ Hard requirement before any engineering begins

This phase **requires formal Product Owner approval and architecture expansion**:

- ✅ Formal Product Owner decision to move social features into scope (via ROADMAP.md).
- ✅ Architecture expansion for two-user linkage, notification routing, and data-model changes.
- ✅ A locked Contract-Lock Gate (AGENTS.md §2.4) covering the new social data model.
- ✅ Explicit budget for any new AI / infrastructure cost.

**Nothing in this section is scheduled work.** It is recorded only as a directional idea pending explicit owner approval.

---

## Related GitHub Issues

The ideas above relate to existing tracked issues. This document does **not** change their status — it only records the relationship. Each issue carries a comment linking back to this doc.

| Issue | Topic | Doc relation |
| --- | --- | --- |
| [#108](https://github.com/Ham3dParsa/HamZaboonRobot/issues/108) | Extra gamification beyond streak = premium reward surface | Coin Economy (Phase 2) — direct |
| [#87](https://github.com/Ham3dParsa/HamZaboonRobot/issues/87) | Mini-quiz feedback buttons / response trail | Semantic Explorer (Phase 2) — adjacent |
| [#86](https://github.com/Ham3dParsa/HamZaboonRobot/issues/86) | Streak only after full daily-card completion | Weekly Wrap-up / streak (Phase 1) |
| [#88](https://github.com/Ham3dParsa/HamZaboonRobot/issues/88) | User-configurable daily target tied to streak | Weekly Wrap-up / streak (Phase 1) |
| [#105](https://github.com/Ham3dParsa/HamZaboonRobot/issues/105) | Progress-aware learner reminders | Forgetting Alerts (Phase 1) — adjacent |
| [#84](https://github.com/Ham3dParsa/HamZaboonRobot/issues/84) | `retention_events` points (1/3/6/10) | Coin Economy data source (Phase 2) — blocking |

---

## Cross-cutting Notes

### How to use this document going forward

- **Promotion path:** any item moving toward work must first be re-validated against the current codebase, then pass the Contract-Lock Gate, then be added to `ROADMAP.md`.
- **Staleness rule:** because these features are non-imminent, the provisional details here **will drift**. Re-check data dependencies and costs at build time rather than trusting this document.
- **Scope discipline:** only Phase 1 items are realistically reachable with today's architecture. Phases 2–3 imply new state or a TMA migration; Phase 4 is out of scope until the owner acts.

### Constraint Summary

- **Do not** modify `ROADMAP.md`.
- **Do not** touch any `.py` files.
- Every feature above is a **brainstorm reference**, not a commitment. Promotion to actual work requires passing the Contract-Lock Gate and formal entry into the roadmap.
