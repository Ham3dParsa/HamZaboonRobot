"""Canonical card-type registry (REF2-T6 leaf).

Verbatim home of the card-type section split out of ``config/catalog.py``
(R1: replaces the services/db/users.py duplicate; users.py imports from the
catalog). ``config/catalog.py`` keeps a re-export shim so every existing
``from config.catalog import ...`` caller works unchanged.

Leaf-import law: stdlib only (no imports at all). The settings-keys leaf
consumes ``SETTINGS_CARD_TYPES`` for the ``{card_type}_mode`` /
``{card_type}_mode_gate`` pattern resolution — never the reverse.
"""

# Canonical card-type registry — single source for card types/modes/gates
# (R1: replaces services/db/users.py duplicate; users.py imports from here).
CARD_TYPES = ("first_exposure", "review")
CARD_MODES = ("staged", "immediate")
CARD_MODE_GATES = ("all", "premium")
DEFAULT_CARD_MODE = "staged"
DEFAULT_CARD_MODE_GATE = "premium"

# Back-compat alias used by settings_key() resolver; is the same tuple object
# so identity checks keep working. Single source remains CARD_TYPES.
SETTINGS_CARD_TYPES = CARD_TYPES
