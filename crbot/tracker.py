"""Tracking: aus Einzelbild-Erkennungen werden Einheiten mit Geschichte.

Ein Detektor liefert pro Frame eine Liste von Kästen — mehr nicht. Er weiß
nicht, ob der Ritter links derselbe ist wie im Bild davor. Genau das fehlt aber
an drei Stellen:

* **Geschwindigkeit.** Ein Einzelbild verrät nicht, ob der Hog Rider vorwärts
  oder zurück läuft. Das Vorwärtsmodell braucht die Richtung.
* **Aussetzer.** Verdeckt eine Verzauberung die Einheit für zwei Frames, darf
  sie nicht verschwinden und als neue Einheit wieder auftauchen.
* **Identität.** Der Deck-Prior kann nur greifen, wenn eine Einheit über die
  Zeit dieselbe bleibt.

Zuordnung läuft gierig über die **vorhergesagte** Position: Wo müsste die
Einheit jetzt sein, wenn sie so weiterläuft wie bisher? Das trennt kreuzende
Einheiten deutlich besser als reine Nähe zur letzten Position.
"""

from __future__ import annotations

import dataclasses
import itertools
import math

# Schnellste Einheit im Spiel läuft 1,5 Kacheln/s. Mit Zuschlag für Rauschen
# und Verzögerung ist das die Obergrenze für eine plausible Zuordnung.
MAX_SPEED_TILES_S = 1.6
GATE_SLACK_TILES = 0.8

# Zeitfenster, über das die Geschwindigkeit bestimmt wird.
#
# Aus zwei benachbarten Frames zu schätzen wäre naheliegend, aber falsch: Der
# Positionsfehler wird dabei mit 1/dt verstärkt. Bei 0,2 s Abstand und 0,12
# Kacheln Rauschen kommen daraus ±0,85 Kacheln/s — mehr als das halbe Tempo
# einer schnellen Einheit. Über ein längeres Fenster sinkt der Fehler
# proportional zur Zeitbasis.
VELOCITY_WINDOW_S = 0.8
VELOCITY_MIN_SPAN_S = 0.3

# Restglättung auf die Fensterschätzung.
VELOCITY_SMOOTHING = 0.5


@dataclasses.dataclass(slots=True)
class Detection:
    """Eine Erkennung aus einem Einzelbild, in Kacheln."""

    cls: str
    side: int
    x: float
    y: float
    confidence: float = 1.0
    hp_frac: float = 1.0


@dataclasses.dataclass
class Track:
    """Eine über die Zeit verfolgte Einheit."""

    id: int
    cls: str
    side: int
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    hp_frac: float = 1.0
    hits: int = 1
    misses: int = 0
    age: float = 0.0
    last_t: float = 0.0
    history: list[tuple[float, float, float]] = dataclasses.field(default_factory=list)

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)

    def predict(self, dt: float) -> tuple[float, float]:
        return (self.x + self.vx * dt, self.y + self.vy * dt)

    def as_tuple(self) -> tuple[str, int, float, float, float]:
        """Format, das die Suche erwartet: (klasse, seite, x, y, hp)."""
        return (self.cls, self.side, self.x, self.y, 0.0)


class Tracker:
    """Verfolgt Einheiten über Frames hinweg.

    ``min_hits`` verzögert die Geburt eines Tracks: Ein einzelner Fehlalarm des
    Detektors soll nicht sofort als Bedrohung in die Suche wandern.
    ``max_misses`` hält ihn am Leben, wenn er kurz nicht erkannt wird.
    """

    def __init__(self, min_hits: int = 2, max_misses: int = 3,
                 same_class_bonus: float = 1.2) -> None:
        self.min_hits = min_hits
        self.max_misses = max_misses
        self.same_class_bonus = same_class_bonus
        self._tracks: list[Track] = []
        self._next_id = itertools.count(1)
        self._last_t: float | None = None

    @property
    def tracks(self) -> list[Track]:
        """Nur bestätigte Tracks — die, denen man trauen kann."""
        return [t for t in self._tracks if t.hits >= self.min_hits]

    @property
    def all_tracks(self) -> list[Track]:
        return list(self._tracks)

    def update(self, detections: list[Detection], t: float) -> list[Track]:
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t

        gate = MAX_SPEED_TILES_S * max(dt, 0.1) + GATE_SLACK_TILES
        pairs: list[tuple[float, int, int]] = []
        for ti, tr in enumerate(self._tracks):
            px, py = tr.predict(dt)
            for di, det in enumerate(detections):
                d = math.hypot(det.x - px, det.y - py)
                if d > gate:
                    continue
                # Gleiche Klasse wird bevorzugt, aber nicht erzwungen — der
                # Detektor verwechselt aehnliche Einheiten gelegentlich.
                cost = d / (self.same_class_bonus if det.cls == tr.cls else 1.0)
                if det.side != tr.side:
                    cost *= 3.0
                pairs.append((cost, ti, di))

        pairs.sort()
        used_t: set[int] = set()
        used_d: set[int] = set()
        for _cost, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            self._absorb(self._tracks[ti], detections[di], dt, t)

        # Nicht zugeordnete Tracks altern; zu lange vermisste verschwinden.
        for ti, tr in enumerate(self._tracks):
            if ti in used_t:
                continue
            tr.misses += 1
            tr.age += dt
            # Position fortschreiben, damit die Vorhersage nicht einfriert.
            tr.x, tr.y = tr.predict(dt)
        self._tracks = [t for t in self._tracks if t.misses <= self.max_misses]

        # Neue Erkennungen werden zu neuen Tracks.
        for di, det in enumerate(detections):
            if di in used_d:
                continue
            self._tracks.append(Track(
                id=next(self._next_id), cls=det.cls, side=det.side,
                x=det.x, y=det.y, hp_frac=det.hp_frac, last_t=t,
                history=[(t, det.x, det.y)],
            ))

        return self.tracks

    def _absorb(self, tr: Track, det: Detection, dt: float, t: float) -> None:
        tr.history.append((t, det.x, det.y))
        while tr.history and t - tr.history[0][0] > VELOCITY_WINDOW_S:
            tr.history.pop(0)

        t0, x0, y0 = tr.history[0]
        span = t - t0
        if span >= VELOCITY_MIN_SPAN_S:
            vx, vy = (det.x - x0) / span, (det.y - y0) / span
            a = VELOCITY_SMOOTHING
            tr.vx = (1 - a) * tr.vx + a * vx
            tr.vy = (1 - a) * tr.vy + a * vy
        elif dt > 1e-6 and tr.hits > 1:
            # Noch zu kurze Zeitbasis — grobe Schaetzung, stark gedaempft.
            tr.vx = 0.75 * tr.vx + 0.25 * (det.x - tr.x) / dt
            tr.vy = 0.75 * tr.vy + 0.25 * (det.y - tr.y) / dt
        tr.x, tr.y = det.x, det.y
        tr.hp_frac = det.hp_frac
        tr.cls = det.cls
        tr.side = det.side
        tr.hits += 1
        tr.misses = 0
        tr.age += dt
        tr.last_t = t

    def reset(self) -> None:
        self._tracks.clear()
        self._last_t = None
