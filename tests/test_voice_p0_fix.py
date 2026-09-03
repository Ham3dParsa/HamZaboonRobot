"""P0 voice fix: channel upload must not pass filename to send_voice."""
import pathlib

def test_channel_upload_no_filename_kwarg():
    # Phase-01 TTS deep: channel upload lives in services/tts_service.py
    # (bot.py only delegates). Target the service seam.
    text = pathlib.Path("services/tts_service.py").read_text(encoding="utf-8")
    # The channel upload call is _send_voice(bot, channel_id, voice_bytes, caption=caption)
    # Indent-agnostic: voice upload must not regress to passing filename=
    assert "voice_bytes," in text and "caption=caption" in text
    # Ensure filename= not in that specific call (no regression)
    # Find the block after channel upload — tolerate indent changes
    import re

    m = re.search(r"msg = await _send_voice\(\s*bot,\s*channel_id,", text)
    assert m is not None, "channel upload call not found"
    snippet = text[m.start() : m.start() + 300]
    assert "filename" not in snippet

def test_send_voice_retry_has_inputfile_parity():
    text = pathlib.Path("services/utils/helpers.py").read_text(encoding="utf-8")
    # Phase-03 unified seam: byte capture lives in _capture_media_bytes and
    # RetryAfter rebuilds via InputFile(io.BytesIO(raw_bytes), ...) (R2).
    # Behavior (identical-bytes resend) is covered by
    # test_send_media_with_retry_rebuilds_inputfile_bytes_on_retry_after.
    assert "_capture_media_bytes" in text
    assert "InputFile(io.BytesIO(raw_bytes)" in text

def test_tts_has_timeout():
    text = pathlib.Path("services/tts.py").read_text(encoding="utf-8")
    assert "wait_for" in text
    assert "_TTS_TIMEOUT_S" in text
