"""Arena-Geometrie.

Alle Zahlen hier sind **aus Daten abgeleitet**, nicht geschätzt: Median über
117.294 annotierte Boxen aus 6.966 echten Frames (siehe
``docs/dataset-report.md`` und ``tools/analyze_dataset.py``).

Referenzsystem ist der Arena-Ausschnitt in 568x896 — die Auflösung, in der
sowohl die Hintergründe als auch die Cutouts des Quelldatensatzes vorliegen.
Alles andere im Projekt rechnet in normalisierten Koordinaten, damit ein
Wechsel der Capture-Auflösung nichts kaputt macht.
"""

from __future__ import annotations

import dataclasses

ARENA_W = 568
ARENA_H = 896


@dataclasses.dataclass(frozen=True, slots=True)
class TowerAnchor:
    """Feste Position eines Turms in Pixeln des Referenzsystems."""

    name: str
    blong: int  # 0 = eigener Turm, 1 = gegnerischer
    cx: float
    cy: float
    w: float
    h: float


# Median-Positionen aus den echten Labels. blong=0 ist unten (eigene Seite).
TOWERS: tuple[TowerAnchor, ...] = (
    TowerAnchor("king-tower", 0, 284.0, 776.0, 124.0, 135.0),
    TowerAnchor("king-tower", 1, 284.0, 116.0, 106.0, 139.0),
    TowerAnchor("queen-tower", 0, 114.0, 684.0, 92.0, 105.0),
    TowerAnchor("queen-tower", 0, 456.0, 684.0, 92.0, 106.0),
    TowerAnchor("queen-tower", 1, 112.0, 211.0, 90.0, 102.0),
    TowerAnchor("queen-tower", 1, 455.0, 212.0, 90.0, 101.0),
)

# Der Fluss liegt mittig zwischen den beiden Prinzessinnenturm-Reihen
# ((211 + 684) / 2 = 447.5). Bodeneinheiten stehen nie im Wasser.
RIVER_Y = 448.0
RIVER_HALF_HEIGHT = 18.0

# Brücken liegen auf den x-Achsen der Prinzessinnentürme.
BRIDGE_X = (114.0, 456.0)
BRIDGE_HALF_WIDTH = 26.0

# Spielbare Fläche (die Ränder sind Deko/UI).
FIELD_X = (26.0, 542.0)
FIELD_Y = (60.0, 840.0)

# Perspektive: hinten sind Einheiten leicht kleiner. Aus dem Größenvergleich
# der Prinzessinnentürme (eigene 92x105 vs. gegnerische 90x101) ergibt sich
# ein schwacher Effekt von ca. 4 % über die volle Feldhöhe.
SCALE_AT_TOP = 0.96
SCALE_AT_BOTTOM = 1.0


def depth_scale(y_px: float) -> float:
    """Skalierungsfaktor für eine Einheit auf Höhe ``y_px``."""
    top, bottom = FIELD_Y
    t = (y_px - top) / (bottom - top)
    t = min(1.0, max(0.0, t))
    return SCALE_AT_TOP + t * (SCALE_AT_BOTTOM - SCALE_AT_TOP)


def in_river(y_px: float) -> bool:
    return abs(y_px - RIVER_Y) <= RIVER_HALF_HEIGHT


def on_bridge(x_px: float) -> bool:
    return any(abs(x_px - bx) <= BRIDGE_HALF_WIDTH for bx in BRIDGE_X)


def is_walkable(x_px: float, y_px: float) -> bool:
    """Darf dort eine Bodeneinheit stehen?"""
    if not (FIELD_X[0] <= x_px <= FIELD_X[1] and FIELD_Y[0] <= y_px <= FIELD_Y[1]):
        return False
    if in_river(y_px) and not on_bridge(x_px):
        return False
    return True


def tower_footprints() -> list[tuple[float, float, float, float]]:
    """Turm-Rechtecke (x1, y1, x2, y2), damit nichts mitten im Turm landet."""
    return [
        (t.cx - t.w / 2, t.cy - t.h / 2, t.cx + t.w / 2, t.cy + t.h / 2)
        for t in TOWERS
    ]


def side_of(blong: int) -> tuple[float, float]:
    """Grober y-Bereich der eigenen Hälfte einer Partei.

    Einheiten laufen über den Fluss, deshalb ist das nur die Verteilung beim
    Platzieren — der Generator lässt bewusst auch Einheiten auf der
    gegnerischen Seite zu.
    """
    return (RIVER_Y, FIELD_Y[1]) if blong == 0 else (FIELD_Y[0], RIVER_Y)
