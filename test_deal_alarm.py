from __future__ import annotations

from models import Product
from database import ProductChange
from notifier import send_product_change


def main() -> None:
    product = Product(
        shop="Demo Shop",
        product_id="deal-test-001",
        title="Pokémon TCG Journey Together Elite Trainer Box (DE)",
        url="https://example.com/deal-test",
        price="CHF 69.90",
        status="available",
        is_preorder=False,
        image_url=None,
    )

    change = ProductChange(
        "deal",
        product,
        old_price="CHF 89.90",
    )
    send_product_change(change)
    print("[OK] Deal-Test wurde an Discord gesendet.")


if __name__ == "__main__":
    main()
