"""Admin stats domain module (Finding #7 seam).

Expand step: this module re-exports the standalone stats symbols currently
imported by the admin monolith so that task 7.5 (Batch A migration) can move
the ``admin:stats`` handler logic here without changing call sites. Behavior is
unchanged; nothing routes to this module yet.
"""

from config.keyboards import stats_back_keyboard, stats_menu_keyboard

__all__ = ["stats_back_keyboard", "stats_menu_keyboard"]
