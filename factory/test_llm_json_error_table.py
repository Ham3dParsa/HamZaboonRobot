"""C4a: hermetic tests for factory/llm_json.classify + single-owner guard.

Every table row is pinned: code rules, each per-provider snippet, each
generic snippet, and the fail-closed default. No network, no clock.
"""

import pathlib

import llm_json as LJ


def test_code_rules():
    assert LJ.classify(401, "", "zen") == LJ.ABORT
    assert LJ.classify(403, "", "google") == LJ.ABORT
    assert LJ.classify(429, "", "zen") == LJ.ROTATE
    assert LJ.classify(429, "", "unknown-provider") == LJ.ROTATE
    assert LJ.classify(500, "", "google") == LJ.RETRY_ONCE
    assert LJ.classify(503, "", "avalai") == LJ.RETRY_ONCE
    assert LJ.classify(599, "", "zen") == LJ.RETRY_ONCE
    assert LJ.classify(408, "", "openrouter") == LJ.RETRY_ONCE


def test_code_rules_beat_body():
    # A 429 with an auth-looking body is still a rotation, not an abort.
    assert LJ.classify(429, "invalid_api_key", "zen") == LJ.ROTATE


def test_provider_snippets_every_row():
    for provider, rows in LJ._PROVIDER_SNIPPETS.items():
        assert 1 <= len(rows) <= 3, provider
        for snippet, action in rows:
            got = LJ.classify(None, "xx %s yy" % snippet.upper(), provider)
            assert got == action, (provider, snippet)


def test_provider_scope_isolation():
    # Google location snippets do not fire for other providers.
    body = "User location is not supported for the API use."
    assert LJ.classify(400, body, "google") == LJ.COOLDOWN_SWITCH
    assert LJ.classify(400, body, "zen") == LJ.FAIL_CLOSED
    # Unknown providers only match generic rows.
    assert LJ.classify(None, "rate limit exceeded", "nope") == LJ.FAIL_CLOSED


def test_generic_snippets():
    assert LJ.classify(None, "invalid_api_key", "zen") == LJ.ABORT
    assert LJ.classify(400, "incorrect_api_key", "avalai") == LJ.ABORT
    assert LJ.classify(None, "Request timed out.", "google") == LJ.RETRY_ONCE
    assert LJ.classify(None, "APITimeoutError: Request timed out.", "x") == (
        LJ.RETRY_ONCE
    )
    assert LJ.classify(None, "deadline exceeded", "zen") == LJ.RETRY_ONCE


def test_fail_closed_default():
    assert LJ.classify(None, None, "zen") == LJ.FAIL_CLOSED
    assert LJ.classify(400, "some weird body", "zen") == LJ.FAIL_CLOSED
    assert LJ.classify(404, "not found", "google") == LJ.FAIL_CLOSED
    assert LJ.classify("bogus", "bogus", "bogus") == LJ.FAIL_CLOSED


def test_recorded_real_bodies():
    # Bodies copied from W:/hamzaban_data_factory/logs + canonical Google
    # 400 location payload (no network; pure classify).
    zen_429 = (
        '{"type":"error","error":{"type":"FreeUsageLimitError",'
        '"message":"Rate limit exceeded. Please try again later."}}'
    )
    assert LJ.classify(429, zen_429, "zen") == LJ.ROTATE
    assert LJ.classify(None, zen_429, "zen") == LJ.ROTATE
    groq_403 = '{"error":{"message":"Forbidden"}}'
    assert LJ.classify(403, groq_403, "zen") == LJ.ABORT
    google_timeout = "APITimeoutError: Request timed out."
    assert LJ.classify(None, google_timeout, "google") == LJ.RETRY_ONCE
    google_location = (
        '{"error":{"code":400,"message":"User location is not supported '
        'for the API use.","status":"FAILED_PRECONDITION"}}'
    )
    assert LJ.classify(400, google_location, "google") == LJ.COOLDOWN_SWITCH
    avalai_429 = '{"error":{"message":"Rate limit exceeded, slow down"}}'
    assert LJ.classify(429, avalai_429, "avalai") == LJ.ROTATE


def test_single_owner_guard():
    """classify + error-action taxonomy live ONLY in factory/llm_json.py.

    No rival `def classify` and no distinctive action literals
    (cooldown_switch/retry_once/fail_closed) in any other scanned module.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    scanned = (
        list((root / "factory").glob("*.py"))
        + list((root / "services").rglob("*.py"))
        + list((root / "handlers").glob("*.py"))
        + [root / "bot.py"]
    )
    assert scanned, "scan found no modules"
    offenders = []
    for path in scanned:
        if path.name in ("llm_json.py", "test_llm_json_error_table.py"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Error-taxonomy classify has (code, body, ...) signature; the
        # unrelated lemma classifier in sample_lemmas.py is out of scope.
        if "def classify(code" in text:
            offenders.append("%s: rival def classify(code" % path.name)
        # Action literals are production-taxonomy markers; other test
        # files (e.g. test_awl_coverage's test_load_awl_fail_closed)
        # may use similar words for unrelated behavior.
        if path.name.startswith("test_"):
            continue
        for lit in ("cooldown_switch", "retry_once", "fail_closed"):
            if lit in text:
                offenders.append("%s: rival literal %s" % (path.name, lit))
    assert offenders == [], offenders
