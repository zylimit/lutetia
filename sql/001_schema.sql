-- Lutetia schema. Raw values are stored untouched; unit conversion lives in the views at the bottom.

CREATE TABLE IF NOT EXISTS device (
    source          text NOT NULL,            -- 'gps51' | 'dingtek'
    device_id       text NOT NULL,            -- gps51: deviceid; dingtek: ThingsBoard UUID (name/label hold the IMEI)
    name            text,
    device_type     text,
    expected_online boolean,                  -- gps51: isfree==1; dingtek: attribute active==true
    extra           jsonb,                    -- the vendor's device record as received
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, device_id)
);

CREATE TABLE IF NOT EXISTS gps_position (
    device_id       text NOT NULL,
    update_time     timestamptz NOT NULL,     -- gps51 updatetime: dedupe key and ordering key
    device_time     timestamptz,              -- GPS fix time reported by the device
    arrived_time    timestamptz,              -- time the vendor server received it
    lat             double precision,
    lon             double precision,
    speed_raw       double precision,         -- vendor unit is metres per HOUR despite the docs saying metres
    course          integer,
    altitude        double precision,
    total_distance  double precision,         -- metres
    status          bigint,
    alarm           bigint,
    strstatus       text,
    stralarm        text,
    moving          smallint,
    temp1           integer,                  -- 1/100 degC, sentinel values already mapped to NULL
    temp2           integer,
    temp3           integer,
    temp4           integer,
    origin          text NOT NULL,            -- 'push' | 'poll' | 'tracks'
    raw             jsonb,
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (device_id, update_time)
);
CREATE INDEX IF NOT EXISTS gps_position_update_time_idx ON gps_position (update_time DESC);

CREATE TABLE IF NOT EXISTS sensor_telemetry (
    device_id       text NOT NULL,            -- ThingsBoard UUID
    key             text NOT NULL,
    ts              timestamptz NOT NULL,
    value_num       double precision,
    value_str       text,                     -- non-numeric values (FSM state, booleans)
    origin          text NOT NULL,            -- 'ws' | 'rest'
    ingested_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (device_id, key, ts)
);
CREATE INDEX IF NOT EXISTS sensor_telemetry_ts_idx ON sensor_telemetry (ts DESC);

CREATE TABLE IF NOT EXISTS sensor_attribute (
    device_id       text NOT NULL,
    key             text NOT NULL,
    value           text,
    last_update_ts  timestamptz,
    PRIMARY KEY (device_id, key)
);

CREATE TABLE IF NOT EXISTS api_call (
    id          bigserial PRIMARY KEY,
    source      text NOT NULL,
    action      text NOT NULL,
    ok          boolean NOT NULL,
    called_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS api_call_source_time_idx ON api_call (source, called_at DESC);

CREATE OR REPLACE VIEW gps_position_v AS
SELECT p.*,
       p.speed_raw / 1000.0 AS speed_kmh,
       p.total_distance / 1000.0 AS total_distance_km,
       p.temp1 / 100.0 AS temp1_c,
       p.temp2 / 100.0 AS temp2_c
FROM gps_position p;

CREATE OR REPLACE VIEW sensor_telemetry_v AS
SELECT t.*,
       CASE t.key
           WHEN 'volt' THEN t.value_num / 100.0    -- assumed x0.01 V, unconfirmed by vendor
           WHEN 'rsrp' THEN t.value_num / 10.0     -- assumed x0.1 dBm, unconfirmed by vendor
           ELSE t.value_num
       END AS value_si
FROM sensor_telemetry t;
