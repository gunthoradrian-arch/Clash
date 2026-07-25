"""Gegnermodell: was hat er auf der Hand, und was kann er sich leisten?

Der wichtigste Teil einer "Vorhersage" ist gar keine Vorhersage, sondern
Buchführung. Clash Royale zieht aus einem **festen Zyklus von acht Karten**:
Eine gespielte Karte wandert ans Ende der Warteschlange, die vorderste rückt
nach. Wer mitzählt, weiß nach dem ersten vollständigen Zyklus **exakt**, welche
vier Karten in der Hand liegen und welche als nächste kommt — keine Statistik,
keine Unsicherheit.

Dasselbe gilt fürs Elixir des Gegners: Startwert, bekannte Regenerationsrate,
minus die Kosten jeder beobachteten Karte. Ergibt eine harte Schätzung mit
kleiner Fehlerspanne.

Erst darauf setzt echte Statistik auf — wohin er legt und wann. Diese Reihenfolge
ist wichtig: Wer die exakt berechenbaren Teile durch ein gelerntes Modell
ersetzt, tauscht Gewissheit gegen Rauschen.

Praktischer Nutzen
------------------
* **Elixir-Vorteil erkennen**: "Gegner hat 3 Elixir, in der Hand nur Teures"
  ist der Moment für einen Push.
* **Vorhaltende Zauber**: Wenn der Zyklus sagt, dass der Kobold-Fass wieder
  bereit ist, lohnt sich der Log auf den Turm, *bevor* das Fass fliegt.
* **Bedrohungen antizipieren**: Was er in vier Sekunden legen *kann*, ist eine
  kurze, exakte Liste — nicht das ganze Deck.
"""

from __future__ import annotations

import dataclasses

from crbot.cardstats import UnitStats, load_table

DECK_SIZE = 8
HAND_SIZE = 4

ELIXIR_START = 5.0
ELIXIR_MAX = 10.0

# Regenerationsphasen: einfach, doppelt ab 2:00, dreifach in der Verlängerung.
SINGLE_RATE = 1.0 / 2.8
DOUBLE_FROM_S = 120.0
TRIPLE_FROM_S = 180.0


def elixir_rate(t: float) -> float:
    if t >= TRIPLE_FROM_S:
        return 3 * SINGLE_RATE
    if t >= DOUBLE_FROM_S:
        return 2 * SINGLE_RATE
    return SINGLE_RATE


def elixir_regenerated(t_from: float, t_to: float) -> float:
    """Integriert die Rate über ein Intervall, inklusive Phasenwechsel."""
    total = 0.0
    cuts = sorted({t_from, t_to} | {c for c in (DOUBLE_FROM_S, TRIPLE_FROM_S)
                                    if t_from < c < t_to})
    for a, b in zip(cuts, cuts[1:]):
        total += (b - a) * elixir_rate(a)
    return total


@dataclasses.dataclass
class CyclePrediction:
    hand: list[str | None]        # 4 Plätze, None = noch unbekannt
    next_card: str | None         # die 5. Karte, im Spiel sichtbar angedeutet
    known_cards: int              # wie viele der 8 Deckkarten wir kennen
    complete: bool                # Zyklus vollständig bekannt?

    @property
    def certain(self) -> list[str]:
        return [c for c in self.hand if c]


class OpponentModel:
    """Verfolgt Deck-Zyklus und Elixir des Gegners.

    Beides ist reine Buchführung über beobachtete Züge. Fehlt ein Zug, weil die
    Wahrnehmung ihn verpasst hat, driftet die Schätzung — deshalb meldet
    ``elixir_confidence`` sinkendes Vertrauen mit der Zahl unerklärter Sprünge.
    """

    def __init__(self, table: dict[str, UnitStats] | None = None) -> None:
        self.table = table or load_table()
        # Warteschlange der acht Deckkarten in Zyklusreihenfolge.
        # Vorne die Hand, dahinter die Nachrücker; None = noch nicht gesehen.
        self.queue: list[str | None] = [None] * DECK_SIZE
        self.plays: list[tuple[float, str]] = []

        self._elixir = ELIXIR_START
        self._last_t = 0.0
        self._unexplained = 0

    # ------------------------------------------------------------ Beobachten

    def observe_play(self, t: float, card: str) -> None:
        """Meldet einen beobachteten gegnerischen Zug."""
        self._advance_to(t)
        self._elixir = max(0.0, self._elixir - self.cost_of(card))
        self.plays.append((t, card))
        self._rotate(card)

    def observe_elixir(self, t: float, value: float) -> None:
        """Korrigiert die Schätzung, falls der Balken doch ablesbar ist."""
        self._advance_to(t)
        if abs(value - self._elixir) > 1.5:
            self._unexplained += 1
        self._elixir = value

    def _advance_to(self, t: float) -> None:
        if t > self._last_t:
            self._elixir = min(ELIXIR_MAX,
                               self._elixir + elixir_regenerated(self._last_t, t))
            self._last_t = t

    def _rotate(self, card: str) -> None:
        """Karte ans Ende der Warteschlange, Rest rückt nach."""
        if card in self.queue:
            idx = self.queue.index(card)
        else:
            # Neue Karte: sie lag in einem noch unbekannten Handplatz.
            idx = next((i for i in range(HAND_SIZE) if self.queue[i] is None), None)
            if idx is None:
                # Mehr als acht verschiedene Karten gesehen — sollte nicht
                # vorkommen. Ältesten Platz freimachen statt zu verlieren.
                idx = 0
            self.queue[idx] = card
        self.queue.pop(idx)
        self.queue.append(card)

    # ------------------------------------------------------------- Auskünfte

    def cost_of(self, card: str) -> float:
        st = self.table.get(card)
        if st is None:
            for suffix in ("-evolution", "-big", "-mid", "-small"):
                if card.endswith(suffix):
                    st = self.table.get(card[: -len(suffix)])
                    break
        if st is not None and st.elixir:
            return float(st.elixir)
        return 4.0  # unbekannte Karte: mittlerer Wert statt Absturz

    def elixir(self, t: float | None = None) -> float:
        if t is not None:
            self._advance_to(t)
        return self._elixir

    @property
    def elixir_confidence(self) -> float:
        """1.0 = sauber mitgezählt, sinkt mit unerklärten Sprüngen."""
        return max(0.0, 1.0 - 0.25 * self._unexplained)

    def cycle(self) -> CyclePrediction:
        known = sum(1 for c in self.queue if c)
        return CyclePrediction(
            hand=list(self.queue[:HAND_SIZE]),
            next_card=self.queue[HAND_SIZE],
            known_cards=known,
            complete=known == DECK_SIZE,
        )

    def affordable_now(self, t: float | None = None) -> list[str]:
        """Karten der Hand, die er sich **jetzt** leisten kann."""
        e = self.elixir(t)
        return [c for c in self.cycle().certain if self.cost_of(c) <= e]

    def affordable_within(self, seconds: float, t: float | None = None) -> list[str]:
        """Karten, die er innerhalb der nächsten Sekunden bezahlen kann.

        Das ist die eigentlich relevante Bedrohungsliste: kurz, exakt, und viel
        kleiner als "irgendwas aus acht Karten".
        """
        now = self._last_t if t is None else t
        e = self.elixir(now) + elixir_regenerated(now, now + seconds)
        e = min(ELIXIR_MAX, e)
        return [c for c in self.cycle().certain if self.cost_of(c) <= e]

    def cycle_position(self, card: str) -> int | None:
        """Wie viele Züge dauert es, bis ``card`` wieder in der Hand ist?

        0 = liegt jetzt in der Hand. None = Karte noch nie gesehen.
        """
        if card not in self.queue:
            return None
        idx = self.queue.index(card)
        return max(0, idx - (HAND_SIZE - 1))

    def elixir_advantage(self, our_elixir: float, t: float | None = None) -> float:
        """Positiv heißt: wir haben mehr Elixir als er."""
        return our_elixir - self.elixir(t)


# --------------------------------------------------------------- Spekulation


@dataclasses.dataclass
class SpeculativeCall:
    """Bewertung eines vorhaltenden Zuges — z.B. Log auf den Turm."""

    card: str
    x: float
    y: float
    probability: float     # wie wahrscheinlich trifft die Vorhersage?
    value_if_hit: float    # aus dem Vorwärtsmodell: gesparte Turm-HP
    cost_elixir: float
    elixir_advantage: float

    @property
    def expected_value(self) -> float:
        """Erwartungswert in Turm-HP.

        Der Elixir-Einsatz wird in HP umgerechnet und mit dem Vorteil skaliert:
        Wer vorne liegt, kann sich einen Fehlschuss leisten; wer hinten liegt,
        nicht. Genau das macht Spekulation zu einer Frage der Lage, nicht des
        Mutes.
        """
        miss_penalty = self.cost_elixir * _elixir_to_hp(self.elixir_advantage)
        return self.probability * self.value_if_hit - (1 - self.probability) * miss_penalty

    @property
    def worth_it(self) -> bool:
        return self.expected_value > 0.0


def _elixir_to_hp(advantage: float) -> float:
    """Was ein Elixir "kostet", gemessen in Turm-HP.

    Bei Gleichstand rund 120 HP je Elixir. Mit wachsendem Vorsprung sinkt der
    Wert (man kann verschwenden), mit Rückstand steigt er stark.
    """
    base = 120.0
    return base * max(0.35, 1.0 - 0.18 * advantage)
