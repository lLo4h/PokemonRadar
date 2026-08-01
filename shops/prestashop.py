from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from config import REQUEST_TIMEOUT, USER_AGENT
from models import Product

TCG_WORDS = (
    "tcg", "booster", "display", "trainer box", "top trainer box", "elite trainer",
    "etb", "collection", "kollektion", "coffret", "blister", "bundle", "bundel",
    "tin", "deck", "sammelkarten", "trading card", "karten", "box",
    # Französische Bezeichnungen, die Schweizer Shops häufig verwenden.
    "boite de boosters", "boîte de boosters", "pokebox", "tripack", "duopack",
)
EXCLUDED_WORDS = (
    "plüsch", "plush", "figur", "figure", "funko", "videospiel", "switch",
    "t-shirt", "hoodie", "mütze", "cap", "schlüsselanhänger", "keychain",
    "sleeves", "hüllen", "binder", "portfolio", "playmat", "spielmatte",
    "einzelkarte", "single card", "zubehör", "accessory", "accessories",
    "deck box", "album", "ordner", "poster", "tasse", "rucksack",
    # Einzelkarten und Grading auf Französisch.
    "carte gradée", "cartes gradées", "carte psa", "psa 10", "pca 10",
    "lot de cartes",
)


def _normalise(text: str) -> str:
    return " ".join(text.split()).strip()


def _is_tcg_title(title: str, *, pokemon_catalog: bool = False) -> bool:
    """Prüft einen Produkttitel.

    Manche reine Pokémon-Shops schreiben nicht in jeden Titel erneut
    "Pokémon". In einem eindeutig als Pokémon erkannten Katalog reicht
    deshalb ein typischer TCG-Begriff wie Display, Booster oder Coffret.
    """
    text = title.lower()
    if any(word in text for word in EXCLUDED_WORDS):
        return False
    has_pokemon = any(word in text for word in ("pokemon", "pokémon", "pkm"))
    has_tcg_word = any(word in text for word in TCG_WORDS)
    return has_tcg_word and (has_pokemon or pokemon_catalog)


def _is_pokemon_catalog(soup: BeautifulSoup) -> bool:
    """Erkennt Seiten, deren gesamter Katalog klar Pokémon-TCG gewidmet ist."""
    signals: list[str] = []

    if soup.title:
        signals.append(soup.title.get_text(" ", strip=True))

    for selector in (
        'meta[name="description"]',
        'meta[property="og:title"]',
        'meta[property="og:description"]',
        "h1",
    ):
        node = soup.select_one(selector)
        if node:
            signals.append(str(node.get("content") or node.get_text(" ", strip=True)))

    # Navigation und sichtbarer Seitentext helfen bei reinen Pokémon-Shops,
    # deren Kategorieüberschrift nur "Displays" oder "Scellés" lautet.
    signals.append(soup.get_text(" ", strip=True)[:12000])
    text = " ".join(signals).lower()

    has_pokemon = "pokemon" in text or "pokémon" in text
    has_card_context = any(word in text for word in (
        "tcg", "cartes", "sammelkarten", "trading card", "boosters",
        "elite trainer box", "produits scellés",
    ))
    return has_pokemon and has_card_context


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


def _status_from_text(text: str) -> str:
    lower = text.lower()
    unavailable = any(word in lower for word in (
        "nicht auf lager", "nicht verfügbar", "out-of-stock", "out of stock",
        "sold out", "rupture de stock", "indisponible",
    ))
    available = any(word in lower for word in (
        "auf lager", "in stock", "nur noch wenige", "last items in stock",
        "in den warenkorb", "add to cart", "ajouter au panier", "en stock",
    ))
    return "unavailable" if unavailable else "available" if available else "unknown"


def _is_preorder(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in (
        "vorbestellung", "vorbestellbar", "pre-order", "preorder", "précommande",
    ))


def _append_product(
    products: list[Product],
    seen: set[str],
    *,
    shop_name: str,
    page_url: str,
    title: str,
    href: str,
    price: str | None,
    status: str,
    preorder: bool,
    image_url: str | None,
    product_id: str | None = None,
) -> None:
    title = _normalise(title)
    if not title or not href:
        return
    url = urljoin(page_url, href)
    product_id = product_id or url.rstrip("/").split("/")[-1].split(".html")[0]
    if not product_id or product_id in seen:
        return
    if image_url:
        image_url = urljoin(page_url, image_url)
    products.append(Product(shop_name, product_id, title, url, price, status, preorder, image_url))
    seen.add(product_id)


def _parse_json_ld(
    soup: BeautifulSoup,
    *,
    shop_name: str,
    page_url: str,
    pokemon_catalog: bool,
    products: list[Product],
    seen: set[str],
) -> None:
    """Fallback für Themes, welche Produktkarten fast nur per JavaScript aufbauen."""
    for node in soup.select('script[type="application/ld+json"]'):
        raw = node.string or node.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "Product" not in types:
                continue

            title = str(item.get("name") or "")
            if not _is_tcg_title(title, pokemon_catalog=pokemon_catalog):
                continue

            href = str(item.get("url") or item.get("@id") or "")
            if not href:
                continue

            offers = item.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = None
            status = "unknown"
            if isinstance(offers, dict):
                raw_price = offers.get("price") or offers.get("lowPrice")
                if raw_price is not None:
                    price = _extract_price(f"CHF {raw_price}")
                availability = str(offers.get("availability") or "").lower()
                if "instock" in availability:
                    status = "available"
                elif "outofstock" in availability or "soldout" in availability:
                    status = "unavailable"

            image = item.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            elif isinstance(image, dict):
                image = image.get("url")

            _append_product(
                products,
                seen,
                shop_name=shop_name,
                page_url=page_url,
                title=title,
                href=href,
                price=price,
                status=status,
                preorder=_is_preorder(title),
                image_url=str(image) if image else None,
                product_id=str(item.get("sku") or item.get("productID") or "") or None,
            )


def parse_prestashop_html(html: str, *, shop_name: str, page_url: str) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    pokemon_catalog = _is_pokemon_catalog(soup)
    products: list[Product] = []
    seen: set[str] = set()

    # Verschiedene PrestaShop-Themes verwenden unterschiedliche Container.
    cards = list(soup.select(
        "article.product-miniature, .product-miniature, .js-product-miniature, "
        "[data-id-product], .product-container, .product-item"
    ))

    for card in cards:
        # Titel und Produktlink getrennt suchen. Einige moderne PrestaShop-Themes
        # (z. B. Hummingbird bei Pokelu) speichern den Titel in einem <p>,
        # während der eigentliche Link im umgebenden <a>-Element liegt.
        title_node = card.select_one(
            ".product-miniature__title, "
            ".product-title a, h2.product-title a, h3.product-title a, "
            ".product-name a, a.product-name"
        )
        link_node = card.select_one(
            "a.product-miniature__link, "
            ".product-miniature__title a, "
            ".product-title a, h2.product-title a, h3.product-title a, "
            ".product-name a, a.product-name, a.product-thumbnail, "
            "a[href*='.html']"
        )

        image = card.select_one("img")
        title = _normalise(title_node.get_text(" ", strip=True)) if title_node else ""
        if not title and image:
            title = _normalise(str(image.get("alt") or image.get("title") or ""))
        if not _is_tcg_title(title, pokemon_catalog=pokemon_catalog):
            continue

        href = link_node.get("href") if link_node else None
        if not href:
            continue

        text = _normalise(card.get_text(" ", strip=True))
        price_node = card.select_one(
            ".product-price-and-shipping .price, .product-price, .price, "
            "[itemprop='price']"
        )
        price_text = price_node.get("content") if price_node and price_node.get("content") else (
            price_node.get_text(" ", strip=True) if price_node else text
        )
        image_url = None
        if image:
            image_url = image.get("data-src") or image.get("data-lazy-src") or image.get("src")

        _append_product(
            products,
            seen,
            shop_name=shop_name,
            page_url=page_url,
            title=title,
            href=str(href),
            price=_extract_price(str(price_text)),
            status=_status_from_text(text),
            preorder=_is_preorder(text),
            image_url=str(image_url) if image_url else None,
            product_id=_product_id(card, urljoin(page_url, str(href))),
        )

    # Zweiter Weg: strukturierte Produktdaten. Das behebt u. a. Themes, bei denen
    # die sichtbare Karte andere Klassen nutzt als das klassische PrestaShop-Theme.
    _parse_json_ld(
        soup,
        shop_name=shop_name,
        page_url=page_url,
        pokemon_catalog=pokemon_catalog,
        products=products,
        seen=seen,
    )

    return products


def _next_page(soup: BeautifulSoup, current_url: str) -> str | None:
    node = soup.select_one("a.next, a[rel='next'], .pagination a.next, a.next.js-search-link")
    if not node:
        return None
    href = node.get("href")
    return urljoin(current_url, str(href)) if href else None


def _is_shop_homepage(url: str) -> bool:
    """True, wenn die URL nur auf die Domainwurzel zeigt."""
    parsed = urlparse(url)
    return parsed.path in ("", "/") and not parsed.query


def _discover_catalog_urls(soup: BeautifulSoup, start_url: str) -> list[str]:
    """Findet auf einer PrestaShop-Startseite relevante TCG-Kategorien.

    Pokelu zeigt auf der Startseite nur wechselnde Produktmodule. Darum werden
    stattdessen die Hauptkategorien für versiegelte Produkte und Booster genutzt.
    Einzelkarten, Zubehör, Blog, Konto usw. werden bewusst ausgeschlossen.
    """
    wanted_terms = (
        "scellés", "scelles", "sealed", "versiegelt",
        "booster", "boosters",
    )
    blocked_terms = (
        "carte gradée", "cartes gradées", "graded", "single", "einzelkarte",
        "accessoire", "accessory", "zubehör", "blog", "contact", "compte",
        "account", "connexion", "login", "livraison", "paiement",
    )

    base_host = (urlparse(start_url).hostname or "").lower()
    found: list[str] = []
    seen: set[str] = set()

    for link in soup.select("a[href]"):
        label = _normalise(link.get_text(" ", strip=True)).lower()
        href = str(link.get("href") or "").strip()
        if not label or not href:
            continue
        if any(term in label for term in blocked_terms):
            continue
        if not any(term in label for term in wanted_terms):
            continue

        url = urljoin(start_url, href)
        parsed = urlparse(url)
        if (parsed.hostname or "").lower() != base_host:
            continue

        # PrestaShop-Produkte enden bei Pokelu auf .html. Deren Titel enthalten
        # häufig ebenfalls "booster" und würden sonst fälschlich als Kategorie
        # erkannt. Nur echte Katalog-/Kategoriepfade übernehmen.
        path_lower = parsed.path.lower().rstrip("/")
        if path_lower.endswith(".html"):
            continue
        if not re.search(r"/\d+-[^/]+$", path_lower):
            continue

        # Fragmente entfernen; Query-Parameter bleiben erhalten, falls der Shop
        # sie für Sprache oder Seitengröße benötigt.
        clean_url = parsed._replace(fragment="").geturl()
        if clean_url not in seen:
            seen.add(clean_url)
            found.append(clean_url)

    return found


def _scan_category(
    session: requests.Session,
    headers: dict[str, str],
    *,
    shop_name: str,
    start_url: str,
    max_pages: int,
    products: list[Product],
    seen_ids: set[str],
    visited_urls: set[str],
) -> None:
    page_url: str | None = start_url

    for _ in range(max_pages):
        if not page_url or page_url in visited_urls:
            break
        visited_urls.add(page_url)

        response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        page_products = parse_prestashop_html(
            response.text,
            shop_name=shop_name,
            page_url=page_url,
        )
        for product in page_products:
            if product.product_id not in seen_ids:
                products.append(product)
                seen_ids.add(product.product_id)

        soup = BeautifulSoup(response.text, "html.parser")
        page_url = _next_page(soup, page_url)


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

    start_urls = [category_url]

    # Eine Startseite enthält bei manchen Themes nur wechselnde Empfehlungen.
    # In diesem Fall zuerst passende Hauptkategorien aus der Navigation finden.
    if _is_shop_homepage(category_url):
        response = session.get(category_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        discovered = _discover_catalog_urls(soup, category_url)
        if discovered:
            start_urls = discovered
            print(f"[{shop_name}] {len(start_urls)} relevante Katalog-Kategorie(n) gefunden:")
            for url in start_urls:
                print(f"[{shop_name}] -> {url}")
        else:
            print(f"[{shop_name}] Keine Katalog-Kategorie erkannt; Startseite wird direkt gescannt.")

    for start_url in start_urls:
        _scan_category(
            session,
            headers,
            shop_name=shop_name,
            start_url=start_url,
            max_pages=max_pages,
            products=products,
            seen_ids=seen_ids,
            visited_urls=visited_urls,
        )

    if not products:
        raise RuntimeError("PrestaShop wurde geladen, aber keine Pokémon-TCG-Produkte wurden erkannt.")
    return products
