import pytest
from ai import normalize_phonetic

def test_normalize_phonetic_labeled():
    # Correct 3-line labeled input (any order, any case)
    raw = """
    IPA: /ɡruːv/
    Latin: groov
    Persian: گروو
    """
    assert normalize_phonetic(raw) == {"ipa": "/ɡruːv/", "latin": "groov", "persian": "گروو"}

    raw_mixed_order = """
    Persian: گروو
    IPA: /ɡruːv/
    Latin: groov
    """
    assert normalize_phonetic(raw_mixed_order) == {"ipa": "/ɡruːv/", "latin": "groov", "persian": "گروو"}

    raw_case_insensitive = """
    ipa: /ɡruːv/
    LATIN: groov
    peRsIaN: گروو
    """
    assert normalize_phonetic(raw_case_insensitive) == {"ipa": "/ɡruːv/", "latin": "groov", "persian": "گروو"}

def test_normalize_phonetic_legacy_pipe():
    # Legacy pipe-separated single-line input
    raw = "/ɡruːv/ | groov | گروو"
    assert normalize_phonetic(raw) == {"ipa": "/ɡruːv/", "latin": "groov", "persian": "گروو"}

def test_normalize_phonetic_malformed():
    # Malformed input
    assert normalize_phonetic("/ɡruːv/ | groov") is None # 2 parts
    assert normalize_phonetic("/ɡruːv/ | groov | گروو | extra") is None # 4 parts
    assert normalize_phonetic("just a string") is None # no separators
    assert normalize_phonetic("") is None # empty

def test_normalize_phonetic_leaks():
    # Ensure label text never leaks into stored values
    raw = """
    IPA: /ɡruːv/
    Latin: groov
    Persian: گروو
    """
    result = normalize_phonetic(raw)
    assert "IPA:" not in result["ipa"]
    assert "Latin:" not in result["latin"]
    assert "Persian:" not in result["persian"]
