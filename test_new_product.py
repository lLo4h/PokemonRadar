from __future__ import annotations

from contextlib import closing

from database import connect, init_db, save_product
from models import Product
from notifier import send_product_changes


SHOP = "Demo Shop"
PRODUCT_ID = "new-product-test-001"


def main() -> None:
    init_db()

    # Entfernt nur den künstlichen Testeintrag, damit der Test wiederholbar bleibt.
    with closing(connect()) as connection:
        connection.execute(
            "DELETE FROM products WHERE shop = ? AND product_id = ?",
            (SHOP, PRODUCT_ID),
        )
        connection.commit()

    product = Product(
        shop=SHOP,
        product_id=PRODUCT_ID,
        title="Pokémon TCG Automatischer Neuheiten-Test",
        url="https://example.com/pokemon-neuheit",
        price="CHF 49.90",
        status="available",
        is_preorder=False,
        image_url=None,
    )

    changes = save_product(product, initial_scan=False)

    if len(changes) != 1 or changes[0].kind != "new_product":
        kinds = [change.kind for change in changes]
        raise RuntimeError(
            f"Erwartet wurde genau new_product, erhalten: {kinds or 'keine Änderung'}"
        )

    sent = send_product_changes(SHOP, changes)
    print(f"[OK] Automatische Neuheit erkannt und in {sent} Discord-Meldung(en) gesendet.")


if __name__ == "__main__":
    main()
