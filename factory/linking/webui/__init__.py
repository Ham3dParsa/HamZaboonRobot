"""Backward-compatible shim: the console now lives at :mod:`factory.webui`.

The old ``from factory.linking.webui import server`` path keeps working
(and keeps pointing at the canonical module); new code should import
from :mod:`factory.webui` instead.
"""

__all__ = ["server"]
