"""Dashboard anomaly rules: pure functions over already-fetched rows (no DB, no I/O)."""
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from ..db import max_age_hours

LEVEL_RED = "red"
LEVEL_YELLOW = "yellow"
# alarmLevel is deliberately absent: constantly 1 on all 12 real manholes since 2026-08-17, meaning unknown (open Spec question for the vendor)
ALARM_KEYS = ("alarmFall", "alarmBattery")
PUSH_SILENT_LIMIT_SEC = 900
# DFX-Spec dim 2 / Task 6.2: backup runs daily at 02:30; 26 h = one day plus 2.5 h slack before it counts as overdue
BACKUP_MAX_AGE_H = 26
# DFX-Spec candidate (Decisions 2026-11-09): the collector writes a heartbeat every 30 s, 90 s = three missed beats. One place only.
HEARTBEAT_STALE_SEC = 90
KIND_ORDER = ("collector", "stale", "alarm", "push", "backup", "low_volt", "quota", "login")
VOLT_RED_MARGIN = 0.2
QUOTA_YELLOW_RATIO = 0.8
KIND_LABELS = {"collector": "采集", "stale": "失联", "low_volt": "低电压", "alarm": "报警", "push": "推送通道", "backup": "备份", "quota": "配额", "login": "登录次数"}


def _item(level: str, kind: str, detail: str, device_id: Any = None, name: Any = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"level": level, "kind": kind, "detail": detail}
    if device_id is not None:
        out["device_id"] = device_id
    if name is not None:
        out["name"] = name
    return out


def _stale(now: datetime, devices: Iterable[Dict[str, Any]], default_h: float) -> List[Dict[str, Any]]:
    out = []
    for d in devices:
        if not d["expected_online"]:
            continue
        last = d["last_ts"]
        if last is None:
            out.append(_item(LEVEL_RED, "stale", "从未入库", d["device_id"], d["name"]))
        elif now - last > timedelta(hours=max_age_hours(default_h, d["upload_interval_h"])):
            hours = (now - last).total_seconds() / 3600
            out.append(_item(LEVEL_RED, "stale", "最后入库 %.1f 小时前" % hours, d["device_id"], d["name"]))
    return out


def _low_volt(rows: Iterable[Dict[str, Any]], low_volt: float) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        v = r["value_si"]
        if r["key"] == "volt" and v is not None and v < low_volt:
            level = LEVEL_RED if v < low_volt - VOLT_RED_MARGIN else LEVEL_YELLOW
            out.append(_item(level, "low_volt", "电压 %s V" % round(float(v), 3), r["device_id"], r["name"]))
    return out


def _alarms(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_dev: Dict[Any, Dict[str, Any]] = {}
    for r in rows:
        if r["key"] in ALARM_KEYS and r["value_num"]:
            d = by_dev.setdefault(r["device_id"], {"name": r["name"], "parts": []})
            d["parts"].append((ALARM_KEYS.index(r["key"]), "%s=%s" % (r["key"], int(r["value_num"]) if float(r["value_num"]).is_integer() else r["value_num"])))
    return [_item(LEVEL_RED, "alarm", ", ".join(p for _, p in sorted(d["parts"])), dev, d["name"]) for dev, d in by_dev.items()]


def _calls(calls: Iterable[Dict[str, Any]], budget: int) -> List[Dict[str, Any]]:
    out = []
    gps = sum(c["n"] for c in calls if c["source"] == "gps51")
    if budget > 0 and gps >= budget * QUOTA_YELLOW_RATIO:
        level = LEVEL_RED if gps >= budget else LEVEL_YELLOW
        out.append(_item(level, "quota", "GPS51 24 小时 %d / %d" % (gps, budget)))
    logins = sum(c["n"] for c in calls if c["source"] == "dingtek" and c["action"] == "login")
    if logins > 1:
        out.append(_item(LEVEL_RED, "login", "Dingtek 24 小时登录 %d 次" % logins))
    return out


def _backup(now: datetime, summary: Dict[str, Any], max_age_h: float = BACKUP_MAX_AGE_H) -> List[Dict[str, Any]]:
    out = []
    last = summary["last_ok_at"]
    if last is None:
        out.append(_item(LEVEL_RED, "backup", "从未成功备份"))
    elif now - last > timedelta(hours=max_age_h):
        out.append(_item(LEVEL_RED, "backup", "距上次成功备份 %.1f 小时（阈值 %d 小时）" % ((now - last).total_seconds() / 3600, max_age_h)))
    if summary["latest_ok"] is False:
        out.append(_item(LEVEL_RED, "backup", "最近一次备份失败：%s" % (summary["latest_error"] or "无错误信息")))
    return out


def _collector(collector: Dict[str, Any], stale_sec: int = HEARTBEAT_STALE_SEC) -> List[Dict[str, Any]]:
    if collector["updated_at"] is None:
        return [_item(LEVEL_RED, "collector", "采集从未上报心跳")]
    age = collector["age_sec"]  # database clock, see Database.collector_status
    if age > stale_sec:
        return [_item(LEVEL_RED, "collector", "采集心跳已 %d 分 %d 秒未更新（阈值 %d 秒）" % (age // 60, age % 60, stale_sec))]
    return []


def compute(now: datetime, devices: List[Dict[str, Any]], latest_sensor: List[Dict[str, Any]],
            latest_alarms: List[Dict[str, Any]], receiver: Optional[Dict[str, Any]], calls_24h: List[Dict[str, Any]],
            budget: int, low_volt: float, max_age_hours_default: float = 3.0,
            push_silent_limit_sec: int = PUSH_SILENT_LIMIT_SEC,
            backup: Optional[Dict[str, Any]] = None, collector: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    items = _stale(now, devices, max_age_hours_default) + _low_volt(latest_sensor, low_volt) + _alarms(latest_alarms)
    if receiver is not None and receiver["silent_sec"] > push_silent_limit_sec:
        items.append(_item(LEVEL_RED, "push", "推送位置静默 %d 分钟（阈值 %d 分钟）" % (receiver["silent_sec"] // 60, push_silent_limit_sec // 60)))
    items += _calls(list(calls_24h), budget)
    if backup is not None:
        items += _backup(now, backup)
    if collector is not None:  # None = caller has no heartbeat to judge (pure-rule tests); the web layer always passes one
        items += _collector(collector)
    items.sort(key=lambda i: (i["level"] != LEVEL_RED, KIND_ORDER.index(i["kind"]), str(i.get("name", ""))))
    return items


def summarize(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "全部正常"
    red = sum(1 for i in items if i["level"] == LEVEL_RED)
    return "%d 项异常（红 %d，黄 %d）" % (len(items), red, len(items) - red)
