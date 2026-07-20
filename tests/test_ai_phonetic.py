import pytest
from services.ai.ai import normalize_phonetic

def test_normalize_phonetic_labeled():
    # Correct 2-line labeled input (any order, any case)
    raw = """
    IPA: /ɡruːv/
    Persian: گروو
    """
    assert normalize_phonetic(raw) == {"ipa": "/ɡruːv/", "persian": "گروو"}

    raw_mixed_order = """
    Persian: گروو
    IPA: /ɡruːv/
    """
    assert normalize_phonetic(raw_mixed_order) == {"ipa": "/ɡruːv/", "persian": "گروو"}

    raw_case_insensitive = """
    ipa: /ɡruːv/
    peRsIaN: گروو
    """
    assert normalize_phonetic(raw_case_insensitive) == {"ipa": "/ɡruːv/", "persian": "گروو"}

def test_normalize_phonetic_legacy_pipe():
    # Legacy pipe-separated single-line input (2 parts: IPA|Persian)
    raw = "/ɡruːv/ | گروو"
    assert normalize_phonetic(raw) == {"ipa": "/ɡruːv/", "persian": "گروو"}

def test_normalize_phonetic_malformed():
    # Malformed input
    assert normalize_phonetic("/ɡruːv/") is None # 1 part
    assert normalize_phonetic("/ɡruːv/ | groov | گروو") is None # 3 parts
    assert normalize_phonetic("/ɡruːv/ | groov | گروو | extra") is None # 4 parts
    assert normalize_phonetic("just a string") is None # no separators
    assert normalize_phonetic("") is None # empty

def test_normalize_phonetic_leaks():
    # Ensure label text never leaks into stored values
    raw = """
    IPA: /ɡruːv/
    Persian: گروو
    """
    result = normalize_phonetic(raw)
    assert "IPA:" not in result["ipa"]
    assert "Persian:" not in result["persian"]
