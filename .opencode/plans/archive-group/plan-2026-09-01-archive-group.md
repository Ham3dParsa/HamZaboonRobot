STATE: LOCKED
# Plan: Archive Group (feat/archive-group) — 2026-09-01
Contract LOCKED per user prompt. Env fallbacks ARCHIVE_CHAT_ID/TTS_CACHE_CHAT_ID (this branch only ARCHIVE). Settings key archive_chat_id (TEXT), resolution: settings wins > env > None. Deep module services/archive.py owns caption/send/validation/is_bot_admin. config/__init__.py only parses env. Unified menu admin:backup_restore submenu, keyboards in config/keyboards/admin.py, routing via services/routing. Unified flow do_backup via asyncio.to_thread + build_backup_caption + _send_document_with_retry to resolved id or owner PV. handle_restore_doc accepts PV+group without strict awaiting. auto_backup_job every 10800s first 60s, decoupled from OWNER_ID, shared lock, prune 3 days. _send_document_with_retry in helpers. No duplicate registry, codebase-design compliant.

Tickets: T1 env+settings, T2 archive service, T3 admin UI submenu, T4 unified flow+job
