from __future__ import annotations

import os
import time
import re
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

import requests

from config import DISCORD_WEBHOOK, REQUEST_TIMEOUT
from database import ProductChange
from product_classifier import classify_product


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
            "content": "✅ **Pokémon Radar V4 ist verbunden.**\n"
                       "Produktbilder und professionelle Embeds sind aktiv.",
            "allowed_mentions": {"parse": []},
        }
    )


LABELS = {
    "new_product": ("🆕 Neu im Shop", 0x3498DB),
    "new_preorder": ("📦 Vorbestellung geöffnet", 0x9B59B6),
    "restock": ("🔥 Wieder verfügbar", 0x2ECC71),
    "deal": ("🔥 Deal erkannt", 0x2ECC71),
    "price_change": ("💰 Preisänderung", 0xF1C40F),
}

STATUS_LABELS = {
    "available": "🟢 Verfügbar",
    "unavailable": "🔴 Nicht verfügbar",
    "unknown": "⚪ Unbekannt",
}

MAX_RICH_EMBEDS_PER_BATCH = 5


def _clean_title(value: str, *, max_length: int = 256) -> str:
    title = " ".join(value.split())
    if len(title) > max_length:
        return title[: max_length - 1] + "…"
    return title


def _safe_value(value: str | None, *, fallback: str = "Keine Angabe") -> str:
    cleaned = " ".join((value or "").split())
    return cleaned[:1024] if cleaned else fallback


def _price_amount(value: str | None) -> Decimal | None:
    if not value:
        return None
    match = re.search(r"-?[0-9][0-9'’.,]*", value)
    if not match:
        return None
    raw = match.group(0).replace("'", "").replace("’", "").replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _price_change_details(change: ProductChange) -> tuple[str, int, str | None]:
    """Erstellt Richtung, Farbe und Differenz für Preisänderungen."""
    old_amount = _price_amount(change.old_price)
    new_amount = _price_amount(change.product.price)

    if old_amount is None or new_amount is None:
        return "💰 Preisänderung", 0xF1C40F, None

    difference = new_amount - old_amount
    percent = (abs(difference) / old_amount * Decimal("100")) if old_amount else Decimal("0")

    if difference < 0:
        label = "📉 Preis gesunken"
        color = 0x2ECC71
        direction = "günstiger"
    elif difference > 0:
        label = "📈 Preis erhöht"
        color = 0xE67E22
        direction = "teurer"
    else:
        return "💰 Preisänderung", 0xF1C40F, None

    detail = f"CHF {abs(difference):.2f} {direction} ({percent:.1f} %)"
    return label, color, detail


def _rich_product_embed(change: ProductChange) -> dict[str, Any]:
    product = change.product
    label, color = LABELS.get(change.kind, ("Produktänderung", 0x95A5A6))
    price_difference_text: str | None = None

    if change.kind in {"price_change", "deal"}:
        label, color, price_difference_text = _price_change_details(change)
        if change.kind == "deal":
            label = "🔥 Deal erkannt"
            color = 0x2ECC71

    # Ereignisfarben bleiben eindeutig. Nur ein widersprüchlicher Restock-Test
    # mit "nicht verfügbar" wird rot dargestellt.
    if change.kind == "new_product":
        color = 0x3498DB
    elif change.kind == "new_preorder":
        color = 0x9B59B6
    elif change.kind == "restock":
        color = 0x2ECC71 if product.status == "available" else 0xE74C3C

    fields: list[dict[str, Any]] = [
        {
            "name": "🏪 Shop",
            "value": _safe_value(product.shop),
            "inline": True,
        },
        {
            "name": "📦 Status",
            "value": (
                "🟣 Vorbestellbar"
                if change.kind == "new_preorder" and product.status == "available"
                else STATUS_LABELS.get(product.status, _safe_value(product.status))
            ),
            "inline": True,
        },
    ]

    if product.price:
        fields.append(
            {
                "name": "💰 Preis",
                "value": f"**{_safe_value(product.price)}**",
                "inline": True,
            }
        )

    classification = classify_product(product.title)
    if classification.set_name:
        fields.append(
            {
                "name": "🧩 Set",
                "value": classification.set_name,
                "inline": True,
            }
        )
    if classification.product_type:
        fields.append(
            {
                "name": "📦 Typ",
                "value": classification.product_type,
                "inline": True,
            }
        )
    if classification.language:
        fields.append(
            {
                "name": "🌐 Sprache",
                "value": classification.language,
                "inline": True,
            }
        )

    if change.kind in {"price_change", "deal"} and change.old_price:
        fields.append(
            {
                "name": "↩️ Vorher",
                "value": _safe_value(change.old_price),
                "inline": True,
            }
        )

    if price_difference_text:
        fields.append(
            {
                "name": "📊 Unterschied",
                "value": price_difference_text,
                "inline": False,
            }
        )

    embed: dict[str, Any] = {
        "title": f"{label}: {_clean_title(product.title, max_length=210)}",
        "url": product.url,
        "color": color,
        "description": f"[🛒 **Direkt zum Produkt**]({product.url})",
        "fields": fields,
        "footer": {"text": "⚡ Pokémon Radar • Schweiz"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if product.image_url:
        embed["image"] = {"url": product.image_url}

    return embed


def _compact_product_line(change: ProductChange) -> str:
    product = change.product
    title = _clean_title(product.title, max_length=140)

    details: list[str] = []
    if product.price:
        details.append(product.price)
    if change.kind in {"price_change", "deal"} and change.old_price:
        details.append(f"vorher {change.old_price}")
    if product.status:
        details.append(STATUS_LABELS.get(product.status, product.status))

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


def _compact_group_embeds(
    grouped: dict[str, list[ProductChange]],
) -> list[dict[str, Any]]:
    embeds: list[dict[str, Any]] = []
    order = ("new_product", "new_preorder", "restock", "deal", "price_change")

    for kind in order:
        kind_changes = grouped.get(kind, [])
        if not kind_changes:
            continue

        label, color = LABELS[kind]
        lines = [_compact_product_line(change) for change in kind_changes]
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
                    "footer": {"text": "⚡ Pokémon Radar • Schweiz"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

    return embeds


def _make_batches(
    embeds: list[dict[str, Any]],
    *,
    max_embeds: int,
    max_embed_chars: int = 5500,
) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current_batch: list[dict[str, Any]] = []
    current_chars = 0

    for embed in embeds:
        embed_chars = (
            len(str(embed.get("title", "")))
            + len(str(embed.get("description", "")))
            + sum(
                len(str(field.get("name", ""))) + len(str(field.get("value", "")))
                for field in embed.get("fields", [])
            )
        )

        if current_batch and (
            len(current_batch) >= max_embeds
            or current_chars + embed_chars > max_embed_chars
        ):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(embed)
        current_chars += embed_chars

    if current_batch:
        batches.append(current_batch)

    return batches


ROLE_ENV_BY_KIND = {
    "restock": "RESTOCK_ROLE_ID",
    "deal": "DEAL_ROLE_ID",
    "new_preorder": "PREORDER_ROLE_ID",
}


def _role_ids_for_changes(changes: Iterable[ProductChange]) -> list[str]:
    """Liest nur die Rollen aus, die zu den enthaltenen Meldungstypen passen."""
    role_ids: list[str] = []
    seen: set[str] = set()

    for change in changes:
        env_name = ROLE_ENV_BY_KIND.get(change.kind)
        if not env_name:
            continue

        role_id = os.getenv(env_name, "").strip()
        if role_id and role_id.isdigit() and role_id not in seen:
            role_ids.append(role_id)
            seen.add(role_id)

    return role_ids


def _role_mention_text(role_ids: Iterable[str]) -> str:
    return " ".join(f"<@&{role_id}>" for role_id in role_ids)


def send_product_changes(shop_name: str, changes: Iterable[ProductChange]) -> int:
    """Sendet kleine Mengen mit grossen Bildern, grosse Mengen kompakt."""
    change_list = list(changes)
    total = len(change_list)
    if total == 0:
        return 0

    role_ids = _role_ids_for_changes(change_list)
    role_mentions = _role_mention_text(role_ids)

    grouped: dict[str, list[ProductChange]] = defaultdict(list)
    for change in change_list:
        grouped[change.kind].append(change)

    if total <= MAX_RICH_EMBEDS_PER_BATCH:
        embeds = [_rich_product_embed(change) for change in change_list]
        batches = _make_batches(
            embeds,
            max_embeds=MAX_RICH_EMBEDS_PER_BATCH,
        )
    else:
        embeds = _compact_group_embeds(grouped)
        batches = _make_batches(embeds, max_embeds=10)

    message_count = 0
    for index, embed_batch in enumerate(batches, start=1):
        summary = f"**{shop_name}** – {total} Produktänderung(en)"
        if len(batches) > 1:
            summary += f" – Nachricht {index}/{len(batches)}"

        # Rollen werden nur in der ersten Nachricht eines Batches erwähnt,
        # damit bei mehreren Discord-Nachrichten kein Mehrfach-Ping entsteht.
        content = summary
        allowed_mentions: dict[str, Any] = {"parse": []}
        if index == 1 and role_mentions:
            content = f"{role_mentions}\n{summary}"
            allowed_mentions["roles"] = role_ids

        _post(
            {
                "username": "Pokémon Radar",
                "content": content,
                "embeds": embed_batch,
                "allowed_mentions": allowed_mentions,
            }
        )
        message_count += 1

    return message_count


def send_product_change(change: ProductChange) -> None:
    """Kompatibilität für bestehende Tests: sendet eine einzelne Änderung."""
    send_product_changes(change.product.shop, [change])
