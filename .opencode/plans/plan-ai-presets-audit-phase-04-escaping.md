# Phase 04 — Escaping: centralized HTML escape + show_settings (R4, R7, R10)

## Blocking edges
- None.

## Scope
- `services/utils/formatting.py` — add `html_escape(text)` (centralized choke point).
- `handlers/admin_ai.py` — apply `html_escape` to every dynamic value interpolated
  into `ParseMode.HTML` messages (~9 render sites: `_show_ai_settings`,
  `_show_ai_preset_view`, `_edit_ai_preset_field`, `_show_wizard_field`,
  `_show_wizard_summary`, `_show_linear_presets`, `_show_grouped_presets`,
  `_handle_group_view`, `_show_group_manager`, `_handle_group_manager_rename`).
- `handlers/admin.py` — `show_settings` branch: switch `ParseMode.MARKDOWN_V2` →
  `ParseMode.HTML` (R4) and always mask the API key (`***` for ≤12-char) (R7).

## Tests
- Focused: values containing `&`, `<`, `>` render without raising; `html_escape`
  escapes the reserved HTML characters.
- Integration: dispatch a callback that renders a preset with a `base_url` containing
  `&`, assert no `BadRequest` and the escaped text is present in the mocked reply.
- Unit: `show_settings` renders a ≤12-char key as `***`.

## Gates
- R4 (show_settings → HTML), R7 (mask short API keys), R10 (centralized HTML escaping).

## Wiring rows
| Dependency type | Items | Disposition |
|---|---|---|
| Formatting | `services/utils/formatting.py` | update (add html_escape) |
| Handlers | `handlers/admin_ai.py` (~9 sites), `handlers/admin.py` show_settings | update |
| Tests | focused escaping test, integration render test, show_settings mask test | add |

## Acceptance criteria
- `html_escape` handles `& < > " '`; admin panel renders special-char values without
  parse crashes; short API keys always masked.
