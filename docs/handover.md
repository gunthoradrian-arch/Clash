# Übergabe an den PC

Was gebaut ist, warum es so gebaut ist, und was als Nächstes drankommt.

---

## In fünf Minuten lauffähig

```bash
git clone https://github.com/gunthoradrian-arch/Clash.git
cd Clash
git checkout claude/clash-royale-bot-overview-ym909j

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

git clone --depth 1 https://github.com/wty-yy/Clash-Royale-Detection-Dataset.git ../crds

# Prüfen, dass alles läuft (dauert unter einer Minute)
for t in forward opponent decision tracker pipeline; do python tools/${t}_selftest.py; done
```

Erwartet: 12 + 10 + 10 + 7 + 6 = **45 bestandene Tests**.

Unter Windows PowerShell statt der Schleife:

```powershell
foreach ($t in "forward","opponent","decision","tracker","pipeline") {
    python tools/${t}_selftest.py
}
```

---

## Was da ist

| Baustein | Datei | Geprüft durch |
|---|---|---|
| Labelformat, Cutout-Namen | `crbot/labels.py` | Generator-Läufe |
| Arena-Geometrie | `crbot/arena.py` | aus 117k echten Boxen abgeleitet |
| Szenensynthese | `crbot/compose.py` | Sichtprüfung der Preview-Bilder |
| Kampfwerte (283 Einträge) | `crbot/cardstats.py` | Stichprobe gegen bekannte Werte |
| Vorwärtsmodell | `crbot/forward.py` | 12 Selbsttests |
| Gegnermodell (Zyklus, Elixir) | `crbot/opponent.py` | 10 Selbsttests |
| Rollout-Suche | `crbot/search.py` | 10 Selbsttests |
| Kalibrierung | `crbot/calibration.py` | im selben Satz |
| Tracker | `crbot/tracker.py` | 7 Selbsttests |
| Spielschleife | `crbot/pipeline.py` | 6 Selbsttests |
| Nachanalyse | `crbot/postmortem.py` | Demo-Lauf |
| Kontrafaktik | `crbot/counterfactual.py` | Demo-Lauf |

---

## Die Reihenfolge auf dem PC

### 1. Messen, bevor du optimierst

```bash
pip install ultralytics mss
python tools/bench_latency.py --all --detector yolov8s.pt --imgsz 768 1024 1280
```

Erwartung: **`adb input tap` und `adb screencap` fressen 90 % des Budgets**,
die GPU langweilt sich. Wenn das stimmt, ist der erste Umbau Capture per scrcpy
und Eingabe per minitouch — nicht ein größeres Modell.

Zielmarke: unter 150 ms von Bildschirm bis Tap.

### 2. Detektor trainieren

Lokal auf der 3080 statt Colab — grob 2–3× schneller, rund 4–6 Stunden für
60 Epochen bei `yolov8s` @ 768 und 20.000 synthetischen Bildern.

```bash
python tools/analyze_dataset.py --root ../crds --md docs/dataset-report.md
python tools/generate_dataset.py --dataset-root ../crds --out data/synth -n 20000 --preview 12
python tools/prepare_real_val.py --dataset-root ../crds --out data/real --val-ratio 1.0 --symlink
```

**Vor dem Training die Preview-Bilder ansehen.** `data/synth/preview/` zeigt die
Szenen mit eingezeichneten Boxen, blau = eigene Einheit, rot = gegnerische. Wenn
die unrealistisch aussehen, ist Rechenzeit verschwendet.

Trainingsparameter stehen in `training/train_colab.ipynb` — die Zelle lässt sich
lokal übernehmen. Wichtig darin: **nicht spiegeln und nicht rotieren.** Die
Arena hat eine feste Orientierung, links und rechts tragen Bedeutung.

Danach die Auswertungszelle laufen lassen: Sie listet die 25 Klassen mit dem
schlechtesten Recall auf echten Bildern. Das ist die Arbeitsliste für Schritt 3.

### 3. Lücken schließen

```bash
python tools/coverage_gap.py --dataset-root ../crds --source supercell \
    --token <key> --md docs/harvest-list.md
```

Kostenloser Key auf [developer.clashroyale.com](https://developer.clashroyale.com),
IP-gebunden. Ohne ihn ist die Kartenliste selbst veraltet und meldet fälschlich
„keine Lücken".

Dann ernten, was fehlt:

```bash
python tools/harvest_cutouts.py --selftest
python tools/harvest_cutouts.py --reference leer.png --frames frames/ --card <karte>
```

Verfahren: leere Arena aufnehmen → eine Karte legen → Differenzbild → Maske.
Label und Position fallen ab, es wird nichts von Hand annotiert. Ein Nachmittag
reicht für die volle Abdeckung, wenn du es über die ADB-Schicht skriptest.

**Neue Arenen und Turm-Skins nicht vergessen** — der Generator hat 28
Hintergründe von 2023.

### 4. Anschließen

`crbot/pipeline.py` erwartet eine Wahrnehmung mit genau einer Methode:

```python
class Perception(Protocol):
    def detect(self, frame, t: float) -> list[Detection]: ...
```

`Detection` trägt Klasse, Seite, x, y in **Kacheln**. Der echte Detektor liefert
Pixel — `arena.px_to_tile` rechnet um. Alles hinter dieser Grenze ist bereits
geprüft; `ScriptedPerception` im selben Modul zeigt, wie eine Implementierung
aussieht.

---

## Was noch offen ist, nach Wirkung sortiert

**Die Suche nimmt an, dass der Gegner nichts tut.** Das ist die größte
inhaltliche Lücke. Sie rollt nur eigene Alternativen aus, deshalb wirkt früher
Druck attraktiver als er ist — im Trockenlauf legt der Bot schon bei Sekunde 0
eine Musketiererin an die Brücke. Der Fix: die wahrscheinlichste gegnerische
Antwort mitsimulieren. Die Kandidaten dafür liefert
`OpponentModel.affordable_within()` bereits.

**Platzierungs-Priors.** Wohin legt der Gegner welche Karte? Braucht echte
Replay-Daten. Fällt als Nebenprodukt aus derselben Pipeline ab, die man für
Imitation Learning ohnehin braucht.

**Torch-Backend des Vorwärtsmodells.** Die NumPy-Fassung ist die geprüfte
Referenz — bei einer Portierung müssen die 12 Selbsttests weiter bestehen.
Erst dann lohnt sich die GPU: Aus 120 ms Reserve werden dann tausende Rollouts
statt 200.

**Zauber über Zeit** (Gift, Tornado, Erdbeben) haben Radius und Kosten, aber
Schaden 0. Der steckt im Flächeneffekt-Objekt des Dumps.

---

## Was du beim Weiterarbeiten wissen solltest

Bei einem fehlgeschlagenen Test **erst nachrechnen, dann den Code anfassen**.
In der Entwicklung waren von acht Fehlschlägen fünf falsche Testerwartungen und
nur drei echte Codefehler. Beispiele:

- Ein Skelett starb „zu schnell" — es waren die eigenen Prinzessinnentürme, die
  mitschossen. 65,8 + 2 × 62,5 DPS erklären die gemessenen 0,17 s exakt.
- Die Temposchätzung schien um 40 % daneben — über 40 Läufe gemittelt lag sie
  bei 1,097 statt 1,10. Unverzerrt, nur verrauscht.
- Eine leere Handvorhersage nach drei gegnerischen Zügen ist richtig: Frisch
  gespielte Karten liegen hinten in der Warteschlange.

Die Commit-Nachrichten dokumentieren jede dieser Entscheidungen mit den Zahlen
dahinter. `git log` ist hier die eigentliche Projektgeschichte.

---

## Rechtliches

Automatisiertes Spielen verstößt gegen die Nutzungsbedingungen von Supercell und
kann zur Kontosperrung führen. Die Wahrnehmungsschicht ist ohne Spielsteuerung
nutzbar — Live-Overlay, Deck-Tracker, Replay-Analyse.
