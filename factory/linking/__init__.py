"""Offline build-time Kaikki -> WordNet sense-linker (own package identity).

Moved verbatim from ``factory/precard/linker.py`` (origin/main, M1-M3 move):
the scoring core stays in :mod:`factory.linking.linker` with zero logic
change — stdlib only, no I/O, no network, no model, no embeddings. The
shipped vendor table moved verbatim to ``factory/linking/table.tsv`` with
its pins in ``table.meta.json``.

Public surface (everything else is private-by-convention):

- :data:`LINK_METHOD_VOCAB` — frozen method vocabulary.
- :mod:`factory.linking.gates` — v0.8 gate-core for the enrich path
  (F3: LowRankZeroOverlapVeto / EvidenceGlossMismatchVeto /
  SplitVoteVeto enforcing, SignalQualityVeto log-only).
- :func:`validate_table_rows` — pure vendor-table guard (re-exported).
- :func:`build_link_index` / :func:`lookup_link` — thin pure TSV-row
  index helpers for the CLI (new in M1-M3; no scoring logic).
- :mod:`factory.linking.linker` — full scoring core (``arbitrate_link``,
  ``signal_sa/sb/sc/sd``, ``match_exact``, ...).

Deliberately NOT here (deferred, not invented): ``link`` / ``lookup`` /
``attach_fields`` / ``resolve_keys`` name pipeline-stage functions that do
not exist on the origin/main base — defining them would invent behavior
(logic-lock rule) and risks colliding with the parallel precard workers
(enrich/anchor/pipeline). Recorded as follow-up debt in the M1-M3 report.
Likewise ``linker_viewer.py`` stays at ``factory/precard/`` (parallel
feat/linker-viewer worker owns it) — see the M1-M3 report viewer-move
debt note.
"""

from factory.linking import gates, linker
from factory.linking.linker import LINK_METHOD_VOCAB, validate_table_rows

__all__ = [
    "LINK_METHOD_VOCAB",
    "gates",
    "linker",
    "validate_table_rows",
    "build_link_index",
    "lookup_link",
]


def build_link_index(rows):
    """Index TSV row dicts by ``kaikki_sense_id`` (pure, stdlib).

    Values are row *lists* — kids repeat in the vendor table (one kid can
    LINK two sensekeys, e.g. ``...:source_of_illumination1``). First-seen
    order is kept.
    """
    index = {}
    for row in rows:
        index.setdefault(row.get("kaikki_sense_id", "?"), []).append(row)
    return index


def lookup_link(index, kid):
    """Return the row list for ``kid`` (``[]`` when absent)."""
    return list(index.get(kid, []))
