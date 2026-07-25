"""Format für Match-Aufzeichnungen — die Grundlage jeder Nachanalyse.

Ein Bot, der verliert und nicht weiß warum, wird nie besser. Deshalb schreibt
jedes Spiel ein Protokoll: was auf dem Feld stand, wie viel Elixir da war, was
gelegt wurde und wie sich die Turm-HP entwickelt haben.

JSONL, eine Zeile pro Eintrag, streambar — bricht das Spiel ab, ist alles bis
dahin trotzdem lesbar:

    {"type":"meta",  "deck":[...], "mode":"1v1", "started_at":...}
    {"type":"tick",  "t":12.3, "elixir":6.2, "towers":{...}, "units":[...]}
    {"type":"play",  "t":12.5, "side":0, "card":"knight", "x":9.0, "y":20.0}
    {"type":"result","t":184.0, "outcome":"loss", "crowns":[0,2]}

Koordinaten sind **Kacheln** (18 x 32), nicht Pixel — dieselbe Einheit wie die
Kampfwerte in ``crbot.cardstats``. Umrechnung: ``crbot.arena.px_to_tile``.

``side``: 0 = wir, 1 = Gegner. Gleiche Konvention wie ``blong`` im Labelformat.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import time
from typing import Iterator

TOWER_KEYS = ("self_left", "self_right", "self_king", "opp_left", "opp_right", "opp_king")

# Elixir-Regeneration: 1 Elixir pro 2,8 s in der einfachen Phase.
ELIXIR_PER_S_SINGLE = 1.0 / 2.8
ELIXIR_MAX = 10.0


@dataclasses.dataclass(slots=True)
class Unit:
    """Eine Einheit auf dem Feld zum Zeitpunkt eines Ticks."""

    uid: int
    cls: str
    side: int
    x: float
    y: float
    hp_frac: float = 1.0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass(slots=True)
class Tick:
    t: float
    elixir: float
    towers: dict[str, float]           # Turm -> aktuelle HP
    units: list[Unit] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": "tick", "t": round(self.t, 2), "elixir": round(self.elixir, 2),
            "towers": {k: round(v, 1) for k, v in self.towers.items()},
            "units": [u.to_dict() for u in self.units],
        }


@dataclasses.dataclass(slots=True)
class Play:
    t: float
    side: int
    card: str
    x: float
    y: float
    elixir_cost: float | None = None

    def to_dict(self) -> dict:
        return {"type": "play", "t": round(self.t, 2), "side": self.side,
                "card": self.card, "x": round(self.x, 2), "y": round(self.y, 2),
                "elixir_cost": self.elixir_cost}


@dataclasses.dataclass
class MatchLog:
    meta: dict = dataclasses.field(default_factory=dict)
    ticks: list[Tick] = dataclasses.field(default_factory=list)
    plays: list[Play] = dataclasses.field(default_factory=list)
    outcome: str | None = None          # "win" | "loss" | "draw"
    crowns: tuple[int, int] = (0, 0)
    duration_s: float = 0.0

    # --------------------------------------------------------------- Schreiben

    def write(self, path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            f.write(json.dumps({"type": "meta", **self.meta}) + "\n")
            # Ticks und Plays zeitlich verschraenkt schreiben, damit das
            # Protokoll auch beim Abbruch chronologisch bleibt.
            entries: list[tuple[float, dict]] = [(t.t, t.to_dict()) for t in self.ticks]
            entries += [(p.t, p.to_dict()) for p in self.plays]
            for _t, d in sorted(entries, key=lambda e: e[0]):
                f.write(json.dumps(d) + "\n")
            if self.outcome:
                f.write(json.dumps({
                    "type": "result", "t": round(self.duration_s, 2),
                    "outcome": self.outcome, "crowns": list(self.crowns),
                }) + "\n")

    # ----------------------------------------------------------------- Lesen

    @classmethod
    def read(cls, path: pathlib.Path) -> "MatchLog":
        log = cls()
        for entry in _iter_jsonl(path):
            kind = entry.get("type")
            if kind == "meta":
                log.meta = {k: v for k, v in entry.items() if k != "type"}
            elif kind == "tick":
                log.ticks.append(Tick(
                    t=entry["t"], elixir=entry.get("elixir", 0.0),
                    towers=entry.get("towers", {}),
                    units=[Unit(**u) for u in entry.get("units", [])],
                ))
            elif kind == "play":
                log.plays.append(Play(
                    t=entry["t"], side=entry["side"], card=entry["card"],
                    x=entry["x"], y=entry["y"],
                    elixir_cost=entry.get("elixir_cost"),
                ))
            elif kind == "result":
                log.outcome = entry.get("outcome")
                log.crowns = tuple(entry.get("crowns", (0, 0)))
                log.duration_s = entry.get("t", 0.0)
        if not log.duration_s and log.ticks:
            log.duration_s = log.ticks[-1].t
        return log

    # ------------------------------------------------------------ Hilfsgroessen

    def tower_hp(self, key: str) -> list[tuple[float, float]]:
        """Zeitreihe (t, HP) eines Turms."""
        return [(tk.t, tk.towers[key]) for tk in self.ticks if key in tk.towers]

    def plays_of(self, side: int) -> list[Play]:
        return [p for p in self.plays if p.side == side]

    def units_at(self, t: float) -> list[Unit]:
        """Einheiten im zeitlich naechstgelegenen Tick."""
        if not self.ticks:
            return []
        nearest = min(self.ticks, key=lambda tk: abs(tk.t - t))
        return nearest.units


def _iter_jsonl(path: pathlib.Path) -> Iterator[dict]:
    with pathlib.Path(path).open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # Abgeschnittene letzte Zeile nach einem Absturz — ignorieren.
                continue


class MatchRecorder:
    """Sammelt Ticks und Plays waehrend des Spiels.

    Bewusst schlank: Der Recorder darf die Spielschleife nicht ausbremsen.
    Geschrieben wird erst am Ende bzw. auf Zuruf.
    """

    def __init__(self, deck: list[str], mode: str = "1v1") -> None:
        self.log = MatchLog(meta={
            "deck": deck, "mode": mode, "started_at": time.time(),
        })

    def tick(self, t: float, elixir: float, towers: dict[str, float],
             units: list[Unit]) -> None:
        self.log.ticks.append(Tick(t, elixir, dict(towers), list(units)))

    def play(self, t: float, side: int, card: str, x: float, y: float,
             elixir_cost: float | None = None) -> None:
        self.log.plays.append(Play(t, side, card, x, y, elixir_cost))

    def finish(self, outcome: str, crowns: tuple[int, int], t: float) -> MatchLog:
        self.log.outcome = outcome
        self.log.crowns = crowns
        self.log.duration_s = t
        return self.log
