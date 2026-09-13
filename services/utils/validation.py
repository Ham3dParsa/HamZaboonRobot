"""Custom-word input validation seam (Rule B).

``validate_word_query`` is a pure function: given the raw text a learner typed
and their target language, it returns an error key describing why the query is
rejected, or ``None`` when the query may proceed to quota reserve / AI.

The acceptance rules are locked (see the custom-word-query plan, Rule B):

1. Normalize: trim; collapse internal ZWNJ/ZWSP/spaces to a single space.
2. Empty input is rejected.
3. Longer than ``_CUSTOM_WORD_MAX_CHARS`` (48) characters is rejected.
4. More than ``_CUSTOM_WORD_MAX_WORDS`` (4) whitespace-separated tokens is
   rejected.
5. Any character that is not a Unicode letter (``str.isalpha``) and not in the
   allowed punctuation set is rejected -- digits are therefore rejected.
6. There is no vowel heuristic: ``str.isalpha`` is language-agnostic, so a
   letter-only string is accepted regardless of whether it contains vowels.
7. A query with fewer than ``_MIN_LETTERS`` (2) letters is rejected, so
   punctuation-only input (e.g. ``"-"`` or ``"'"``) cannot reserve quota or
   trigger an AI call.

``language`` is retained for potential message tailoring but does NOT change
acceptance.
"""

from services.utils.helpers_pure import _normalize_custom_word_input

_CUSTOM_WORD_MAX_CHARS = 48
_CUSTOM_WORD_MAX_WORDS = 4
_MIN_LETTERS = 2
_ALLOWED_PUNCTUATION = frozenset({"-", "\u200c", "'", "’"})

ERR_EMPTY = "empty"
ERR_TOO_LONG = "too_long"
ERR_TOO_MANY_WORDS = "too_many_words"
ERR_INVALID_CHARS = "invalid_chars"
ERR_TOO_FEW_LETTERS = "too_few_letters"


def validate_word_query(text: str, language: str) -> str | None:
    """Return an error key if ``text`` is invalid, else ``None``.

    ``language`` does not change acceptance; it is retained so callers can
    tailor an error message per target language if needed.
    """
    normalized = _normalize_custom_word_input(text)
    if not normalized:
        return ERR_EMPTY

    if len(normalized) > _CUSTOM_WORD_MAX_CHARS:
        return ERR_TOO_LONG

    words = normalized.split()
    if len(words) > _CUSTOM_WORD_MAX_WORDS:
        return ERR_TOO_MANY_WORDS

    for word in words:
        for char in word:
            if char not in _ALLOWED_PUNCTUATION and not char.isalpha():
                return ERR_INVALID_CHARS

    if sum(1 for char in normalized if char.isalpha()) < _MIN_LETTERS:
        return ERR_TOO_FEW_LETTERS

    return None
