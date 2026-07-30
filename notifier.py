from typing import Any

import requests

from config import DISCORD_WEBHOOK, REQUEST_TIMEOUT
from database import ProductChange


class WebhookError(RuntimeError):
    pass


def _require_webhook() -> str:
    if not DISCORD_WEBHOOK:
        raise WebhookError(
            "DISCORD_WEBHOOK wurde nicht gefunden. Öffne ein neues CMD-Fenster "
            "und prüfe mit: echo %DISCORD_WEBHOOK%"
        )
    return DISCORD_WEBHOOK


def _post(payload: dict[str, Any]) -> None:
    response = requests.post(
        _require_webhook(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 204:
        raise WebhookError(
            f"Discord antwortete mit Status {response.status_code}: "
            f"{response.text[:200]}"
        )


def send_test_message() -> None:
    _post(
        {
            "username": "Pokémon Radar",
            "content": "✅ **Pokémon Radar V2 ist verbunden.**\nDer neue Webhook funktioniert.",
            "allowed_mentions": {"parse": []},
        }
    )


def send_product_change(change: ProductChange) -> None:
    labels = {
        "new_product": ("🆕 Neues Produkt", 0x3498DB),
        "new_preorder": ("📦 Neue Vorbestellung", 0x9B59B6),
        "restock": ("🔥 Wieder verfügbar", 0x2ECC71),
        "price_change": ("💰 Preisänderung", 0xF1C40F),
    }
    title, color = labels.get(change.kind, ("Produktänderung", 0x95A5A6))
    product = change.product

    fields: list[dict[str, Any]] = [
        {"name": "Shop", "value": product.shop, "inline": True},
        {"name": "Status", "value": product.status, "inline": True},
    ]
    if product.price:
        fields.append({"name": "Preis", "value": product.price, "inline": True})
    if change.kind == "price_change" and change.old_price:
        fields.append(
            {"name": "Alter Preis", "value": change.old_price, "inline": True}
        )

    embed: dict[str, Any] = {
        "title": title,
        "description": f"[{product.title}]({product.url})",
        "color": color,
        "fields": fields,
    }
    if product.image_url:
        embed["thumbnail"] = {"url": product.image_url}

    _post(
        {
            "username": "Pokémon Radar",
            "embeds": [embed],
            "allowed_mentions": {"parse": []},
        }
    )
