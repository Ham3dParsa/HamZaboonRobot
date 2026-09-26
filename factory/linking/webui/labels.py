"""Backward-compatible shim: the label store now lives at :mod:`factory.webui`.

Pure re-export — no logic here. ``from factory.linking.webui import
labels`` keeps returning the canonical module object.
"""

import sys as _sys

from factory.webui import labels as _labels

_sys.modules[__name__] = _labels
