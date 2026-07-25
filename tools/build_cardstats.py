"""Erzeugt die Kampfwerte-Tabelle einmalig aus dem oeffentlichen Spieldaten-Dump.

    python tools/build_cardstats.py

Ergebnis landet in ``crbot/data/unit_stats.json`` und wird eingecheckt — zur
Laufzeit braucht der Bot dann kein Netz. Nach einem Balance-Update erneut
laufen lassen.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from crbot.cardstats import (  # noqa: E402
    CARDS_URL, TABLE_PATH, build_table, fetch_raw, save_table,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=pathlib.Path, help="lokale cards_stats.json statt Download")
    ap.add_argument("--cards", type=pathlib.Path, help="lokale cards.json statt Download")
    ap.add_argument("--out", type=pathlib.Path, default=TABLE_PATH)
    args = ap.parse_args()

    raw = json.loads(args.raw.read_text()) if args.raw else fetch_raw()
    cards = json.loads(args.cards.read_text()) if args.cards else fetch_raw(CARDS_URL)
    table = build_table(raw, cards)
    save_table(table, args.out)

    movers = [u for u in table.values() if u.speed > 0]
    ranged = [u for u in table.values() if u.range > 2.0]
    no_dmg = [u.key for u in table.values() if u.damage <= 0]

    print(f"{len(table)} Einheiten -> {args.out}")
    print(f"  beweglich: {len(movers)}   Fernkaempfer (>2 Kacheln): {len(ranged)}")
    print(f"  ohne Schaden: {len(no_dmg)} ({', '.join(sorted(no_dmg)[:8])}"
          f"{' ...' if len(no_dmg) > 8 else ''})")

    print("\nStichprobe:")
    print(f"  {'Einheit':16s} {'HP':>6s} {'DPS':>7s} {'Rw':>5s} {'Tempo':>6s}  Ziele")
    for key in ("knight", "musketeer", "hog-rider", "golem", "minion", "skeleton", "balloon"):
        u = table.get(key)
        if not u:
            continue
        targets = []
        if u.attacks_ground:
            targets.append("Boden")
        if u.attacks_air:
            targets.append("Luft")
        if u.targets_buildings_only:
            targets = ["nur Gebaeude"]
        print(f"  {u.key:16s} {u.hp:6.0f} {u.dps:7.1f} {u.range:5.1f} "
              f"{u.speed:6.2f}  {'/'.join(targets)}")


if __name__ == "__main__":
    main()
