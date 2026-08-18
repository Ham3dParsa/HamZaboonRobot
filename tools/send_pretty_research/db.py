"""Minimal db stub for the send_pretty research sandbox.

`helpers.py` only calls `get_setting` (user-activity toggle) and
`set_user_blocked` (on a Forbidden send). Both are no-ops here since the
sandbox never touches the real database.
"""


def get_setting(key: str, default: str = "") -> str:
    return default


def set_user_blocked(chat_id: int) -> None:
    return None
