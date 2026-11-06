# Lutetia

巴黎项目 IoT 数据采集服务：把 GPS51（途强物联 GPS）和 Dingtek Cloud（DC414 井盖传感器）的数据持续落到自己的 PostgreSQL。需求与设计约束见 `Product-Spec.md`，两家接口的调研结论和真实样例见 `docs/vendor/`。

## 本地开发

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # 填 GPS51_* / DINGTEK_* 凭据
docker run -d --name lutetia-pg -e POSTGRES_USER=lutetia -e POSTGRES_PASSWORD=lutetia -e POSTGRES_DB=lutetia -p 127.0.0.1:15433:5432 postgres:16-alpine
lutetia migrate
pytest
```

## 命令

| 命令 | 作用 |
|---|---|
| `lutetia migrate` | 建表（幂等） |
| `lutetia backfill dingtek --from 2026-08-21` | REST 全量回补，可重复执行，第二次新增为 0 |
| `lutetia run` | 常驻：GPS51 推送接收端 + 静默 15 分钟后轮询；Dingtek WebSocket 订阅 + 每日回补 |
| `lutetia status` | 每台设备最后入库时间；在线设备超过 3 小时无数据则退出码 1 |
| `lutetia gps51 sync-devices` / `poll-once` | 手工同步设备、单次轮询 |
| `lutetia gps51 tracks --device ID --begin '2026-10-06 00:00:00' --end '2026-10-06 23:59:59'` | 单次历史轨迹，每设备每天限 5 次，只能手工 |

## 部署（固定公网 IP 的云主机）

1. 把主机公网 IP 加进 GPS51 后台「白名单」，openapi 才放行。
2. `docker compose up -d --build`，推送接收端监听 8080，建议前面加 HTTPS 反代。
3. GPS51 后台「转发平台列表」新建 `Http Json` 转发，地址填 `http://<IP>:8080/gps51/push`（或反代后的 https 地址）。
4. `docker compose exec collector lutetia backfill dingtek --from 2026-08-21` 做首次回补。
5. 用 `GET /health` 和 `lutetia status` 做监控。

## 数据表

`device`（两源混放，`source` 区分）、`gps_position`（宽表，去重键 deviceid+updatetime）、`sensor_telemetry`（窄表，去重键 uuid+key+ts）、`sensor_attribute`、`api_call`（调用计数）。原始值不换算，单位换算在 `gps_position_v` / `sensor_telemetry_v` 视图里。
