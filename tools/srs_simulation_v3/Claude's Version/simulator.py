"""
SRS Lab v3 -- "Adaptive Hybrid" spaced-repetition engine simulator (GOLDEN).
============================================================================

WHAT THIS FILE IS
------------------
A pure-Python, offline math model of how a HamZaboon-style learner's vocabulary
review queue behaves over months/years, WITHOUT touching the real bot, AI
provider, or database. It exists to answer questions like:

    - If a Free-plan user asks lots of custom words, does that starve their
      new-vocabulary growth? (It shouldn't -- see THROTTLE DESIGN below.)
    - How overdue do review cards get before the user finally sees them?
    - Does the "unreviewed word" pile grow forever, or self-correct?
    - How does upgrading Free -> Silver -> Gold actually change outcomes?

Nothing here is wired into production code. It's a design/tuning sandbox.

THE THREE CONTENT SOURCES (in priority order every day)
---------------------------------------------------------
  Tier 1 -- DUE REVIEWS   : cards already in the SRS loop whose scheduled
                            review date has arrived. Always served first --
                            protecting review spacing is the #1 priority.
  Tier 2 -- QUERY BACKLOG : words the user explicitly looked up ("Ask a Word")
                            and chose to save. These are pure user-pull
                            content and are NEVER capacity-throttled at the
                            point of asking -- only at the point of being
                            slotted into a session (see SLOT SPLIT below).
  Tier 3 -- NEW AI CARDS  : brand-new vocabulary the system proactively
                            generates to fill any slots left over after
                            Tier 1 and Tier 2. This is the one and only
                            source that gets throttled by review debt.

THROTTLE DESIGN (the core design decision of this file)
---------------------------------------------------------
Only Tier 3 (new AI generation) is throttled, and ONLY by real due-card debt
(Tier 1 pressure) -- never by how many words the user has queried. This was a
deliberate fix: an earlier version of this simulator computed the throttle
from (due debt + query backlog) combined, which meant an engaged user who
asked lots of questions was accidentally punishing their own vocabulary
growth harder than a lazy user who never asked anything. Query quota is a
paid-plan purchase driver and must stay generous regardless of backlog.

SLOT SPLIT (how Tier 2 vs Tier 3 share the leftover seats)
---------------------------------------------------------
After Tier 1 takes its due cards, the remaining seats in today's sessions are
split between Tier 2 (query backlog) and Tier 3 (new AI) using a "query
share" that normally sits at 50/50, but rises toward 100% if the query
backlog has grown past a "comfortable" size (~3 months' worth of daily
capacity). This is a self-correcting negative-feedback loop: a neglected
pile of asked-but-unreviewed words gets priority to drain, so it can't
literally grow forever even over a multi-year timescale, and it relaxes back
to 50/50 automatically once the pile shrinks back down.

WHY "VOCAB EXPOSURE" IS THE HEADLINE METRIC, NOT JUST "AI-GENERATED"
---------------------------------------------------------------------
An earlier version of this lab only counted AI-generated cards as "vocabulary
growth." That's misleading: an eager user who spends session capacity
reviewing self-chosen queried words instead of random AI suggestions is not
"falling behind" -- they're doing self-directed vocabulary building, which is
arguably even better. So `total_vocab_exposure` = AI-generated + query-
promoted cards combined is the metric that actually represents "how many
distinct words has this learner been introduced to."

GLOSSARY OF OUTPUT COLUMNS / FIELDS (read this before reading any table)
---------------------------------------------------------------------------
  plan               Free / Silver / Gold -- which subscription tier.
  persona            Simulated learner behavior archetype (see PERSONAS).
  vocab_exp / total_vocab_exposure
                     TOTAL distinct words ever introduced to this learner,
                     combining AI-generated words AND user-queried words
                     that got promoted into the SRS loop. This is the
                     headline "how much vocabulary did they gain" number.
  ai_gen / total_new_words
                     Subset of the above: only the AI-*generated* words
                     (not from queries). Useful as an AI-cost/usage proxy,
                     NOT as the vocabulary-growth KPI on its own.
  learned / learned_words
                     How many cards (of any origin) reached at least their
                     2nd successful review by the end of the simulation --
                     a rough "durably learned" count (not just "seen once").
  avg_score          Average familiarity score (0 = struggling, 5 = mastered)
                     across all cards still active in the SRS loop at the end.
  due_bl / max_due_backlog
                     The worst-case number of due (overdue) cards that could
                     NOT be fit into a session on any single day of the run.
                     High and/or growing = the review queue is falling behind.
  q_bl / max_query_backlog
                     The worst-case number of user-queried words still
                     waiting for their first review slot on any single day.
                     This is a "wishlist size," not lost content -- it's
                     addressed by the self-correcting slot split above.
  avg_late / avg_lateness_days
                     Average number of days a due card sat waiting past its
                     scheduled review date, averaged across every review
                     that ever happened in the run. Low = spacing preserved.
  max_late / max_lateness_days
                     The single worst-case delay (in days) that any one due
                     card experienced before finally being reviewed.
  archived / archived_lost_words
                     Cards that were abandoned so long (see ARCHIVE_* below)
                     that the system gave up on them rather than letting
                     them rot in the queue forever. Should stay at (or very
                     near) 0 -- a nonzero number means real content is being
                     permanently lost, which is a red flag, not a feature.

HOW TO RUN THIS
----------------
    python3 run_experiments.py
runs every persona x plan combination at 180 and 360 simulated days and
prints the summary table described above. To experiment with a single
scenario interactively:

    from simulator import simulate, SimConfig
    rows, summary = simulate(SimConfig(plan="gold", persona="eager", days=360))
    print(summary)
    # rows[0], rows[1], ... are the day-by-day breakdown (see the docstring
    # of simulate() for exactly what each day's dict contains).
"""
import math
import random
from dataclasses import dataclass
from typing import Optional

# The fixed SRS review ladder in days. A card graduates from "never seen"
# (idx = -1) to idx 0 on first exposure, then climbs one rung per successful
# "Remembered" click, and drops back to idx 0 on any "Again" click.
#   idx:      0  1  2   3   4   5
INTERVALS = [1, 3, 9, 18, 38, 70, 120, 250, 400, 730]  # days between reviews for each SRS ladder rung

# Per-plan capacity knobs. These mirror the values already used in
# docs/Plan_srs_v3.md for continuity with the real product plan; change them
# here to experiment with different tiers.
#   sessions        : review sessions offered per day
#   session_size    : cards per session
#   ai_daily_cap    : max brand-new AI-generated cards allowed per day (before
#                      throttling -- this is the ceiling, not the guarantee)
#   query_daily_cap : max "Ask a Word" queries allowed per day
#   queue_cap_days  : how many days' worth of daily_slots (sessions x
#                      session_size) of DUE-CARD debt the system will
#                      tolerate before it hard-stops new AI generation
#                      entirely (the "waiting room" -- see simulate()).
PLAN_DEFAULTS = {
    "free":   {"sessions": 1, "session_size": 4, "ai_daily_cap": 3,  "query_daily_cap": 3,  "queue_cap_days": 2},
    "silver": {"sessions": 3, "session_size": 6, "ai_daily_cap": 5, "query_daily_cap": 7,  "queue_cap_days": 3},
    "gold":   {"sessions": 5, "session_size": 9, "ai_daily_cap": 12, "query_daily_cap": 10, "queue_cap_days": 4},
}

# Simulated learner archetypes. These are NOT arbitrary -- they're meant to
# roughly span the real range of behavior we'd expect from actual users:
#   attend     : probability the user opens the app / studies at all on a
#                given day (ignored for "fluctuating", see _attend_prob).
#   q_lo, q_hi : each attending day, the user makes a random number of
#                "Ask a Word" queries in this range (further capped by the
#                plan's query_daily_cap).
#   save_prob  : chance that any single query gets saved into the review
#                queue (vs. just being a one-off lookup).
#   forget     : chance of clicking "Again" (forgot it) on any review card,
#                which resets that card back to idx 0.
PERSONAS = {
    "lazy":        {"attend": 0.35, "q_lo": 0, "q_hi": 1, "save_prob": 0.30, "forget": 0.35},
    "average":     {"attend": 0.70, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
    "eager":       {"attend": 0.92, "q_lo": 2, "q_hi": 6, "save_prob": 0.70, "forget": 0.10},
    # "fluctuating" ignores the static `attend` value above and instead uses
    # a 21-day sine-wave motivation cycle -- see _attend_prob() -- to model a
    # real person whose consistency ebbs and flows (exam weeks, travel,
    # motivation dips, etc.) rather than a constant coin-flip every day.
    "fluctuating": {"attend": None, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
}

# A card is only ever permanently given up on (archived) if it has been
# overdue for longer than ARCHIVE_OVERDUE_DAYS *and* its familiarity score is
# still below ARCHIVE_SCORE_THRESHOLD (i.e. the user was clearly struggling
# with it, not just busy). This is a last-resort safety valve, not a normal
# part of the flow -- in every scenario tested so far it never had to fire.
ARCHIVE_SCORE_THRESHOLD = 1.0
ARCHIVE_OVERDUE_DAYS = 45

# Self-correction target for the query backlog (Tier 2), expressed as "how
# many months' worth of daily slot capacity is a comfortable pile size."
# Below this size, Tier 2 and Tier 3 split leftover slots roughly 50/50.
# Above it, Tier 2's share climbs toward 100%, prioritizing draining the
# pile over generating more brand-new AI content, then relaxes back down
# once the pile shrinks again. See the "SLOT SPLIT" section in the module
# docstring above for the full rationale.
QUERY_TARGET_MONTHS = 3.0


@dataclass
class Card:
    """One vocabulary card tracked by the simulation.

    idx == -1 means "never reviewed yet" (either freshly AI-generated or
    freshly saved from a query, and not yet promoted into the SRS ladder).
    idx >= 0 means "in the SRS ladder," indexing into INTERVALS above.
    """
    id: int
    idx: int = -1
    score: float = 2.0            # familiarity score, 0 (struggling) .. 5 (mastered)
    next_review: Optional[int] = None   # simulated day number this card is next due
    due_since: Optional[int] = None     # day it FIRST became due (for lateness tracking);
                                         # reset to None every time it's actually reviewed


@dataclass
class SimConfig:
    """Everything needed to run one scenario. Pass to `simulate()`."""
    plan: str = "free"          # one of PLAN_DEFAULTS keys: "free" / "silver" / "gold"
    persona: str = "average"    # one of PERSONAS keys
    days: int = 180             # how many simulated days to run
    seed: Optional[int] = 42    # RNG seed; same seed = reproducible run, for fair A/B comparisons
    jitter: float = 0.15        # +/- randomization applied to review intervals (0.15 = +/-15%)
                                 # so cards don't all clump onto the exact same future day


def _attend_prob(persona: str, day: int, rng: random.Random) -> bool:
    """Decide whether the simulated user studies at all on this given day.

    For most personas this is a flat coin-flip using their `attend` prob.
    For "fluctuating" it instead follows a 21-day sine wave oscillating
    between roughly 30% and 90% attendance, to model realistic motivation
    cycles (a burst of enthusiasm, a dip, recovery, repeat) rather than a
    constant probability that never changes.
    """
    p = PERSONAS[persona]
    if persona == "fluctuating":
        phase = (2 * math.pi * day) / 21.0
        prob = 0.60 + 0.30 * math.sin(phase)
        return rng.random() < prob
    return rng.random() < p["attend"]


def simulate(cfg: SimConfig):
    """Run one full scenario and return (daily_rows, summary).

    daily_rows: list of dicts, one per simulated day, with keys:
        day             - simulated day number (0-indexed)
        attended        - did the user study at all today (bool)
        due_processed   - how many due/overdue cards were reviewed today
        due_remaining   - how many due cards did NOT fit into today's
                          sessions and are carried over to tomorrow
        queries         - how many "Ask a Word" queries the user made today
        q_saved         - how many of those queries were saved to the
                          review queue today
        q_backlog       - size of the query backlog waiting for a first
                          review slot, as of the end of today
        ai_gen          - how many brand-new AI cards were actually
                          generated today (after throttling)
        ai_cap          - the plan's raw daily AI-generation ceiling
                          (for reference; `ai_gen` is throttled below this)
        active          - total cards currently in the SRS loop (idx >= 0)
        archived_today  - cards permanently given up on today (see
                          ARCHIVE_OVERDUE_DAYS / ARCHIVE_SCORE_THRESHOLD)

    summary: a dict of end-of-run aggregate stats. See the module docstring
    "GLOSSARY OF OUTPUT COLUMNS" section for what each field means.
    """
    plan = PLAN_DEFAULTS[cfg.plan]
    persona = PERSONAS[cfg.persona]
    rng = random.Random(cfg.seed)

    active: list[Card] = []          # cards currently in the SRS ladder (idx >= 0)
    query_backlog: list[Card] = []   # queried-and-saved words waiting for their first review
    next_id = 0
    rows = []
    archived_count = 0               # running total across the whole simulation
    total_new_words = 0              # running total of AI-generated cards only
    total_cards_created = 0          # running total of ALL cards ever created (AI + query)
    lateness_samples = []            # one entry per due-card review, days-late for that review

    def new_card(idx=-1, next_review=None) -> Card:
        """Create and ID-tag a new card, and count it toward vocab-exposure."""
        nonlocal next_id, total_cards_created
        next_id += 1
        total_cards_created += 1
        return Card(id=next_id, idx=idx, next_review=next_review)

    # Total review "seats" available per day = sessions x cards-per-session.
    daily_slots = plan["sessions"] * plan["session_size"]
    # The "waiting room" ceiling: if due-card debt ever grows past this many
    # cards, new AI generation is paused completely (0/day) until the debt
    # is worked back down below the line. Sized as N days' worth of normal
    # daily capacity for this plan.
    queue_cap_due = plan["queue_cap_days"] * daily_slots

    for day in range(cfg.days):
        attended = _attend_prob(cfg.persona, day, rng)

        # =====================================================================
        # STEP 1 -- USER QUERIES ("Ask a Word")
        # Pure user-pull content. Deliberately NOT throttled by backlog
        # pressure of any kind here -- only capped by the plan's own daily
        # query allowance. This preserves the query feature as an
        # uncompromised paid-plan purchase driver.
        # =====================================================================
        queries_today = 0
        saved_today = 0
        if attended:
            q_hi = min(persona["q_hi"], plan["query_daily_cap"])
            q_lo = min(persona["q_lo"], q_hi)
            queries_today = rng.randint(q_lo, q_hi)
            for _ in range(queries_today):
                if rng.random() < persona["save_prob"]:
                    query_backlog.append(new_card(idx=-1, next_review=None))
                    saved_today += 1

        # =====================================================================
        # STEP 2 -- COLLECT TODAY'S DUE CARDS (Tier 1 candidates)
        # =====================================================================
        due = [c for c in active if c.next_review is not None and c.next_review <= day]
        for c in due:
            if c.due_since is None:
                c.due_since = c.next_review  # remember when it FIRST became due, for lateness stats
        due.sort(key=lambda c: c.due_since)   # oldest-overdue first
        due_before = len(due)

        # =====================================================================
        # STEP 3 -- ARCHIVE SAFETY VALVE
        # Only for cards that have been overdue for a very long time AND are
        # still weak (low score) -- i.e. genuinely abandoned, not just
        # temporarily behind. This should rarely if ever trigger; if it does,
        # it means real vocabulary content is being permanently lost, which
        # is worth flagging to a human, not silently accepting.
        # =====================================================================
        archived_today = 0
        if attended:
            still_active = []
            for c in active:
                if (c.next_review is not None and c.due_since is not None
                        and (day - c.due_since) > ARCHIVE_OVERDUE_DAYS
                        and c.score < ARCHIVE_SCORE_THRESHOLD):
                    archived_today += 1
                    archived_count += 1
                else:
                    still_active.append(c)
            active = still_active
            due = [c for c in due if c in active]

        due_slots_used = 0
        query_slots_used = 0
        ai_generated = 0

        if attended:
            # =================================================================
            # STEP 4 -- TIER 1: DUE REVIEWS ALWAYS GO FIRST
            # =================================================================
            remaining = daily_slots
            tier1 = due[:remaining]
            due_slots_used = len(tier1)
            remaining -= due_slots_used

            # =================================================================
            # STEP 5 -- THROTTLE TIER 3 (new AI cards) BY DUE DEBT ONLY
            # `due_pressure` = how many due cards COULDN'T be served today,
            # i.e. real review debt piling up. This -- and only this -- decides
            # how much new AI content is allowed today. Query backlog size
            # never enters this calculation (see module docstring).
            # =================================================================
            due_pressure = due_before - due_slots_used
            if due_pressure >= queue_cap_due:
                # Waiting room: review debt is too large, pause new words
                # entirely until the backlog is worked back down.
                ai_cap_today = 0
            else:
                # Linear taper: at zero debt, full ai_daily_cap is available;
                # as debt approaches the waiting-room ceiling, the cap shrinks
                # down to a floor of 30% of the plan's ceiling (never fully
                # zero until the hard waiting-room line is actually crossed).
                throttle = max(0.3, 1.0 - (due_pressure / queue_cap_due) * 0.7)
                ai_cap_today = math.floor(plan["ai_daily_cap"] * throttle)

            # =================================================================
            # STEP 6 -- SELF-CORRECTING SPLIT OF REMAINING SLOTS
            # (Tier 2: query backlog)  vs  (Tier 3: new AI cards)
            #
            # query_share starts at 0.5 (an even split) when the query
            # backlog is at or under its "comfortable" target size, and rises
            # linearly toward 1.0 as the backlog grows past that target --
            # so a neglected pile of asked-but-unreviewed words gets
            # increasing priority to drain, capping how large it can grow
            # indefinitely, while easing back to 50/50 automatically once
            # it's under control again.
            # =================================================================
            q_target = max(1, round(QUERY_TARGET_MONTHS * 30 * daily_slots))
            q_ratio = len(query_backlog) / q_target
            query_share = min(1.0, 0.5 + 0.5 * q_ratio)

            target_query_slots = math.ceil(remaining * query_share)
            tier2 = query_backlog[:min(target_query_slots, len(query_backlog), remaining)]
            query_backlog = query_backlog[len(tier2):]
            query_slots_used = len(tier2)
            remaining -= query_slots_used

            # =================================================================
            # STEP 7 -- TIER 3: FILL WHATEVER SLOTS ARE LEFT WITH NEW AI CARDS
            # (bounded by both remaining seats AND today's throttled cap)
            # =================================================================
            ai_take = min(remaining, ai_cap_today)
            tier3 = [new_card(idx=-1, next_review=None) for _ in range(ai_take)]
            ai_generated = ai_take
            total_new_words += ai_take
            remaining -= ai_take

            # If the AI throttle capped Tier 3 below what slots were actually
            # available, don't waste those seats -- hand them back to the
            # query backlog instead of leaving them empty.
            if remaining > 0 and query_backlog:
                extra = query_backlog[:remaining]
                query_backlog = query_backlog[len(extra):]
                tier2 = tier2 + extra
                query_slots_used += len(extra)

            # =================================================================
            # STEP 8 -- "REVIEW" EVERY CARD SELECTED FOR TODAY'S SESSIONS
            # New cards (idx == -1) always graduate straight to idx 0 on
            # first exposure. Cards already in the ladder either advance one
            # rung (success) or reset to idx 0 (forgot / clicked "Again"),
            # per the persona's `forget` probability.
            # =================================================================
            candidates = tier1 + tier2 + tier3
            for c in candidates:
                was_due = c in tier1
                if was_due:
                    lateness_samples.append(day - c.due_since)

                if c.idx == -1:
                    # First-ever exposure: graduate into the ladder.
                    c.idx = 0
                    c.next_review = day + INTERVALS[0]
                    c.due_since = None
                    if c not in active:
                        active.append(c)
                else:
                    if rng.random() < persona["forget"]:
                        # "Again" -- reset to the bottom of the ladder.
                        c.idx = 0
                        c.score = max(0.0, c.score - 1.0)
                        c.next_review = day + INTERVALS[0]
                    else:
                        # "Remembered" -- advance one rung, with jitter so
                        # cards don't all clump onto identical future days.
                        c.idx = min(c.idx + 1, len(INTERVALS) - 1)
                        c.score = min(5.0, c.score + 0.5)
                        jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
                        c.next_review = day + max(1, round(INTERVALS[c.idx] * jitter))
                    c.due_since = None  # reset lateness tracking now that it's been seen

        due_remaining = due_before - due_slots_used

        rows.append({
            "day": day, "attended": attended,
            "due_processed": due_slots_used, "due_remaining": due_remaining,
            "queries": queries_today, "q_saved": saved_today, "q_backlog": len(query_backlog),
            "ai_gen": ai_generated, "ai_cap": plan["ai_daily_cap"],
            "active": len(active), "archived_today": archived_today,
        })

    # =========================================================================
    # END-OF-RUN SUMMARY STATS -- see module docstring "GLOSSARY" section for
    # a plain-English definition of every one of these fields.
    # =========================================================================
    learned = sum(1 for c in active if c.idx >= 2)
    avg_score = (sum(c.score for c in active) / len(active)) if active else 0.0
    max_due_backlog = max(r["due_remaining"] for r in rows)
    max_query_backlog = max(r["q_backlog"] for r in rows)
    avg_lateness = (sum(lateness_samples) / len(lateness_samples)) if lateness_samples else 0.0
    max_lateness = max(lateness_samples) if lateness_samples else 0

    summary = {
        "plan": cfg.plan, "persona": cfg.persona, "days": cfg.days,
        "total_vocab_exposure": total_cards_created,  # AI-gen + query-origin combined (the real growth KPI)
        "total_new_words": total_new_words,            # AI-generated only (cost/usage proxy)
        "final_active_cards": len(active),
        "learned_words": learned,
        "avg_score": round(avg_score, 2),
        "max_due_backlog": max_due_backlog,
        "max_query_backlog": max_query_backlog,
        "avg_lateness_days": round(avg_lateness, 1),
        "max_lateness_days": max_lateness,
        "archived_lost_words": archived_count,
        "avg_ai_gen_per_day": round(total_new_words / cfg.days, 2),
    }
    return rows, summary