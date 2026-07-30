POKÉMON RADAR – FESTER PROJEKTORDNER MIT GIT

Ab jetzt arbeitest du nur noch mit diesem Ordner:

    PokemonRadar

WICHTIG: BESTEHENDE DATENBANK ÜBERNEHMEN

1. Beende den laufenden Bot mit Strg + C.
2. Öffne PokemonRadarV2_Phase11.
3. Kopiere dort den kompletten Ordner "data".
4. Füge ihn in diesen neuen Ordner "PokemonRadar" ein.
5. Ersetze den vorhandenen leeren data-Ordner.

Dadurch bleiben deine bereits gespeicherten Produkte erhalten.

SCHNELLTEST

    python app.py --scan-all-once

DAUERBETRIEB

    python app.py --run

Alternativ per Doppelklick:

    start_scan_once.bat
    start_radar.bat

GIT EINMALIG EINRICHTEN

1. Installiere "Git for Windows", falls Git noch nicht installiert ist.
2. Doppelklicke auf setup_git.bat.
3. Das Skript erstellt ein lokales Git-Projekt und speichert die erste Version.

WICHTIG ZU SENSIBLEN DATEIEN

Die Datei .env und die Datenbank unter data/ werden durch .gitignore nicht in Git gespeichert.
Dein Discord-Webhook und deine lokale Produktdatenbank bleiben dadurch privat.

OPTIONALE .ENV-DATEI

1. Kopiere .env.example und benenne die Kopie zu .env um.
2. Trage deinen Discord-Webhook ein.
3. Hinweis: Der aktuelle Code liest normale Windows-Umgebungsvariablen. Die .env-Datei ist
   bereits als sichere Vorlage enthalten und kann in einem späteren Update automatisch geladen werden.

ALTE ORDNER

Wenn der Test im neuen PokemonRadar-Ordner erfolgreich war und die Datenbank übernommen wurde,
kannst du Phase1 bis Phase10 löschen. Phase11 solltest du noch einige Tage als Sicherung behalten.
