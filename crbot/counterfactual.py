"""Kontrafaktische Analyse: was wäre besser gewesen?

Die Nachanalyse in :mod:`crbot.postmortem` beschreibt, *was* passiert ist.
Dieses Modul beantwortet die nächste Frage: *was hättest du stattdessen tun
sollen?*

Für jeden eigenen Zug wird der Spielzustand von damals rekonstruiert und die
Rollout-Suche darauf angewandt. Der tatsächlich gespielte Zug steht dann neben
den Alternativen, bewertet in derselben Währung — Turm-HP.

Der Clou bei der Handrekonstruktion
-----------------------------------
Welche Karten damals in der Hand lagen, muss nicht geraten werden: Der
Deck-Zyklus ist deterministisch. Dieselbe Buchführung, die im Spiel das
gegnerische Blatt verfolgt (:class:`crbot.opponent.OpponentModel`), läuft hier
rückwärts über die eigenen Züge.

Grenzen, die man kennen muss
----------------------------
Die Bewertung nutzt dasselbe Vorwärtsmodell wie die Suche. Ein Zug, den das
Modell falsch einschätzt, wird auch im Rückblick falsch eingeschätzt — die
Analyse kann die eigene Blindheit nicht sehen. Sie taugt für grobe Fehlgriffe
("du hast auf der falschen Seite verteidigt"), nicht für Feinheiten.
"""

from __future__ import annotations

import dataclasses

from crbot.matchlog import MatchLog, Play
from crbot.opponent import OpponentModel
from crbot.search import Candidate, RolloutSearch


@dataclasses.dataclass
class Counterfactual:
    """Ein Zug im Vergleich zur besten Alternative."""

    t: float
    played: str
    played_x: float
    played_y: float
    played_score: float
    best: Candidate | None
    best_score: float
    wait_score: float
    hand: list[str]

    @property
    def loss(self) -> float:
        """Wie viel Turm-HP der tatsächliche Zug gegenüber dem besten kostete."""
        return self.best_score - self.played_score

    @property
    def better_to_wait(self) -> bool:
        return self.wait_score > self.played_score and self.wait_score >= self.best_score


def analyze_plays(log: MatchLog, search: RolloutSearch | None = None,
                  max_plays: int = 40) -> list[Counterfactual]:
    """Bewertet die eigenen Züge gegen die Alternativen von damals."""
    search = search or RolloutSearch()
    own = OpponentModel(search.table)   # verfolgt hier *unser* Blatt
    deck = [c for c in log.meta.get("deck", []) if c]

    plays = sorted(log.plays_of(0), key=lambda p: p.t)
    out: list[Counterfactual] = []
    for n, play in enumerate(plays):
        if n >= max_plays:
            break
        hand = _reconstruct_hand(own, deck, plays[:n], play.card)

        cf = _evaluate_play(log, search, play, hand)
        if cf is not None:
            out.append(cf)
        own.observe_play(play.t, play.card)

    out.sort(key=lambda c: -c.loss)
    return out


def _reconstruct_hand(own: OpponentModel, deck: list[str],
                      earlier: list[Play], played: str) -> list[str]:
    """Welche Karten lagen zu diesem Zeitpunkt plausibel auf der Hand?

    Beim **eigenen** Blatt ist die Lage besser als beim gegnerischen: Das Deck
    steht von Anfang an fest. Solange der Zyklus noch nicht vollständig
    beobachtet ist, füllen wir die unbekannten Plätze mit Deckkarten auf, die
    zuletzt nicht gespielt wurden — die liegen dann nämlich ganz hinten in der
    Warteschlange und stehen gerade *nicht* zur Verfügung.
    """
    hand = [c for c in own.cycle().hand if c]
    if played not in hand:
        hand = hand + [played]

    if deck:
        recent = {p.card for p in earlier[-3:]}
        for card in deck:
            if len(hand) >= 4:
                break
            if card not in hand and card not in recent:
                hand.append(card)
    return hand


def _evaluate_play(log: MatchLog, search: RolloutSearch, play: Play,
                   hand: list[str]) -> Counterfactual | None:
    tick = _tick_before(log, play.t)
    if tick is None:
        return None

    units = [(u.cls, u.side, u.x, u.y, 0.0) for u in tick.units]
    threats = [(u.x, u.y) for u in tick.units if u.side == 1]

    # Der tatsaechliche Zug wird als erster Kandidat mitbewertet — gleiche
    # Waehrung, gleicher Horizont, gleicher Zustand.
    st = search._stats(play.card)
    cost = float(st.elixir) if st and st.elixir else 4.0
    actual = Candidate(play.card, play.x, play.y, cost, "gespielt")

    alternatives = search.candidates(hand, elixir=tick.elixir, threats=threats)
    cands = [actual] + [c for c in alternatives
                        if not (c.card == actual.card
                                and abs(c.x - actual.x) < 0.3
                                and abs(c.y - actual.y) < 0.3)]

    wait_score, scores = search.evaluate(units, cands, tick.towers or None)
    played_score = scores[0]
    best_idx = max(range(len(scores)), key=lambda i: scores[i])

    return Counterfactual(
        t=play.t, played=play.card, played_x=play.x, played_y=play.y,
        played_score=played_score,
        best=cands[best_idx] if best_idx != 0 else None,
        best_score=scores[best_idx], wait_score=wait_score, hand=hand,
    )


def _tick_before(log: MatchLog, t: float):
    """Letzter Tick vor dem Zug — der Zustand, auf dem entschieden wurde."""
    prior = [tk for tk in log.ticks if tk.t <= t]
    return prior[-1] if prior else None


def to_markdown(cfs: list[Counterfactual], top_n: int = 6) -> str:
    if not cfs:
        return ("## Kontrafaktische Analyse\n\nKeine auswertbaren Züge — das "
                "Protokoll enthält zu wenige Ticks vor den Zügen.\n")

    L = ["## Was besser gewesen wäre\n"]
    notable = [c for c in cfs if c.loss > 20.0][:top_n]
    if not notable:
        L.append("Kein Zug lag nennenswert unter der besten Alternative. Die "
                 "Niederlage lag dann nicht an der Kartenwahl — eher an "
                 "Elixir-Haushalt oder Wahrnehmung.\n")
        return "\n".join(L) + "\n"

    L.append("| Zeit | gespielt | besser gewesen | Unterschied |")
    L.append("|---|---|---|---|")
    for c in notable:
        alt = "warten" if c.best is None else str(c.best)
        L.append(f"| {c.t:.0f} s | `{c.played}` @({c.played_x:.1f},{c.played_y:.1f}) "
                 f"| `{alt}` | **{c.loss:.0f} HP** |")
    L.append("")

    worst = notable[0]
    alt = "nichts zu tun" if worst.best is None else f"`{worst.best}`"
    L.append(f"> Der teuerste Fehlgriff war bei {worst.t:.0f} s: `{worst.played}` "
             f"statt {alt} kostete rund {worst.loss:.0f} Turm-HP. "
             f"Auf der Hand lagen damals: {', '.join(f'`{h}`' for h in worst.hand)}.\n")
    L.append("> Bewertet mit demselben Vorwärtsmodell, das auch die Suche nutzt — "
             "grobe Fehlgriffe findet es, Feinheiten nicht.\n")
    return "\n".join(L) + "\n"
