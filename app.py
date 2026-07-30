import argparse
import json
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests

from config import SCAN_INTERVAL_SECONDS
from database import has_shop_products, init_db, reset_demo_product, save_product
from models import Product
from notifier import WebhookError, send_product_change, send_test_message
from shops.shopify import parse_shopify_products, scan_shopify
from shops.wog import SHOP_NAME as WOG_SHOP_NAME
from shops.wog import scan_wog
from shops.woocommerce import parse_woocommerce_html, scan_woocommerce
from shops.prestashop import parse_prestashop_html, scan_prestashop
from shops_config import PRESTASHOP_SHOPS, SHOPIFY_SHOPS, WOOCOMMERCE_SHOPS
from shop_detector import detect_shop_type, scanner_name


def run_database_demo(send_discord: bool) -> None:
    reset_demo_product()
    unavailable = Product("Demo Shop", "demo-001", "Pokémon TCG Demo Elite Trainer Box", "https://example.com/pokemon-demo", "CHF 59.90", "unavailable")
    available = Product("Demo Shop", "demo-001", "Pokémon TCG Demo Elite Trainer Box", "https://example.com/pokemon-demo", "CHF 59.90", "available")
    first_changes = save_product(unavailable, initial_scan=True)
    print(f"[TEST 1] Erstscan: {len(first_changes)} Meldungen (erwartet: 0)")
    restock_changes = save_product(available, initial_scan=False)
    print(f"[TEST 2] Restock: {len(restock_changes)} Änderung(en) (erwartet: 1)")
    for change in restock_changes:
        print(f"         erkannt: {change.kind}")
        if send_discord:
            send_product_change(change)
    print("[OK] Datenbank-Logik funktioniert.")


def process_products(shop_name: str, products: list[Product]) -> dict[str, int]:
    initial_scan = not has_shop_products(shop_name)
    if initial_scan:
        print(f"[{shop_name}] Erster Scan: Produkte werden nur gespeichert, ohne Meldungsflut.")

    counts = {"available": 0, "unavailable": 0, "unknown": 0}
    sent = 0
    for product in products:
        counts[product.status] += 1
        for change in save_product(product, initial_scan=initial_scan):
            send_product_change(change)
            sent += 1
            print(f"[{shop_name}] Meldung gesendet: {change.kind} – {product.title}")

    print(f"[{shop_name}] {len(products)} Pokémon-TCG-Produkte erkannt.")
    print(f"[{shop_name}] Status: {counts['available']} verfügbar, {counts['unavailable']} nicht verfügbar, {counts['unknown']} unbekannt.")
    print(f"[{shop_name}] Discord-Meldungen in diesem Durchlauf: {sent}")
    return {"products": len(products), "notifications": sent}


def run_wog_once() -> None:
    process_products(WOG_SHOP_NAME, scan_wog())


def run_shopify_test() -> None:
    sample = {
        "products": [
            {
                "id": 1001,
                "title": "Pokémon TCG Scarlet & Violet Booster Display",
                "handle": "pokemon-booster-display",
                "product_type": "Trading Cards",
                "vendor": "Pokémon",
                "tags": ["Pokemon", "TCG"],
                "variants": [{"price": "149.90", "available": True}],
                "images": [{"src": "https://example.com/display.jpg"}],
            },
            {
                "id": 1002,
                "title": "Pokémon Pikachu Plüschfigur",
                "handle": "pikachu-pluesch",
                "product_type": "Plüsch",
                "vendor": "Pokémon",
                "tags": ["Pokemon"],
                "variants": [{"price": "29.90", "available": True}],
                "images": [],
            },
        ]
    }
    products = parse_shopify_products(sample, shop_name="Shopify Test", shop_url="https://example.com")
    print(f"[SHOPIFY-TEST] Erkannte TCG-Produkte: {len(products)} (erwartet: 1)")
    for product in products:
        print(f"[SHOPIFY-TEST] {product.title} | {product.price} | {product.status}")
    if len(products) != 1:
        raise RuntimeError("Shopify-Filtertest ist fehlgeschlagen.")
    print("[OK] Shopify-Scanner und Ausschlussfilter funktionieren.")


def run_shopify_once(shop_name: str, shop_url: str) -> None:
    products = scan_shopify(shop_name, shop_url)
    process_products(shop_name, products)



def run_all_shopify_once() -> None:
    print(f"[SHOPIFY] Starte {len(SHOPIFY_SHOPS)} konfigurierte Shops.")
    succeeded = 0
    failed = 0
    for shop in SHOPIFY_SHOPS:
        name = shop["name"]
        url = shop["url"]
        print(f"\n[{name}] Scan startet …")
        try:
            products = scan_shopify(name, url)
            process_products(name, products)
            succeeded += 1
        except Exception as error:
            failed += 1
            print(f"[{name}] FEHLER: {type(error).__name__}: {error}")
    print(f"\n[SHOPIFY] Fertig: {succeeded} erfolgreich, {failed} fehlgeschlagen.")



def run_woocommerce_test() -> None:
    sample = """
    <ul class="products">
      <li class="product post-2001">
        <a class="woocommerce-loop-product__link" href="https://example.com/produkt/pokemon-etb/">
          <h2 class="woocommerce-loop-product__title">Pokémon TCG Elite Trainer Box</h2>
          <img src="https://example.com/etb.jpg">
        </a>
        <span class="price">CHF 59.95</span>
        <a class="add_to_cart_button">In den Warenkorb</a>
      </li>
      <li class="product post-2002">
        <a class="woocommerce-loop-product__link" href="https://example.com/produkt/pikachu-pluesch/">
          <h2 class="woocommerce-loop-product__title">Pokémon Pikachu Plüschfigur</h2>
        </a>
        <span class="price">CHF 24.95</span>
      </li>
    </ul>
    """
    products = parse_woocommerce_html(sample, shop_name="WooCommerce Test", page_url="https://example.com")
    print(f"[WOOCOMMERCE-TEST] Erkannte TCG-Produkte: {len(products)} (erwartet: 1)")
    for product in products:
        print(f"[WOOCOMMERCE-TEST] {product.title} | {product.price} | {product.status}")
    if len(products) != 1 or products[0].status != "available":
        raise RuntimeError("WooCommerce-Filtertest ist fehlgeschlagen.")
    print("[OK] WooCommerce-Scanner und Ausschlussfilter funktionieren.")


def run_all_woocommerce_once() -> None:
    print(f"[WOOCOMMERCE] Starte {len(WOOCOMMERCE_SHOPS)} konfigurierte Shops.")
    succeeded = 0
    failed = 0
    for shop in WOOCOMMERCE_SHOPS:
        name = shop["name"]
        print(f"\n[{name}] Scan startet …")
        try:
            products = scan_woocommerce(name, shop["url"], max_pages=int(shop.get("max_pages", 10)))
            process_products(name, products)
            succeeded += 1
        except Exception as error:
            failed += 1
            print(f"[{name}] FEHLER: {type(error).__name__}: {error}")
    print(f"\n[WOOCOMMERCE] Fertig: {succeeded} erfolgreich, {failed} fehlgeschlagen.")



def run_prestashop_test() -> None:
    sample = """
    <div class="products">
      <article class="product-miniature js-product-miniature" data-id-product="3001">
        <a class="product-thumbnail" href="https://example.com/pokemon-booster.html">
          <img src="https://example.com/booster.jpg" alt="Pokémon KP10 Booster DE">
        </a>
        <h2 class="product-title"><a href="https://example.com/pokemon-booster.html">Pokémon KP10 Booster DE</a></h2>
        <div class="product-price-and-shipping"><span class="price">CHF 9,95</span></div>
        <span>Auf Lager</span>
      </article>
      <article class="product-miniature js-product-miniature" data-id-product="3002">
        <h2 class="product-title"><a href="https://example.com/pikachu-pluesch.html">Pokémon Pikachu Plüschfigur</a></h2>
        <span class="price">CHF 24,95</span>
      </article>
    </div>
    """
    products = parse_prestashop_html(sample, shop_name="PrestaShop Test", page_url="https://example.com")
    print(f"[PRESTASHOP-TEST] Erkannte TCG-Produkte: {len(products)} (erwartet: 1)")
    for product in products:
        print(f"[PRESTASHOP-TEST] {product.title} | {product.price} | {product.status}")
    if len(products) != 1 or products[0].status != "available":
        raise RuntimeError("PrestaShop-Filtertest ist fehlgeschlagen.")
    print("[OK] PrestaShop-Scanner und Ausschlussfilter funktionieren.")


def run_all_prestashop_once() -> None:
    print(f"[PRESTASHOP] Starte {len(PRESTASHOP_SHOPS)} konfigurierte Shops.")
    succeeded = 0
    failed = 0
    for shop in PRESTASHOP_SHOPS:
        name = shop["name"]
        print(f"\n[{name}] Scan startet …")
        try:
            products = scan_prestashop(name, shop["url"], max_pages=int(shop.get("max_pages", 70)))
            process_products(name, products)
            succeeded += 1
        except Exception as error:
            failed += 1
            print(f"[{name}] FEHLER: {type(error).__name__}: {error}")
    print(f"\n[PRESTASHOP] Fertig: {succeeded} erfolgreich, {failed} fehlgeschlagen.")


def build_scan_jobs() -> list[dict[str, object]]:
    """Erstellt die Liste aller konfigurierten Shop-Scans."""
    jobs: list[dict[str, object]] = [
        {
            "name": WOG_SHOP_NAME,
            "scanner": scan_wog,
        }
    ]

    for shop in SHOPIFY_SHOPS:
        jobs.append(
            {
                "name": shop["name"],
                "scanner": lambda shop=shop: scan_shopify(shop["name"], shop["url"]),
            }
        )

    for shop in WOOCOMMERCE_SHOPS:
        jobs.append(
            {
                "name": shop["name"],
                "scanner": lambda shop=shop: scan_woocommerce(
                    shop["name"],
                    shop["url"],
                    max_pages=int(shop.get("max_pages", 10)),
                ),
            }
        )

    for shop in PRESTASHOP_SHOPS:
        jobs.append(
            {
                "name": shop["name"],
                "scanner": lambda shop=shop: scan_prestashop(
                    shop["name"],
                    shop["url"],
                    max_pages=int(shop.get("max_pages", 70)),
                ),
            }
        )

    return jobs


def run_scan_all_once(max_workers: int = 5) -> dict[str, int]:
    """Lädt mehrere Shops parallel und verarbeitet Ergebnisse kontrolliert.

    Nur die Netzwerkabfragen laufen gleichzeitig. Datenbankzugriffe und
    Discord-Meldungen werden danach im Hauptthread verarbeitet. Dadurch
    bleibt SQLite zuverlässig, während langsame Shop-Antworten nicht mehr
    alle anderen Shops blockieren.
    """
    jobs = build_scan_jobs()
    workers = max(1, min(int(max_workers), len(jobs)))

    print(f"[ALLE SHOPS] Starte {len(jobs)} konfigurierte Shops.")
    print(f"[PARALLEL] Bis zu {workers} Shops werden gleichzeitig geladen.")

    succeeded = 0
    failed = 0
    total_products = 0
    total_notifications = 0
    failed_names: list[str] = []
    started = time.monotonic()

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="shop-scan") as executor:
        future_to_name = {}
        for job in jobs:
            name = str(job["name"])
            scanner = job["scanner"]
            print(f"[{name}] Scan eingeplant …")
            future = executor.submit(scanner)
            future_to_name[future] = name

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            print(f"\n[{name}] Download abgeschlossen – Produkte werden verarbeitet …")
            try:
                products = future.result()
                result = process_products(name, products)
                total_products += result["products"]
                total_notifications += result["notifications"]
                succeeded += 1
            except Exception as error:
                failed += 1
                failed_names.append(name)
                print(f"[{name}] FEHLER: {type(error).__name__}: {error}")

    duration = time.monotonic() - started
    print("\n" + "=" * 58)
    print("[GESAMTÜBERSICHT]")
    print(f"Shops erfolgreich: {succeeded}")
    print(f"Shops fehlgeschlagen: {failed}")
    print(f"Produkte geprüft: {total_products}")
    print(f"Discord-Meldungen: {total_notifications}")
    print(f"Scan-Dauer: {duration:.1f} Sekunden")
    if failed_names:
        print(f"Fehlerhafte Shops: {', '.join(failed_names)}")
    print("=" * 58)
    return {
        "succeeded": succeeded,
        "failed": failed,
        "products": total_products,
        "notifications": total_notifications,
    }



def run_shop_detection(url: str) -> None:
    print("=" * 58)
    print("[SHOP-DETEKTIV] Shop wird analysiert …")
    print(f"Eingegebene URL: {url}")
    result = detect_shop_type(url)
    print(f"Erreichte URL:   {result.final_url}")
    print("-" * 58)
    if result.shop_type == "unknown":
        print("[?] Shopsystem konnte nicht sicher erkannt werden.")
        print("    Das bedeutet nicht automatisch, dass der Shop ungeeignet ist.")
        print("    Möglicherweise braucht er einen eigenen Scanner.")
    else:
        labels = {
            "shopify": "Shopify",
            "woocommerce": "WooCommerce",
            "prestashop": "PrestaShop",
        }
        print(f"[OK] Shopsystem erkannt: {labels[result.shop_type]}")
        print(f"Sicherheit:              {result.confidence}")
        print(f"Empfohlener Scanner:     {scanner_name(result.shop_type)}")
        print(f"Erkannte Hinweise:       {', '.join(result.evidence)}")
    print("=" * 58)



def suggested_shop_name(url: str) -> str:
    """Erstellt aus einer URL einen gut lesbaren vorläufigen Shopnamen."""
    hostname = (urlparse(url).hostname or "Neuer Shop").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    base = hostname.split(".")[0].replace("-", " ").replace("_", " ")
    return base.title() or "Neuer Shop"


def normalized_hostname(url: str) -> str:
    """Vereinheitlicht eine Shop-Domain für die Duplikatprüfung."""
    hostname = (urlparse(url).hostname or "").lower().strip()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def find_configured_shop(url: str) -> dict[str, str] | None:
    """Sucht einen bereits konfigurierten Shop mit derselben Domain."""
    wanted_host = normalized_hostname(url)
    for shop_type, shops in (
        ("shopify", SHOPIFY_SHOPS),
        ("woocommerce", WOOCOMMERCE_SHOPS),
        ("prestashop", PRESTASHOP_SHOPS),
    ):
        for shop in shops:
            if normalized_hostname(shop["url"]) == wanted_host:
                return {
                    "name": shop["name"],
                    "url": shop["url"],
                    "shop_type": shop_type,
                }
    return None


def save_shop_to_config(shop_type: str, shop_name: str, shop_url: str) -> None:
    """Fügt einen geprüften Shop sicher in shops_config.py ein."""
    variable_names = {
        "shopify": "SHOPIFY_SHOPS",
        "woocommerce": "WOOCOMMERCE_SHOPS",
        "prestashop": "PRESTASHOP_SHOPS",
    }
    variable_name = variable_names[shop_type]
    config_path = Path(__file__).with_name("shops_config.py")
    content = config_path.read_text(encoding="utf-8")

    entry: dict[str, object] = {"name": shop_name, "url": shop_url}
    if shop_type == "woocommerce":
        entry["max_pages"] = 10
    elif shop_type == "prestashop":
        entry["max_pages"] = 70

    pattern = re.compile(
        rf"(?ms)^(?P<head>{variable_name}\s*=\s*\[)(?P<body>.*?)(?P<tail>^\])"
    )
    match = pattern.search(content)
    if not match:
        raise RuntimeError(f"Bereich {variable_name} wurde in shops_config.py nicht gefunden.")

    entry_text = "    " + json.dumps(entry, ensure_ascii=False) + ",\n"
    body = match.group("body")
    if body and not body.endswith("\n"):
        body += "\n"

    updated_block = match.group("head") + body + entry_text + match.group("tail")
    updated_content = content[: match.start()] + updated_block + content[match.end() :]

    backup_path = config_path.with_suffix(".py.bak")
    backup_path.write_text(content, encoding="utf-8")
    config_path.write_text(updated_content, encoding="utf-8")


def run_add_shop(url: str) -> None:
    """Erkennt, testet und speichert einen Shop nach Bestätigung."""
    print("=" * 58)
    print("[SHOP-IMPORTER] Neuer Shop wird geprüft …")
    print(f"Eingegebene URL: {url}")

    detection = detect_shop_type(url)
    print(f"Erreichte URL:   {detection.final_url}")
    print("-" * 58)

    if detection.shop_type == "unknown":
        print("[STOP] Shopsystem konnte nicht sicher erkannt werden.")
        print("       Der Shop wurde nicht getestet und nicht gespeichert.")
        print("=" * 58)
        return

    labels = {
        "shopify": "Shopify",
        "woocommerce": "WooCommerce",
        "prestashop": "PrestaShop",
    }
    shop_name = suggested_shop_name(detection.final_url)

    print(f"[OK] Shopsystem erkannt: {labels[detection.shop_type]}")
    print(f"Vorläufiger Shopname:    {shop_name}")
    print(f"Empfohlener Scanner:     {scanner_name(detection.shop_type)}")
    print("-" * 58)
    print("[TESTSCAN] Pokémon-Produkte werden gesucht …")

    started = time.monotonic()
    if detection.shop_type == "shopify":
        products = scan_shopify(shop_name, detection.final_url)
    elif detection.shop_type == "woocommerce":
        products = scan_woocommerce(shop_name, detection.final_url, max_pages=10)
    else:
        products = scan_prestashop(shop_name, detection.final_url, max_pages=70)
    duration = time.monotonic() - started

    available = sum(product.status == "available" for product in products)
    unavailable = sum(product.status == "unavailable" for product in products)
    unknown = sum(product.status == "unknown" for product in products)

    if not products:
        print("[WARNUNG] Scanner lief, aber es wurden keine Pokémon-TCG-Produkte gefunden.")
        print("          Der Shop wurde nicht gespeichert.")
        print("=" * 58)
        return

    print(f"[OK] Testscan erfolgreich: {len(products)} Pokémon-TCG-Produkte gefunden.")
    print(f"Status: {available} verfügbar, {unavailable} nicht verfügbar, {unknown} unbekannt.")
    print(f"Dauer:  {duration:.1f} Sekunden")

    configured = find_configured_shop(detection.final_url)
    if configured:
        print("-" * 58)
        print(f"[INFO] Dieser Shop ist bereits als '{configured['name']}' konfiguriert.")
        print(f"       Gespeicherte URL: {configured['url']}")
        print("       Es wurde kein Duplikat angelegt.")
        print("=" * 58)
        return

    print("-" * 58)
    answer = input("Shop dauerhaft hinzufügen? (J/N): ").strip().lower()
    if answer not in {"j", "ja", "y", "yes"}:
        print("[INFO] Abgebrochen. Der Shop wurde nicht gespeichert.")
        print("=" * 58)
        return

    save_shop_to_config(detection.shop_type, shop_name, detection.final_url)
    print(f"[OK] '{shop_name}' wurde in shops_config.py gespeichert.")
    print("[INFO] Eine Sicherung wurde als shops_config.py.bak erstellt.")
    print("[INFO] Beim nächsten Scan wird der neue Shop automatisch berücksichtigt.")
    print("=" * 58)

def timestamp() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def run_forever(interval_seconds: int, max_workers: int = 5) -> None:
    interval_seconds = max(60, int(interval_seconds))
    round_number = 0
    print(f"[{timestamp()}] [DAUERBETRIEB] Pokémon Radar wurde gestartet.")
    print(f"[{timestamp()}] [DAUERBETRIEB] Scan-Intervall: {interval_seconds} Sekunden.")
    print(f"[{timestamp()}] [DAUERBETRIEB] Beenden mit Strg + C.")

    try:
        while True:
            round_number += 1
            started = time.monotonic()
            print("\n" + "#" * 58)
            print(f"[{timestamp()}] [RUNDE {round_number}] Scan beginnt.")
            run_scan_all_once(max_workers)
            duration = int(time.monotonic() - started)
            next_start = datetime.now() + timedelta(seconds=interval_seconds)
            print(f"[{timestamp()}] [RUNDE {round_number}] Dauer: {duration} Sekunden.")
            print(f"[{timestamp()}] [DAUERBETRIEB] Nächster Scan ungefähr um {next_start.strftime('%H:%M:%S')}.")
            print("#" * 58)
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print(f"\n[{timestamp()}] [DAUERBETRIEB] Sauber beendet. Bis zum nächsten Start!")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pokémon Radar V2")
    parser.add_argument("--test-webhook", action="store_true")
    parser.add_argument("--test-database", action="store_true")
    parser.add_argument("--test-restock-discord", action="store_true")
    parser.add_argument("--test-shopify", action="store_true")
    parser.add_argument("--test-woocommerce", action="store_true")
    parser.add_argument("--test-prestashop", action="store_true")
    parser.add_argument("--scan-wog-once", action="store_true")
    parser.add_argument("--scan-shopify-once", action="store_true")
    parser.add_argument("--scan-shopify-shops-once", action="store_true")
    parser.add_argument("--scan-woocommerce-shops-once", action="store_true")
    parser.add_argument("--scan-prestashop-shops-once", action="store_true")
    parser.add_argument("--scan-all-once", action="store_true")
    parser.add_argument("--detect-shop", metavar="URL", help="Shopsystem einer URL erkennen")
    parser.add_argument("--add-shop", metavar="URL", help="Shop erkennen, testen und nach Bestätigung speichern")
    parser.add_argument("--workers", type=int, default=5, help="Maximal gleichzeitig geladene Shops (Standard: 5)")
    parser.add_argument("--run", action="store_true", help="Alle Shops dauerhaft in einem Intervall scannen")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL_SECONDS, help="Wartezeit zwischen Scanrunden in Sekunden (mindestens 60)")
    parser.add_argument("--shop-name", default="Shopify Shop")
    parser.add_argument("--shop-url")
    args = parser.parse_args()

    init_db()
    print("[OK] Datenbank wurde vorbereitet.")

    try:
        if args.add_shop:
            run_add_shop(args.add_shop)
        elif args.detect_shop:
            run_shop_detection(args.detect_shop)
        elif args.test_webhook:
            send_test_message(); print("[OK] Testnachricht wurde an Discord gesendet.")
        elif args.test_database:
            run_database_demo(False)
        elif args.test_restock_discord:
            run_database_demo(True); print("[OK] Restock-Demo wurde an Discord gesendet.")
        elif args.test_shopify:
            run_shopify_test()
        elif args.test_woocommerce:
            run_woocommerce_test()
        elif args.test_prestashop:
            run_prestashop_test()
        elif args.scan_wog_once:
            run_wog_once()
        elif args.scan_shopify_shops_once:
            run_all_shopify_once()
        elif args.scan_woocommerce_shops_once:
            run_all_woocommerce_once()
        elif args.scan_prestashop_shops_once:
            run_all_prestashop_once()
        elif args.scan_all_once:
            run_scan_all_once(args.workers)
        elif args.run:
            if args.interval < 60:
                parser.error("Das Intervall muss mindestens 60 Sekunden betragen.")
            run_forever(args.interval, args.workers)
        elif args.scan_shopify_once:
            if not args.shop_url:
                parser.error("Für --scan-shopify-once fehlt --shop-url.")
            run_shopify_once(args.shop_name, args.shop_url)
        else:
            print("[INFO] PokemonRadar ist bereit.")
            print("[INFO] Shop erkennen:    python app.py --detect-shop https://shop.ch")
            print("[INFO] Shop testen:      python app.py --add-shop https://shop.ch")
            print("[INFO] Einmaliger Scan: python app.py --scan-all-once")
            print("[INFO] Dauerbetrieb:    python app.py --run")
    except WebhookError as error:
        print(f"[FEHLER] {error}"); return 1
    except requests.exceptions.HTTPError as error:
        print(f"[FEHLER] Shop antwortete mit einem HTTP-Fehler: {error}"); return 1
    except Exception as error:
        print(f"[FEHLER] {type(error).__name__}: {error}"); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
