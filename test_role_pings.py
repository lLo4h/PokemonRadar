from __future__ import annotations

import os

# Nur für diesen lokalen Test. Auf Quaxly kommen die Werte später
# als echte Umgebungsvariablen hinein.
os.environ["RESTOCK_ROLE_ID"] = "1533211830791438366"
os.environ["DEAL_ROLE_ID"] = "1533211924827996262"
os.environ["PREORDER_ROLE_ID"] = "1533211984772862102"

from database import ProductChange
from models import Product
from notifier import send_product_change


def make_product(title: str, product_id: str, *, preorder: bool = False) -> Product:
    return Product(
        shop="Demo Shop",
        product_id=product_id,
        title=title,
        url="https://example.com/rollen-test",
        price="CHF 69.90",
        status="available",
        is_preorder=preorder,
        image_url=None,
    )


def main() -> None:
    tests = [
        ProductChange(
            "restock",
            make_product(
                "Pokémon TCG Journey Together Elite Trainer Box (DE)",
                "role-restock-test",
            ),
            old_status="unavailable",
        ),
        ProductChange(
            "deal",
            make_product(
                "Pokémon TCG White Flare Booster Display (JP)",
                "role-deal-test",
            ),
            old_price="CHF 89.90",
        ),
        ProductChange(
            "new_preorder",
            make_product(
                "Pokémon TCG Mega Evolution Booster Display (EN)",
                "role-preorder-test",
                preorder=True,
            ),
        ),
    ]

    for change in tests:
        send_product_change(change)

    print("[OK] Restock-, Deal- und Vorbestellungs-Ping wurden gesendet.")


if __name__ == "__main__":
    main()
