-- gps_position.raw was double-encoded (JSON string); unwrap to a JSON object. Idempotent.
UPDATE gps_position SET raw = (raw #>> '{}')::jsonb WHERE jsonb_typeof(raw) = 'string';
