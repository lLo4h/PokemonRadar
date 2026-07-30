from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from config import REQUEST_TIMEOUT, USER_AGENT
from models import Product

POKEMON_WORDS = ("pokemon", "pokémon")
TCG_WORDS = (
    "tcg",
    "trading card",
    "booster",
    "display",
    "elite trainer box",
    "etb",
    "collection",
    "tin",
    "blister",
    "bundle",
    "deck",
    "karten",
    "sammelkarten",
)
EXCLUDED_WORDS = (
    "plüsch",
    "plush",
    "figur",
    "figure",
    "funko",
    "videospiel",
    "game für",
    "switch",
    "poster",
    "t-shirt",
    "hoodie",
    "mütze",
    "cap",
    "schlüsselanhänger",
    "keychain",
)


def _clean_base_url(shop_url: str) -> str:
    parsed = urlparse(shop_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Ungültige Shop-Adresse. Beispiel: https://meinshop.ch")
    return f"{parsed.scheme}://{parsed.netloc}"


def _text_blob(product: dict[str, Any]) -> str:
    tags = product.get("tags", [])
    if isinstance(tags, list):
        tag_text = " ".join(str(tag) for tag in tags)
    else:
        tag_text = str(tags)
    return " ".join(
        [
            str(product.get("title", "")),
            str(product.get("product_type", "")),
            str(product.get("vendor", "")),
            tag_text,
        ]
    ).lower()


def is_pokemon_tcg(product: dict[str, Any]) -> bool:
    text = _text_blob(product)
    if not any(word in text for word in POKEMON_WORDS):
        return False
    if any(word in text for word in EXCLUDED_WORDS):
        return False
    return any(word in text for word in TCG_WORDS)


def _format_price(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    return f"CHF {amount:.2f}"


def _product_status(variants: list[dict[str, Any]]) -> str:
    if not variants:
        return "unknown"
    return "available" if any(bool(v.get("available")) for v in variants) else "unavailable"


def _lowest_price(variants: list[dict[str, Any]]) -> str | None:
    prices: list[Decimal] = []
    for variant in variants:
        value = variant.get("price")
        try:
            prices.append(Decimal(str(value)))
        except (InvalidOperation, TypeError):
            continue
    if not prices:
        return None
    return _format_price(min(prices))


def parse_shopify_products(
    data: dict[str, Any], *, shop_name: str, shop_url: str
) -> list[Product]:
    base_url = _clean_base_url(shop_url)
    raw_products = data.get("products")
    if not isinstance(raw_products, list):
        raise RuntimeError("Shopify-Antwort enthält keine gültige Produktliste.")

    products: list[Product] = []
    seen_ids: set[str] = set()

    for raw in raw_products:
        if not isinstance(raw, dict) or not is_pokemon_tcg(raw):
            continue

        product_id = str(raw.get("id", "")).strip()
        title = str(raw.get("title", "")).strip()
        handle = str(raw.get("handle", "")).strip()
        if not product_id or not title or not handle or product_id in seen_ids:
            continue

        variants = raw.get("variants", [])
        if not isinstance(variants, list):
            variants = []

        images = raw.get("images", [])
        image_url = None
        if isinstance(images, list) and images and isinstance(images[0], dict):
            image_url = images[0].get("src")

        text = _text_blob(raw)
        products.append(
            Product(
                shop=shop_name,
                product_id=product_id,
                title=title,
                url=urljoin(base_url, f"/products/{handle}"),
                price=_lowest_price(variants),
                status=_product_status(variants),
                is_preorder=any(word in text for word in ("preorder", "pre-order", "vorbestellung")),
                image_url=str(image_url) if image_url else None,
            )
        )
        seen_ids.add(product_id)

    return products


def _shopify_endpoint(shop_url: str) -> str:
    """Use the selected collection when possible, otherwise scan all products."""
    parsed = urlparse(shop_url.strip())
    base_url = _clean_base_url(shop_url)
    parts = [part for part in parsed.path.split("/") if part]

    # Supports /collections/name and language prefixes such as /de/collections/name.
    if "collections" in parts:
        index = parts.index("collections")
        if index + 1 < len(parts):
            handle = parts[index + 1]
            return urljoin(base_url, f"/collections/{handle}/products.json?limit=250")

    return urljoin(base_url, "/products.json?limit=250")


def scan_shopify(shop_name: str, shop_url: str) -> list[Product]:
    base_url = _clean_base_url(shop_url)
    endpoint = _shopify_endpoint(shop_url)
    response = requests.get(
        endpoint,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "de-CH,de;q=0.9",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as error:
        raise RuntimeError(
            "Der Shop liefert unter /products.json keine Shopify-Produktliste."
        ) from error

    products = parse_shopify_products(data, shop_name=shop_name, shop_url=base_url)
    if not products:
        raise RuntimeError(
            "Shopify wurde erreicht, aber es wurden keine Pokémon-TCG-Produkte erkannt."
        )
    return products
