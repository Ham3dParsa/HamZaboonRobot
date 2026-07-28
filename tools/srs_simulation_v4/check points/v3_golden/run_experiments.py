"""
Runs every persona x plan combination through the v3 simulator at 180 and
360 simulated days, and prints a summary table for each.

Usage:
    python3 run_experiments.py

For what each column means, see the "GLOSSARY OF OUTPUT COLUMNS" section at
the top of simulator.py -- the legend below is a short-form reminder only.
"""
import sys
sys.path.insert(0, "/home/claude/srs_lab/v3")
from simulator import simulate, SimConfig, PLAN_DEFAULTS, PERSONAS

LEGEND = """
COLUMN LEGEND (full explanation in simulator.py docstring):
  plan/persona : which subscription tier / simulated learner behavior
  vocab_exp    : TOTAL distinct words introduced (AI-generated + queried) -- the headline growth number
  ai_gen       : subset of vocab_exp that came from AI generation only (cost/usage proxy, not the KPI)
  learned      : cards that reached >= 2 successful reviews by the end (durably learned, rough measure)
  avg_score    : average familiarity of still-active cards at the end (0 = weak .. 5 = mastered)
  due_bl       : worst-case count of due cards that missed a session on any single day (spacing risk)
  q_bl         : worst-case size of the "asked but not yet reviewed" query pile on any single day
  avg_late     : average days a due card sat waiting past its scheduled date, across all reviews
  max_late     : the single worst delay (days) any one due card ever experienced
  archived     : cards permanently given up on (should stay ~0 -- nonzero = real content being lost)
"""

if __name__ == "__main__":
    print(LEGEND)
    for DAYS in (7, 30, 90, 180, 360, 720):
        print(f"\n===== {DAYS}-day simulation =====")
        print(f"{'plan':7} {'persona':12} {'vocab_exp':9} {'ai_gen':7} {'learned':8} {'avg_score':9} "
              f"{'due_bl':7} {'q_bl':6} {'avg_late':8} {'max_late':8} {'archived':8}")
        print("-" * 100)
        for plan in PLAN_DEFAULTS:
            for persona in PERSONAS:
                cfg = SimConfig(plan=plan, persona=persona, days=DAYS, seed=42)
                rows, s = simulate(cfg)
                print(f"{plan:7} {persona:12} {s['total_vocab_exposure']:9} {s['total_new_words']:7} "
                      f"{s['learned_words']:8} {s['avg_score']:9} {s['max_due_backlog']:7} "
                      f"{s['max_query_backlog']:6} {s['avg_lateness_days']:8} {s['max_lateness_days']:8} "
                      f"{s['archived_lost_words']:8}")