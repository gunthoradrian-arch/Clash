"""Labelformat für die Wahrnehmungsschicht.

Wir schreiben ein **Superset** des Ultralytics-Formats:

    class cx cy w h  blong movement shield visible rage slow heal_clone

Die ersten fünf Felder sind exakt das, was stock-Ultralytics erwartet — die
sieben Zustandsfelder hängen hinten dran und werden von einem
Standard-Training schlicht ignoriert.

Der Grund für den Aufbau: Du kannst **heute** mit unverändertem Ultralytics
trainieren (`to_ultralytics()` projiziert auf 5 Felder) und später auf ein
Mehrkopf-Modell umsteigen, das die Zustände mitlernt — ohne den Datensatz neu
zu erzeugen. Das Format ist kompatibel zu wty-yy/Clash-Royale-Detection-Dataset,
damit dessen echte Frames und unsere synthetischen Szenen mischbar bleiben.

Team (`blong`) gehört bewusst NICHT in die Klasse. Sonst müsste das Netz
"Ritter" zweimal unabhängig lernen und der Klassenraum verdoppelt sich.
"""

from __future__ import annotations

import dataclasses
import pathlib

# Reihenfolge der Zustandsfelder hinter der Box. Fix — nicht umsortieren,
# sonst werden bestehende Labels stillschweigend falsch interpretiert.
STATE_FIELDS = (
    "blong",       # 0 = eigene Einheit, 1 = gegnerische
    "movement",    # 0 norm/walk/wait, 1 attack, 2 deploy, 3 freeze, 4 dash
    "shield",      # 0 ohne, 1 mit Schild
    "visible",     # 0 sichtbar, 1 unsichtbar
    "rage",        # 0 norm, 1 gerage-t
    "slow",        # 0 norm, 1 verlangsamt
    "heal_clone",  # 0 norm, 1 heal, 2 clone
)

N_BBOX_FIELDS = 5
N_FIELDS = N_BBOX_FIELDS + len(STATE_FIELDS)

# Zustandsnamen, wie sie in den Cutout-Dateinamen auftauchen
# (z.B. "dark-prince_1_attack_shield_0000123.png"), auf (Feld, Wert) gemappt.
NAME_TOKEN_TO_STATE = {
    "attack": ("movement", 1),
    "deploy": ("movement", 2),
    "freeze": ("movement", 3),
    "dash": ("movement", 4),
    "destory": ("movement", 4),  # Schreibweise aus dem Quelldatensatz
    "shield": ("shield", 1),
    "invisible": ("visible", 1),
    "rage": ("rage", 1),
    "slow": ("slow", 1),
    "heal": ("heal_clone", 1),
    "clone": ("heal_clone", 2),
}


@dataclasses.dataclass(slots=True)
class Box:
    """Eine annotierte Box in normalisierten Koordinaten (0..1, cx/cy/w/h)."""

    cls_id: int
    cx: float
    cy: float
    w: float
    h: float
    states: dict[str, int] = dataclasses.field(default_factory=dict)

    @property
    def blong(self) -> int:
        return self.states.get("blong", 0)

    def to_row(self) -> str:
        vals = [str(self.cls_id), *(f"{v:.6f}" for v in (self.cx, self.cy, self.w, self.h))]
        vals += [str(int(self.states.get(f, 0))) for f in STATE_FIELDS]
        return " ".join(vals)

    @classmethod
    def from_row(cls, row: str) -> "Box | None":
        parts = row.split()
        if len(parts) < N_BBOX_FIELDS:
            return None
        try:
            cls_id = int(float(parts[0]))
            cx, cy, w, h = (float(p) for p in parts[1:5])
        except ValueError:
            return None
        states = {}
        for name, raw in zip(STATE_FIELDS, parts[N_BBOX_FIELDS:]):
            try:
                states[name] = int(float(raw))
            except ValueError:
                states[name] = 0
        return cls(cls_id, cx, cy, w, h, states)

    def clip(self) -> "Box | None":
        """Auf den Bildrand beschneiden. None, wenn danach nichts Sinnvolles bleibt."""
        x1, y1 = self.cx - self.w / 2, self.cy - self.h / 2
        x2, y2 = self.cx + self.w / 2, self.cy + self.h / 2
        x1, y1 = max(0.0, x1), max(0.0, y1)
        x2, y2 = min(1.0, x2), min(1.0, y2)
        if x2 - x1 <= 1e-4 or y2 - y1 <= 1e-4:
            return None
        return Box(self.cls_id, (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1, dict(self.states))


def parse_cutout_name(stem: str) -> tuple[str, dict[str, int]]:
    """Zerlegt einen Cutout-Dateinamen in (Klassenname, Zustände).

    Konvention im Quelldatensatz: ``<klasse>_<blong>[_<zustand>...]_<index>``
    Beispiele::

        knight_0_0000059            -> ("knight",       {"blong": 0})
        archer-queen_1_attack_0007  -> ("archer-queen", {"blong": 1, "movement": 1})

    Unbekannte Tokens werden ignoriert statt zu knallen — der Quelldatensatz
    ist an ein paar Stellen inkonsistent benannt.
    """
    tokens = stem.split("_")
    if len(tokens) < 2:
        return stem, {}

    name = tokens[0]
    states: dict[str, int] = {}
    # Letztes Token ist der laufende Index -> abschneiden.
    body = tokens[1:-1] if len(tokens) > 2 else tokens[1:]

    for tok in body:
        if tok in ("0", "1"):
            states["blong"] = int(tok)
        elif tok in NAME_TOKEN_TO_STATE:
            field, value = NAME_TOKEN_TO_STATE[tok]
            states[field] = value
    return name, states


def write_label(path: pathlib.Path, boxes: list[Box]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(b.to_row() for b in boxes) + ("\n" if boxes else ""))


def read_label(path: pathlib.Path) -> list[Box]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        box = Box.from_row(line)
        if box is not None:
            out.append(box)
    return out


def to_ultralytics(boxes: list[Box]) -> str:
    """Projektion auf das 5-Feld-Format für unverändertes Ultralytics-Training."""
    return "\n".join(
        f"{b.cls_id} {b.cx:.6f} {b.cy:.6f} {b.w:.6f} {b.h:.6f}" for b in boxes
    ) + ("\n" if boxes else "")
