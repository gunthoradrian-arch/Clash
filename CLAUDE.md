# Projektkontext

Wahrnehmungs- und Entscheidungsschicht für einen Clash-Royale-Bot. Diese Datei
gibt einer neuen Claude-Code-Sitzung den Stand, ohne dass jemand die
Vorgeschichte nacherzählen muss.

## Umgebung

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
git clone --depth 1 https://github.com/wty-yy/Clash-Royale-Detection-Dataset.git ../crds
```

Der Datensatz (~1,3 GB) liegt bewusst **außerhalb** des Repos und ist in
`.gitignore`. Pfad wird überall als `--dataset-root ../crds` übergeben.

## Tests

Alle Selbsttests laufen ohne GPU, Emulator oder Spiel:

```bash
python tools/forward_selftest.py    # Vorwärtsmodell, 12
python tools/opponent_selftest.py   # Gegnermodell, 10
python tools/decision_selftest.py   # Suche + Kalibrierung, 10
python tools/tracker_selftest.py    # Tracking, 7
python tools/pipeline_selftest.py   # ganze Schleife, 6
```

Es gibt kein pytest — die Tests sind eigenständige Skripte mit Rückgabecode.
**Vor jedem Commit alle fünf laufen lassen.**

## Wie hier getestet wird

Sollwerte kommen aus den **Spielregeln oder den Kampfwerten**, von Hand
gerechnet — nie aus einer früheren Ausgabe des Modells. Sonst zementiert man
den eigenen Fehler.

Das hat sich mehrfach ausgezahlt: Von acht fehlgeschlagenen Tests in der
Entwicklung waren **fünf falsche Testerwartungen und drei echte Codefehler**.
Bei einem Fehlschlag also erst nachrechnen, dann den Code anfassen.

## Feste Konventionen

| Sache | Konvention |
|---|---|
| Koordinaten | **Kacheln** (18 × 32), nicht Pixel. Umrechnung: `arena.px_to_tile` |
| Seiten | `0` = wir, `1` = Gegner (heißt im Labelformat `blong`) |
| Referenzbild | 568 × 896 — Auflösung von Cutouts und Hintergründen |
| Klassen-IDs | Aus `crbot/classes.py`. **Niemals verschieben**, nur hinten anhängen |
| Kampfwerte | `crbot/data/unit_stats.json`, eingecheckt. Neu bauen mit `tools/build_cardstats.py` |

## Architekturentscheidungen (nicht ohne Grund umwerfen)

**Drei Teilprobleme, drei Lösungen.** Handkarten per Pixel-Fingerprint, Elixir
und Turm-HP per festem Pixelread plus Simulation, nur die Arena-Einheiten per
Detektor. Wer alles durch ein Netz jagt, wird langsamer und schlechter.

**Team gehört nicht in die Klasse.** Sonst muss das Netz „Ritter" zweimal
lernen. `blong` ist ein eigenes Zustandsfeld; die HP-Balkenfarbe verrät das Team
ohnehin billiger.

**Trainingsdaten werden erzeugt, nicht gelabelt.** Von 154 Einheitenklassen
haben in den echten Frames nur 40 mehr als 200 Beispiele. Handlabeln schließt
die Lücke nicht.

**Validiert wird nur auf echten Bildern.** Ein mAP auf synthetischen Daten misst
den Generator, nicht das Modell.

**Was nachschlagbar ist, wird nicht gelernt.** HP, DPS, Reichweite, Tempo stehen
in der Tabelle.

**Rechenleistung wird über Suche zu Spielstärke, nicht über größere Netze.**
Das Vorwärtsmodell rollt Kandidaten batchweise aus.

## Bekannte Grenzen

- Die Suche simuliert **eine** gegnerische Antwort mit, pessimistisch gewählt
  (härteste bezahlbare Karte). Keine Vorhersage — dafür fehlen Replay-Daten.
- Vorwärtsmodell ohne Wegfindung um Gebäude, Aggro-Wechsel, Ladeangriffe,
  Verlangsamung, Schilde, Spawner. Über 3–8 s brauchbar, über 20 s nicht.
- Zauber mit Wirkung über Zeit (Gift, Tornado, Erdbeben) haben Radius und
  Kosten, aber Schaden 0 — der steckt im Flächeneffekt-Objekt.
- Schadenszuordnung in der Nachanalyse ist eine Heuristik (Reichweite + DPS).

## Was noch den PC braucht

Detektor trainieren (GPU), Capture und Eingabe (scrcpy/minitouch statt ADB),
Handkarten-Fingerprint, Cutout-Ernte, Torch-Backend. Details in
`docs/handover.md`.

## Stil

Deutsch in Kommentaren, Docstrings und Commit-Nachrichten. Kommentare erklären
**warum**, nicht was. Grenzen und Näherungen gehören dokumentiert, nicht
versteckt.
