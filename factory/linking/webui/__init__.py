"""Linker-line local WebUI (thin adapter over the precard engine).

Lives next to the linker line it serves (:mod:`factory.linking`), not next
to the precard judge tool. Import the Flask app as::

    from factory.linking.webui import server
"""

__all__ = ["server"]
