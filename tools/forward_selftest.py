"""Prüft das Vorwärtsmodell an Szenarien mit nachrechenbarem Ausgang.

    python tools/forward_selftest.py

Jeder Test vergleicht gegen einen Wert, der sich aus den Kampfwerten von Hand
ergibt — nicht gegen eine frühere Ausgabe des Modells. Sonst zementiert man nur
den eigenen Fehler.
"""

from __future__ import annotations

import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from crbot.forward import (  # noqa: E402
    RIVER_Y_TILES, BRIDGE_X_TILES, ForwardModel,
)

PASS, FAIL = "OK  ", "FEHL"
results: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((ok, name))
    print(f"[{PASS if ok else FAIL}] {name}\n       {detail}")


def duel_state(fm: ForwardModel, capacity: int = 8):
    """Arena **ohne Türme** — für Tests, die ein reines Duell messen wollen.

    Mit Türmen misst man sonst unbemerkt deren Beschuss mit: Ein
    Prinzessinnenturm reicht 7,5 Kacheln weit und macht 62,5 DPS, zwei davon
    übertreffen jede kleine Einheit deutlich.
    """
    return fm.empty_state(1, capacity)


def t_movement_speed(fm: ForwardModel) -> None:
    """Hog Rider läuft mit 1,5 Kacheln/s — über 2 s also 3,0 Kacheln."""
    st = fm.with_towers(1, 12)
    fm.add_unit(st, 6, "hog-rider", 0, BRIDGE_X_TILES[0], RIVER_Y_TILES - 1.0)
    y0 = float(st.pos[0, 6, 1])
    out = fm.rollout(st, horizon_s=2.0, dt=0.05)
    travelled = abs(out.pos[0, 6, 1] - y0)
    check("Bewegungstempo Hog Rider",
          2.6 <= travelled <= 3.1,
          f"in 2,0 s zurückgelegt: {travelled:.2f} Kacheln (erwartet ~3,0)")


def t_knight_vs_skeleton(fm: ForwardModel) -> None:
    """Ritter 65,8 DPS gegen Skelett 32 HP -> tot nach ~0,49 s.

    Ohne Türme, sonst schießen die mit und das Skelett stirbt dreimal so schnell.
    """
    st = duel_state(fm)
    fm.add_unit(st, 6, "knight", 0, 9.0, 20.0)
    fm.add_unit(st, 7, "skeleton", 1, 9.4, 20.0)

    dead_at = None
    for i in range(200):
        fm.step(st, 0.02)
        if not st.alive[0, 7]:
            dead_at = (i + 1) * 0.02
            break
    knight_hp = st.hp[0, 6]
    check("Ritter tötet Skelett",
          dead_at is not None and 0.40 <= dead_at <= 0.62,
          f"Skelett tot nach {dead_at if dead_at else float('nan'):.2f} s "
          f"(erwartet ~0,49), Ritter noch {knight_hp:.0f}/690 HP")


def t_range_advantage(fm: ForwardModel) -> None:
    """Musketier (6 Kacheln) trifft, während der Ritter (1,2) erst anlaufen muss."""
    st = fm.with_towers(1, 12)
    fm.add_unit(st, 6, "musketeer", 0, 9.0, 22.0)
    fm.add_unit(st, 7, "knight", 1, 9.0, 14.0)   # 8 Kacheln entfernt
    fm.rollout(st, 0.0)
    out = fm.rollout(st, horizon_s=4.0, dt=0.05)
    knight_dmg = 690.0 - out.hp[0, 7]
    musk_dmg = 340.0 - out.hp[0, 6]
    check("Reichweitenvorteil Musketier",
          knight_dmg > 150 and musk_dmg == 0,
          f"Ritter hat {knight_dmg:.0f} Schaden genommen, Musketier {musk_dmg:.0f} "
          f"— der Ritter ist nach 4 s noch nicht in Reichweite")


def t_buildings_only(fm: ForwardModel) -> None:
    """Golem greift nur Gebäude an und läuft an Truppen vorbei.

    Ohne eigene Türme aufgebaut, sonst beschiessen die den gegnerischen Ritter
    und der Test misst deren Schaden statt den des Golems. Ein weit entfernter
    gegnerischer Turm ist trotzdem nötig — sonst greift die Rückfallregel und
    der Golem geht mangels Gebäude doch auf Truppen los.
    """
    st = duel_state(fm)
    fm.add_unit(st, 0, "princess-tower", 1, 3.5, 6.5, hp=3052.0)
    fm.add_unit(st, 6, "golem", 0, 9.0, 20.0)
    fm.add_unit(st, 7, "knight", 1, 9.6, 20.0)   # direkt daneben
    out = fm.rollout(st, horizon_s=3.0, dt=0.05)
    knight_dmg = 690.0 - out.hp[0, 7]
    moved = np.linalg.norm(out.pos[0, 6] - st.pos[0, 6])
    check("Golem ignoriert Truppen",
          knight_dmg == 0 and moved > 1.0,
          f"Ritter nahm {knight_dmg:.0f} Schaden, Golem ist {moved:.2f} Kacheln "
          f"weitergelaufen (Richtung Turm)")


def t_river_routing(fm: ForwardModel) -> None:
    """Bodeneinheiten laufen zur Brücke, nicht quer durchs Wasser."""
    st = fm.with_towers(1, 12)
    start_x = 9.0   # Feldmitte, weit von beiden Brücken
    fm.add_unit(st, 6, "knight", 0, start_x, RIVER_Y_TILES + 4.0)
    out = fm.rollout(st, horizon_s=4.0, dt=0.05)
    dx = out.pos[0, 6, 0] - start_x
    nearest_bridge = min(BRIDGE_X_TILES, key=lambda b: abs(b - start_x))
    toward_bridge = np.sign(nearest_bridge - start_x)
    check("Bodeneinheit nimmt die Brücke",
          abs(dx) > 0.5 and np.sign(dx) == toward_bridge,
          f"seitlich {dx:+.2f} Kacheln Richtung Brücke bei x={nearest_bridge:.1f}")


def t_air_ignores_river(fm: ForwardModel) -> None:
    """Lufteinheiten fliegen direkt."""
    st = fm.with_towers(1, 12)
    start_x = 9.0
    fm.add_unit(st, 6, "baby-dragon", 0, start_x, RIVER_Y_TILES + 4.0)
    out = fm.rollout(st, horizon_s=4.0, dt=0.05)
    dy = st.pos[0, 6, 1] - out.pos[0, 6, 1]
    check("Lufteinheit fliegt direkt",
          dy > 1.0,
          f"{dy:.2f} Kacheln nach vorn, ohne Umweg über die Brücke")


def t_batch_consistency(fm: ForwardModel) -> None:
    """Gleiche Szenarien im Batch müssen identische Ergebnisse liefern."""
    b = 64
    st = fm.with_towers(b, 12)
    fm.add_unit(st, 6, "knight", 0, 9.0, 20.0)
    fm.add_unit(st, 7, "musketeer", 1, 9.0, 17.0)
    out = fm.rollout(st, horizon_s=3.0, dt=0.05)
    spread = float(np.abs(out.hp - out.hp[0:1]).max())
    check("Batch-Konsistenz",
          spread < 1e-4,
          f"maximale Abweichung über {b} identische Szenarien: {spread:.2e}")


def t_scoring(fm: ForwardModel) -> None:
    """Ein Verteidiger muss besser bewertet werden als gar nichts zu tun."""
    cap = 12
    st = fm.with_towers(2, cap)
    # Beide Szenarien: gegnerischer Hog Rider vor unserem linken Turm.
    tower_x, tower_y = st.pos[0, 0]
    fm.add_unit(st, 6, "hog-rider", 1, float(tower_x), float(tower_y) - 2.5)
    # Nur in Szenario 1: wir stellen einen Ritter dagegen.
    mask = np.array([False, True])
    fm.add_unit(st, 7, "knight", 0, float(tower_x), float(tower_y) - 2.0,
                batch_mask=mask)

    out = fm.rollout(st, horizon_s=6.0, dt=0.05)
    scores = fm.score(st, out)
    check("Bewertung bevorzugt Verteidigung",
          scores[1] > scores[0],
          f"ohne Verteidiger {scores[0]:.0f}, mit Ritter {scores[1]:.0f} "
          f"(Differenz {scores[1] - scores[0]:.0f} Turm-HP)")


def t_throughput(fm: ForwardModel) -> None:
    """Wie viele Kandidaten sind pro Zug realistisch?"""
    b, cap, horizon, dt = 512, 24, 4.0, 0.25
    st = fm.with_towers(b, cap)
    for slot, (key, side) in enumerate(
            [("knight", 0), ("musketeer", 0), ("hog-rider", 1), ("minion", 1)], start=6):
        fm.add_unit(st, slot, key, side, 9.0 + slot * 0.3, 16.0 + side * 4)

    t0 = time.perf_counter()
    fm.rollout(st, horizon_s=horizon, dt=dt)
    elapsed = time.perf_counter() - t0
    per_scenario_us = elapsed / b * 1e6
    check("Durchsatz",
          elapsed < 5.0,
          f"{b} Szenarien x {horizon:.0f} s Horizont in {elapsed * 1000:.0f} ms "
          f"({per_scenario_us:.0f} us je Szenario, NumPy auf CPU)")


def main() -> int:
    fm = ForwardModel()
    print(f"Kampfwerte geladen: {len(fm.stats.keys)} Einheitentypen\n")

    for fn in (t_movement_speed, t_knight_vs_skeleton, t_range_advantage,
               t_buildings_only, t_river_routing, t_air_ignores_river,
               t_batch_consistency, t_scoring, t_throughput):
        try:
            fn(fm)
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
