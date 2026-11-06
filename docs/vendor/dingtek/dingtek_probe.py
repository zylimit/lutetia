import json, sys, time, urllib.request, urllib.parse, os
BASE = "https://cloud.dingtek.com"
OUT = sys.argv[1]
USER, PWD = os.environ["DINGTEK_USER"], os.environ["DINGTEK_PWD"]

def req(method, path, body=None, token=None, params=None):
    url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token: h["X-Authorization"] = "Bearer " + token
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode()[:300])

# login once, cache token
tokfile = f"{OUT}/token.json"
if os.path.exists(tokfile) and time.time() - os.path.getmtime(tokfile) < 3600:
    tok = json.load(open(tokfile))["token"]; print("[login] cached token")
else:
    st, d = req("POST", "/api/auth/login", {"username": USER, "password": PWD})
    print("[login] HTTP", st, (list(d.keys()) if isinstance(d, dict) else d))
    if st != 200: sys.exit(1)
    json.dump(d, open(tokfile, "w")); tok = d["token"]

# who am I
st, me = req("GET", "/api/auth/user", token=tok)
print("[auth/user] HTTP", st, {k: me.get(k) for k in ("authority", "tenantId", "customerId", "email")} if isinstance(me, dict) else me)

# devices
st, dv = req("GET", "/api/user/devices", token=tok, params={"pageSize": 100, "page": 0, "sortProperty": "name"})
json.dump(dv, open(f"{OUT}/devices.json", "w"), indent=1, ensure_ascii=False)
devs = dv.get("data", []) if isinstance(dv, dict) else []
print(f"[devices] HTTP {st} total={dv.get('totalElements') if isinstance(dv, dict) else '?'} hasNext={dv.get('hasNext') if isinstance(dv,dict) else '?'} got={len(devs)}")
from collections import Counter
print("  types:", Counter(d.get("type") for d in devs).most_common())
for d in devs[:15]:
    print(f"  {d['id']['id']}  name={d.get('name')}  type={d.get('type')}  label={d.get('label')}  created={time.strftime('%Y-%m-%d', time.gmtime(d.get('createdTime',0)/1000))}")

# per-device: ts keys, attributes, latest values (cap at 6 devices)
summary = {}
for d in devs[:6]:
    did = d["id"]["id"]; name = d.get("name")
    st1, keys = req("GET", f"/api/plugins/telemetry/DEVICE/{did}/keys/timeseries", token=tok)
    st2, attrs = req("GET", f"/api/plugins/telemetry/DEVICE/{did}/values/attributes", token=tok)
    st3, latest = req("GET", f"/api/plugins/telemetry/DEVICE/{did}/values/timeseries", token=tok)
    summary[did] = {"name": name, "type": d.get("type"), "keys": keys, "attrs": attrs, "latest": latest}
    print(f"\n== {name} ({d.get('type')}) {did}")
    print(f"  ts keys [{st1}]: {keys if isinstance(keys, list) else str(keys)[:200]}")
    if isinstance(attrs, list):
        print(f"  attributes [{st2}] ({len(attrs)}):")
        for a in attrs[:25]:
            print(f"    {a.get('key')} = {str(a.get('value'))[:80]}  @{time.strftime('%Y-%m-%d %H:%M', time.gmtime(a.get('lastUpdateTs',0)/1000))}")
    else: print(f"  attributes [{st2}]: {str(attrs)[:200]}")
    if isinstance(latest, dict):
        print(f"  latest telemetry [{st3}] ({len(latest)} keys):")
        for k, v in list(latest.items())[:30]:
            v0 = v[0] if isinstance(v, list) and v else v
            print(f"    {k} = {str(v0.get('value'))[:60]}  @{time.strftime('%Y-%m-%d %H:%M', time.gmtime(v0.get('ts',0)/1000))}")
    else: print(f"  latest [{st3}]: {str(latest)[:200]}")
    time.sleep(0.5)
json.dump(summary, open(f"{OUT}/device_summary.json", "w"), indent=1, ensure_ascii=False)
