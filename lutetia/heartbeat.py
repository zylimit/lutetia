"""Collector heartbeat: every HEARTBEAT_SEC upsert one row into collector_status so the web container can read it (ADR-4)."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import __version__
from .db import Database

log = logging.getLogger(__name__)

HEARTBEAT_SEC = 30
PROCESS_STARTED_AT = datetime.now(timezone.utc)  # collector process start (wall clock), shown next to the heartbeat
DETAIL_COUNTERS = ("received", "stored", "rejected", "unrecognised", "alarms", "failed")


def receiver_details(receiver: Any) -> dict:
    """Counters as they are at write time; the web side adds the heartbeat age to the two silent_* values."""
    out = {k: getattr(receiver, k) for k in DETAIL_COUNTERS}
    out["queued"] = receiver.queue.qsize()
    out["silent_sec"] = receiver.silent_for()
    out["message_silent_sec"] = receiver.message_silent_for()
    out["collector_started_at"] = PROCESS_STARTED_AT.isoformat()
    return out


async def write_once(db: Database, receiver: Any, poller: Any, dws: Optional[Any]) -> bool:
    """One heartbeat. A failed write is logged and reported False, never raised: collecting must go on."""
    try:
        await db.write_heartbeat(__version__, receiver.last_position_wall,
                                 None if dws is None else bool(dws.connected),  # None = dingtek ws not enabled (shown as 未启用)
                                 bool(poller.polling), receiver_details(receiver))
        return True
    except Exception as e:  # noqa: BLE001 - heartbeat must never take collection down; the web side shows a stale heartbeat
        log.warning("heartbeat write failed: %s: %s", type(e).__name__, e)
        return False


async def heartbeat_loop(db: Database, receiver: Any, poller: Any, get_dws: Callable[[], Optional[Any]]) -> None:
    while True:
        await write_once(db, receiver, poller, get_dws())
        await asyncio.sleep(HEARTBEAT_SEC)
