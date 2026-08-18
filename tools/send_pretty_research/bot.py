"""Minimal bot stub for the send_pretty research sandbox.

`helpers._reset_telegram_cb()` sets health flags on the live `bot` module after
a successful send. The sandbox has no real bot module, so this stub provides the
two attributes it touches.
"""

_telegram_offline = False
_consecutive_health_failures = 0
