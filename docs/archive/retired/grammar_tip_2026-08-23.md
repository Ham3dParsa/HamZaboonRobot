# Retired Grammar Tip Handler — 2026-08-23

Exported from `handlers/user.py:send_grammar_tip` per #24 O-grammar-standalone retire decision (owner: "export it's logic for now").

Production bot disables this feature; logic kept here for future work.

## Original handler (full body)

```python
async def send_grammar_tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    log_user_activity(update, action="grammar_tip", outcome="requested")
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await _send_with_retry(context.bot, update.effective_chat.id, "اول باید /start رو بزنی.")
        return

    limit = daily_word_query_limit_for_plan(row["plan"] or "free")
    usage_before_text = _grammar_tip_usage_text(row)
    if not db.reserve_grammar_tip(
        user_id,
        limit,
        bypass_limits=OWNER_BYPASS_LIMITS and is_owner(user_id),
    ):
        await _send_with_retry(...)
        return
    # ... full AI pipeline via prompts.grammar_tip_system_prompt + ai.ask_json
    # ... db.add_grammar_tip, format_grammar_tip, touch_streak, etc.
```

Helpers retired along with handler:
- `_grammar_tip_usage(row)` / `_grammar_tip_usage_text(row)` — quota display
- `services/db/__init__.py:add_grammar_tip`, `recent_grammar_tip_titles` — kept in DB but not called in prod
- `services/ai/prompts.py:grammar_tip_system_prompt` — kept for future
- Table `grammar_tips` + columns `grammar_tips_asked_today/date` — retained (no migration), idle in prod

## To re-enable
1. Restore handler body from this file to `handlers/user.py`
2. Re-add quota line in `show_status` (💡 نکته گرامری)
3. Add button `IBTN_GRAMMAR_TIP` to `main_menu` or `settings_inline_keyboard` with `callback_data="grammar:tip"`
4. Wire `callback_router` `elif data == "grammar:tip": await send_grammar_tip(...)`

No AI cost impact while retired.
