"""Tests for normalize_phonetic function in services/ai/ai.py."""

import unittest
from services.ai.ai import normalize_phonetic


class NormalizePhoneticTests(unittest.TestCase):
    """Tests for normalize_phonetic covering labeled, legacy, malformed, and leak cases."""

    def test_normalize_phonetic_labeled(self):
        raw = """
        IPA: /ɡruːv/
        Persian: گروو
        """
        self.assertEqual(normalize_phonetic(raw), {"ipa": "/ɡruːv/", "persian": "گروو"})

        raw_mixed_order = """
        Persian: گروو
        IPA: /ɡruːv/
        """
        self.assertEqual(normalize_phonetic(raw_mixed_order), {"ipa": "/ɡruːv/", "persian": "گروو"})

        raw_case_insensitive = """
        ipa: /ɡruːv/
        peRsIaN: گروو
        """
        self.assertEqual(normalize_phonetic(raw_case_insensitive), {"ipa": "/ɡruːv/", "persian": "گروو"})

    def test_normalize_phonetic_legacy_pipe(self):
        raw = "/ɡruːv/ | گروو"
        self.assertEqual(normalize_phonetic(raw), {"ipa": "/ɡruːv/", "persian": "گروو"})

    def test_normalize_phonetic_malformed(self):
        self.assertIsNone(normalize_phonetic("/ɡruːv/"))
        self.assertIsNone(normalize_phonetic("/ɡruːv/ | groov | گروو"))
        self.assertIsNone(normalize_phonetic("/ɡruːv/ | groov | گروو | extra"))
        self.assertIsNone(normalize_phonetic("just a string"))
        self.assertIsNone(normalize_phonetic(""))

    def test_normalize_phonetic_leaks(self):
        raw = """
        IPA: /ɡruːv/
        Persian: گروو
        """
        result = normalize_phonetic(raw)
        self.assertNotIn("IPA:", result["ipa"])
        self.assertNotIn("Persian:", result["persian"])
