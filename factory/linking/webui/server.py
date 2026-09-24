"""Backward-compatible shim: the console now lives at :mod:`factory.webui`.

Pure re-export — no logic here. ``from factory.linking.webui import
server`` keeps returning the canonical module object, so current
command lines, test suites, and monkeypatches keep working unchanged.
"""

import sys as _sys

from factory.webui import server as _server

_sys.modules[__name__] = _server
