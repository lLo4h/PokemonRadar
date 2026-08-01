import os
from pathlib import Path

# ==========================================================
# Pfade und bestehende Grundeinstellungen
# ==========================================================

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
    """Alte globale Intervalloption für Kompatibilität beibehalten."""
    raw = os.getenv("SCAN_INTERVAL_SECONDS", "300").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 300
    return max(60, value)


SCAN_INTERVAL_SECONDS = _read_scan_interval()


# ==========================================================
# Scheduler
# ==========================================================

MAX_WORKERS = 3
DEFAULT_SHOP_INTERVAL_SECONDS = 180

SHOP_INTERVALS = {
    # Nicht-Shopify: etwas häufiger, weil diese Shops aktuell keine 429-Welle zeigen.
    "World of Games": 60,
    "Toytans": 180,
    "Pokelu": 180,
    "MetaGames": 180,
    "The Uncommon Shop": 180,
    "Cardcollectors": 240,

    # Shopify: bewusst schonender. Mehrere dieser Shops blockierten die
    # gemeinsame Server-IP bei Intervallen von 45 bis 90 Sekunden.
    "Pikaversum": 300,
    "Pokealp": 300,
    "MaRo Games Shop": 300,
    "Ryu Land": 300,
    "JapHunter": 300,
    "Zadoys": 300,
    "Sparkleaf": 300,
    "Boosterbox": 300,
}


# ==========================================================
# Retry und Backoff
# Diese Werte werden im nächsten Schritt von retry.py genutzt.
# ==========================================================

RETRY_ATTEMPTS = 3
RETRY_DELAYS = (5, 15)


# ==========================================================
# Dashboard und Logging
# ==========================================================

DASHBOARD_REFRESH_SECONDS = 1.0
LOG_RETENTION_DAYS = 30
