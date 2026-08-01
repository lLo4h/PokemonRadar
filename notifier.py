from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Iterable

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


def _retry_after_seconds(response: requests.Response) -> float:
    """Liest Discord retry_after robust aus."""
    try:
        payload = response.json()
        value = float(payload.get("retry_after", 1.0))
    except (ValueError, TypeError, requests.exceptions.JSONDecodeError):
        value = 1.0

    # Discord liefert normalerweise Sekunden. Sehr grosse Werte behandeln wir
    # vorsichtshalber als Millisekunden.
    if value > 1000:
        value /= 1000
    return max(0.5, value)


def _post(payload: dict[str, Any], *, max_retries: int = 8) -> None:
    """Sendet einen Webhook und wartet automatisch bei Discord-Rate-Limits."""
    webhook = _require_webhook()

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                webhook,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as error:
            if attempt >= max_retries:
                raise WebhookError(f"Discord-Netzwerkfehler: {error}") from error
            time.sleep(min(2 ** attempt, 10))
            continue

        if response.status_code == 204:
            return

        if response.status_code == 429:
            if attempt >= max_retries:
                raise WebhookError(
                    f"Discord-Rate-Limit nach {max_retries + 1} Versuchen: "
                    f"{response.text[:200]}"
                )
            wait_seconds = _retry_after_seconds(response) + 0.25
            print(f"[DISCORD] Rate-Limit aktiv – warte {wait_seconds:.2f} Sekunden …")
            time.sleep(wait_seconds)
            continue

        # Vorübergehende Discord-Serverfehler ebenfalls erneut versuchen.
        if 500 <= response.status_code < 600 and attempt < max_retries:
            time.sleep(min(2 ** attempt, 10))
            continue

        raise WebhookError(
            f"Discord antwortete mit Status {response.status_code}: "
            f"{response.text[:200]}"
        )

    raise WebhookError("Discord-Nachricht konnte nicht gesendet werden.")


def send_test_message() -> None:
    _post(
        {
            "username": "Pokémon Radar",
            "content": "✅ **Pokémon Radar V3 ist verbunden.**\n"
                       "Rate-Limit-Schutz und Sammelmeldungen sind aktiv.",
            "allowed_mentions": {"parse": []},
        }
    )


LABELS = {
    "new_product": ("🆕 Neue Produkte", 0x3498DB),
    "new_preorder": ("📦 Neue Vorbestellungen", 0x9B59B6),
    "restock": ("🔥 Wieder verfügbar", 0x2ECC71),
    "price_change": ("💰 Preisänderungen", 0xF1C40F),
}


def _product_line(change: ProductChange) -> str:
    product = change.product
    title = " ".join(product.title.split())
    if len(title) > 140:
        title = title[:137] + "…"

    details: list[str] = []
    if product.price:
        details.append(product.price)
    if change.kind == "price_change" and change.old_price:
        details.append(f"vorher {change.old_price}")
    if product.status:
        details.append(product.status)

    suffix = f" — {' | '.join(details)}" if details else ""
    return f"• [{title}]({product.url}){suffix}"


def _chunk_lines(lines: list[str], *, max_chars: int = 3500) -> list[str]:
    """Teilt Beschreibungen sicher unter Discord-Längenlimits auf."""
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for line in lines:
        extra = len(line) + (1 if current else 0)
        if current and current_length + extra > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length += len(line) + (1 if len(current) > 1 else 0)

    if current:
        chunks.append("\n".join(current))
    return chunks


def send_product_changes(shop_name: str, changes: Iterable[ProductChange]) -> int:
    """Sendet Änderungen eines Shops als wenige kompakte Sammelmeldungen.

    Rückgabewert: Anzahl gesendeter Discord-Webhook-Nachrichten.
    """
    grouped: dict[str, list[ProductChange]] = defaultdict(list)
    total = 0
    for change in changes:
        grouped[change.kind].append(change)
        total += 1

    if total == 0:
        return 0

    embeds: list[dict[str, Any]] = []
    order = ("new_product", "new_preorder", "restock", "price_change")

    for kind in order:
        kind_changes = grouped.get(kind, [])
        if not kind_changes:
            continue

        label, color = LABELS[kind]
        lines = [_product_line(change) for change in kind_changes]
        descriptions = _chunk_lines(lines)

        for index, description in enumerate(descriptions, start=1):
            title = f"{label} ({len(kind_changes)})"
            if len(descriptions) > 1:
                title += f" – Teil {index}/{len(descriptions)}"
            embeds.append(
                {
                    "title": title,
                    "description": description,
                    "color": color,
                }
            )

    # Discord erlaubt maximal 10 Embeds und insgesamt höchstens 6000 Zeichen
    # in allen Embeds einer Webhook-Nachricht. Wir bleiben bewusst darunter.
    batches: list[list[dict[str, Any]]] = []
    current_batch: list[dict[str, Any]] = []
    current_chars = 0
    max_embed_chars = 5500

    for embed in embeds:
        embed_chars = len(str(embed.get("title", ""))) + len(str(embed.get("description", "")))

        if current_batch and (
            len(current_batch) >= 10
            or current_chars + embed_chars > max_embed_chars
        ):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(embed)
        current_chars += embed_chars

    if current_batch:
        batches.append(current_batch)

    message_count = 0
    for index, embed_batch in enumerate(batches, start=1):
        content = f"**{shop_name}** – {total} Produktänderung(en)"
        if len(batches) > 1:
            content += f" – Nachricht {index}/{len(batches)}"

        _post(
            {
                "username": "Pokémon Radar",
                "content": content,
                "embeds": embed_batch,
                "allowed_mentions": {"parse": []},
            }
        )
        message_count += 1

    return message_count


def send_product_change(change: ProductChange) -> None:
    """Kompatibilität für bestehende Tests: sendet eine einzelne Änderung."""
    send_product_changes(change.product.shop, [change])
