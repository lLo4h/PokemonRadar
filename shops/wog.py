import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from config import REQUEST_TIMEOUT, USER_AGENT
from models import Product

SHOP_NAME = "World of Games"
WOG_URL = "https://www.wog.ch/de/index.cfm/search?query=pokemon"
BASE_URL = "https://www.wog.ch"

PRODUCT_ID_RE = re.compile(r"/product/(\d+)", re.IGNORECASE)
PRICE_RE = re.compile(r"CHF\s*\d+(?:[.’'\s]\d{3})*(?:[.,]\d{2})?", re.IGNORECASE)

AVAILABLE_WORDS = (
    "ab unserem lager verfügbar",
    "sofort lieferbar",
    "beim lieferanten bestellbar",
    "verfügbar",
    "lieferbar",
)
UNAVAILABLE_WORDS = (
    "nicht mehr bestellbar",
    "nicht bestellbar",
    "nicht mehr lieferbar",
    "derzeit ausverkauft",
    "ausverkauft",
)
PREORDER_WORDS = (
    "vorbestellbar",
    "vorbestellen",
    "vorbestellung",
    "noch nicht erschienen",
)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _status_from_text(text: str) -> tuple[str, bool]:
    lowered = text.casefold()
    is_preorder = any(word in lowered for word in PREORDER_WORDS)

    # Negative Aussagen zuerst prüfen, weil "nicht lieferbar" auch
    # das Wort "lieferbar" enthält.
    if any(word in lowered for word in UNAVAILABLE_WORDS):
        return "unavailable", is_preorder
    if is_preorder or any(word in lowered for word in AVAILABLE_WORDS):
        return "available", is_preorder
    return "unknown", is_preorder


def _product_container(link: Tag) -> Tag:
    selectors = (
        "div.product-tile",
        "div.product-box",
        "div.list-item",
        "article",
        "li",
        "div.product",
    )
    for selector in selectors:
        parent = link.find_parent(selector)
        if isinstance(parent, Tag):
            return parent

    # Begrenzter Fallback: nicht die komplette Seite verwenden, da dort
    # Status-Legenden zu anderen Produkten stehen können.
    parent = link.parent
    for _ in range(3):
        if isinstance(parent, Tag) and len(_clean(parent.get_text(" ", strip=True))) >= 25:
            return parent
        parent = parent.parent if isinstance(parent, Tag) else None
    return link


def _title_from_link(link: Tag) -> str:
    title = _clean(link.get_text(" ", strip=True))
    if title:
        return title

    for attribute in ("title", "aria-label"):
        value = link.get(attribute)
        if isinstance(value, str) and value.strip():
            return _clean(value)

    image = link.find("img")
    if isinstance(image, Tag):
        alt = image.get("alt")
        if isinstance(alt, str) and alt.strip():
            return _clean(alt).removesuffix(" Image")
    return "Unbenanntes Pokémon-Produkt"


def _image_from_container(container: Tag) -> str | None:
    image = container.find("img")
    if not isinstance(image, Tag):
        return None
    source = image.get("src") or image.get("data-src") or image.get("data-lazy-src")
    if isinstance(source, str) and source.strip():
        return urljoin(BASE_URL, source.strip())
    return None


def scan_wog() -> list[Product]:
    """Liest die aktuell sichtbaren Pokémon-Produkte der WOG-Liste aus."""
    response = requests.get(
        WOG_URL,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "de-CH,de;q=0.9"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    links = soup.select('a[href*="/details/product/"], a[href*="/product/"]')

    products: dict[str, Product] = {}
    for link in links:
        href = link.get("href")
        if not isinstance(href, str):
            continue

        url = urljoin(BASE_URL, href)
        product_match = PRODUCT_ID_RE.search(url)
        if not product_match:
            continue

        product_id = product_match.group(1)
        container = _product_container(link)
        title = _title_from_link(link)
        container_text = _clean(container.get_text(" ", strip=True))

        # WOG speichert den genauen Lagerstatus teilweise in einem HTML-
        # Attribut namens "content" (Tooltip). BeautifulSoup.get_text()
        # liest Attribute nicht mit, deshalb ergänzen wir sie ausdrücklich.
        tooltip_text = " ".join(
            value for tag in container.select("[content]")
            if isinstance((value := tag.get("content")), str)
        )
        status_text = _clean(f"{container_text} {BeautifulSoup(tooltip_text, 'html.parser').get_text(' ', strip=True)}")

        # Nur Pokémon-Kartenprodukte behalten. Der Publisher-Filter kann auch
        # Videospiele oder Merchandising liefern.
        combined = f"{title} {container_text}".casefold()
        tcg_markers = ("pokemon", "pokémon")
        card_markers = (
            "tcg", "trading card", "sammelkarten", "booster", "display",
            "trainer-box", "trainer box", "collection", "kollektion",
            "blister", "tin", "karten",
        )
        if not any(marker in combined for marker in tcg_markers):
            continue
        if not any(marker in combined for marker in card_markers):
            continue

        price_match = PRICE_RE.search(container_text)
        price = _clean(price_match.group(0)) if price_match else None
        status, is_preorder = _status_from_text(status_text)

        candidate = Product(
            shop=SHOP_NAME,
            product_id=product_id,
            title=title,
            url=url,
            price=price,
            status=status,
            is_preorder=is_preorder,
            image_url=_image_from_container(container),
        )

        # Derselbe Artikel kann durch Bild, Titel und Sprachvarianten mehrfach
        # verlinkt sein. Die Variante mit dem längeren Titel behalten.
        existing = products.get(product_id)
        if existing is None or len(candidate.title) > len(existing.title):
            products[product_id] = candidate

    if not products:
        raise RuntimeError(
            "WOG wurde geladen, aber es wurden keine Produkte erkannt. "
            "Die Website-Struktur könnte sich geändert haben."
        )

    return list(products.values())
