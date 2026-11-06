# risk: high
"""DingtekSync.backfill: 一台设备失败不拖垮整批(F10)。stub client / db，无网络。"""
import lutetia.sources.dingtek as dk


class FakeClient:
    def __init__(self):
        self.ts_requested = []

    async def list_devices(self):
        return [{"id": {"id": "dev-%d" % i}, "name": "d%d" % i} for i in range(3)]

    async def ts_keys(self, uuid):
        if uuid == "dev-0":
            raise dk.DingtekError("GET keys: HTTP 500")
        return ["volt"]

    async def attributes(self, uuid):
        return []

    async def timeseries(self, uuid, keys, a, b):
        self.ts_requested.append(uuid)
        return {"volt": [{"ts": a + 1, "value": 1}]}


class StubDB:
    async def record_api_call(self, *a):
        pass

    async def upsert_devices(self, d):
        pass

    async def upsert_attributes(self, a):
        pass

    async def set_expected_online(self, *a):
        pass

    async def insert_telemetry(self, rows):
        return len(rows)


async def test_f10_one_device_failure_does_not_abort_batch():
    # risk: high  (每日 reconcile 走这条路径；一台挂掉后面全不拉 = 缺口)
    fc = FakeClient()
    sync = dk.DingtekSync(fc, StubDB())
    err, n = None, None
    try:
        n = await sync.backfill(0, 86400000 - 1)
    except Exception as e:  # noqa: BLE001
        err = e
    assert err is None, "第 1 台失败不应让 backfill 抛出；抛了 %r" % err
    assert fc.ts_requested == ["dev-1", "dev-2"], "第 2、3 台仍应被拉取；实际 %s" % fc.ts_requested
    assert isinstance(n, int) and n == 2
    failures = getattr(sync, "last_failures", None)
    assert failures is not None and len(failures) == 1 and failures[0][0] == "dev-0", "last_failures=%s" % (failures,)


async def test_f10_last_failures_reset_on_each_backfill():
    # risk: medium
    fc = FakeClient()
    sync = dk.DingtekSync(fc, StubDB())
    sync.last_failures = [("old", "old", "stale")]
    try:
        await sync.backfill(0, 86400000 - 1)
    except Exception:  # noqa: BLE001
        pass
    assert [f[0] for f in getattr(sync, "last_failures", [])] == ["dev-0"], "每次 backfill 开头应清空旧失败记录"
