"""Admin AI facade (REF2-T4).

Thin re-export shim over the split leaves — ``admin_ai_wizard.py`` (wizard
helpers), ``admin_ai_list.py`` (list/view), ``admin_ai_create.py`` (create),
``admin_ai_fallback.py`` (fallback/usage) and ``admin_ai_custom.py``
(custom-test + central router). Every existing
``from handlers.admin_ai import ...`` caller works unchanged; the canonical
definitions live in the leaves (old defs removed same PR).

Patch-contract compat: ``asyncio``, ``db``, ``ai``, ``preset_fields`` and
``prompts`` are intentionally exposed here — tests patch
``handlers.admin_ai.db.get_preset``, ``handlers.admin_ai.ai.test_connection``,
``handlers.admin_ai.asyncio.to_thread`` and
``handlers.admin_ai.prompts.daily_batch_system_prompt``. The leaves import
those modules directly (``from services import db`` etc.) but share the same
module objects, so attribute patches (``db.get_preset``) are visible. Whole-
object patches (``patch(\"handlers.admin_ai.db\")``) are propagated to the
leaves via the custom module ``__setattr__`` below. New code MUST import from
the leaves directly.
"""

import asyncio  # noqa: F401 — compat: tests patch handlers.admin_ai.asyncio.to_thread
import logging
import sys
import types

from services import db  # noqa: F401 — compat: tests patch handlers.admin_ai.db
from services.ai import ai  # noqa: F401 — compat: tests patch handlers.admin_ai.ai
from services.ai import preset_fields, prompts  # noqa: F401 — compat: tests patch prompts/preset_fields
from services.send_pretty import say  # noqa: F401 — compat: tests patch handlers.admin_ai.say
from services.utils.callback_notifications import notify_callback  # noqa: F401 — compat: tests patch handlers.admin_ai.notify_callback
from services.utils.helpers import _clear_awaiting_prompt, _rotate_awaiting_msg  # noqa: F401 — compat: tests patch helpers via admin_ai

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Leaf re-exports (verbatim move, order: wizard → list → create → fallback → custom)
# ---------------------------------------------------------------------------

from handlers.admin_ai_wizard import (
    FIELD_LABELS,
    MAX_GROUP_LABEL_LEN,
    TOTAL_WIZARD_FIELDS,
    WIZARD_FIELDS,
    WIZARD_GROUP_HEADERS,
    _FIELD_HELP,
    _preset_edit_diffs,
    _validate_wizard_value,
)
from handlers.admin_ai_list import (
    _activate_ai_preset,
    _confirm_delete_no,
    _confirm_delete_yes,
    _confirm_save_preset,
    _delete_ai_preset,
    _detach_ai_preset_group,
    _detect_key_groups,
    _discard_all_preset_changes,
    _duplicate_ai_preset,
    _edit_ai_preset,
    _edit_ai_preset_field,
    _handle_ai_preset_field_input,
    _handle_full_edit_back,
    _handle_full_edit_cancel,
    _handle_full_edit_input,
    _handle_full_edit_next,
    _handle_full_edit_pick_group,
    _handle_full_edit_save,
    _handle_full_edit_skip,
    _handle_group_batch_key,
    _handle_group_manager_clear,
    _handle_group_manager_rename,
    _handle_group_set_label,
    _handle_group_view,
    _key_hash,
    _preset_brief_spans,
    _render_preset_brief,
    _resolve_label_ref,
    _resolve_preset_ref,
    _save_ai_preset,
    _show_ai_preset_view,
    _show_ai_presets,
    _show_ai_settings,
    _show_group_manager,
    _show_grouped_presets,
    _show_linear_presets,
    _show_wizard_field,
    _show_wizard_summary,
    _start_full_edit_wizard,
    _toggle_preset_view_mode,
)
from handlers.admin_ai_create import (
    _add_ai_preset,
    _handle_ai_preset_new_name,
    _handle_create_priority_choice,
    _handle_create_priority_manual,
    _handle_create_status_choice,
    _handle_create_test,
    _handle_create_toggle_enable,
    _normal_chain_count,
    _preset_ref,
    _show_create_priority,
    _show_create_status,
    _finish_create,
    _test_ai_connection,
    _test_ai_preset,
)
from handlers.admin_ai_fallback import (
    USAGE_PAGE_SIZE,
    _handle_ai_fallback,
    _handle_ai_text_input,
    _handle_fallback_rank,
    _render_usage_page,
    _show_ai_fallback,
    _show_fallback_chain,
    _show_fallback_preset_picker,
    _show_fallback_usage_details,
    _show_help_fallback_chain,
    _show_help_presets,
    _show_usage_page,
    _usage_page_keyboard,
    _usage_rows,
)
from handlers.admin_ai_custom import (
    _custom_test_step_goal,
    _custom_test_step_lang,
    _custom_test_step_level,
    _custom_test_step_preset,
    _custom_test_step_target,
    _handle_custom_test_wizard,
    _run_custom_test,
    _start_custom_test_wizard,
    handle_ai_callback,
)

__all__ = [
    "MAX_GROUP_LABEL_LEN",
    "_FIELD_HELP",
    "FIELD_LABELS",
    "WIZARD_FIELDS",
    "WIZARD_GROUP_HEADERS",
    "TOTAL_WIZARD_FIELDS",
    "USAGE_PAGE_SIZE",
    "_preset_edit_diffs",
    "_validate_wizard_value",
    "_show_ai_settings",
    "_show_ai_presets",
    "_key_hash",
    "_resolve_preset_ref",
    "_resolve_label_ref",
    "_detect_key_groups",
    "_preset_brief_spans",
    "_render_preset_brief",
    "_show_linear_presets",
    "_show_grouped_presets",
    "_show_ai_preset_view",
    "_activate_ai_preset",
    "_edit_ai_preset",
    "_edit_ai_preset_field",
    "_handle_ai_preset_field_input",
    "_start_full_edit_wizard",
    "_show_wizard_field",
    "_handle_full_edit_input",
    "_handle_full_edit_next",
    "_handle_full_edit_pick_group",
    "_handle_full_edit_skip",
    "_handle_full_edit_back",
    "_handle_full_edit_cancel",
    "_show_wizard_summary",
    "_handle_full_edit_save",
    "_toggle_preset_view_mode",
    "_handle_group_view",
    "_handle_group_batch_key",
    "_handle_group_set_label",
    "_show_group_manager",
    "_handle_group_manager_rename",
    "_handle_group_manager_clear",
    "_confirm_save_preset",
    "_discard_all_preset_changes",
    "_detach_ai_preset_group",
    "_save_ai_preset",
    "_delete_ai_preset",
    "_confirm_delete_yes",
    "_confirm_delete_no",
    "_duplicate_ai_preset",
    "_add_ai_preset",
    "_handle_ai_preset_new_name",
    "_show_create_priority",
    "_show_create_status",
    "_finish_create",
    "_normal_chain_count",
    "_handle_create_test",
    "_handle_create_toggle_enable",
    "_test_ai_preset",
    "_handle_create_priority_choice",
    "_handle_create_priority_manual",
    "_handle_create_status_choice",
    "_preset_ref",
    "_test_ai_connection",
    "_show_ai_fallback",
    "_handle_ai_fallback",
    "_show_fallback_preset_picker",
    "_show_help_presets",
    "_show_help_fallback_chain",
    "_show_fallback_chain",
    "_usage_rows",
    "_usage_page_keyboard",
    "_render_usage_page",
    "_show_fallback_usage_details",
    "_show_usage_page",
    "_handle_fallback_rank",
    "_handle_ai_text_input",
    "_start_custom_test_wizard",
    "_custom_test_step_lang",
    "_custom_test_step_goal",
    "_custom_test_step_level",
    "_custom_test_step_target",
    "_run_custom_test",
    "_handle_custom_test_wizard",
    "_custom_test_step_preset",
    "handle_ai_callback",
    # patch-contract modules
    "asyncio",
    "db",
    "ai",
    "preset_fields",
    "prompts",
    "say",
    "notify_callback",
    "_clear_awaiting_prompt",
    "_rotate_awaiting_msg",
]

# ---------------------------------------------------------------------------
# Whole-object patch propagation (B5/Kilo): ``patch("handlers.admin_ai.db")``
# replaces the ``db`` attribute on this facade with a MagicMock. The leaves
# imported ``from services import db`` directly, so they would otherwise keep
# the original ``services.db`` module. This custom module type propagates a
# whole-object replacement to every leaf that has already been imported —
# and ONLY there. Owner modules (``services.db`` itself,
# ``services.send_pretty``, ``callback_notifications``, ``helpers``) and
# ``sys.modules`` are NEVER rewritten, so a facade patch cannot leak
# process-wide to unrelated consumers. Attribute patches
# (``db.get_preset``) need no propagation — they mutate the shared module
# object itself.
#
# Whole-object allowlist (only these five names propagate; anything else,
# e.g. a future ``patch("handlers.admin_ai.ai")``, stays facade-local
# because leaves bind those objects directly and attribute patches already
# share them): ``db``, ``say``, ``notify_callback``,
# ``_rotate_awaiting_msg``, ``_clear_awaiting_prompt``.
# ---------------------------------------------------------------------------

class _AdminAiModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name in ("db", "say", "notify_callback", "_rotate_awaiting_msg", "_clear_awaiting_prompt"):
            # Propagate whole-object mock to already-imported leaves ONLY —
            # never to owner modules or sys.modules (no process-wide leak).
            for leaf in (
                "handlers.admin_ai_wizard",
                "handlers.admin_ai_list",
                "handlers.admin_ai_create",
                "handlers.admin_ai_fallback",
                "handlers.admin_ai_custom",
            ):
                mod = sys.modules.get(leaf)
                if mod is not None:
                    mod.__dict__[name] = value


# Switch the already-loaded facade module to the custom type so future
# ``patch("handlers.admin_ai.db")`` assignments trigger propagation.
def _switch_module_class():
    """Install the patch-propagating module type (best-effort, warned)."""
    try:
        sys.modules[__name__].__class__ = _AdminAiModule
    except TypeError as exc:
        logger.warning("admin_ai patch-propagation shim disabled: %s", exc)


_switch_module_class()
