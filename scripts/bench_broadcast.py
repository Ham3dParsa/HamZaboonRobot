"""Local wall-time benchmark for the RT-BN1 broadcast fan-out (NOT CI-gated).

Measures the sequential-vs-concurrent speedup by driving
``handlers.admin._handle_admin_broadcast`` with a mocked Telegram send that
sleeps a fixed per-send latency, over N users.

Run manually::

    python scripts/bench_broadcast.py [N] [latency_ms]

Reports wall time for sequential vs concurrent (BROADCAST_MAX_CONCURRENCY) fan-out.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import BROADCAST_MAX_CONCURRENCY, TELEGRAM_MAX_CONCURRENCY  # noqa: E402

# Model the global transport cap (_telegram_slots) that the real _send_with_retry
# acquires per send, so the reported speedup reflects production concurrency
# min(BROADCAST_MAX_CONCURRENCY, TELEGRAM_MAX_CONCURRENCY), not an unreal 20-way.
_transport = asyncio.Semaphore(TELEGRAM_MAX_CONCURRENCY)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
LATENCY_MS = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
LATENCY_S = LATENCY_MS / 1000.0


def _make_update():
    update = MagicMock()
    update.effective_user.id = 1
    update.effective_chat.id = 1
    update.callback_query = None
    update.message.text = "bench"
    update.message.reply_text = AsyncMock()
    return update


def _make_context():
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot = AsyncMock()
    return ctx


async def _slow_send(bot_ref, chat_id, text, *args, **kwargs):
    async with _transport:
        await asyncio.sleep(LATENCY_S)
    return MagicMock()


async def _run_concurrent():
    import bot

    update = _make_update()
    ctx = _make_context()
    ctx.user_data["awaiting"] = "admin_broadcast"
    users = [{"user_id": i} for i in range(2, N + 2)]
    with patch("services.db.all_active_users", return_value=users), patch(
        "handlers.admin._send_with_retry", new=AsyncMock(side_effect=_slow_send)
    ), patch("bot.is_owner", return_value=True), patch(
        "bot._maintenance_blocked", new=AsyncMock(return_value=False)
    ):
        await bot.text_router(update, ctx)
    return ctx


async def _run_sequential_reference():
    """Reference: the pre-RT-BN1 sequential loop over the same users (slow mock)."""
    update = _make_update()
    ctx = _make_context()
    users = [{"user_id": i} for i in range(2, N + 2)]
    with patch("services.db.all_active_users", return_value=users), patch(
        "services.utils.helpers._send_with_retry", new=AsyncMock(side_effect=_slow_send)
    ) as send:
        for u in users:
            try:
                await send(ctx.bot, u["user_id"], "hi")
            except Exception:
                pass
    return ctx


def main() -> None:
    import tempfile

    from services import db
    from services.db import schema as db_schema

    tmp = tempfile.TemporaryDirectory()
    db.DB_PATH = os.path.join(tmp.name, "bench.sqlite")
    db_schema.DB_PATH = db.DB_PATH
    db.init_db()
    db.create_user_if_needed(1, "bench")

    t0 = time.perf_counter()
    asyncio.run(_run_sequential_reference())
    seq = time.perf_counter() - t0

    t0 = time.perf_counter()
    asyncio.run(_run_concurrent())
    conc = time.perf_counter() - t0

    tmp.cleanup()

    effective = min(BROADCAST_MAX_CONCURRENCY, TELEGRAM_MAX_CONCURRENCY)
    print(f"N={N}  latency={LATENCY_MS}ms  broadcast_cap={BROADCAST_MAX_CONCURRENCY}  transport_cap={TELEGRAM_MAX_CONCURRENCY}")
    print(f"effective in-flight cap = min(broadcast, transport) = {effective}")
    print(f"sequential: {seq:.2f}s")
    print(f"concurrent: {conc:.2f}s")
    print(f"speedup:    {seq / max(conc, 1e-9):.2f}x (raise TELEGRAM_MAX_CONCURRENCY to widen)")


if __name__ == "__main__":
    main()