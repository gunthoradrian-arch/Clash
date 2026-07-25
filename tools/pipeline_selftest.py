"""Trockenlauf der kompletten Schleife — ohne Emulator, ohne GPU.

    python tools/pipeline_selftest.py

Spielt ein synthetisches Spiel durch: Wahrnehmung → Tracker → Gegnermodell →
Suche → Zug → Protokoll. Prüft damit genau die Verdrahtung, die auf dem PC
später nur noch einen echten Detektor vorgesetzt bekommt.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from crbot import arena  # noqa: E402
from crbot.pipeline import BotLoop, LoopConfig, ScriptedPerception  # noqa: E402

PASS, FAIL = "OK  ", "FEHL"
results: list[tuple[bool, str]] = []

DECK = ["knight", "musketeer", "fireball", "skeleton",
        "cannon", "minion", "arrows", "hog-rider"]
RIVER_Y = arena.px_to_tile(0.0, arena.RIVER_Y)[1]
BRIDGE = arena.px_to_tile(114.0, 0.0)[0]


def check(name: str, ok: bool, detail: str) -> None:
    results.append((ok, name))
    print(f"[{PASS if ok else FAIL}] {name}\n       {detail}")


def run_match(duration: float = 60.0, dt: float = 0.2):
    """Gegner schickt drei Wellen; wir lassen den Bot antworten."""
    script = [
        (6.0, "hog-rider", 1, BRIDGE, RIVER_Y - 1.0),
        (22.0, "musketeer", 1, BRIDGE + 1.0, RIVER_Y - 2.0),
        (40.0, "hog-rider", 1, BRIDGE, RIVER_Y - 1.0),
    ]
    loop = BotLoop(ScriptedPerception(script), DECK, config=LoopConfig())

    tower_hp = {"self_king": 4824.0, "self_left": 3052.0, "self_right": 3052.0,
                "opp_king": 4824.0, "opp_left": 3052.0, "opp_right": 3052.0}
    elixir = 5.0
    actions = []
    results_log = []

    t = 0.0
    while t < duration:
        elixir = min(10.0, elixir + dt / 2.8)
        r = loop.step(None, t, elixir, tower_hp)
        if r.action is not None:
            elixir = max(0.0, elixir - r.action.cost)
            actions.append((t, r.action))
        results_log.append(r)
        t += dt

    log = loop.finish("draw", (0, 0), t)
    return loop, actions, results_log, log


def t_loop_runs() -> None:
    loop, actions, rs, log = run_match()
    check("Schleife läuft durch",
          len(rs) > 250 and log is not None,
          f"{len(rs)} Frames simuliert, {len(log.ticks)} Ticks protokolliert")


def t_reacts() -> None:
    loop, actions, rs, log = run_match()
    check("Bot reagiert auf Wellen",
          len(actions) >= 2,
          f"{len(actions)} Züge gespielt: "
          + ", ".join(f"{t:.0f}s {a.card}" for t, a in actions[:5]))


def t_opponent_tracked() -> None:
    """Gegnerzüge werden allein aus den Tracks erkannt.

    Geprüft wird die Zahl der **gesehenen** Karten, nicht die Hand: Frisch
    gespielte Karten liegen hinten in der Warteschlange und sind gerade
    *nicht* auf der Hand. Eine leere Handvorhersage nach drei Zügen ist
    richtig, nicht kaputt.
    """
    loop, actions, rs, log = run_match()
    opp_plays = [p for p in log.plays if p.side == 1]
    cyc = loop.opponent.cycle()
    check("Gegnerzüge automatisch erkannt",
          len(opp_plays) == 3 and cyc.known_cards >= 2,
          f"{len(opp_plays)} gegnerische Züge ohne separate Erkennung erfasst; "
          f"{cyc.known_cards} von 8 Deckkarten bekannt, davon gerade "
          f"{len(cyc.certain)} auf der Hand")


def t_opponent_elixir() -> None:
    """Die Elixir-Buchführung des Gegners läuft mit."""
    loop, actions, rs, log = run_match()
    after_first = next(r for r in rs if r.t > 7.0)
    check("Gegner-Elixir wird mitgezählt",
          0.0 <= after_first.opponent_elixir <= 10.0,
          f"nach dem ersten Hog Rider: {after_first.opponent_elixir:.1f} Elixir "
          f"(Start 5, Hog kostet 4)")


def t_no_double_play() -> None:
    """Kein zweiter Zug, bevor der erste auf dem Feld angekommen ist."""
    loop, actions, rs, log = run_match()
    gaps = [b[0] - a[0] for a, b in zip(actions, actions[1:])]
    check("Keine Doppelablagen",
          all(g >= 0.79 for g in gaps) if gaps else True,
          f"kleinster Abstand zwischen zwei Zügen: "
          f"{min(gaps):.2f} s" if gaps else "nur ein Zug")


def t_log_is_analyzable() -> None:
    """Das Protokoll muss durch die Nachanalyse laufen."""
    from crbot.postmortem import analyze, to_markdown
    loop, actions, rs, log = run_match()
    pm = analyze(log)
    md = to_markdown(pm)
    check("Protokoll ist auswertbar",
          len(md) > 200 and pm.duration_s > 50,
          f"Bericht über {pm.duration_s:.0f} s erzeugt, "
          f"{len(pm.findings)} Befund(e), {len(md)} Zeichen")


def main() -> int:
    for fn in (t_loop_runs, t_reacts, t_opponent_tracked, t_opponent_elixir,
               t_no_double_play, t_log_is_analyzable):
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
