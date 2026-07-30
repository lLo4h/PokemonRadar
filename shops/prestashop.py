from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from config import REQUEST_TIMEOUT, USER_AGENT
from models import Product

TCG_WORDS = (
    "tcg", "booster", "display", "trainer box", "top trainer box", "elite trainer",
    "etb", "collection", "kollektion", "coffret", "blister", "bundle", "bundel",
    "tin", "deck", "sammelkarten", "trading card", "karten", "box",
)
EXCLUDED_WORDS = (
    "plüsch", "plush", "figur", "figure", "funko", "videospiel", "switch",
    "t-shirt", "hoodie", "mütze", "cap", "schlüsselanhänger", "keychain",
    "sleeves", "hüllen", "binder", "portfolio", "playmat", "spielmatte",
    "einzelkarte", "single card", "zubehör", "accessory", "accessories",
    "deck box", "album", "ordner", "poster", "tasse", "rucksack",
)


def _normalise(text: str) -> str:
    return " ".join(text.split()).strip()


def _is_tcg_title(title: str) -> bool:
    text = title.lower()
    if any(word in text for word in EXCLUDED_WORDS):
        return False
    has_pokemon = any(word in text for word in ("pokemon", "pokémon", "pkm"))
    has_tcg_word = any(word in text for word in TCG_WORDS)
    return has_pokemon and has_tcg_word


def _extract_price(text: str) -> str | None:
    # Supports CHF 79,95 and CHF 79.95. The final number is usually the current price.
    matches = re.findall(r"(?:CHF\s*)?([0-9][0-9'’.,]*)", text, flags=re.IGNORECASE)
    if not matches:
        return None
    raw = matches[-1].replace("'", "").replace("’", "").replace(",", ".")
    try:
        return f"CHF {Decimal(raw):.2f}"
    except InvalidOperation:
        return None


def _product_id(card: Tag, url: str) -> str:
    for key in ("data-id-product", "data-product-id", "data-id-product-attribute", "data-id"):
        value = card.get(key)
        if value:
            return str(value)
    return url.rstrip("/").split("/")[-1].split(".html")[0]


def parse_prestashop_html(html: str, *, shop_name: str, page_url: str) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    cards = list(soup.select("article.product-miniature, .product-miniature, .js-product-miniature"))

    products: list[Product] = []
    seen: set[str] = set()

    for card in cards:
        title_node = card.select_one(".product-title a, h2.product-title a, h3.product-title a, a.product-thumbnail")
        if not title_node:
            continue

        title = _normalise(title_node.get_text(" ", strip=True))
        if not title:
            image = card.select_one("img[alt]")
            title = _normalise(str(image.get("alt", ""))) if image else ""
        if not _is_tcg_title(title):
            continue

        href = title_node.get("href")
        if not href:
            continue
        url = urljoin(page_url, str(href))
        product_id = _product_id(card, url)
        if not product_id or product_id in seen:
            continue

        text = _normalise(card.get_text(" ", strip=True))
        lower = text.lower()
        unavailable = any(word in lower for word in (
            "nicht auf lager", "nicht verfügbar", "out-of-stock", "out of stock", "sold out"
        ))
        available = any(word in lower for word in (
            "auf lager", "in stock", "nur noch wenige", "last items in stock", "in den warenkorb", "add to cart"
        ))
        status = "unavailable" if unavailable else "available" if available else "unknown"
        preorder = any(word in lower for word in (
            "vorbestellung", "vorbestellbar", "pre-order", "preorder", "précommande"
        ))

        price_node = card.select_one(".product-price-and-shipping .price, .product-price, .price")
        price = _extract_price(price_node.get_text(" ", strip=True) if price_node else text)

        image_url = None
        image = card.select_one("img")
        if image:
            image_url = image.get("data-src") or image.get("data-lazy-src") or image.get("src")
            if image_url:
                image_url = urljoin(page_url, str(image_url))

        products.append(Product(shop_name, product_id, title, url, price, status, preorder, image_url))
        seen.add(product_id)

    return products


def _next_page(soup: BeautifulSoup, current_url: str) -> str | None:
    node = soup.select_one("a.next, a[rel='next'], .pagination a.next, a.next.js-search-link")
    if not node:
        return None
    href = node.get("href")
    return urljoin(current_url, str(href)) if href else None


def scan_prestashop(shop_name: str, category_url: str, *, max_pages: int = 70) -> list[Product]:
    session = requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "de-CH,de;q=0.9,en;q=0.7",
    }
    products: list[Product] = []
    seen_ids: set[str] = set()
    visited_urls: set[str] = set()
    page_url: str | None = category_url

    for _ in range(max_pages):
        if not page_url or page_url in visited_urls:
            break
        visited_urls.add(page_url)

        response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        page_products = parse_prestashop_html(response.text, shop_name=shop_name, page_url=page_url)
        for product in page_products:
            if product.product_id not in seen_ids:
                products.append(product)
                seen_ids.add(product.product_id)

        soup = BeautifulSoup(response.text, "html.parser")
        page_url = _next_page(soup, page_url)

    if not products:
        raise RuntimeError("PrestaShop wurde geladen, aber keine Pokémon-TCG-Produkte wurden erkannt.")
    return products
