# Clash Royale — Wahrnehmungsschicht

Erste Ebene eines Clash-Royale-Bots: **aus dem Bild einen brauchbaren
Spielzustand machen.** Policy und Lernen kommen später — ohne verlässliche
Wahrnehmung ist jede Entscheidungslogik Raten.

Der Teil ist auch für sich nützlich: Live-Overlay, Deck-Tracker,
Replay-Analyse. Selbst wenn der spielende Bot nie fertig wird.

---

## Leitentscheidungen

**Das Problem zerfällt in drei Teile mit drei verschiedenen besten Lösungen.**
Bestehende Bots vermischen sie und werden dadurch schlecht.

| Teilproblem | Lösung | Warum |
|---|---|---|
| Handkarten (4 feste Slots) | Pixel-Fingerprint | Feste Position, festes Rendering → deterministisch, ~0 ms |
| Elixir, Turm-HP, Timer | Feste Pixelreads + Simulation | Elixir regeneriert mit bekannter Rate |
| Einheiten auf der Arena | Objektdetektor | Das einzige echte CV-Problem |

**Das Team steht nicht in der Klasse.** Sonst müsste das Netz „Ritter" zweimal
unabhängig lernen und der Klassenraum verdoppelt sich. Stattdessen ist `blong`
ein eigenes Zustandsfeld — und im Zweifel verrät die Farbe des HP-Balkens
(blau/rot) das Team billiger als jedes gelernte Feature.

**Trainingsdaten werden erzeugt, nicht gelabelt.** Was man selbst
zusammensetzt, muss man nicht annotieren: Die Box fällt beim Einfügen ab und
ist pixelgenau. Das löst auch die Klassenschieflage, siehe unten.

**Validiert wird ausschließlich auf echten Bildern.** Ein mAP auf synthetischen
Daten misst nur, wie gut der Generator sich selbst reproduziert.

---

## Warum synthetisch — die Zahlen

Aus `docs/dataset-report.md`, gerechnet über den kompletten Quelldatensatz:

| Kennzahl | Wert |
|---|---|
| Echte gelabelte Arena-Frames | 6.966 |
| Annotierte Boxen | 117.294 |
| Davon **echte Einheiten** | 31.104 (**26,5 %**) |
| Klassen gesamt | 154 (+ 47 Platzhalter-Slots) |
| Klassen mit ≥ 200 Boxen | **40** |
| Cutouts für die Synthese | 4.654 |

Der Rest der Boxen sind Türme, HP-Balken und UI. Über 100 Klassen sind so dünn
belegt, dass ein Detektor sie nie zuverlässig lernt — und die Aufnahmen stammen
aus wenigen Decks weniger Kanäle, die Kartenauswahl ist entsprechend schief.
**Genau diese Lücke schließt der Generator**, weil er die Klassenverteilung
frei bestimmt.

---

## Was drin ist

```
crbot/
  labels.py     Labelformat (12 Felder = Ultralytics-Superset) + Cutout-Namensparser
  arena.py      Arena-Geometrie — aus 117k echten Boxen abgeleitet, nicht geschätzt
  cutouts.py    Cutout-Bibliothek, HP-Balken-Farbklassifikation, Schwarm-/Zauberlisten
  compose.py    Szenensynthese
  classes.py    Klassenliste als einzige Quelle der Wahrheit
  cardstats.py  Kampfwerte (HP, DPS, Reichweite, Tempo) aus dem Spieldaten-Dump
  matchlog.py   Match-Protokoll (JSONL) + Recorder
  postmortem.py Nachanalyse: woran lag die Niederlage?
  forward.py    Vorwärtsmodell — B Szenarien parallel durchrechnen (NumPy, batched)
  opponent.py   Deck-Zyklus und Elixir des Gegners mitzählen + Spekulations-EV
  search.py     Rollout-Suche: Kandidaten erzeugen, ausrollen, besten wählen
  calibration.py Quoten gegen die Wirklichkeit prüfen und korrigieren
  counterfactual.py  Was wäre besser gewesen? Züge gegen Alternativen
  tracker.py    Erkennungen über Frames verfolgen: Kennung, Tempo, Aussetzer
  pipeline.py   Die Schleife: Wahrnehmung → Tracker → Gegnermodell → Suche → Zug
  data/unit_stats.json   208 Einheiten, eingecheckt — zur Laufzeit kein Netz noetig
tools/
  analyze_dataset.py    Datensatz-Report (Klassen, Boxgrößen, Lücken)
  generate_dataset.py   Synthetische Bilder + Labels + Preview-Overlays
  prepare_real_val.py   Val-Set aus echten Frames, Split nach Episode
  harvest_cutouts.py    Eigene Cutouts per Hintergrundsubtraktion (+ Selbsttest)
  coverage_gap.py       Abgleich gegen die aktuelle Kartenliste -> Ernteliste
  bench_latency.py      Latenzbudget messen (Capture / Detektor / Eingabe)
  build_cardstats.py    Kampfwerte-Tabelle erzeugen (nach Balance-Updates neu)
  analyze_match.py      Nachanalyse eines Spiels (--demo laeuft ohne Emulator)
  forward_selftest.py   9 Szenarien mit handgerechnetem Sollwert
  opponent_selftest.py  10 Abläufe gegen die Spielregeln geprüft
  decision_selftest.py  Suche + Kalibrierung, 10 Prüfungen
  tracker_selftest.py   Tracking, 7 Prüfungen
  pipeline_selftest.py  Trockenlauf der ganzen Schleife, 6 Prüfungen
training/
  train_colab.ipynb     Training auf Gratis-GPU, läuft im Browser
scripts/
  setup.sh / setup.ps1  Umgebung einrichten und alle Tests laufen lassen
docs/
  dataset-report.md     Generierter Report
  handover.md           Übergabe: Stand, Reihenfolge, offene Punkte
CLAUDE.md               Projektkontext für eine Claude-Code-Sitzung
```

### Arena-Geometrie aus Daten

Alle Anker in `crbot/arena.py` sind Mediane über die echten Labels, kein
Augenmaß (Referenzsystem 568×896):

| Objekt | Position | Größe |
|---|---|---|
| Königsturm eigen | (284, 776) | 124×135 |
| Königsturm gegner | (284, 116) | 106×139 |
| Prinzessinnentürme eigen | (114 / 456, 684) | 92×105 |
| Prinzessinnentürme gegner | (112 / 455, 211) | 90×102 |
| Fluss | y = 448 | Brücken bei x = 114 / 456 |

Der Perspektiveffekt ist mit **~4 %** über die Feldhöhe klein — abgelesen am
Größenunterschied der beiden Prinzessinnenturm-Reihen.

> **Korrektur zu einer früheren Einschätzung:** Ich hatte zwei Detektoren nach
> Objektgröße empfohlen. Die Daten stützen das nur schwach — die Diagonalen
> liegen zwischen 38 px (p1) und 203 px (p99), also Faktor ~5, und der obere
> Rand kommt von Zaubern und Turmbalken, nicht von Einheiten. Erst messen, dann
> splitten.

---

## Loslegen

Ein Befehl richtet alles ein und prüft es:

```bash
./scripts/setup.sh                                    # Linux/macOS
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # Windows
```

Oder von Hand:

```bash
pip install -r requirements.txt
git clone --depth 1 https://github.com/wty-yy/Clash-Royale-Detection-Dataset.git ../crds

python tools/analyze_dataset.py --root ../crds --md docs/dataset-report.md
python tools/generate_dataset.py --dataset-root ../crds --out data/synth -n 2000 --preview 12
python tools/prepare_real_val.py --dataset-root ../crds --out data/real --val-ratio 1.0 --symlink
```

`data/synth/preview/` enthält Bilder mit eingezeichneten Boxen — **immer erst
draufschauen**, bevor Rechenzeit verbrannt wird. Blau = eigene Einheit,
Rot = gegnerische.

Trainiert wird in `training/train_colab.ipynb` auf einer Gratis-GPU
(Colab/Kaggle). Läuft im Browser, PC nicht nötig.

### Eigene Cutouts ernten (braucht Emulator + Spiel)

Für alles, was der Fremddatensatz nicht abdeckt — neue Karten, Evolutionen,
Champions:

```bash
python tools/harvest_cutouts.py --selftest          # prüft die Extraktion, läuft überall
python tools/harvest_cutouts.py --reference leer.png --frames frames/ --card knight
```

Verfahren: Referenzbild der leeren Arena → eine Karte legen → Differenzbild →
Maske → freigestelltes RGBA. Du weißt exakt was und wo, das Label fällt ab.

---

## Stand

**Fertig und geprüft**
- Datensatz-Analyse (auf 6.966 Frames / 117.294 Boxen gelaufen)
- Generator inkl. Sichtprüfung der Ausgabe
- Val-Set-Aufbereitung (42 Episoden, Split nach Episode, 115 Klassen belegt)
- Cutout-Ernte, Kernextraktion per Selbsttest verifiziert (IoU 0,92)
- Abdeckungsabgleich gegen eine aktuelle Kartenliste
- Kampfwerte-Tabelle: 208 Einheiten, Stichprobe gegen bekannte Werte geprueft
- Nachanalyse, Ende-zu-Ende auf einem synthetischen Spiel verifiziert
- Vorwärtsmodell, 9/9 Selbsttests gegen von Hand gerechnete Sollwerte
- Gegnermodell (Zyklus, Elixir, Spekulations-EV), 10/10 Selbsttests
- Rollout-Suche mit Aktionsmaskierung, 10/10 Selbsttests
- Kalibrierung der Vorhersagequoten
- Kollision und Blocken im Vorwärtsmodell
- Kontrafaktische Nachanalyse (`analyze_match.py --counterfactual`)
- Tracker mit Geschwindigkeitsschätzung, 7/7 Selbsttests
- Komplette Schleife im Trockenlauf, 6/6 Selbsttests
- Colab-Notebook

**45 Selbsttests laufen ohne GPU, ohne Emulator und ohne Spiel.**

**Braucht zwingend den PC** (GPU, Emulator oder laufendes Spiel)
- Detektor trainieren — Datensatz und Notebook stehen, es fehlt nur die GPU
- Capture- und Eingabeschicht (scrcpy/minitouch) samt Latenzmessung
- Handkarten-Fingerprint — braucht Screenshots aus dem Spiel
- Cutout-Ernte für neue Karten
- Torch-Backend des Vorwärtsmodells (die NumPy-Fassung ist die Referenz)

**Braucht Daten, nicht den PC**
- Statistische Platzierungs-Priors (wohin legt der Gegner welche Karte?)
- Tracker (ByteTrack/IoU) — baubar, aber erst sinnvoll mit echten Detektionen

**Bekannte Einschränkungen**
- Teamverteilung der Cutouts liegt bei ~1:2 (eigene:gegnerische). Der Generator
  gleicht aus, soweit es geht, aber für viele Klassen existieren nur Cutouts
  einer Seite. Die Blickrichtung ist im Bild eingebacken, deshalb wird die Seite
  **gewählt statt umetikettiert** — Spiegeln würde falsch aussehende Daten
  erzeugen.
- Ein Cutout-Ordner (`small-text`) hat keine Klassen-ID und wird übersprungen.
- Die Zeichenreihenfolge folgt der Ziehreihenfolge, nicht strikt y-sortiert.
- Die Schadenszuordnung in der Nachanalyse ist eine Heuristik (Reichweite + DPS).
  Bei mehreren Angreifern auf denselben Turm wird anteilig verteilt, nicht exakt.
- Das Vorwärtsmodell lässt Wegfindung um Gebäude, Aggro-Wechsel, Ladeangriffe,
  Verlangsamung, Schilde und Spawner weg. Über 3–6 s brauchbar, über 20 s nicht.
- Ein Teil der Einträge in `unit_stats.json` hat keine Elixirkosten. Das sind
  überwiegend Projektile, Event-Objekte und Turmvarianten — also nichts, was
  jemand aus der Hand spielt. Alle gängigen Kampfeinheiten und alle 17 Zauber
  haben ihren Preis.
- Zauber mit Wirkung über Zeit (Gift, Tornado, Erdbeben) stehen mit Radius und
  Kosten in der Tabelle, ihr Schaden ist aber 0 — der steckt im
  Flächeneffekt-Objekt und ist noch nicht aufgelöst.
- Die kontrafaktische Analyse nutzt dasselbe Vorwärtsmodell wie die Suche. Was
  das Modell falsch einschätzt, schätzt es auch im Rückblick falsch ein — grobe
  Fehlgriffe findet sie, Feinheiten nicht.
- **Die Suche nimmt an, dass der Gegner nichts tut.** Sie rollt nur die eigenen
  Alternativen aus. Deshalb wirkt früher Druck attraktiver, als er ist — im
  Trockenlauf legt der Bot schon bei Sekunde 0 eine Musketiererin an die
  Brücke. Der nächste Schritt wäre, die wahrscheinlichste gegnerische Antwort
  mitzusimulieren; die Bedrohungsliste aus `opponent.py` liefert die Kandidaten
  dafür bereits.

---

## Herkunft der Daten

- Cutouts, echte Frames und Labelformat:
  [wty-yy/Clash-Royale-Detection-Dataset](https://github.com/wty-yy/Clash-Royale-Detection-Dataset) (MIT)
- Vollständiger Referenzansatz mit Paper:
  [KataCR](https://github.com/wty-yy/KataCR) · [arXiv:2504.04783](https://arxiv.org/pdf/2504.04783)

Kein Code aus [py-clash-bot](https://github.com/pyclashbot/py-clash-bot)
übernommen — dessen Lizenz (NC-CL-1.0 / CC BY-NC-SA 4.0) ist nicht-kommerziell
und mit diesem Repository nicht vereinbar.

---

## Rechtliches

Automatisiertes Spielen verstößt gegen die Nutzungsbedingungen von Supercell und
kann zur Sperrung des Kontos führen. Dieses Repository ist als
Computer-Vision-Projekt angelegt; die Wahrnehmungsschicht ist ohne
Spielsteuerung nutzbar (Overlay, Analyse, Replay-Auswertung).
