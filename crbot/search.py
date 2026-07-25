"""Rollout-Suche: Kandidaten erzeugen, durchrechnen, besten wählen.

Hier wird aus Rechenleistung Spielstärke. Statt einen Zug per Reflex zu wählen,
werden alle sinnvollen Alternativen — inklusive **nichts tun** — im
Vorwärtsmodell parallel ausgerollt und nach Netto-Turmschaden bewertet.

Drei Dinge machen den Unterschied zu einem reinen Regel-Bot:

**Aktionsmaskierung.** Nur bezahlbare Karten auf gültige Felder kommen
überhaupt in Betracht. Ein bekannter Bot mit 2017 flachen Aktionen verbringt
den Grossteil seiner Exploration mit Zügen, die gar nichts bewirken.

**Nichtstun ist ein Kandidat.** Ohne diese Vergleichsbasis spielt ein Bot
zwanghaft Karten, nur weil er Elixir hat. Der Vergleich beantwortet die
eigentliche Frage: Ist dieser Zug besser als warten?

**Rollenabhängige Platzierung.** Wo ein Kandidat sinnvoll liegt, ergibt sich
aus seinen Kampfwerten — Gebäudeangreifer an die Brücke, Verteidiger zwischen
Bedrohung und Turm, Flächenzauber auf den Schwerpunkt der Gegner. Das schrumpft
den Suchraum von tausenden Feldern auf ein paar Dutzend.
"""

from __future__ import annotations

import dataclasses
import time

import numpy as np

from crbot import arena
from crbot.cardstats import UnitStats, load_table
from crbot.forward import ForwardModel

RIVER_Y = arena.px_to_tile(0.0, arena.RIVER_Y)[1]
BRIDGES = tuple(arena.px_to_tile(bx, 0.0)[0] for bx in arena.BRIDGE_X)
OUR_KING = arena.px_to_tile(284.0, 776.0)
OUR_TOWERS = (arena.px_to_tile(114.0, 684.0), arena.px_to_tile(456.0, 684.0))
_OPP_TOWERS = (arena.px_to_tile(112.0, 211.0), arena.px_to_tile(455.0, 212.0))


@dataclasses.dataclass(slots=True)
class Candidate:
    card: str
    x: float
    y: float
    cost: float
    role: str = ""

    def __str__(self) -> str:
        return f"{self.card}@({self.x:.1f},{self.y:.1f})"


@dataclasses.dataclass
class Decision:
    """Ergebnis einer Suche."""

    best: Candidate | None          # None = warten
    score: float
    wait_score: float
    considered: int
    elapsed_ms: float
    ranked: list[tuple[Candidate | None, float]]

    @property
    def plays(self) -> bool:
        return self.best is not None

    @property
    def margin(self) -> float:
        """Um wie viel schlägt der beste Zug das Nichtstun?"""
        return self.score - self.wait_score

    def explain(self) -> str:
        if self.best is None:
            return (f"warten (bester Zug lag {abs(self.margin):.0f} HP darunter, "
                    f"{self.considered} Kandidaten in {self.elapsed_ms:.0f} ms)")
        return (f"{self.best} — {self.margin:+.0f} HP gegenüber warten "
                f"({self.considered} Kandidaten in {self.elapsed_ms:.0f} ms)")


class RolloutSearch:
    """Bewertet Handkarten durch Vorausrechnen.

    ``min_margin`` ist die Schwelle, ab der ein Zug das Nichtstun schlagen muss.
    Sie verhindert, dass der Bot bei Gleichstand aus Rauschen heraus spielt —
    Elixir sparen ist ein legitimer Zug.
    """

    def __init__(self, model: ForwardModel | None = None,
                 table: dict[str, UnitStats] | None = None,
                 horizon_s: float = 8.0, dt: float = 0.25,
                 min_margin: float = 25.0,
                 elixir_margin_hp: float = 30.0) -> None:
        self.fm = model or ForwardModel(table)
        self.table = table or load_table()
        # 8 Sekunden, nicht 5: Eine Bedrohung braucht Zeit, um anzulaufen und
        # zu sterben. Bei 5 s ist sie noch unterwegs, und Verteidigung sieht
        # wertlos aus — gemessen sprang der Vorteil einer Musketiererin gegen
        # einen Hog Rider von 70 auf 352 HP, allein durch den laengeren Blick.
        # Ab etwa 8 s aendert sich nichts mehr, weil die Lage entschieden ist.
        # Laenger zu rechnen haeuft nur Modellfehler an.
        self.horizon_s = horizon_s
        self.dt = dt
        self.min_margin = min_margin
        # Was ein Elixir im Vergleich zum Nichtstun wert sein muss.
        #
        # Ueber ein ganzes Spiel entspricht 1 Elixir grob 120 Turm-HP. Diesen
        # vollen Preis gegen einen nur 5 Sekunden weit gerechneten Nutzen zu
        # stellen, waere unfair: Die Kosten fallen ganz an, der Nutzen wird vom
        # Horizont abgeschnitten. Ergebnis waere ein Bot, der aus lauter
        # Sparsamkeit nie verteidigt. Deshalb hier der Anteil, der innerhalb
        # des Horizonts realistisch zurueckkommt.
        self.elixir_margin_hp = elixir_margin_hp

    # ------------------------------------------------------ Kandidatenauswahl

    def _stats(self, card: str) -> UnitStats | None:
        st = self.table.get(card)
        if st is not None:
            return st
        for suffix in ("-evolution", "-big", "-mid", "-small"):
            if card.endswith(suffix):
                return self.table.get(card[: -len(suffix)])
        return None

    def _placements(self, card: str, st: UnitStats,
                    threats: list[tuple[float, float]]) -> list[tuple[float, float, str]]:
        """Sinnvolle Ablagepunkte für eine Karte, abhängig von ihrer Rolle."""
        spots: list[tuple[float, float, str]] = []

        # Zauber: auf den Schwerpunkt der Bedrohungen, sonst auf den Turm.
        if st.is_spell:
            for tx, ty in _clusters(threats):
                spots.append((tx, ty, "zauber"))
            if not spots:
                for tx, ty in _OPP_TOWERS:
                    spots.append((tx, ty, "zauber-turm"))
            return spots

        # Gebäudeangreifer wollen über die Brücke.
        if st.targets_buildings_only:
            for bx in BRIDGES:
                spots.append((bx, RIVER_Y + 0.5, "angriff"))
            return spots

        # Verteidiger: zwischen Bedrohung und dem bedrohten Turm.
        for tx, ty in threats:
            tower = min(OUR_TOWERS, key=lambda t: (t[0] - tx) ** 2 + (t[1] - ty) ** 2)
            for frac in (0.35, 0.6):
                spots.append((tx + (tower[0] - tx) * frac,
                              ty + (tower[1] - ty) * frac, "verteidigung"))
            # Direkt davor, um den Weg zu blockieren.
            spots.append((tx, ty + 1.5, "block"))

        # Ohne erkannte Bedrohung: hinter dem Königsturm aufbauen.
        if not spots:
            spots.append((OUR_KING[0], OUR_KING[1] - 1.5, "aufbau"))
            for bx in BRIDGES:
                spots.append((bx, RIVER_Y + 2.0, "druck"))
        return spots

    def candidates(self, hand: list[str], elixir: float,
                   threats: list[tuple[float, float]]) -> list[Candidate]:
        """Alle bezahlbaren, sinnvoll platzierten Züge.

        Die Maskierung passiert hier und nur hier: Was nicht bezahlbar oder
        nicht sinnvoll platzierbar ist, taucht gar nicht erst auf.
        """
        out: list[Candidate] = []
        for card in hand:
            if not card:
                continue
            st = self._stats(card)
            if st is None:
                continue
            cost = float(st.elixir) if st.elixir else 4.0
            if cost > elixir:
                continue
            for x, y, role in self._placements(card, st, threats):
                x = float(np.clip(x, 0.5, arena.TILES_W - 0.5))
                y = float(np.clip(y, 0.5, arena.TILES_H - 0.5))
                out.append(Candidate(card, x, y, cost, role))
        return out

    # ---------------------------------------------------------------- Suche

    def evaluate(self, units: list[tuple[str, int, float, float, float]],
                 cands: list[Candidate],
                 tower_hp: dict[str, float] | None = None) -> tuple[float, list[float]]:
        """Bewertet vorgegebene Kandidaten. Gibt (Warte-Score, Scores) zurueck.

        Getrennt von :meth:`decide`, damit auch **nachtraeglich** bewertet
        werden kann — die Nachanalyse stellt hier den tatsaechlich gespielten
        Zug neben die Alternativen.
        """
        batch = len(cands) + 1
        capacity = 6 + len(units) + 1

        st = self.fm.with_towers(batch, capacity, tower_hp)
        for i, (cls, side, x, y, hp) in enumerate(units):
            key = cls if cls in self.fm.stats.index else _base_key(cls, self.fm.stats.index)
            if key is None:
                continue
            self.fm.add_unit(st, 6 + i, key, side, x, y, hp=hp if hp > 0 else None)

        slot = 6 + len(units)
        for i, c in enumerate(cands, start=1):
            key = c.card if c.card in self.fm.stats.index else _base_key(c.card, self.fm.stats.index)
            if key is None:
                continue
            mask = np.zeros(batch, bool)
            mask[i] = True
            cs = self._stats(c.card)
            if cs is not None and cs.is_spell:
                self.fm.apply_spell(st, c.x, c.y, cs.splash_radius, cs.damage,
                                    caster_side=0, batch_mask=mask)
            else:
                self.fm.add_unit(st, slot, key, 0, c.x, c.y, batch_mask=mask)

        out = self.fm.rollout(st, self.horizon_s, self.dt)
        # Reiner Turm-HP-Saldo; das Elixir kommt erst in der Schwelle dazu.
        scores = self.fm.score(st, out)
        return float(scores[0]), [float(v) for v in scores[1:]]

    def decide(self, units: list[tuple[str, int, float, float, float]],
               hand: list[str], elixir: float,
               tower_hp: dict[str, float] | None = None) -> Decision:
        """Waehlt den besten Zug.

        ``units`` sind die wahrgenommenen Einheiten als
        ``(klasse, seite, x, y, hp)``.
        """
        t0 = time.perf_counter()
        threats = [(x, y) for cls, side, x, y, _hp in units
                   if side == 1 and self._stats(cls) is not None]

        cands = self.candidates([c for c in hand if c], elixir, threats)
        wait_score, scores = self.evaluate(units, cands, tower_hp)

        ranked: list[tuple[Candidate | None, float]] = [(None, wait_score)]
        ranked += list(zip(cands, scores))
        ranked.sort(key=lambda r: -r[1])

        best_cand, best_score = ranked[0]
        # Nur spielen, wenn der Vorsprung Grundschwelle plus Elixirpreis schlaegt.
        if best_cand is not None:
            required = self.min_margin + best_cand.cost * self.elixir_margin_hp
            if best_score - wait_score < required:
                best_cand, best_score = None, wait_score

        return Decision(
            best=best_cand, score=best_score, wait_score=wait_score,
            considered=len(cands), ranked=ranked[:8],
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        )


def _base_key(card: str, index: dict[str, int]) -> str | None:
    for suffix in ("-evolution", "-big", "-mid", "-small"):
        if card.endswith(suffix) and card[: -len(suffix)] in index:
            return card[: -len(suffix)]
    return None


def _clusters(points: list[tuple[float, float]], radius: float = 2.5
              ) -> list[tuple[float, float]]:
    """Gruppiert Punkte grob und liefert die Schwerpunkte.

    Ein Flächenzauber lohnt sich dort, wo mehrere Einheiten stehen — nicht auf
    der erstbesten.
    """
    remaining = list(points)
    out: list[tuple[float, float]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        rest = []
        for p in remaining:
            if (p[0] - seed[0]) ** 2 + (p[1] - seed[1]) ** 2 <= radius * radius:
                group.append(p)
            else:
                rest.append(p)
        remaining = rest
        out.append((sum(p[0] for p in group) / len(group),
                    sum(p[1] for p in group) / len(group)))
    return out
