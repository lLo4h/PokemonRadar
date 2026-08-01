import sqlite3
import re
from decimal import Decimal, InvalidOperation
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone

from config import DATA_DIR, DB_PATH
from models import Product


@dataclass(frozen=True, slots=True)
class ProductChange:
    kind: str
    product: Product
    old_status: str | None = None
    old_price: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with closing(connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                shop TEXT NOT NULL,
                product_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                price TEXT,
                status TEXT NOT NULL,
                is_preorder INTEGER NOT NULL DEFAULT 0,
                image_url TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_notified_at TEXT,
                PRIMARY KEY (shop, product_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_products_status
            ON products (shop, status)
            """
        )
        connection.commit()


PRICE_CHANGE_MIN_CHF = Decimal("5.00")
PRICE_CHANGE_MIN_PERCENT = Decimal("5.00")

# Ein Preisnachlass gilt als Deal, wenn mindestens eine Grenze erreicht wird.
DEAL_MIN_CHF = Decimal("10.00")
DEAL_MIN_PERCENT = Decimal("10.00")


def _price_amount(value: str | None) -> Decimal | None:
    """Liest Preise wie CHF 69.90, 69,90 oder 1'299.00 robust ein."""
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


def _is_relevant_price_change(old_price: str | None, new_price: str | None) -> bool:
    """Meldet Änderungen ab CHF 5 oder ab 5 Prozent."""
    old_amount = _price_amount(old_price)
    new_amount = _price_amount(new_price)

    if old_amount is None or new_amount is None or old_amount <= 0:
        return False

    difference = abs(new_amount - old_amount)
    percent = (difference / old_amount) * Decimal("100")

    return (
        difference >= PRICE_CHANGE_MIN_CHF
        or percent >= PRICE_CHANGE_MIN_PERCENT
    )


def _is_deal(old_price: str | None, new_price: str | None) -> bool:
    """Erkennt deutliche Preissenkungen als Deal."""
    old_amount = _price_amount(old_price)
    new_amount = _price_amount(new_price)

    if old_amount is None or new_amount is None or old_amount <= 0:
        return False
    if new_amount >= old_amount:
        return False

    saving = old_amount - new_amount
    percent = (saving / old_amount) * Decimal("100")
    return saving >= DEAL_MIN_CHF or percent >= DEAL_MIN_PERCENT


def save_product(product: Product, *, initial_scan: bool) -> list[ProductChange]:
    """Speichert ein Produkt und gibt erkannte Änderungen zurück.

    Beim ersten Scan werden neue Produkte nur gespeichert. Dadurch entsteht
    beim Start keine Discord-Meldungsflut.
    """
    now = utc_now()
    changes: list[ProductChange] = []

    with closing(connect()) as connection:
        existing = connection.execute(
            """
            SELECT * FROM products
            WHERE shop = ? AND product_id = ?
            """,
            (product.shop, product.product_id),
        ).fetchone()

        if existing is None:
            connection.execute(
                """
                INSERT INTO products (
                    shop, product_id, title, url, price, status,
                    is_preorder, image_url, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product.shop,
                    product.product_id,
                    product.title,
                    product.url,
                    product.price,
                    product.status,
                    int(product.is_preorder),
                    product.image_url,
                    now,
                    now,
                ),
            )

            if not initial_scan:
                # Eine neue Vorbestellung ist bereits eine vollständige Meldung.
                # Dadurch wird dasselbe Produkt nicht zusätzlich als
                # "Neues Produkt" doppelt an Discord geschickt.
                if product.is_preorder:
                    changes.append(ProductChange("new_preorder", product))
                else:
                    changes.append(ProductChange("new_product", product))
        else:
            old_status = existing["status"]
            old_price = existing["price"]
            old_preorder = bool(existing["is_preorder"])

            if old_status == "unavailable" and product.status == "available":
                changes.append(
                    ProductChange(
                        "restock",
                        product,
                        old_status=old_status,
                        old_price=old_price,
                    )
                )

            if _is_relevant_price_change(old_price, product.price):
                change_kind = "deal" if _is_deal(old_price, product.price) else "price_change"
                changes.append(
                    ProductChange(
                        change_kind,
                        product,
                        old_status=old_status,
                        old_price=old_price,
                    )
                )

            if not old_preorder and product.is_preorder:
                changes.append(
                    ProductChange(
                        "new_preorder",
                        product,
                        old_status=old_status,
                        old_price=old_price,
                    )
                )

            connection.execute(
                """
                UPDATE products
                SET title = ?, url = ?, price = ?, status = ?,
                    is_preorder = ?, image_url = ?, last_seen_at = ?
                WHERE shop = ? AND product_id = ?
                """,
                (
                    product.title,
                    product.url,
                    product.price,
                    product.status,
                    int(product.is_preorder),
                    product.image_url,
                    now,
                    product.shop,
                    product.product_id,
                ),
            )

        connection.commit()

    return changes


def reset_demo_product() -> None:
    with closing(connect()) as connection:
        connection.execute(
            "DELETE FROM products WHERE shop = ? AND product_id = ?",
            ("Demo Shop", "demo-001"),
        )
        connection.commit()


def has_shop_products(shop: str) -> bool:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT 1 FROM products WHERE shop = ? LIMIT 1",
            (shop,),
        ).fetchone()
    return row is not None
