STATE: LOCKED

# Plan — TTS Cache Channel (feat/tts-cache-channel)

Contract LOCKED per user message. Two groups separate; this branch only TTS_CACHE_CHAT_ID.

## Tickets
- T1 env+settings
- T2 pure helpers filename/caption
- T3 tts_cache.db + LRU
- T4 channel + admin UI + bot integration

## Decisions
- settings key tts_cache_chat_id TEXT, resolution settings>env>None
- filename time_lang_text 60-char slug +4 hash
- caption exact spoken text truncated 1024 with …
- tts_cache.db separate, LRU 3000 in front of FS, services/tts.py sole owner of normalization
- New module services/tts_cache.py owns DB+channel
- Admin under backup submenu, keys admin:backup:set_tts_cache etc
