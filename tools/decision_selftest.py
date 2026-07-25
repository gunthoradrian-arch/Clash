"""Prüft Rollout-Suche und Kalibrierung.

    python tools/decision_selftest.py

Die Suche wird an Lagen geprüft, bei denen die richtige Antwort offensichtlich
ist: Bedrohung vor dem Turm -> verteidigen. Nichts los und wenig Elixir ->
warten. Die Kalibrierung wird gegen künstlich erzeugte Vorhersagereihen mit
bekanntem Bias geprüft.
"""

from __future__ import annotations

import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from crbot.calibration import Calibrator, Prediction, wilson_interval  # noqa: E402
from crbot.search import BRIDGES, RIVER_Y, RolloutSearch  # noqa: E402

PASS, FAIL = "OK  ", "FEHL"
results: list[tuple[bool, str]] = []
HAND = ["knight", "musketeer", "fireball", "skeleton"]


def check(name: str, ok: bool, detail: str) -> None:
    results.append((ok, name))
    print(f"[{PASS if ok else FAIL}] {name}\n       {detail}")


# ------------------------------------------------------------------- Suche


def t_defends_threat(rs: RolloutSearch) -> None:
    """Ein Hog Rider vor dem Turm muss eine Antwort auslösen."""
    threat = (BRIDGES[0], RIVER_Y + 3.0)
    units = [("hog-rider", 1, threat[0], threat[1], 800.0)]
    d = rs.decide(units, HAND, elixir=10.0)
    check("Verteidigt gegen Bedrohung",
          d.plays and d.margin > 0,
          d.explain())


def t_action_masking(rs: RolloutSearch) -> None:
    """Mit 2 Elixir dürfen teure Karten gar nicht erst auftauchen."""
    threat = (BRIDGES[0], RIVER_Y + 3.0)
    units = [("hog-rider", 1, threat[0], threat[1], 800.0)]
    cands = rs.candidates(HAND, elixir=2.0, threats=[threat])
    cards = {c.card for c in cands}
    check("Aktionsmaskierung",
          cards <= {"skeleton"} and "musketeer" not in cards and "fireball" not in cards,
          f"bei 2 Elixir bleiben {sorted(cards) or 'keine Karten'} "
          f"({len(cands)} Kandidaten statt aller Felder)")


def t_waiting_is_an_option(rs: RolloutSearch) -> None:
    """Ohne Bedrohung und ohne Nutzen ist Warten die richtige Antwort."""
    d = rs.decide(units=[], hand=HAND, elixir=3.0)
    check("Warten ist ein Kandidat",
          not d.plays,
          d.explain())


def t_spell_targets_cluster(rs: RolloutSearch) -> None:
    """Ein Flächenzauber zielt auf die Gruppe, nicht auf eine Einzeleinheit."""
    cluster = [(6.0, 10.0), (6.4, 10.3), (5.8, 10.6), (6.2, 9.7)]
    lonely = (14.0, 9.0)
    threats = cluster + [lonely]
    cands = rs.candidates(["fireball"], elixir=10.0, threats=threats)
    if not cands:
        check("Zauber zielt auf die Gruppe", False, "keine Kandidaten erzeugt")
        return
    cx = sum(p[0] for p in cluster) / len(cluster)
    cy = sum(p[1] for p in cluster) / len(cluster)
    near_cluster = [c for c in cands
                    if (c.x - cx) ** 2 + (c.y - cy) ** 2 < 1.0]
    check("Zauber zielt auf die Gruppe",
          bool(near_cluster),
          f"{len(cands)} Zielpunkte, davon {len(near_cluster)} auf dem Schwerpunkt "
          f"({cx:.1f},{cy:.1f})")


def t_determinism(rs: RolloutSearch) -> None:
    """Gleiche Lage muss gleiche Entscheidung liefern."""
    units = [("hog-rider", 1, BRIDGES[1], RIVER_Y + 2.0, 800.0)]
    a = rs.decide(units, HAND, elixir=8.0)
    b = rs.decide(units, HAND, elixir=8.0)
    same = (a.best is None) == (b.best is None) and abs(a.score - b.score) < 1e-6
    check("Determinismus",
          same,
          f"zweimal dieselbe Lage -> {a.explain().split(' — ')[0]} / "
          f"{b.explain().split(' — ')[0]}")


def t_latency(rs: RolloutSearch) -> None:
    """Passt die Suche ins Latenzbudget?"""
    units = [("hog-rider", 1, BRIDGES[0], RIVER_Y + 2.0, 800.0),
             ("musketeer", 1, BRIDGES[0] - 1, RIVER_Y - 1.0, 340.0),
             ("knight", 0, BRIDGES[0], RIVER_Y + 5.0, 690.0)]
    d = rs.decide(units, HAND, elixir=10.0)
    check("Latenz der Suche",
          d.elapsed_ms < 120.0,
          f"{d.considered} Kandidaten in {d.elapsed_ms:.1f} ms "
          f"(Budget für die Entscheidung ~120 ms)")


def t_opponent_response_dampens(rs: RolloutSearch) -> None:
    """Eine simulierte Gegnerantwort muss frühen Druck unattraktiver machen.

    Ohne sie sieht ein Zug an der Brücke grossartig aus, weil ihn niemand
    bestraft. Genau das war im Trockenlauf zu sehen: Der Bot legte schon bei
    Sekunde 0 eine Musketiererin vor.
    """
    from crbot.opponent import OpponentModel

    om = OpponentModel(rs.table)
    for i, card in enumerate(["hog-rider", "musketeer", "knight", "fireball"]):
        om.observe_play(i * 6.0, card)
    om.observe_elixir(40.0, 10.0)

    naive = rs.decide([], HAND, elixir=10.0)
    aware = rs.decide([], HAND, elixir=10.0, opponent=om)

    naive_role = naive.best.role if naive.best else "warten"
    aware_role = aware.best.role if aware.best else "warten"
    defensive = {"verteidigung", "block", "zauber"}

    check("Gegnerantwort dämpft frühen Druck",
          naive_role == "druck" and aware_role in defensive,
          f"ohne Antwort wählt er Druck an der Brücke ({naive.best}); mit "
          f"angenommener Antwort ({aware.response}) verteidigt er stattdessen "
          f"({aware.best}, Rolle {aware_role})")


def t_response_is_fair(rs: RolloutSearch) -> None:
    """Die Antwort kommt in alle Szenarien — auch ins Warten."""
    from crbot.opponent import OpponentModel

    om = OpponentModel(rs.table)
    om.observe_play(0.0, "hog-rider")
    om.observe_elixir(10.0, 10.0)

    without = rs.decide([], HAND, elixir=10.0)
    with_resp = rs.decide([], HAND, elixir=10.0, opponent=om)
    check("Antwort trifft alle Szenarien gleich",
          with_resp.wait_score < without.wait_score,
          f"Warte-Score sinkt von {without.wait_score:.0f} auf "
          f"{with_resp.wait_score:.0f} — die Antwort schadet auch beim Nichtstun")


# -------------------------------------------------------------- Kalibrierung


def _series(n: int, predicted: float, true_rate: float, seed: int = 0) -> list[Prediction]:
    rng = random.Random(seed)
    return [Prediction(t=float(i), kind="spell_prediction", predicted=predicted,
                       hit=rng.random() < true_rate) for i in range(n)]


def t_calibration_identity() -> None:
    """Wer richtig liegt, wird nicht korrigiert."""
    c = Calibrator()
    c.record_many(_series(400, predicted=0.5, true_rate=0.5, seed=1))
    corrected = c.calibrate(0.5)
    check("Kalibrierung lässt korrekte Quoten stehen",
          abs(corrected - 0.5) < 0.05,
          f"0,50 vorhergesagt, 0,50 eingetreten -> korrigiert {corrected:.3f}, "
          f"Brier {c.brier_score():.3f}")


def t_calibration_shrinks_overconfidence() -> None:
    """Wer zu mutig ist, bekommt die Quote gesenkt."""
    c = Calibrator()
    c.record_many(_series(400, predicted=0.8, true_rate=0.4, seed=2))
    corrected = c.calibrate(0.8)
    oc = c.overconfidence()
    check("Übermut wird gesenkt",
          corrected < 0.55 and oc > 0.3,
          f"0,80 vorhergesagt, {1 - (oc or 0) - 0.2:.2f} eingetreten -> "
          f"korrigiert {corrected:.3f} (Abweichung {oc:+.3f})")


def t_calibration_small_sample() -> None:
    """Bei drei Beobachtungen darf sich fast nichts ändern."""
    c = Calibrator()
    c.record_many([Prediction(t=float(i), kind="spell_prediction",
                              predicted=0.7, hit=False) for i in range(3)])
    corrected = c.calibrate(0.7)
    lo, hi = wilson_interval(0, 3)
    check("Kleine Stichprobe verschiebt wenig",
          corrected > 0.45,
          f"3x daneben -> korrigiert {corrected:.3f} statt auf 0 zu fallen "
          f"(Konfidenzintervall der Messung: {lo:.2f}–{hi:.2f})")


def t_calibration_closes_gate() -> None:
    """Die Korrektur muss einen spekulativen Zug tatsächlich abschalten können."""
    from crbot.opponent import SpeculativeCall

    raw_p = 0.45
    c = Calibrator()
    c.record_many(_series(400, predicted=raw_p, true_rate=0.12, seed=3))
    cal_p = c.calibrate(raw_p)

    common = dict(card="the-log", x=3.5, y=6.5, value_if_hit=700.0,
                  cost_elixir=2.0, elixir_advantage=0.0)
    before = SpeculativeCall(**common, probability=raw_p)
    after = SpeculativeCall(**common, probability=cal_p)
    check("Kalibrierung schliesst das Tor",
          before.worth_it and not after.worth_it,
          f"roh {raw_p:.2f} -> EV {before.expected_value:+.0f} HP (spielen); "
          f"kalibriert {cal_p:.2f} -> EV {after.expected_value:+.0f} HP (lassen)")


def main() -> int:
    rs = RolloutSearch()
    print("Rollout-Suche bereit\n")
    for fn in (t_defends_threat, t_action_masking, t_waiting_is_an_option,
               t_spell_targets_cluster, t_determinism, t_latency,
               t_opponent_response_dampens, t_response_is_fair):
        try:
            fn(rs)
        except Exception as e:  # noqa: BLE001
            check(fn.__name__, False, f"Ausnahme: {type(e).__name__}: {e}")
        print()

    for fn2 in (t_calibration_identity, t_calibration_shrinks_overconfidence,
                t_calibration_small_sample, t_calibration_closes_gate):
        try:
            fn2()
        except Exception as e:  # noqa: BLE001
            check(fn2.__name__, False, f"Ausnahme: {type(e).__name__}: {e}")
        print()

    failed = [n for ok, n in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} bestanden")
    if failed:
        print("Fehlgeschlagen: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
