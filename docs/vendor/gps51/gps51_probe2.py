import hashlib, json, sys, urllib.request, time, os
BASE = sys.argv[1]            # e.g. http://api.gps51.com/openapi
OUT  = sys.argv[2]
USER, PWD = os.environ["GPS51_USER"], os.environ["GPS51_PWD"]

def call(action, body, token=None, serverid=None):
    url = f"{BASE}?action={action}"
    if token: url += f"&token={token}&serverid={serverid}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode(); hdrs = dict(r.headers)
    try: d = json.loads(raw)
    except Exception: d = {"_raw": raw[:500]}
    d["_ms"] = int((time.time()-t0)*1000)
    json.dump(d, open(f"{OUT}/{action}.json", "w"), ensure_ascii=False, indent=1)
    return d, hdrs

def brief(tag, d, extra=""):
    print(f"[{tag}] status={d.get('status')} cause={d.get('cause')} {d['_ms']}ms {extra}")

# 1 login
login, h = call("login", {"type":"USER","from":"WEB","username":USER,
                 "password":hashlib.md5(PWD.encode()).hexdigest(),"browser":"Chrome/120"})
brief("login", login, f"token={login.get('token')} serverid={login.get('serverid')}")
print("   resp headers of interest:", {k:v for k,v in h.items() if any(s in k.lower() for s in ('limit','quota','remain','rate'))} or "none")
if login.get("status") != 0: sys.exit(1)
tok, sid = login["token"], login["serverid"]
time.sleep(1)

# 2 device list
ml, _ = call("querymonitorlist", {"username": USER}, tok, sid)
devs = [d for g in ml.get("groups", []) for d in g.get("devices", [])]
brief("querymonitorlist", ml, f"devices={len(devs)}")
time.sleep(1)

# 3 device types
dt, _ = call("querydevicetypeownerbyuser", {}, tok, sid)
brief("querydevicetypeownerbyuser", dt, f"types={len(dt.get('devicetypes', []))}")
for t in dt.get("devicetypes", []):
    if t.get("devicetypeid") in (1, 53):
        print(f"   type {t['devicetypeid']}: {t.get('typename')} / {t.get('remark')} / models={str(t.get('supportmodels'))[:60]}")
time.sleep(1)

# 4 lastposition full, then incremental
lp, _ = call("lastposition", {"username":USER,"deviceids":[],"lastquerypositiontime":0}, tok, sid)
brief("lastposition(t=0)", lp, f"records={len(lp.get('records', []))} lqpt={lp.get('lastquerypositiontime')}")
time.sleep(1)
lp2, _ = call("lastposition", {"username":USER,"deviceids":[],"lastquerypositiontime":lp.get("lastquerypositiontime")}, tok, sid)
brief("lastposition(incremental)", lp2, f"records={len(lp2.get('records', []))} lqpt={lp2.get('lastquerypositiontime')}")
time.sleep(1)

# 5 history track: most recently active device, the day of its last position
best = max([r for r in lp.get("records", []) if r.get("devicetime")], key=lambda r: r["devicetime"])
import datetime
day = datetime.datetime.fromtimestamp(best["devicetime"]/1000, datetime.timezone(datetime.timedelta(hours=8)))
b, e = day.strftime("%Y-%m-%d 00:00:00"), day.strftime("%Y-%m-%d 23:59:59")
tr, _ = call("querytracks", {"deviceid":best["deviceid"],"begintime":b,"endtime":e,"timezone":8}, tok, sid)
recs = tr.get("records", [])
brief("querytracks", tr, f"device={best['deviceid']} {b}~{e} records={len(recs)}")
if recs:
    print("   first record keys:", list(recs[0].keys()))
    print("   first record:", json.dumps(recs[0], ensure_ascii=False)[:700])
    print("   trackCount sum:", sum(r.get("trackCount", 0) or 0 for r in recs))
time.sleep(1)

# 6 trips same window
tp, _ = call("querytrips", {"deviceid":best["deviceid"],"begintime":b,"endtime":e,"timezone":8}, tok, sid)
brief("querytrips", tp, f"trips={len(tp.get('totaltrips', []))} totaldistance={tp.get('totaldistance')}m totaltriptime={tp.get('totaltriptime')}ms")
