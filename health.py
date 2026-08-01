from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from config import (
    DATA_DIR,
    DB_PATH,
    DISCORD_WEBHOOK,
    LOG_RETENTION_DAYS,
    MAX_WORKERS,
    RETRY_ATTEMPTS,
    RETRY_DELAYS,
    SHOP_INTERVALS,
)
from shops.wog import SHOP_NAME as WOG_SHOP_NAME
from shops_config import PRESTASHOP_SHOPS, SHOPIFY_SHOPS, WOOCOMMERCE_SHOPS


@dataclass(frozen=True)
class HealthItem:
    name: str
    ok: bool
    details: str


def _check_database() -> HealthItem:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as connection:
            connection.execute("SELECT 1")
        return HealthItem("Datenbank", True, f"erreichbar: {DB_PATH}")
    except Exception as error:
        return HealthItem("Datenbank", False, f"{type(error).__name__}: {error}")


def _check_logs() -> HealthItem:
    logs_dir = Path("logs")
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=logs_dir,
            prefix=".health_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            test_path = Path(handle.name)
            handle.write("PokemonRadar health check\n")
        test_path.unlink(missing_ok=True)
        return HealthItem(
            "Logordner",
            True,
            f"beschreibbar: {logs_dir.resolve()} · Aufbewahrung {LOG_RETENTION_DAYS} Tage",
        )
    except Exception as error:
        return HealthItem("Logordner", False, f"{type(error).__name__}: {error}")


def _check_discord() -> HealthItem:
    if not DISCORD_WEBHOOK:
        return HealthItem(
            "Discord",
            False,
            "DISCORD_WEBHOOK ist nicht gesetzt. Es wurde keine Testnachricht gesendet.",
        )

    if not DISCORD_WEBHOOK.startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")):
        return HealthItem(
            "Discord",
            False,
            "Webhook ist gesetzt, sieht aber nicht wie eine Discord-Webhook-URL aus.",
        )

    return HealthItem(
        "Discord",
        True,
        "Webhook ist konfiguriert. Es wurde keine Testnachricht gesendet.",
    )


def _configured_shop_names() -> list[str]:
    names = [WOG_SHOP_NAME]
    for shops in (SHOPIFY_SHOPS, WOOCOMMERCE_SHOPS, PRESTASHOP_SHOPS):
        names.extend(str(shop["name"]) for shop in shops)
    return names


def _check_shops() -> HealthItem:
    names = _configured_shop_names()
    duplicates = sorted({name for name in names if names.count(name) > 1})
    missing_intervals = sorted(name for name in names if name not in SHOP_INTERVALS)
    invalid_intervals = sorted(
        name
        for name in names
        if name in SHOP_INTERVALS and int(SHOP_INTERVALS[name]) < 5
    )

    problems: list[str] = []
    if duplicates:
        problems.append(f"doppelte Namen: {', '.join(duplicates)}")
    if missing_intervals:
        problems.append(f"kein eigenes Intervall: {', '.join(missing_intervals)}")
    if invalid_intervals:
        problems.append(f"Intervall unter 5 Sekunden: {', '.join(invalid_intervals)}")

    if problems:
        return HealthItem("Shops", False, " · ".join(problems))

    return HealthItem(
        "Shops",
        True,
        f"{len(names)} Shops konfiguriert · alle Intervalle gültig",
    )


def _check_runtime_settings() -> HealthItem:
    problems: list[str] = []

    if MAX_WORKERS < 1:
        problems.append("MAX_WORKERS muss mindestens 1 sein")
    if RETRY_ATTEMPTS < 1:
        problems.append("RETRY_ATTEMPTS muss mindestens 1 sein")
    if len(RETRY_DELAYS) < max(0, RETRY_ATTEMPTS - 1):
        problems.append(
            "RETRY_DELAYS enthält weniger Wartezeiten als mögliche Wiederholungen"
        )
    if any(float(delay) < 0 for delay in RETRY_DELAYS):
        problems.append("RETRY_DELAYS darf keine negativen Werte enthalten")

    if problems:
        return HealthItem("Einstellungen", False, " · ".join(problems))

    return HealthItem(
        "Einstellungen",
        True,
        f"{MAX_WORKERS} Worker · {RETRY_ATTEMPTS} Versuche · Backoff {tuple(RETRY_DELAYS)}",
    )


def run_health_check() -> bool:
    """Prüft die lokale Einsatzbereitschaft ohne Shopscans oder Discord-Spam."""
    checks = [
        _check_database(),
        _check_logs(),
        _check_discord(),
        _check_shops(),
        _check_runtime_settings(),
    ]

    print("=" * 64)
    print("POKÉMON RADAR · HEALTH CHECK")
    print("=" * 64)

    for item in checks:
        symbol = "[OK]" if item.ok else "[FEHLER]"
        print(f"{symbol:<9} {item.name:<16} {item.details}")

    failed = [item for item in checks if not item.ok]
    print("-" * 64)
    if failed:
        print(f"[ERGEBNIS] {len(failed)} Prüfung(en) fehlgeschlagen.")
        return False

    print("[ERGEBNIS] Alles bereit.")
    return True
