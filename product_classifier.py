from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class ProductClassification:
    set_name: str | None
    product_type: str | None
    language: str | None


# Reihenfolge ist wichtig: spezifische Namen stehen vor allgemeinen Begriffen.
SET_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Scarlet & Violet
    ("Prismatic Evolutions", ("prismatic evolutions", "prismatische entwicklungen")),
    ("Journey Together", ("journey together", "gemeinsam unterwegs")),
    ("Destined Rivals", ("destined rivals", "ewige rivalen")),
    ("Black Bolt", ("black bolt", "schwarzer blitz", "schwarzes blitz")),
    ("White Flare", ("white flare", "weisse flammen", "weiße flammen")),
    ("Surging Sparks", ("surging sparks", "sturmische funken", "stürmische funken")),
    ("Stellar Crown", ("stellar crown", "stellarkrone")),
    ("Shrouded Fable", ("shrouded fable", "nebel der sagen")),
    ("Twilight Masquerade", ("twilight masquerade", "maskerade im zwielicht")),
    ("Temporal Forces", ("temporal forces", "gewalten der zeit")),
    ("Paldean Fates", ("paldean fates", "paldeas schicksale")),
    ("Paradox Rift", ("paradox rift", "paradoxrift")),
    ("151", ("pokemon 151", "pokémon 151", "sv2a 151", "scarlet violet 151")),
    ("Obsidian Flames", ("obsidian flames", "obsidianflammen")),
    ("Paldea Evolved", ("paldea evolved", "entwicklungen in paldea")),
    ("Scarlet & Violet Base", ("scarlet violet base", "karmesin purpur basis", "sv base")),

    # Sword & Shield
    ("Crown Zenith", ("crown zenith", "zenit der konige", "zenit der könige")),
    ("Silver Tempest", ("silver tempest", "silberne sturmwinde")),
    ("Lost Origin", ("lost origin", "verlorener ursprung")),
    ("Pokémon GO", ("pokemon go", "pokémon go")),
    ("Astral Radiance", ("astral radiance", "astralglanz")),
    ("Brilliant Stars", ("brilliant stars", "strahlende sterne")),
    ("Fusion Strike", ("fusion strike", "fusionsangriff")),
    ("Celebrations", ("celebrations",)),
    ("Evolving Skies", ("evolving skies", "entwicklungen in paldea", "drachenwandel")),
    ("Chilling Reign", ("chilling reign", "schaurige herrschaft")),
    ("Battle Styles", ("battle styles", "kampfstile")),
    ("Shining Fates", ("shining fates", "glanzendes schicksal")),
    ("Vivid Voltage", ("vivid voltage", "farbenschock")),
    ("Champion's Path", ("champions path", "weg des champs")),
    ("Darkness Ablaze", ("darkness ablaze", "flammende finsternis")),
    ("Rebel Clash", ("rebel clash", "clash der rebellen")),
    ("Sword & Shield Base", ("sword shield base", "schwert schild basis")),

    # Sun & Moon / ältere Sets
    ("Cosmic Eclipse", ("cosmic eclipse", "welten im wandel")),
    ("Hidden Fates", ("hidden fates", "verborgene schicksale")),
    ("Unified Minds", ("unified minds", "bund der gleichgesinnten")),
    ("Unbroken Bonds", ("unbroken bonds", "krafte im einklang", "kräfte im einklang")),
    ("Team Up", ("team up",)),
    ("Lost Thunder", ("lost thunder", "echo des donners")),
    ("Celestial Storm", ("celestial storm", "sturm am firmament")),
    ("Forbidden Light", ("forbidden light", "grauen der lichtfinsternis")),
    ("Ultra Prism", ("ultra prism", "ultra-prisma")),
    ("Crimson Invasion", ("crimson invasion", "aufziehen der sturmroten")),
    ("Burning Shadows", ("burning shadows", "nacht in flammen")),
    ("Guardians Rising", ("guardians rising", "stunde der wachter")),

    # Japanische Spezialsets und aktuelle Reihen
    ("Mega Evolution", ("mega evolution", "mega entwicklung", "mega-entwicklung")),
    ("Mega Brave", ("mega brave",)),
    ("Mega Symphonia", ("mega symphonia",)),
    ("Mega Dream ex", ("mega dream ex",)),
    ("Mega-Mondschein ex", ("mega mondschein ex", "mega-mondschein ex")),
    ("VSTAR Universe", ("vstar universe", "s12a")),
    ("Paradise Dragona", ("paradise dragona", "sv7a")),
    ("Terastal Festival ex", ("terastal festival ex", "sv8a")),
    ("Battle Partners", ("battle partners", "sv9")),
    ("Heat Wave Arena", ("heat wave arena", "sv9a")),
    ("The Glory of Team Rocket", ("glory of team rocket", "rocket glory", "sv10")),
    ("Night Wanderer", ("night wanderer", "sv6a")),
    ("Crimson Haze", ("crimson haze", "sv5a")),
    ("Wild Force", ("wild force", "sv5k")),
    ("Cyber Judge", ("cyber judge", "sv5m")),
    ("Shiny Treasure ex", ("shiny treasure ex", "sv4a")),
    ("Ancient Roar", ("ancient roar", "sv4k")),
    ("Future Flash", ("future flash", "sv4m")),
    ("Raging Surf", ("raging surf", "sv3a")),
    ("Pokémon Card 151", ("pokemon card 151", "sv2a")),
    ("Clay Burst", ("clay burst", "sv2d")),
    ("Snow Hazard", ("snow hazard", "sv2p")),
    ("Triple Beat", ("triple beat", "sv1a")),
    ("Scarlet ex", ("scarlet ex", "sv1s")),
    ("Violet ex", ("violet ex", "sv1v")),

    # Weitere bekannte Spezialprodukte
    ("Classic Collection", ("pokemon trading card game classic", "pokemon tcg classic")),
    ("Detective Pikachu", ("detective pikachu",)),
)


TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Ultra Premium Collection", ("ultra premium collection", "ultra-premium collection", "upc")),
    ("Premium Collection", ("premium collection",)),
    ("Super Premium Collection", ("super premium collection",)),
    ("Elite Trainer Box", ("elite trainer box", "pokemon center etb", " etb ")),
    ("Booster Display", ("booster display", "display box", "booster box", " display ")),
    ("Booster Bundle", ("booster bundle",)),
    ("Build & Battle Stadium", ("build battle stadium", "build & battle stadium")),
    ("Build & Battle Box", ("build battle box", "build & battle box")),
    ("Trainer Toolkit", ("trainer toolkit",)),
    ("Collection Box", ("collection box", "kollektion box", "collection set")),
    ("Ex Box", (" ex box", "ex-box")),
    ("Battle Deck", ("battle deck", "kampfdeck")),
    ("League Battle Deck", ("league battle deck",)),
    ("Theme Deck", ("theme deck",)),
    ("Deck", (" deck", "deck ")),
    ("Mini Tin", ("mini tin",)),
    ("Tin", (" tin", "tin ")),
    ("Three-Pack Blister", ("3 pack blister", "3-pack blister", "three pack blister")),
    ("Two-Pack Blister", ("2 pack blister", "2-pack blister", "two pack blister")),
    ("Blister", (" blister", "blister ")),
    ("Sleeved Booster", ("sleeved booster",)),
    ("Booster Pack", ("booster pack", " booster", "booster ")),
    ("Card Binder Collection", ("binder collection", "sammelalbum collection")),
    ("Poster Collection", ("poster collection",)),
    ("Sticker Collection", ("sticker collection",)),
    ("Figure Collection", ("figure collection", "figuren collection")),
    ("Accessory", ("sleeves", "deck box", "binder", "playmat", "kartenhullen", "kartenhüllen")),
)


LANGUAGE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("DE", ("(de)", "[de]", " deutsch", "german", "deutsche ausgabe")),
    ("EN", ("(en)", "[en]", " english", "englisch", "english edition")),
    ("JP", ("(jp)", "(jpn)", "[jp]", " japanese", "japanisch", "jpn", "japanese edition")),
    ("FR", ("(fr)", "[fr]", " french", "franzosisch", "französisch", "francais", "français")),
    ("IT", ("(it)", "[it]", " italian", "italienisch")),
    ("KR", ("(kr)", "[kr]", " korean", "koreanisch")),
    ("CN", ("(cn)", "[cn]", " chinese", "chinesisch")),
    ("ES", ("(es)", "[es]", " spanish", "spanisch")),
)


def _normalise(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[_/|:]+", " ", text)
    text = re.sub(r"[-–—]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return f" {text.strip()} "


def _match_first(
    text: str,
    patterns: tuple[tuple[str, tuple[str, ...]], ...],
) -> str | None:
    for label, aliases in patterns:
        if any(alias in text for alias in aliases):
            return label
    return None


def classify_product(title: str) -> ProductClassification:
    text = _normalise(title)
    return ProductClassification(
        set_name=_match_first(text, SET_PATTERNS),
        product_type=_match_first(text, TYPE_PATTERNS),
        language=_match_first(text, LANGUAGE_PATTERNS),
    )
