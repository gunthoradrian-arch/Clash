"""Die Spielschleife: Wahrnehmung → Zustand → Entscheidung → Zug.

Hier laufen alle Bausteine zusammen. Die Wahrnehmung ist bewusst als
austauschbare Schnittstelle geschnitten — auf dieser Seite steckt eine
synthetische Quelle drin, auf dem PC kommt der echte Detektor rein. Alles
dazwischen ist identisch und hier vollständig geprüft.

Ablauf je Frame::

    Bild -> Erkennungen -> Tracker -> Bedrohungen
                                   |
                            Gegnerzüge erkannt -> Gegnermodell (Zyklus, Elixir)
                                   |
                                 Suche -> Zug oder warten -> Protokoll

Ein Detail, das leicht übersehen wird: **Gegnerzüge muss niemand melden.** Ein
neu bestätigter gegnerischer Track ist ein gelegter Zug — daraus füttert sich
die Zyklus- und Elixir-Buchführung von selbst.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol

from crbot import arena
from crbot.matchlog import MatchRecorder
from crbot.matchlog import Unit as LogUnit
from crbot.opponent import OpponentModel
from crbot.search import Candidate, Decision, RolloutSearch
from crbot.tracker import Detection, Track, Tracker

RIVER_Y = arena.px_to_tile(0.0, arena.RIVER_Y)[1]


class Perception(Protocol):
    """Was die Wahrnehmungsschicht liefern muss.

    Auf dem PC: Detektor + Kachel-Umrechnung. Hier: eine synthetische Quelle.
    Die Schleife kennt den Unterschied nicht.
    """

    def detect(self, frame, t: float) -> list[Detection]:
        ...


@dataclasses.dataclass
class LoopConfig:
    # Wie oft entschieden wird. Häufiger kostet Rechenzeit ohne Gewinn — das
    # Spiel ändert sich nicht in 50 Millisekunden grundlegend.
    decide_every_s: float = 0.35
    # Mindestabstand zwischen zwei eigenen Zügen; verhindert Doppelablagen,
    # solange der gelegte Zug noch nicht auf dem Feld erkannt wurde.
    min_play_gap_s: float = 0.8
    record: bool = True


@dataclasses.dataclass
class LoopResult:
    t: float
    tracks: list[Track]
    decision: Decision | None
    action: Candidate | None
    opponent_elixir: float
    opponent_hand: list[str]


class BotLoop:
    """Führt Wahrnehmung, Gegnermodell, Suche und Protokoll zusammen."""

    def __init__(self, perception: Perception, deck: list[str],
                 search: RolloutSearch | None = None,
                 tracker: Tracker | None = None,
                 config: LoopConfig | None = None) -> None:
        self.perception = perception
        self.deck = list(deck)
        self.search = search or RolloutSearch()
        self.tracker = tracker or Tracker()
        self.cfg = config or LoopConfig()

        self.opponent = OpponentModel(self.search.table)
        self.own = OpponentModel(self.search.table)
        self.recorder = MatchRecorder(deck=self.deck) if self.cfg.record else None

        self._seen_enemy_ids: set[int] = set()
        self._last_decision_t = -999.0
        self._last_play_t = -999.0

    # ------------------------------------------------------------------ Lauf

    def step(self, frame, t: float, our_elixir: float,
             tower_hp: dict[str, float] | None = None) -> LoopResult:
        detections = self.perception.detect(frame, t)
        tracks = self.tracker.update(detections, t)

        self._absorb_opponent_plays(tracks, t)

        decision: Decision | None = None
        action: Candidate | None = None
        if t - self._last_decision_t >= self.cfg.decide_every_s:
            self._last_decision_t = t
            hand = self._own_hand()
            units = [tr.as_tuple() for tr in tracks]
            decision = self.search.decide(units, hand, our_elixir, tower_hp,
                                          opponent=self.opponent)
            if decision.plays and t - self._last_play_t >= self.cfg.min_play_gap_s:
                action = decision.best
                self._commit(action, t)

        if self.recorder is not None:
            self.recorder.tick(
                t, our_elixir, tower_hp or {},
                [LogUnit(tr.id, tr.cls, tr.side, tr.x, tr.y, tr.hp_frac) for tr in tracks],
            )

        return LoopResult(
            t=t, tracks=tracks, decision=decision, action=action,
            opponent_elixir=self.opponent.elixir(t),
            opponent_hand=self.opponent.cycle().certain,
        )

    # ------------------------------------------------------------- Bausteine

    def _absorb_opponent_plays(self, tracks: list[Track], t: float) -> None:
        """Ein neu bestätigter gegnerischer Track ist ein gelegter Zug.

        Damit füttert sich die Zyklus- und Elixir-Buchführung von selbst — es
        braucht keine separate Erkennung der gegnerischen Handleiste.
        """
        for tr in tracks:
            if tr.side != 1 or tr.id in self._seen_enemy_ids:
                continue
            self._seen_enemy_ids.add(tr.id)
            self.opponent.observe_play(t, tr.cls)
            if self.recorder is not None:
                self.recorder.play(t, 1, tr.cls, tr.x, tr.y)

    def _own_hand(self) -> list[str]:
        """Eigenes Blatt: Zyklus, aufgefüllt aus dem bekannten Deck."""
        hand = [c for c in self.own.cycle().hand if c]
        for card in self.deck:
            if len(hand) >= 4:
                break
            if card not in hand:
                hand.append(card)
        return hand

    def _commit(self, action: Candidate, t: float) -> None:
        self._last_play_t = t
        self.own.observe_play(t, action.card)
        if self.recorder is not None:
            self.recorder.play(t, 0, action.card, action.x, action.y, action.cost)

    def finish(self, outcome: str, crowns: tuple[int, int], t: float):
        if self.recorder is None:
            return None
        return self.recorder.finish(outcome, crowns, t)


class ScriptedPerception:
    """Synthetische Wahrnehmung für Tests und Trockenläufe.

    Spielt ein Drehbuch aus ``(zeit, klasse, seite, x, y)`` ab und lässt
    Einheiten mit ihrem echten Tempo auf den nächsten Turm zulaufen. Damit
    lässt sich die ganze Schleife prüfen, ohne dass ein Emulator läuft.
    """

    def __init__(self, script: list[tuple[float, str, int, float, float]],
                 table=None) -> None:
        from crbot.cardstats import load_table
        self.table = table or load_table()
        self.script = sorted(script)
        self.spawned: list[dict] = []
        self._last_t = 0.0

    def detect(self, frame, t: float) -> list[Detection]:
        dt = max(0.0, t - self._last_t)
        self._last_t = t

        for entry in self.script:
            if entry[0] <= t and entry not in [s["entry"] for s in self.spawned]:
                _, cls, side, x, y = entry
                self.spawned.append({"entry": entry, "cls": cls, "side": side,
                                     "x": x, "y": y})

        goal_y = {0: 3.0, 1: 25.5}   # jeweils Richtung gegnerischer Turm
        out: list[Detection] = []
        for s in self.spawned:
            st = self.table.get(s["cls"])
            speed = st.speed if st else 0.75
            direction = 1.0 if s["side"] == 1 else -1.0
            s["y"] += direction * speed * dt
            if not (0.0 <= s["y"] <= arena.TILES_H):
                continue
            _ = goal_y
            out.append(Detection(s["cls"], s["side"], s["x"], s["y"]))
        return out
