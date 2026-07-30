from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from config import REQUEST_TIMEOUT, USER_AGENT
from models import Product

TCG_WORDS = (
    "tcg", "booster", "display", "elite trainer box", "trainer box", "etb",
    "collection", "kollektion", "tin", "blister", "bundle", "deck",
    "sammelkarten", "trading card", "karten",
)
EXCLUDED_WORDS = (
    "plüsch", "plush", "figur", "figure", "funko", "videospiel", "switch",
    "t-shirt", "hoodie", "mütze", "cap", "schlüsselanhänger", "keychain",
    "sleeves", "hüllen", "binder", "portfolio", "playmat", "spielmatte",
    "einzelkarte", "single card",
)


def _normalise(text: str) -> str:
    return " ".join(text.split()).strip()


def _is_tcg_title(title: str, *, trusted_pokemon_category: bool = False) -> bool:
    text = title.lower()
    if any(word in text for word in EXCLUDED_WORDS):
        return False
    has_pokemon = any(word in text for word in ("pokemon", "pokémon", "pkm"))
    has_tcg_word = any(word in text for word in TCG_WORDS)
    # In a dedicated Pokémon category, product titles often omit the word
    # “Pokémon” (for example “Destined Rivals Booster Box”).
    return has_tcg_word and (has_pokemon or trusted_pokemon_category)


def _extract_price(text: str) -> str | None:
    matches = re.findall(r"(?:CHF\s*)?([0-9][0-9'’.,]*)", text, flags=re.IGNORECASE)
    if not matches:
        return None
    raw = matches[-1].replace("'", "").replace("’", "").replace(",", ".")
    try:
        return f"CHF {Decimal(raw):.2f}"
    except InvalidOperation:
        return None


def _product_id(card: Tag, url: str) -> str:
    for key in ("data-product_id", "data-product-id", "data-id"):
        value = card.get(key)
        if value:
            return str(value)
    classes = " ".join(card.get("class", []))
    match = re.search(r"post-(\d+)", classes)
    if match:
        return match.group(1)
    return url.rstrip("/").split("/")[-1]


def _find_title_link(card: Tag) -> tuple[str, str] | None:
    selectors = (
        "h2.woocommerce-loop-product__title a",
        "h2.woocommerce-loop-product__title",
        "h3 a",
        ".woocommerce-loop-product__link",
        "a[href]",
    )
    for selector in selectors:
        node = card.select_one(selector)
        if not node:
            continue
        title = _normalise(node.get_text(" ", strip=True))
        href = node.get("href") if node.name == "a" else None
        if not href:
            parent = node.find_parent("a", href=True)
            href = parent.get("href") if parent else None
        if title and href:
            return title, str(href)
    return None


def _candidate_container(link: Tag) -> Tag:
    """Find the smallest surrounding product card that contains price/status text."""
    current: Tag = link
    best: Tag = link
    for _ in range(6):
        parent = current.parent
        if not isinstance(parent, Tag):
            break
        text = _normalise(parent.get_text(" ", strip=True))
        if "CHF" in text or "Ausverkauft" in text or "out of stock" in text.lower():
            best = parent
            # Stop before accidentally selecting the complete product grid/page.
            if len(parent.select("a[href*='/produkt/']")) <= 1:
                return parent
        current = parent
    return best


def parse_woocommerce_html(
    html: str, *, shop_name: str, page_url: str, trusted_pokemon_category: bool = False
) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    cards = list(soup.select("li.product, .products .product, article.product"))

    # MetaGames currently uses a SumUp-style storefront rather than classic
    # WooCommerce markup. Its category page exposes product links under
    # /produkt/, so create lightweight cards from those links as a fallback.
    if not cards:
        cards = [
            _candidate_container(link)
            for link in soup.select("a[href*='/produkt/']")
            if isinstance(link, Tag)
        ]

    products: list[Product] = []
    seen: set[str] = set()

    for card in cards:
        found = _find_title_link(card)
        if not found:
            continue
        title, href = found
        if not _is_tcg_title(title, trusted_pokemon_category=trusted_pokemon_category):
            continue

        url = urljoin(page_url, href)
        product_id = _product_id(card, url)
        if not product_id or product_id in seen:
            continue

        text = _normalise(card.get_text(" ", strip=True))
        lower = text.lower()
        unavailable = any(word in lower for word in ("ausverkauft", "nicht vorrätig", "out of stock", "sold out"))
        available_marker = bool(card.select_one(".add_to_cart_button, a.add_to_cart_button")) or any(
            word in lower for word in ("in den warenkorb", "add to cart", "jetzt bestellen")
        )
        # On category grids, sold-out items are explicitly marked. If no such
        # marker exists, the product can normally be ordered.
        available = available_marker or (trusted_pokemon_category and not unavailable)
        status = "unavailable" if unavailable else "available" if available else "unknown"
        preorder = any(word in lower for word in ("vorbestellung", "vorbestellbar", "preorder", "pre-order"))

        price_node = card.select_one(".price")
        price = _extract_price(price_node.get_text(" ", strip=True) if price_node else text)

        image = card.select_one("img")
        image_url = None
        if image:
            image_url = image.get("data-src") or image.get("data-lazy-src") or image.get("src")
            if image_url:
                image_url = urljoin(page_url, str(image_url))

        products.append(Product(shop_name, product_id, title, url, price, status, preorder, image_url))
        seen.add(product_id)

    return products


def _next_page(soup: BeautifulSoup, current_url: str) -> str | None:
    node = soup.select_one("a.next.page-numbers, a.next, link[rel='next']")
    if not node:
        return None
    href = node.get("href")
    return urljoin(current_url, str(href)) if href else None


def scan_woocommerce(shop_name: str, category_url: str, *, max_pages: int = 10) -> list[Product]:
    session = requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "de-CH,de;q=0.9",
    }
    products: list[Product] = []
    seen_ids: set[str] = set()
    page_url: str | None = category_url

    for _ in range(max_pages):
        if not page_url:
            break
        response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        page_products = parse_woocommerce_html(
            response.text,
            shop_name=shop_name,
            page_url=page_url,
            trusted_pokemon_category=True,
        )
        for product in page_products:
            if product.product_id not in seen_ids:
                products.append(product)
                seen_ids.add(product.product_id)
        soup = BeautifulSoup(response.text, "html.parser")
        next_url = _next_page(soup, page_url)
        if not next_url or next_url == page_url:
            break
        page_url = next_url

    if not products:
        raise RuntimeError("WooCommerce wurde geladen, aber keine Pokémon-TCG-Produkte wurden erkannt.")
    return products
