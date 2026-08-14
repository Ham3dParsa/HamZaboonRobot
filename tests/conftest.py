"""Shared pytest configuration.

Provides a valid ``AI_MASTER_KEY`` for every test so that any test writing an
API key goes through encryption (fail-closed) instead of raising
``MasterKeyRequiredError``. Tests that deliberately exercise no-master-key
behavior override ``config.AI_MASTER_KEY`` locally (e.g. via ``mock.patch`` in
``setUp``), which takes precedence for their own duration.
"""

import pytest

import config

TEST_MASTER_KEY = "sd4H8UUr5ONYISGXcx468OQwFaUxaktNGGTPs9TBESg="


@pytest.fixture(autouse=True)
def _ai_master_key():
    old = getattr(config, "AI_MASTER_KEY", "")
    config.AI_MASTER_KEY = TEST_MASTER_KEY
    try:
        yield
    finally:
        config.AI_MASTER_KEY = old
