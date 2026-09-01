# Tickets archive-group
| Ticket | Scope | Acceptance |
|---|---|---|
| T1 env+settings | config/__init__.py env parse ARCHIVE_CHAT_ID/TTS_CACHE_CHAT_ID (no logic), config/catalog SETTINGS_KEYS archive_chat_id, services/db/settings helpers | settings wins env, regex ^-100\d{5,}$ or ^-\d{5,}$ validated in archive.py, unit test fallback |
| T2 archive service | services/archive.py deep module + services/utils/helpers _send_document_with_retry | build_backup_caption comprehensive, resolved_archive_chat_id, validate, is_bot_admin, do_backup with retry/slot, no business logic in config |
| T3 admin UI submenu | config/keyboards/admin.py unified menu, services/routing admin:backup_restore | admin panel single button, submenu has 6 options, wiring test passes |
| T4 unified flow+job | handlers/admin.py do_backup/handle_restore_doc/auto_backup_job, bot.py scheduler 10800s/60s decoupled, prune 3d, without quote, no strict awaiting | backup to group or PV, restore PV+group, job runs if resolved or OWNER, integration test |

STATE: T1 pending, T2 pending, T3 pending, T4 pending
