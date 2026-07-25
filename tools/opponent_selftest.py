"""Prüft das Gegnermodell an von Hand nachrechenbaren Abläufen.

    python tools/opponent_selftest.py

Der Zyklus ist deterministisch — die Sollwerte ergeben sich aus den Spielregeln,
nicht aus einem früheren Lauf des Modells.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from crbot.opponent import (  # noqa: E402
    DOUBLE_FROM_S, ELIXIR_START, SINGLE_RATE, OpponentModel, SpeculativeCall,
    elixir_regenerated,
)

PASS, FAIL = "OK  ", "FEHL"
results: list[tuple[bool, str]] = []

DECK = ["knight", "musketeer", "fireball", "skeleton",
        "cannon", "minion", "arrows", "hog-rider"]


def check(name: str, ok: bool, detail: str) -> None:
    results.append((ok, name))
    print(f"[{PASS if ok else FAIL}] {name}\n       {detail}")


def t_cycle_completes() -> None:
    """Nach acht verschiedenen Zügen ist der Zyklus vollständig bekannt."""
    om = OpponentModel()
    for i, card in enumerate(DECK):
        om.observe_play(t=i * 4.0, card=card)
    cyc = om.cycle()
    check("Zyklus vollständig nach 8 Zügen",
          cyc.complete and cyc.known_cards == 8,
          f"bekannt: {cyc.known_cards}/8, Hand: {[c for c in cyc.hand]}")


def t_cycle_order() -> None:
    """Wer acht Karten in Reihenfolge spielt, hat danach die ersten vier in der Hand.

    Nach dem 8. Zug steht die Warteschlange wieder in Ausgangsreihenfolge —
    die zuerst gespielten Karten sind durchrotiert und liegen vorne.
    """
    om = OpponentModel()
    for i, card in enumerate(DECK):
        om.observe_play(t=i * 4.0, card=card)
    hand = om.cycle().hand
    expected = DECK[:4]
    check("Zyklusreihenfolge stimmt",
          hand == expected,
          f"Hand {hand}, erwartet {expected}")


def t_next_card() -> None:
    """Die fünfte Position ist die Karte, die als nächste nachrückt."""
    om = OpponentModel()
    for i, card in enumerate(DECK):
        om.observe_play(t=i * 4.0, card=card)
    om.observe_play(t=40.0, card="knight")   # erste Handkarte gespielt
    cyc = om.cycle()
    check("Nachrückende Karte vorhergesagt",
          cyc.hand == ["musketeer", "fireball", "skeleton", "cannon"]
          and cyc.next_card == "minion",
          f"Hand {cyc.hand}, als nächstes {cyc.next_card}")


def t_elixir_accounting() -> None:
    """Start 5, Feuerball (4) bei t=0, danach 5,6 s Regeneration -> 3,0."""
    om = OpponentModel()
    om.observe_play(t=0.0, card="fireball")
    after_play = om.elixir(0.0)
    later = om.elixir(5.6)
    expected = 1.0 + 5.6 * SINGLE_RATE
    check("Elixir-Buchführung",
          abs(after_play - 1.0) < 0.01 and abs(later - expected) < 0.05,
          f"nach dem Zug {after_play:.2f}, nach 5,6 s {later:.2f} "
          f"(erwartet {expected:.2f})")


def t_double_elixir() -> None:
    """Ab 2:00 regeneriert es doppelt so schnell."""
    single = elixir_regenerated(100.0, 110.0)
    double = elixir_regenerated(130.0, 140.0)
    across = elixir_regenerated(115.0, 125.0)
    expected_across = 5 * SINGLE_RATE + 5 * 2 * SINGLE_RATE
    check("Doppel-Elixir-Phase",
          abs(double - 2 * single) < 1e-6 and abs(across - expected_across) < 1e-6,
          f"10 s einfach {single:.2f}, doppelt {double:.2f}, "
          f"über die Grenze bei {DOUBLE_FROM_S:.0f}s: {across:.2f} "
          f"(erwartet {expected_across:.2f})")


def t_affordable() -> None:
    """Bedrohungsliste: was kann er jetzt und in 4 s bezahlen?"""
    om = OpponentModel()
    for i, card in enumerate(DECK):
        om.observe_play(t=i * 6.0, card=card)
    # Elixirstand direkt setzen statt ihn ueber die Zeit zu erwuerfeln — sonst
    # testet man die Buchfuehrung noch einmal statt die Bezahlbarkeit.
    # Hand ist jetzt knight(3), musketeer(4), fireball(4), skeleton(1).
    om.observe_elixir(t=70.0, value=3.2)
    now = om.affordable_now(t=70.0)
    soon = om.affordable_within(seconds=6.0, t=70.0)   # +2,1 Elixir -> 5,3
    check("Bedrohungsliste waechst mit der Zeit",
          set(now) == {"knight", "skeleton"} and set(soon) == set(om.cycle().certain),
          f"Elixir 3,2 -> jetzt {sorted(now)}; in 6 s ({om.elixir(76.0):.1f}) "
          f"{sorted(soon)}")


def t_cycle_position() -> None:
    """Wie viele Züge, bis eine Karte wieder verfügbar ist?"""
    om = OpponentModel()
    for i, card in enumerate(DECK):
        om.observe_play(t=i * 4.0, card=card)
    in_hand = om.cycle_position("knight")       # liegt jetzt vorne
    far = om.cycle_position("hog-rider")        # zuletzt gespielt
    unknown = om.cycle_position("golem")
    check("Zyklusabstand",
          in_hand == 0 and far == 4 and unknown is None,
          f"knight in {in_hand} Zügen, hog-rider in {far}, "
          f"golem unbekannt ({unknown})")


def t_speculation_direction() -> None:
    """Elixir-Vorteil muss den Erwartungswert in die richtige Richtung schieben.

    Ein guter Tipp bleibt ein guter Tipp: 45 % auf 700 gesparte Turm-HP für
    2 Elixir lohnt sich auch mit Rückstand — nur weniger deutlich. Der Test
    prüft deshalb die Richtung, nicht ein willkürliches Vorzeichen.
    """
    common = dict(card="the-log", x=3.5, y=6.5, probability=0.45,
                  value_if_hit=700.0, cost_elixir=2.0)
    ahead = SpeculativeCall(**common, elixir_advantage=4.0)
    even = SpeculativeCall(**common, elixir_advantage=0.0)
    behind = SpeculativeCall(**common, elixir_advantage=-4.0)
    check("Elixir-Vorteil verschiebt den Erwartungswert",
          ahead.expected_value > even.expected_value > behind.expected_value,
          f"EV bei +4/0/-4 Elixir: {ahead.expected_value:+.0f} / "
          f"{even.expected_value:+.0f} / {behind.expected_value:+.0f} HP")


def t_speculation_flip() -> None:
    """Bei einem knappen Tipp kippt die Lage die Entscheidung.

    Nur 20 % Trefferchance: mit Vorsprung noch vertretbar, mit Rückstand nicht.
    """
    common = dict(card="the-log", x=3.5, y=6.5, probability=0.20,
                  value_if_hit=700.0, cost_elixir=2.0)
    ahead = SpeculativeCall(**common, elixir_advantage=4.0)
    behind = SpeculativeCall(**common, elixir_advantage=-4.0)
    check("Knapper Tipp kippt mit der Lage",
          ahead.worth_it and not behind.worth_it,
          f"mit +4 Elixir: EV {ahead.expected_value:+.0f} HP (spielen), "
          f"mit -4: EV {behind.expected_value:+.0f} HP (lassen)")


def t_partial_knowledge() -> None:
    """Vor dem ersten vollen Zyklus bleibt die Hand teilweise unbekannt."""
    om = OpponentModel()
    for i, card in enumerate(DECK[:3]):
        om.observe_play(t=i * 4.0, card=card)
    cyc = om.cycle()
    unknown = sum(1 for c in cyc.hand if c is None)
    check("Teilwissen wird als solches gemeldet",
          not cyc.complete and cyc.known_cards == 3 and unknown > 0,
          f"3 Karten gesehen, {unknown} Handplätze noch unbekannt, "
          f"sicher: {cyc.certain}")


def main() -> int:
    print(f"Startelixir {ELIXIR_START:.0f}, Regeneration 1 je {1 / SINGLE_RATE:.1f} s\n")
    for fn in (t_cycle_completes, t_cycle_order, t_next_card, t_elixir_accounting,
               t_double_elixir, t_affordable, t_cycle_position,
               t_speculation_direction, t_speculation_flip, t_partial_knowledge):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(fn.__name__, False, f"Ausnahme: {type(e).__name__}: {e}")
        print()

    failed = [n for ok, n in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} bestanden")
    if failed:
        print("Fehlgeschlagen: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
