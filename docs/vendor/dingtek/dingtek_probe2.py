import json, sys, time, urllib.request, urllib.parse, http.client, base64, os
BASE = "https://cloud.dingtek.com"; OUT = sys.argv[1]
tok = json.load(open(f"{OUT}/token.json"))["token"]
def req(method, path, body=None, params=None):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    h = {"Accept": "application/json", "Content-Type": "application/json", "X-Authorization": "Bearer " + tok}
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp: return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:300]
g = lambda ms: time.strftime('%Y-%m-%d %H:%M', time.gmtime(ms/1000))
devs = json.load(open(f"{OUT}/devices.json"))["data"]
summary = json.load(open(f"{OUT}/device_summary.json"))

# 1. remaining devices: attrs + latest
for d in devs[6:]:
    did, name = d["id"]["id"], d["name"]
    _, attrs = req("GET", f"/api/plugins/telemetry/DEVICE/{did}/values/attributes")
    _, latest = req("GET", f"/api/plugins/telemetry/DEVICE/{did}/values/timeseries")
    summary[did] = {"name": name, "type": d["type"], "attrs": attrs, "latest": latest}
    a = {x["key"]: x["value"] for x in attrs} if isinstance(attrs, list) else {}
    l = {k: v[0]["value"] for k, v in latest.items()} if isinstance(latest, dict) else {}
    lt = max((v[0]["ts"] for v in latest.values()), default=0) if isinstance(latest, dict) else 0
    print(f"{name}  fw={a.get('firmware')} upInt={a.get('uploadInterval')}h detInt={a.get('detectInterval')} active={a.get('active')} last={g(lt)} lat/lon={a.get('latitude')},{a.get('longitude')} | level={l.get('level')} temp={l.get('temperature')} volt={l.get('volt')} rsrp={l.get('rsrp')} FSM={l.get('FSM')} alarmLevel={l.get('alarmLevel')}")
    time.sleep(0.3)
json.dump(summary, open(f"{OUT}/device_summary.json", "w"), indent=1, ensure_ascii=False)

# 2. history on an active device: last 7 days, and oldest retained point
did = "79702a70-9ba1-11f1-898a-012e63463e84"; now = int(time.time()*1000)
st, hist = req("GET", f"/api/plugins/telemetry/DEVICE/{did}/values/timeseries",
               params={"keys": "level,temperature,volt,rsrp,frameCounter", "startTs": now-7*86400000, "endTs": now, "limit": 1000})
json.dump(hist, open(f"{OUT}/history_7d_586940.json", "w"), indent=1)
print(f"\n[history 7d] HTTP {st} keys={list(hist.keys()) if isinstance(hist, dict) else hist}")
if isinstance(hist, dict):
    for k, v in hist.items():
        ts = sorted(x["ts"] for x in v)
        gaps = [(ts[i+1]-ts[i])/60000 for i in range(len(ts)-1)]
        gaps.sort()
        print(f"  {k}: {len(v)} pts  {g(ts[0])} -> {g(ts[-1])}  gap(min) min={gaps[0]:.0f} median={gaps[len(gaps)//2]:.0f} max={gaps[-1]:.0f}" if len(ts) > 1 else f"  {k}: {len(v)} pts")
    lv = [x["value"] for x in hist.get("level", [])]; print("  level distinct values:", sorted(set(lv))[:15])
    fc = sorted(hist.get("frameCounter", []), key=lambda x: x["ts"]); 
    if len(fc) > 1: print("  frameCounter first/last:", fc[0]["value"], fc[-1]["value"], "(gap in counter vs pts received:", int(fc[-1]["value"]) - int(fc[0]["value"]) + 1, "vs", len(fc), ")")
st, oldest = req("GET", f"/api/plugins/telemetry/DEVICE/{did}/values/timeseries",
               params={"keys": "level", "startTs": now-120*86400000, "endTs": now, "limit": 1, "orderBy": "ASC"})
print(f"[oldest retained point, 120d window] HTTP {st}", {k: g(v[0]["ts"]) for k, v in oldest.items()} if isinstance(oldest, dict) and oldest else oldest)

# 3. alarms (standard ThingsBoard)
st, al = req("GET", f"/api/alarm/DEVICE/{did}", params={"pageSize": 10, "page": 0})
print(f"[alarms] HTTP {st}", (f"total={al.get('totalElements')} " + str([(x.get('type'), x.get('severity'), x.get('status'), g(x.get('createdTime',0))) for x in al.get('data', [])][:5])) if isinstance(al, dict) else str(al)[:200])

# 4. websocket upgrade handshake only (no library needed)
c = http.client.HTTPSConnection("cloud.dingtek.com", timeout=15)
c.request("GET", f"/api/ws/plugins/telemetry?token={tok}", headers={"Upgrade": "websocket", "Connection": "Upgrade",
          "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode(), "Sec-WebSocket-Version": "13"})
r = c.getresponse(); print(f"[websocket /api/ws/plugins/telemetry] HTTP {r.status} {r.reason}  upgrade={r.getheader('Upgrade')}")
