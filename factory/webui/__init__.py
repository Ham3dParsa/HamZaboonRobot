"""Factory-data console WebUI (thin adapter over the precard engine).

Domain home of the operator console (server, template, labels store,
presets, control script). Serves the linking line among other factory
lines but lives at the factory domain root, not inside
:mod:`factory.linking`. Import the Flask app as::

    from factory.webui import server
"""

__all__ = ["server"]
