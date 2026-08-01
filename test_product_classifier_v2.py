from product_classifier import classify_product


SAMPLES = [
    ("Pokémon TCG Journey Together Elite Trainer Box (DE)", "Journey Together", "Elite Trainer Box", "DE"),
    ("Pokémon TCG White Flare Booster Display (JP)", "White Flare", "Booster Display", "JP"),
    ("Pokémon Prismatic Evolutions Booster Bundle (EN)", "Prismatic Evolutions", "Booster Bundle", "EN"),
    ("Pokémon Mega-Mondschein ex Tin (FR)", "Mega-Mondschein ex", "Tin", "FR"),
    ("Pokémon 151 Ultra Premium Collection (EN)", "151", "Ultra Premium Collection", "EN"),
    ("Pokémon Crown Zenith Mini Tin (DE)", "Crown Zenith", "Mini Tin", "DE"),
    ("Pokémon VSTAR Universe S12a Booster Box JPN", "VSTAR Universe", "Booster Display", "JP"),
    ("Pokémon Surging Sparks 3-Pack Blister (DE)", "Surging Sparks", "Three-Pack Blister", "DE"),
]


failed = 0

for title, expected_set, expected_type, expected_language in SAMPLES:
    result = classify_product(title)
    print(title)
    print(f"  Set: {result.set_name or '-'}")
    print(f"  Typ: {result.product_type or '-'}")
    print(f"  Sprache: {result.language or '-'}")

    actual = (result.set_name, result.product_type, result.language)
    expected = (expected_set, expected_type, expected_language)
    if actual != expected:
        failed += 1
        print(f"  FEHLER: erwartet {expected}, erhalten {actual}")

if failed:
    raise RuntimeError(f"{failed} Klassifizierungs-Test(s) fehlgeschlagen.")

print(f"[OK] Alle {len(SAMPLES)} Klassifizierungs-Tests erfolgreich.")
