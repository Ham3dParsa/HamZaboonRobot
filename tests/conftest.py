"""Shared pytest configuration.

Provides a valid ``AI_MASTER_KEY`` for every test so that any test writing an
API key goes through encryption (fail-closed) instead of raising
``MasterKeyRequiredError``. Tests that deliberately exercise no-master-key
behavior override ``config.AI_MASTER_KEY`` locally (e.g. via ``mock.patch`` in
``setUp``), which takes precedence for their own duration.

Pins ``bot._telegram_offline`` to ``False`` for every test and restores the
previous value afterwards, neutralising the cross-file global leak at its
source: ``test_reliability.py`` leaves the flag ``True`` after a health-job
test, which makes ``bot.text_router``/``callback_router`` early-return offline
for later tests on the same xdist worker.
"""

import pytest

import bot
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


@pytest.fixture(autouse=True)
def _telegram_offline_pinned():
    old = getattr(bot, "_telegram_offline", False)
    bot._telegram_offline = False
    try:
        yield
    finally:
        bot._telegram_offline = old
