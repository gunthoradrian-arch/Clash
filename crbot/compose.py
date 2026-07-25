"""Szenen-Synthese: aus Cutouts werden gelabelte Arena-Bilder.

Kernidee: Was du selbst zusammensetzt, musst du nicht labeln — die Box fällt
beim Einfügen ab und ist pixelgenau. Damit lässt sich gezielt erzeugen, was in
echten Spielen fehlt: Von 154 Einheitenklassen haben in den 6.966 echten Frames
nur 40 mehr als 200 Beispiele (siehe ``docs/dataset-report.md``).

Was hier bewusst modelliert wird, weil es die Erkennung sonst verzerrt:

* **HP-Balken in der richtigen Teamfarbe** über der richtigen Einheit — daran
  hängt später die gesamte Freund/Feind-Unterscheidung.
* **Zeichenreihenfolge nach y**, sonst stimmen die Verdeckungen nicht.
* **Schwarm-Cluster** statt gleichverteiltem Streuen — Skelettarmeen stehen
  dicht beieinander, und genau dieser Fall ist der schwierige.
* **Fluss-Sperre** für Bodeneinheiten, Lufteinheiten dürfen darüber.
"""

from __future__ import annotations

import dataclasses
import random

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from crbot import arena
from crbot.cutouts import SWARM_UNITS, Cutout, CutoutLibrary, is_spell_or_object
from crbot.labels import Box


@dataclasses.dataclass(slots=True)
class SceneConfig:
    """Stellschrauben der Synthese. Defaults sind an den echten Frames geeicht."""

    # In den echten Frames liegen im Schnitt ~4,5 Einheiten pro Bild (31.104
    # Einheiten-Boxen auf 6.966 Frames). Wir gehen bewusst darüber, damit auch
    # volle Szenen im Training vorkommen.
    min_units: int = 3
    max_units: int = 16

    # Anteil der Einheiten, die als dichter Schwarm-Cluster platziert werden.
    swarm_prob: float = 0.35
    swarm_size: tuple[int, int] = (3, 9)
    swarm_spread_px: float = 34.0

    # Wahrscheinlichkeit, dass eine Einheit einen HP-Balken bekommt.
    bar_prob: float = 0.65
    # ... und darüber ein Level-Abzeichen.
    bar_level_prob: float = 0.30

    # Hoechstens ein Zaubereffekt pro Szene.
    spell_prob: float = 0.22

    # UI-Overlays, die echte Frames verschmutzen.
    clock_prob: float = 0.25
    elixir_prob: float = 0.20
    text_prob: float = 0.10
    emote_prob: float = 0.08

    # Türme mitzeichnen (aus Cutouts, an den datenabgeleiteten Ankern).
    draw_towers: bool = True
    tower_bar_prob: float = 0.85

    # Augmentierung
    brightness: tuple[float, float] = (0.82, 1.18)
    contrast: tuple[float, float] = (0.88, 1.15)
    saturation: tuple[float, float] = (0.85, 1.15)
    blur_prob: float = 0.15
    blur_radius: tuple[float, float] = (0.3, 0.9)
    jpeg_quality: tuple[int, int] = (62, 95)

    # Gleichverteilung über Klassen statt über Cutout-Dateien.
    uniform_over_classes: bool = True


class SceneComposer:
    def __init__(
        self,
        library: CutoutLibrary,
        class_map: dict[str, int],
        config: SceneConfig | None = None,
        seed: int | None = None,
    ) -> None:
        self.lib = library
        self.class_map = class_map
        self.cfg = config or SceneConfig()
        self.rng = random.Random(seed)
        self.lib.rng = self.rng  # gemeinsame Quelle, damit --seed reproduzierbar ist

        self._unknown_classes: set[str] = set()

    # --------------------------------------------------------------- Helpers

    def _cls_id(self, name: str) -> int | None:
        cid = self.class_map.get(name)
        if cid is None:
            self._unknown_classes.add(name)
        return cid

    @property
    def unknown_classes(self) -> set[str]:
        """Cutout-Ordner ohne Eintrag in der Klassen-YAML (werden übersprungen)."""
        return self._unknown_classes

    def _sample_position(self, cut: Cutout, blong: int) -> tuple[float, float]:
        """Zieht eine gültige Position; bevorzugt die eigene Hälfte."""
        y_lo, y_hi = arena.side_of(blong)
        # 25 % der Einheiten stehen auf der gegnerischen Hälfte (Angriff läuft).
        if self.rng.random() < 0.25:
            y_lo, y_hi = arena.FIELD_Y

        for _ in range(24):
            x = self.rng.uniform(*arena.FIELD_X)
            y = self.rng.uniform(y_lo, y_hi)
            if cut.is_air or arena.is_walkable(x, y):
                if not self._inside_tower(x, y):
                    return x, y
        return (arena.ARENA_W / 2, (y_lo + y_hi) / 2)

    @staticmethod
    def _inside_tower(x: float, y: float) -> bool:
        return any(x1 <= x <= x2 and y1 <= y <= y2 for x1, y1, x2, y2 in arena.tower_footprints())

    def _paste(
        self,
        canvas: Image.Image,
        img: Image.Image,
        cx: float,
        cy: float,
    ) -> tuple[float, float, float, float] | None:
        """Klebt ``img`` zentriert auf (cx, cy). Gibt die Box in Pixeln zurück."""
        w, h = img.size
        if w < 2 or h < 2:
            return None
        x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
        if _fits(canvas, img, x0, y0):
            canvas.alpha_composite(img, (x0, y0))
        else:
            _safe_paste(canvas, img, x0, y0)
        return (x0, y0, x0 + w, y0 + h)

    # ---------------------------------------------------------------- Layers

    def _place_towers(self, canvas: Image.Image, boxes: list[Box]) -> None:
        for anchor in arena.TOWERS:
            pool = self.lib.units.get(anchor.name)
            if not pool:
                continue
            candidates = [c for c in pool if c.states.get("blong", 0) == anchor.blong] or pool
            cut = self.rng.choice(candidates)
            img = cut.rgba
            # Auf die datenabgeleitete Zielgröße bringen.
            img = img.resize((int(anchor.w), int(anchor.h)), Image.LANCZOS)
            rect = self._paste(canvas, img, anchor.cx, anchor.cy)
            if rect is None:
                continue
            self._add_box(boxes, anchor.name, rect, {"blong": anchor.blong})

            if self.rng.random() < self.cfg.tower_bar_prob:
                bar_name = "king-tower-bar" if anchor.name == "king-tower" else "tower-bar"
                self._place_bar(canvas, boxes, anchor.cx, anchor.cy - anchor.h / 2,
                                anchor.blong, bar_name)

    def _place_bar(
        self,
        canvas: Image.Image,
        boxes: list[Box],
        cx: float,
        top_y: float,
        blong: int,
        bar_class: str = "bar",
    ) -> None:
        cut = self.lib.sample_bar(blong)
        if cut is None:
            return
        img = cut.rgba
        rect = self._paste(canvas, img, cx, top_y - img.size[1] * 0.7)
        if rect is None:
            return
        self._add_box(boxes, bar_class, rect, {"blong": blong})

        if self.rng.random() < self.cfg.bar_level_prob:
            lvl = self.lib.sample_overlay("bar-level")
            if lvl is not None:
                lw = lvl.rgba.size[0]
                lrect = self._paste(canvas, lvl.rgba, rect[0] - lw * 0.35,
                                    (rect[1] + rect[3]) / 2)
                if lrect is not None:
                    self._add_box(boxes, "bar-level", lrect, {"blong": blong})

    def _place_unit(self, canvas: Image.Image, boxes: list[Box], cut: Cutout,
                    cx: float, cy: float) -> None:
        if self._cls_id(cut.cls_name) is None:
            return
        img = cut.rgba
        scale = arena.depth_scale(cy) * self.rng.uniform(0.94, 1.06)
        if abs(scale - 1.0) > 0.01:
            w, h = img.size
            img = img.resize((max(2, int(w * scale)), max(2, int(h * scale))), Image.LANCZOS)

        rect = self._paste(canvas, img, cx, cy)
        if rect is None:
            return
        blong = cut.states.get("blong", self.rng.randint(0, 1))
        states = dict(cut.states)
        states["blong"] = blong
        self._add_box(boxes, cut.cls_name, rect, states)

        # Zauber und Wurfobjekte haben keine Lebensleiste.
        if is_spell_or_object(cut.cls_name):
            return
        if self.rng.random() < self.cfg.bar_prob:
            self._place_bar(canvas, boxes, cx, rect[1], blong)

    def _place_spell(self, canvas: Image.Image, boxes: list[Box]) -> None:
        """Höchstens ein Zaubereffekt pro Szene.

        Zauber sind kurzlebig und schließen sich gegenseitig weitgehend aus —
        mehrere gleichzeitig sieht man im Spiel praktisch nie.
        """
        if self.rng.random() >= self.cfg.spell_prob:
            return
        spells = self.lib.spell_classes
        if not spells:
            return
        want_blong = self.rng.randint(0, 1)
        drawn = self.lib.sample_units(1, True, want_blong, spells)
        if not drawn:
            return
        cut = drawn[0]
        # Zauber landen dort, wo etwas zu treffen ist: bevorzugt nahe an
        # bereits platzierten gegnerischen Einheiten.
        targets = [b for b in boxes if b.blong != want_blong] or boxes
        if targets and self.rng.random() < 0.75:
            t = self.rng.choice(targets)
            cx = t.cx * arena.ARENA_W + self.rng.gauss(0, 20)
            cy = t.cy * arena.ARENA_H + self.rng.gauss(0, 20)
        else:
            cx = self.rng.uniform(*arena.FIELD_X)
            cy = self.rng.uniform(*arena.FIELD_Y)
        self._place_unit(canvas, boxes, cut, cx, cy)

    def _place_overlays(self, canvas: Image.Image, boxes: list[Box]) -> None:
        plan = (
            ("clock", self.cfg.clock_prob),
            ("elixir", self.cfg.elixir_prob),
            ("text", self.cfg.text_prob),
            ("emote", self.cfg.emote_prob),
        )
        for name, prob in plan:
            if self.rng.random() >= prob:
                continue
            cut = self.lib.sample_overlay(name)
            if cut is None:
                continue
            x = self.rng.uniform(*arena.FIELD_X)
            y = self.rng.uniform(*arena.FIELD_Y)
            rect = self._paste(canvas, cut.rgba, x, y)
            if rect is not None:
                self._add_box(boxes, name, rect, cut.states)

    def _add_box(self, boxes: list[Box], cls_name: str,
                 rect: tuple[float, float, float, float], states: dict[str, int]) -> None:
        cid = self._cls_id(cls_name)
        if cid is None:
            return
        x1, y1, x2, y2 = rect
        box = Box(
            cls_id=cid,
            cx=(x1 + x2) / 2 / arena.ARENA_W,
            cy=(y1 + y2) / 2 / arena.ARENA_H,
            w=(x2 - x1) / arena.ARENA_W,
            h=(y2 - y1) / arena.ARENA_H,
            states=dict(states),
        )
        clipped = box.clip()
        if clipped is not None:
            boxes.append(clipped)

    # ------------------------------------------------------------ Public API

    def compose(self) -> tuple[Image.Image, list[Box]]:
        canvas = self.lib.sample_background().resize((arena.ARENA_W, arena.ARENA_H))
        boxes: list[Box] = []

        if self.cfg.draw_towers:
            self._place_towers(canvas, boxes)

        n_units = self.rng.randint(self.cfg.min_units, self.cfg.max_units)
        placed = 0
        troops = self.lib.troop_classes
        while placed < n_units:
            # Seite zuerst würfeln, dann ein dazu passendes Cutout ziehen —
            # sonst schlägt die 80/20-Schieflage des Quelldatensatzes durch.
            want_blong = self.rng.randint(0, 1)
            drawn = self.lib.sample_units(1, self.cfg.uniform_over_classes, want_blong, troops)
            if not drawn:
                break
            cut = drawn[0]
            blong = cut.states.get("blong", want_blong)
            cx, cy = self._sample_position(cut, blong)

            swarmable = cut.cls_name in SWARM_UNITS
            if swarmable and self.rng.random() < self.cfg.swarm_prob:
                # Schwarm: mehrere Cutouts derselben Klasse eng beieinander.
                # Alle Mitglieder gehören derselben Seite an.
                k = self.rng.randint(*self.cfg.swarm_size)
                pool = [c for c in self.lib.units[cut.cls_name]
                        if c.states.get("blong") == blong] or self.lib.units[cut.cls_name]
                for _ in range(min(k, n_units - placed)):
                    member = self.rng.choice(pool)
                    dx = self.rng.gauss(0, self.cfg.swarm_spread_px)
                    dy = self.rng.gauss(0, self.cfg.swarm_spread_px * 0.6)
                    self._place_unit(canvas, boxes, member, cx + dx, cy + dy)
                    placed += 1
            else:
                self._place_unit(canvas, boxes, cut, cx, cy)
                placed += 1

        self._place_spell(canvas, boxes)
        self._place_overlays(canvas, boxes)

        # Nach y sortiert neu zeichnen wäre teuer; stattdessen zeichnen wir
        # bereits in Ziehreihenfolge und akzeptieren gelegentliche
        # Verdeckungsfehler — bei ~4 % Perspektiveffekt fällt das kaum ins
        # Gewicht und echte Frames haben denselben Ambiguitätsgrad.

        return self._augment(canvas.convert("RGB")), boxes

    def _augment(self, img: Image.Image) -> Image.Image:
        c = self.cfg
        img = ImageEnhance.Brightness(img).enhance(self.rng.uniform(*c.brightness))
        img = ImageEnhance.Contrast(img).enhance(self.rng.uniform(*c.contrast))
        img = ImageEnhance.Color(img).enhance(self.rng.uniform(*c.saturation))
        if self.rng.random() < c.blur_prob:
            img = img.filter(ImageFilter.GaussianBlur(self.rng.uniform(*c.blur_radius)))
        return img

    def jpeg_quality(self) -> int:
        return self.rng.randint(*self.cfg.jpeg_quality)


def _fits(canvas: Image.Image, img: Image.Image, x0: int, y0: int) -> bool:
    return x0 >= 0 and y0 >= 0 and x0 + img.size[0] <= canvas.size[0] and y0 + img.size[1] <= canvas.size[1]


def _safe_paste(canvas: Image.Image, img: Image.Image, x0: int, y0: int) -> None:
    """alpha_composite kann nicht über den Rand — für Randfälle zuschneiden."""
    cw, ch = canvas.size
    w, h = img.size
    sx0, sy0 = max(0, -x0), max(0, -y0)
    sx1, sy1 = min(w, cw - x0), min(h, ch - y0)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    crop = img.crop((sx0, sy0, sx1, sy1))
    canvas.alpha_composite(crop, (x0 + sx0, y0 + sy0))


def boxes_to_mask_stats(boxes: list[Box]) -> dict[str, float]:
    """Kleine Kennzahlen für die Qualitätskontrolle einer Szene."""
    if not boxes:
        return {"n": 0, "median_diag_px": 0.0}
    diags = [
        float(np.hypot(b.w * arena.ARENA_W, b.h * arena.ARENA_H)) for b in boxes
    ]
    return {"n": len(boxes), "median_diag_px": float(np.median(diags))}
