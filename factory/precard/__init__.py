"""Precard line, independent home (v1.4.5).

Self-contained like a factory tool: only Python stdlib plus this
package's own modules. No imports from factory/archive,
factory/pipeline, or factory/lexicon domain code (enforced by
tests/factory/test_precard_identity.py::test_no_archive_imports).
"""

__version__ = "1.4.5"


def run(argv=None, **kwargs):
    """Run the precard pipeline (lazy import keeps package import light)."""
    from factory.precard.pipeline import main
    return main(argv, **kwargs)
