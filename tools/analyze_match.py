"""Wertet ein Match-Protokoll aus — vor allem nach Niederlagen.

    python tools/analyze_match.py --log data/matches/2026-07-25_1830.jsonl
    python tools/analyze_match.py --demo          # synthetisches Spiel, prueft die Kette

``--demo`` baut ein plausibles verlorenes Spiel zusammen und analysiert es.
Damit laesst sich die gesamte Kette pruefen, ohne dass ein Emulator laeuft.
"""

from __future__ import annotations

import argparse
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from crbot import arena  # noqa: E402
from crbot.matchlog import MatchLog, MatchRecorder, Unit  # noqa: E402
from crbot.counterfactual import analyze_plays  # noqa: E402
from crbot.counterfactual import to_markdown as cf_markdown  # noqa: E402
from crbot.postmortem import analyze, to_markdown  # noqa: E402

# Turm-HP auf Turnierstufe.
KING_HP = 4824.0
PRINCESS_HP = 3052.0


def synthesize_losing_match(seed: int = 7) -> MatchLog:
    """Baut ein Spiel, das an typischen Fehlern scheitert.

    Eingebaute Muster, die die Analyse finden soll:
    Elixir laeuft mehrfach ueber, auf Hog Rider wird zu spaet reagiert, und
    teure Antworten auf billige Zuege ruinieren die Elixir-Bilanz.
    """
    rng = random.Random(seed)
    deck = ["knight", "musketeer", "fireball", "skeleton",
            "cannon", "minion", "arrows", "hog-rider"]
    rec = MatchRecorder(deck=deck, mode="1v1")

    towers = {
        "self_king": KING_HP, "self_left": PRINCESS_HP, "self_right": PRINCESS_HP,
        "opp_king": KING_HP, "opp_left": PRINCESS_HP, "opp_right": PRINCESS_HP,
    }

    river_y = arena.px_to_tile(0, arena.RIVER_Y)[1]
    left_tower = arena.px_to_tile(114.0, 684.0)

    elixir = 5.0
    units: list[Unit] = []
    uid = 0
    t = 0.0
    dt = 0.5

    # Gegner setzt wiederholt auf Hog Rider, wir antworten zu teuer und zu spaet.
    opp_schedule = [(18.0, "hog-rider"), (46.0, "hog-rider"), (74.0, "hog-rider"),
                    (96.0, "musketeer"), (118.0, "hog-rider"), (150.0, "hog-rider")]
    my_schedule = [(22.5, "fireball", 4.0), (51.0, "musketeer", 4.0),
                   (79.5, "fireball", 4.0), (124.0, "knight", 3.0),
                   (156.5, "musketeer", 4.0)]

    opp_i = my_i = 0
    while t < 180.0:
        rate = 1 / 2.8 if t < 120 else 2 / 2.8
        elixir = min(10.0, elixir + rate * dt)

        while opp_i < len(opp_schedule) and opp_schedule[opp_i][0] <= t:
            _, card = opp_schedule[opp_i]
            x = left_tower[0] + rng.uniform(-1, 1)
            rec.play(t, 1, card, x, river_y + 1.0)
            uid += 1
            units.append(Unit(uid, card, 1, x, river_y + 1.0))
            opp_i += 1

        while my_i < len(my_schedule) and my_schedule[my_i][0] <= t:
            _, card, cost = my_schedule[my_i]
            rec.play(t, 0, card, left_tower[0], left_tower[1] - 2.0, cost)
            elixir = max(0.0, elixir - cost)
            my_i += 1

        # Gegnerische Einheiten laufen auf unseren linken Turm zu und schlagen zu.
        for u in units:
            if u.side != 1:
                continue
            dx, dy = left_tower[0] - u.x, left_tower[1] - u.y
            d = max(1e-6, (dx * dx + dy * dy) ** 0.5)
            if d > 1.8:
                step = 1.5 * dt  # Hog Rider ist sehr schnell
                u.x += dx / d * step
                u.y += dy / d * step
            else:
                towers["self_left"] = max(0.0, towers["self_left"] - 94.0 * dt)

        units = [u for u in units if towers["self_left"] > 0 or u.side == 0]
        if towers["self_left"] <= 0:
            units = [u for u in units if u.side != 1]

        # Wir kratzen am gegnerischen Turm, aber zu wenig.
        if t > 60:
            towers["opp_left"] = max(0.0, towers["opp_left"] - 6.0 * dt)

        rec.tick(t, elixir, towers, list(units))
        t += dt

    crowns = (0, 1 if towers["self_left"] <= 0 else 0)
    return rec.finish("loss" if crowns[1] > crowns[0] else "draw", crowns, t)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", type=pathlib.Path)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--md", type=pathlib.Path, help="Bericht als Markdown schreiben")
    ap.add_argument("--save-demo", type=pathlib.Path, help="synthetisches Protokoll ablegen")
    ap.add_argument("--counterfactual", action="store_true",
                    help="zusaetzlich bewerten, was besser gewesen waere (rechenintensiv)")
    args = ap.parse_args()

    if args.demo:
        log = synthesize_losing_match()
        if args.save_demo:
            log.write(args.save_demo)
            print(f"Protokoll geschrieben: {args.save_demo}")
    elif args.log:
        log = MatchLog.read(args.log)
    else:
        raise SystemExit("--log <datei> oder --demo angeben")

    pm = analyze(log)
    report = to_markdown(pm)

    if args.counterfactual:
        from crbot.search import RolloutSearch
        report += "\n" + cf_markdown(analyze_plays(log, RolloutSearch()))

    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(report)
        print(f"Bericht geschrieben: {args.md}")
    print(report)


if __name__ == "__main__":
    main()
