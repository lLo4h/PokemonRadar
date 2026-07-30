import sqlite3
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
                changes.append(ProductChange("new_product", product))
                if product.is_preorder:
                    changes.append(ProductChange("new_preorder", product))
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

            if old_price != product.price and old_price is not None:
                changes.append(
                    ProductChange(
                        "price_change",
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
