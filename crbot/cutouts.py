"""Cutout-Bibliothek: freigestellte Einheiten als Bausteine für die Synthese.

Erwartet die Ordnerstruktur von wty-yy/Clash-Royale-Detection-Dataset::

    <root>/images/segment/<klasse>/<klasse>_<blong>[_<zustand>...]_<index>.png
    <root>/images/segment/backgrounds/*.jpg

Dieselbe Struktur erzeugt auch ``tools/harvest_cutouts.py`` — eigene Ernte und
Fremddaten landen damit im selben Topf.
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib
import random

import numpy as np
from PIL import Image

from crbot.labels import parse_cutout_name

# Ordner unter segment/, die keine platzierbaren Einheiten sind.
NON_UNIT_DIRS = {"backgrounds", "background-items"}

# Overlays, die der Generator selbst steuert statt sie frei zu streuen.
OVERLAY_DIRS = {"bar", "bar-level", "clock", "elixir", "text", "emote", "big-text", "selected"}

# Klassen, die in der Luft stehen — für sie gilt die Fluss-Sperre nicht.
AIR_UNITS = {
    "minion", "minion-evolution", "mega-minion", "bat", "bat-evolution", "balloon",
    "baby-dragon", "inferno-dragon", "electro-dragon", "skeleton-dragon", "lava-hound",
    "lava-pup", "flying-machine", "phoenix", "phoenix-egg", "heal-spirit",
}

# Zauber und Wurfobjekte. Sie sind kurzlebige Effekte: hoechstens einer pro
# Szene, nie im Schwarm, nie mit HP-Balken. Liste aus der Datensatz-Doku
# ("Clash Royale dataset annotation.md", Abschnitt object).
SPELL_CLASSES = {
    "zap", "zap-evolution", "giant-snowball", "rage", "the-log", "arrows",
    "arrows-evolution", "earthquake", "clone", "tornado", "fireball",
    "fireball-evolution", "freeze", "poison", "rocket", "lightning", "graveyard",
    "barbarian-barrel", "royal-delivery", "goblin-barrel", "goblin-curse", "void",
}
OBJECT_CLASSES = {"dirt", "bowl", "axe", "bomb", "spirit-empty", "background-items"}

# Nur diese Klassen treten legitim in Gruppen auf. Ohne diese Schranke stapelt
# der Generator sonst acht Tornados uebereinander — im Spiel unmoeglich, und
# das Modell lernt daraus Unsinn.
SWARM_UNITS = {
    "skeleton", "skeleton-evolution", "bat", "bat-evolution", "goblin",
    "spear-goblin", "spear-goblin-evolution", "minion", "minion-evolution",
    "barbarian", "barbarian-evolution", "archer", "archer-evolution",
    "royal-recruit", "royal-recruit-evolution", "royal-hog", "rascal-boy",
    "rascal-girl", "guard", "gurad", "lava-pup", "elite-barbarian",
    "three-musketeer", "goblin-gang", "skeleton-army", "minion-horde",
    "royal-ghost", "wall-breaker", "wall-breaker-evolution", "firecracker",
    "bomber", "bomber-evolution", "heal-spirit", "ice-spirit", "fire-spirit",
    "electro-spirit", "dart-goblin", "goblin-brawler", "phoenix-egg",
}


def is_spell_or_object(cls_name: str) -> bool:
    return cls_name in SPELL_CLASSES or cls_name in OBJECT_CLASSES


@dataclasses.dataclass  # bewusst ohne slots: cached_property braucht __dict__
class Cutout:
    """Ein einzelnes freigestelltes Bild samt geparster Zustände.

    ``rgba`` wird beim ersten Zugriff geladen und gehalten — bei 4.654 kleinen
    Cutouts sind das ~60 MB, was den Generator deutlich beschleunigt.
    """

    path: pathlib.Path
    cls_name: str
    states: dict[str, int]

    @functools.cached_property
    def rgba(self) -> Image.Image:
        return Image.open(self.path).convert("RGBA")

    @property
    def is_air(self) -> bool:
        return self.cls_name in AIR_UNITS


class CutoutLibrary:
    """Indiziert alle Cutouts und liefert gewichtete Stichproben.

    Die Gewichtung ist der eigentliche Zweck synthetischer Daten: In echten
    Spielen ist `skeleton` 3.633-mal vertreten und `clone` kein einziges Mal.
    ``sample_units`` zieht standardmäßig **gleichverteilt über die Klassen**,
    nicht über die Bilder — damit bekommt jede Karte gleich viele Beispiele,
    egal wie viele Cutouts für sie existieren.
    """

    def __init__(self, root: pathlib.Path, seed: int | None = None) -> None:
        self.root = pathlib.Path(root)
        seg = self.root / "images" / "segment"
        if not seg.is_dir():
            raise FileNotFoundError(
                f"Kein segment-Ordner unter {seg}. Zeigt --dataset-root auf den "
                "Clash-Royale-Detection-Dataset-Klon?"
            )

        self.rng = random.Random(seed)
        self.units: dict[str, list[Cutout]] = {}
        self.overlays: dict[str, list[Cutout]] = {}

        for d in sorted(seg.iterdir()):
            if not d.is_dir() or d.name in NON_UNIT_DIRS:
                continue
            items = []
            for f in sorted(list(d.glob("*.png")) + list(d.glob("*.jpg"))):
                name, states = parse_cutout_name(f.stem)
                items.append(Cutout(f, d.name, states))
            if not items:
                continue
            target = self.overlays if d.name in OVERLAY_DIRS else self.units
            target[d.name] = items

        self.backgrounds = sorted((seg / "backgrounds").glob("*"))
        if not self.backgrounds:
            raise FileNotFoundError(f"Keine Hintergründe unter {seg / 'backgrounds'}")

        self._bar_by_team = self._split_bars_by_color()

    # ------------------------------------------------------------------ Bars

    def _split_bars_by_color(self) -> dict[int, list[Cutout]]:
        """Teilt die HP-Balken nach Farbe in eigene (blau) und gegnerische (rot).

        Die Team-Erkennung im fertigen Bot hängt an genau dieser Farbe, deshalb
        muss der Generator die richtige über die richtige Einheit malen — sonst
        trainierst du dem Modell den Zusammenhang falsch an.
        """
        out: dict[int, list[Cutout]] = {0: [], 1: []}
        for cut in self.overlays.get("bar", []):
            a = np.asarray(cut.rgba)
            mask = a[..., 3] > 128
            if not mask.any():
                continue
            rgb = a[..., :3][mask].astype(np.int32)
            # Blau dominiert -> eigener Balken, Rot dominiert -> gegnerischer.
            blue_ish = int((rgb[:, 2] > rgb[:, 0] + 25).sum())
            red_ish = int((rgb[:, 0] > rgb[:, 2] + 25).sum())
            if blue_ish == red_ish:
                continue
            out[0 if blue_ish > red_ish else 1].append(cut)
        # Fallback, falls die Farbheuristik bei einer Seite leer ausgeht.
        for team in (0, 1):
            if not out[team]:
                out[team] = self.overlays.get("bar", [])
        return out

    def sample_bar(self, blong: int) -> Cutout | None:
        pool = self._bar_by_team.get(blong) or []
        return self.rng.choice(pool) if pool else None

    def sample_overlay(self, name: str) -> Cutout | None:
        pool = self.overlays.get(name) or []
        return self.rng.choice(pool) if pool else None

    # ----------------------------------------------------------------- Units

    @property
    def unit_classes(self) -> list[str]:
        return sorted(self.units)

    @functools.cached_property
    def troop_classes(self) -> list[str]:
        """Platzierbare Einheiten ohne Zauber/Objekte und ohne Tuerme."""
        return [
            c for c in self.unit_classes
            if not is_spell_or_object(c) and not c.endswith("-tower")
        ]

    @functools.cached_property
    def spell_classes(self) -> list[str]:
        return [c for c in self.unit_classes if c in SPELL_CLASSES]

    def sample_units(
        self,
        n: int,
        uniform_over_classes: bool = True,
        prefer_blong: int | None = None,
        classes: list[str] | None = None,
    ) -> list[Cutout]:
        """Zieht ``n`` Cutouts.

        ``uniform_over_classes=True`` gleicht die Klassenverteilung an — der
        Hauptgrund, überhaupt synthetisch zu erzeugen. Auf False fällt die
        Verteilung auf "so viele Cutouts wie vorhanden" zurück, was die
        Schieflage des Quelldatensatzes reproduziert.

        ``prefer_blong`` gleicht zusätzlich die **Teamverteilung** aus. Nötig,
        weil die Cutouts ihre Seite mitbringen: im Quelldatensatz sind rund 80 %
        gegnerische Einheiten (die Aufnahmen stammen aus der Ich-Perspektive
        einzelner Spieler). Ohne Ausgleich lernt das Modell "unten = selten".
        Die Blickrichtung ist im Cutout eingebacken, deshalb wird die Seite
        **gewählt statt umetikettiert** — gibt es für eine Klasse kein Bild der
        gewünschten Seite, nehmen wir das vorhandene.
        """
        if not self.units:
            return []
        out: list[Cutout] = []
        pick_from = classes if classes else self.unit_classes
        flat = [c for name in pick_from for c in self.units.get(name, [])]
        if not flat:
            return []

        for _ in range(n):
            pool = self.units[self.rng.choice(pick_from)] if uniform_over_classes else flat
            if prefer_blong is not None:
                matching = [c for c in pool if c.states.get("blong") == prefer_blong]
                if matching:
                    pool = matching
            out.append(self.rng.choice(pool))
        return out

    def sample_background(self) -> Image.Image:
        return Image.open(self.rng.choice(self.backgrounds)).convert("RGBA")

    # ------------------------------------------------------------------ Info

    def summary(self) -> str:
        n_unit_imgs = sum(len(v) for v in self.units.values())
        n_ovl_imgs = sum(len(v) for v in self.overlays.values())
        return (
            f"{len(self.units)} Einheitenklassen ({n_unit_imgs} Cutouts), "
            f"{len(self.overlays)} Overlay-Typen ({n_ovl_imgs} Cutouts), "
            f"{len(self.backgrounds)} Hintergründe, "
            f"HP-Balken: {len(self._bar_by_team[0])} blau / {len(self._bar_by_team[1])} rot"
        )
