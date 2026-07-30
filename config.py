import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "pokemon_radar.db"

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "").strip()
REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _read_scan_interval() -> int:
    raw = os.getenv("SCAN_INTERVAL_SECONDS", "300").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 300
    return max(60, value)


SCAN_INTERVAL_SECONDS = _read_scan_interval()
