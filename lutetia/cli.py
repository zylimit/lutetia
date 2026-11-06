import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp

from . import log as logsetup
from .config import Config
from .db import Database
from .sources.dingtek import DingtekClient, DingtekSync
from .sources.gps51 import Gps51Client, Gps51Poller

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _date_ms(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


async def cmd_migrate(cfg: Config, args) -> int:
    db = Database(cfg.database_url)
    await db.connect()
    try:
        for name in await db.migrate(SQL_DIR):
            print("applied", name)
    finally:
        await db.close()
    return 0


async def cmd_run(cfg: Config, args) -> int:
    from .service import run
    await run(cfg)
    return 0


async def cmd_backfill(cfg: Config, args) -> int:
    cfg.require("dingtek_user", "dingtek_pwd")
    db = Database(cfg.database_url)
    await db.connect()
    try:
        async with aiohttp.ClientSession() as session:
            sync = DingtekSync(DingtekClient(cfg, db, session), db)
            end = _date_ms(args.to) + 86400000 - 1 if args.to else None
            n = await sync.backfill(_date_ms(getattr(args, "from")), end)
            print("inserted rows:", n)
    finally:
        await db.close()
    return 0


async def cmd_status(cfg: Config, args) -> int:
    db = Database(cfg.database_url)
    await db.connect()
    try:
        rows = await db.device_status()
        calls = await db.call_summary(24)
    finally:
        await db.close()
    now = datetime.now(timezone.utc)
    stale = []
    print("%-8s %-38s %-16s %-7s %-7s %-17s %s" % ("source", "device_id", "name", "type", "online", "last_data_utc", "max_age_h"))
    for r in rows:
        last = r["last_ts"]
        # a sensor that uploads every N hours is only stale after 2N hours
        max_age = max(args.max_age_hours, 2 * (r["upload_interval_h"] or 0))
        age_ok = last is not None and now - last <= timedelta(hours=max_age)
        if r["expected_online"] and not age_ok:
            stale.append(r)
        print("%-8s %-38s %-16s %-7s %-7s %-17s %-4g%s" % (
            r["source"], r["device_id"], r["name"] or "", r["device_type"] or "",
            {True: "yes", False: "no"}.get(r["expected_online"], "?"),
            last.strftime("%Y-%m-%d %H:%M") if last else "-", max_age,
            "  <-- STALE" if r in stale else ""))
    print("\napi calls last 24h:")
    for c in calls:
        print("  %-8s %-14s %d" % (c["source"], c["action"], c["n"]))
    if stale:
        print("\n%d expected-online device(s) without recent data" % len(stale))
        return 1
    return 0


async def cmd_gps51(cfg: Config, args) -> int:
    cfg.require("gps51_user", "gps51_pwd")
    db = Database(cfg.database_url)
    await db.connect()
    try:
        async with aiohttp.ClientSession() as session:
            poller = Gps51Poller(Gps51Client(cfg, db, session), db)
            if args.gps51_cmd == "sync-devices":
                for d in await poller.sync_devices():
                    print(d.device_id, d.name, d.device_type, "online" if d.expected_online else "-")
            elif args.gps51_cmd == "poll-once":
                print("new positions:", await poller.poll_once())
            elif args.gps51_cmd == "tracks":
                print("new positions:", await poller.fetch_tracks(args.device, args.begin, args.end))
    finally:
        await db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lutetia", description="Paris IoT collector (GPS51 + Dingtek)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply sql/*.sql").set_defaults(fn=cmd_migrate)
    sub.add_parser("run", help="run the collector service").set_defaults(fn=cmd_run)
    b = sub.add_parser("backfill", help="pull history over REST (idempotent)")
    b.add_argument("source", choices=["dingtek"])
    b.add_argument("--from", required=True, help="YYYY-MM-DD (UTC)")
    b.add_argument("--to", help="YYYY-MM-DD inclusive (UTC), default now")
    b.set_defaults(fn=cmd_backfill)
    s = sub.add_parser("status", help="last data per device; exit 1 if an online device is stale")
    s.add_argument("--max-age-hours", type=int, default=3)
    s.set_defaults(fn=cmd_status)
    g = sub.add_parser("gps51", help="manual GPS51 operations")
    gs = g.add_subparsers(dest="gps51_cmd", required=True)
    gs.add_parser("sync-devices")
    gs.add_parser("poll-once")
    t = gs.add_parser("tracks", help="one querytracks call (5 per device per day, manual only)")
    t.add_argument("--device", required=True)
    t.add_argument("--begin", required=True, help="'YYYY-MM-DD HH:MM:SS' in UTC+8")
    t.add_argument("--end", required=True)
    g.set_defaults(fn=cmd_gps51)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    cfg = Config.from_env()
    logsetup.setup(cfg.log_level)
    cfg.require("database_url")
    sys.exit(asyncio.run(args.fn(cfg, args)))


if __name__ == "__main__":
    main()
