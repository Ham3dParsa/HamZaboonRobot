"""Shared save-preview confirmation summary builder (presets phase 01).

Domain-agnostic formatting helper with the same standing as
``services/utils/formatting.py``: prepared-strings-in, spans-out.

Contract:
- Callers pass display-prepared strings. Secrets are pre-masked by the
  caller (via ``mask_key``); this helper NEVER sees plaintext secrets and
  NEVER truncates values.
- Persian digits for the dirty-count line reuse the canonical
  ``to_persian_digits`` from ``services/utils/formatting.py`` (no duplicate).
- Field order is the caller's job (``WIZARD_FIELDS`` order); input order is
  preserved as-is.
- No Telegram imports outside ``send_pretty`` spans; no DB access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from services.send_pretty import Message, bold, code, heading, plain, table
from services.utils.formatting import to_persian_digits

EMPTY_CONFIRM_TEXT = "تغییری برای ذخیره وجود ندارد"


@dataclass
class FieldDiff:
    """One changed field, display-prepared strings in (no masking/truncation inside)."""

    label: str
    old: str
    new: str


def render_diffs(diffs: Sequence[FieldDiff], *, numbered: bool = False) -> list:
    """Render per-field bold-label + vertical قبلی/جدید table lines (D2 seam).

    One block shape, two callers: ``build_confirm_message`` (numbered confirm
    dialog) and ``handlers/admin_ai._edit_ai_preset`` (unnumbered edit menu).
    Returns one ``add_line``-ready span tuple per line (two lines per diff);
    callers splat each entry into ``msg.add_line(*line)``. ``numbered=True``
    prefixes labels with Persian digits (``to_persian_digits``), reproducing
    the former caller-side ``f"{n}. {label}"`` rewrite byte-identically.
    """
    lines: list = []
    for i, diff in enumerate(diffs):
        label = f"{to_persian_digits(i + 1)}. {diff.label}" if numbered else diff.label
        lines.append((bold(label),))
        lines.append(
            (
                table(
                    ("وضعیت", "مقدار"),
                    ("قبلی", code(diff.old)),
                    ("جدید", code(diff.new)),
                ),
            )
        )
    return lines


def build_confirm_message(
    title: str,
    subject: str,
    diffs: Sequence[FieldDiff],
    *,
    notes: Sequence[str] = (),
    numbered: bool = False,
) -> Message:
    """Build a save-preview confirmation ``Message`` via ``send_pretty`` spans only.

    Layout: ``heading(3, title+subject)`` + per-field ``bold(label)`` with a
    vertical 2-row Rich table ``(وضعیت, مقدار) / (قبلی, old) / (جدید, new)``
    (values as ``code()`` cells: LTR-safe, separate rows, no inline arrows) +
    a Persian-digit dirty-count line + notes as plain lines. The per-field
    block renders through the shared :func:`render_diffs` seam (D2);
    ``numbered=True`` prefixes Persian-digit labels for the confirm dialog.

    Empty ``diffs`` returns a Message holding the ``EMPTY_CONFIRM_TEXT`` line.
    """
    msg = Message()
    combined = f"{title} {subject}".strip() if subject else str(title)
    msg.add_line(heading(3, combined))
    if not diffs:
        msg.add_line(plain(EMPTY_CONFIRM_TEXT))
        return msg
    for line in render_diffs(diffs, numbered=numbered):
        msg.add_line(*line)
    msg.add_line(plain(f"{to_persian_digits(len(diffs))} مورد تغییر کرده است"))
    for note in notes:
        msg.add_line(plain(note))
    return msg
