import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines, existing environment wins."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Config:
    database_url: str
    gps51_user: str
    gps51_pwd: str
    gps51_api_base: str
    gps51_daily_budget: int
    gps51_poll_interval: int
    gps51_min_call_gap: float
    push_silence_min: int
    push_host: str
    push_port: int
    push_path: str
    dingtek_user: str
    dingtek_pwd: str
    dingtek_base: str
    dingtek_reconcile_hour_utc: int
    state_dir: Path
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        e = os.environ.get
        cfg = cls(
            database_url=e("DATABASE_URL", ""),
            gps51_user=e("GPS51_USER", ""),
            gps51_pwd=e("GPS51_PWD", ""),
            gps51_api_base=e("GPS51_API_BASE", "http://api.gps51.com/openapi"),
            gps51_daily_budget=int(e("GPS51_DAILY_BUDGET", "1400")),
            gps51_poll_interval=int(e("GPS51_POLL_INTERVAL_SEC", "60")),
            gps51_min_call_gap=float(e("GPS51_MIN_CALL_GAP_SEC", "6")),
            push_silence_min=int(e("PUSH_SILENCE_MIN", "15")),
            push_host=e("PUSH_LISTEN_HOST", "0.0.0.0"),
            push_port=int(e("PUSH_LISTEN_PORT", "8080")),
            push_path=e("PUSH_PATH", "/gps51/push"),
            dingtek_user=e("DINGTEK_USER", ""),
            dingtek_pwd=e("DINGTEK_PWD", ""),
            dingtek_base=e("DINGTEK_BASE", "https://cloud.dingtek.com").rstrip("/"),
            dingtek_reconcile_hour_utc=int(e("DINGTEK_RECONCILE_HOUR_UTC", "3")),
            state_dir=Path(e("STATE_DIR", "./state")),
            log_level=e("LOG_LEVEL", "INFO"),
        )
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        return cfg

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise SystemExit("missing configuration: " + ", ".join(n.upper() for n in missing))
