"""Erkennt verbreitete Shopsysteme anhand ihrer öffentlichen Fingerabdrücke."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import requests


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 PokemonRadar/1.0"
    ),
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.7",
}


@dataclass(frozen=True)
class DetectionResult:
    shop_type: str
    final_url: str
    confidence: str
    evidence: tuple[str, ...]


FINGERPRINTS: dict[str, tuple[tuple[str, int], ...]] = {
    "shopify": (
        ("cdn.shopify.com", 5),
        ("shopify.theme", 5),
        ("shopify.routes", 4),
        ("shopify-section", 3),
        ("myshopify.com", 4),
        ("x-shopify-stage", 5),
    ),
    "woocommerce": (
        ("woocommerce", 5),
        ("wc-ajax", 4),
        ("woocommerce-page", 4),
        ("wp-content/plugins/woocommerce", 5),
        ("add_to_cart_button", 3),
    ),
    "prestashop": (
        ("prestashop", 5),
        ("var prestashop", 5),
        ("prestashop.modules", 5),
        ("/modules/ps_", 3),
        ("product-miniature", 2),
    ),
}


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("Die URL ist leer.")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Ungültige Shop-URL: {url}")
    return url


def detect_shop_type(url: str, timeout: int = 20) -> DetectionResult:
    """Lädt die Startseite und bewertet typische Shop-Fingerabdrücke."""
    normalized_url = normalize_url(url)
    response = requests.get(
        normalized_url,
        headers=DEFAULT_HEADERS,
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()

    searchable = "\n".join(
        [response.text.lower(), str(response.headers).lower(), response.url.lower()]
    )
    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}

    for shop_type, fingerprints in FINGERPRINTS.items():
        scores[shop_type] = 0
        evidence[shop_type] = []
        for marker, weight in fingerprints:
            if marker in searchable:
                scores[shop_type] += weight
                evidence[shop_type].append(marker)

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]
    sorted_scores = sorted(scores.values(), reverse=True)
    second_score = sorted_scores[1]

    # Ein schwacher Einzelhinweis reicht nicht für eine sichere Zuordnung.
    if best_score < 4 or best_score == second_score:
        return DetectionResult("unknown", response.url, "unbekannt", ())

    confidence = "hoch" if best_score >= 8 else "mittel"
    return DetectionResult(
        best_type,
        response.url,
        confidence,
        tuple(evidence[best_type]),
    )


def scanner_name(shop_type: str) -> str:
    return {
        "shopify": "ShopifyScanner",
        "woocommerce": "WooCommerceScanner",
        "prestashop": "PrestaShopScanner",
    }.get(shop_type, "Kein passender Scanner vorhanden")
