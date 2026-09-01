"""P0 voice fix: channel upload must not pass filename to send_voice."""
import pathlib

def test_channel_upload_no_filename_kwarg():
    text = pathlib.Path("bot.py").read_text(encoding="utf-8")
    # The channel upload call is _send_voice_with_retry(context.bot, chat_id, voice_bytes, caption=caption)
    assert "voice_bytes,\n                        caption=caption,\n                    )" in text
    # Ensure filename= not in that specific call (no regression)
    # Find the block after 'if chat_id:' channel upload
    idx = text.index("msg = await _send_voice_with_retry(\n                        context.bot,\n                        chat_id,")
    snippet = text[idx: idx + 300]
    assert "filename" not in snippet

def test_send_voice_retry_has_inputfile_parity():
    text = pathlib.Path("services/utils/helpers.py").read_text(encoding="utf-8")
    assert "_voice_is_inputfile" in text
    assert "InputFile(io.BytesIO(_voice_bytes)" in text

def test_tts_has_timeout():
    text = pathlib.Path("services/tts.py").read_text(encoding="utf-8")
    assert "wait_for" in text
    assert "_TTS_TIMEOUT_S" in text
