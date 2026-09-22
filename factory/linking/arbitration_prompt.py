"""Sense-linking arbitration prompt builder (repatriated, byte-parity).

Pure string assembly ported from the frozen proof-linker v0.7 prompt
assembler (``W:\\hamzaban_data_factory\\proof-linker\\v1`` builder,
``build_prompt``). Stdlib only, zero dependencies, no I/O, no network,
no model calls.

Two locked templates, verified byte-identically against frozen batches:

- :attr:`ArbitrationPromptTemplate.BASE` — v0.7 assembly with no topics
  default and no substitution block (``judge_batch_run20.json``, 327 rows).
- :attr:`ArbitrationPromptTemplate.WITH_IN_PROMPT_SUBSTITUTION` — BASE
  plus exactly one guarded substitution block (``slice_unseen_50.json``,
  50 rows; substitution text cross-checked against
  ``judge_batch_guardedD.json``).

Topics-line, blank-line, and empty-list spellings are conditional, not
per-file variants: the ``topics:`` line appears iff ``kaikki`` carries a
non-empty ``topics`` list; empty synonyms / kaikki-examples render as
``(none)``; candidates without examples render as ``(no example)``.

Deliberately NOT here: verdict parsing, vote tallying, and human-queue
logic live in their own owners and are never redefined in this module.
"""

from enum import Enum


class ArbitrationPromptTemplate(Enum):
    """Locked prompt templates (exactly two; never extended ad hoc)."""

    BASE = "base"
    WITH_IN_PROMPT_SUBSTITUTION = "with_in_prompt_substitution"


LOCKED_INSTRUCTION = (
    "quote the evidence, pick <=1 or NONE, "
    "never generalize the headword level"
)

_SUBSTITUTION_HEADER = "--- ADDED (Guarded-D substitution test) ---"
_SUBSTITUTION_LINE = (
    "SUBSTITUTION TEST: winner gloss must replace kaikki gloss "
    "in the example sentence without shifting meaning, else NONE."
)


class SenseLinkingArbitrationPromptBuilder:
    """Pure v0.7 prompt assembler with a template switch for the guarded block."""

    def build(self, kaikki, candidates, template):
        """Assemble ``(prompt, index_map)`` byte-identically to v0.7.

        ``kaikki`` needs ``lemma``/``gloss``/``synonyms``/``examples``
        (``topics`` optional, read via ``.get``); each candidate needs
        ``sensekey``/``gloss``/``lemmas``/``examples``. ``template`` must
        be an :class:`ArbitrationPromptTemplate` member.
        """
        if not isinstance(template, ArbitrationPromptTemplate):
            raise ValueError(
                "template must be ArbitrationPromptTemplate, got %r" % (template,)
            )
        syns = (
            "; ".join(kaikki["synonyms"]) if kaikki["synonyms"] else "(none)"
        )
        egs = (
            " || ".join(kaikki["examples"][:4])
            if kaikki["examples"]
            else "(none)"
        )
        lines = [
            "You are judging a word-sense link for the headword "
            '"%s".' % kaikki["lemma"],
            "",
            "LEARNER-DICTIONARY ENTRY (kaikki):",
            "gloss: %s" % kaikki["gloss"],
            "synonyms: %s" % syns,
            "examples: %s" % egs,
        ]
        if kaikki.get("topics"):
            lines.append("topics: %s" % "; ".join(kaikki["topics"]))
        lines += ["", "CANDIDATE SENSES (answer with the NUMBER only):"]
        index_map = {}
        for n, c in enumerate(candidates, 1):
            index_map[str(n)] = c["sensekey"]
            lem = "; ".join(c["lemmas"])
            ceg = (
                " || ".join(c["examples"][:2])
                if c["examples"]
                else "(no example)"
            )
            lines.append(
                "%d. %s || words: %s || eg: %s" % (n, c["gloss"], lem, ceg)
            )
        lines += [
            "",
            "RULE: " + LOCKED_INSTRUCTION,
            "Respond with JSON ONLY, exactly these keys:",
            '{"verdict": "LINK" or "NONE", "winner_index": 1, 2, 3 or null, '
            '"kaikki_evidence": "<exact substring copied from the '
            'LEARNER-DICTIONARY ENTRY above>", '
            '"wordnet_evidence": "<exact substring copied from ONE numbered '
            'candidate above>"}',
            "If verdict is NONE, winner_index must be null and "
            'wordnet_evidence must be "".',
            "NEVER write a dotted code or parenthesized label; "
            "the winner is the NUMBER only.",
        ]
        if template is ArbitrationPromptTemplate.WITH_IN_PROMPT_SUBSTITUTION:
            lines += ["", _SUBSTITUTION_HEADER, _SUBSTITUTION_LINE]
        return "\n".join(lines), index_map
