"""Sagt dir, welche Karten dein Datensatz NICHT abdeckt.

Der Fremddatensatz ist von Oktober 2023. Seitdem sind Karten, Evolutionen,
Champions und Turmtruppen dazugekommen. Statt blind "mehr Daten" zu sammeln,
beantwortet dieses Tool die eigentliche Frage: **was genau fehlt?**

Ergebnis ist eine Ernteliste für ``tools/harvest_cutouts.py``.

Quellen für die aktuelle Kartenliste
------------------------------------
``--source supercell --token <T>``
    Offizielle API, ``https://api.clashroyale.com/v1/cards``. Immer aktuell,
    inklusive Evolutionen (``maxEvolutionLevel``). Kostenloser Key unter
    https://developer.clashroyale.com — der Key ist an eine IP gebunden.

``--source royaleapi``  (Standard, ohne Key)
    Öffentliche JSON der Community. Achtung: die Basiskarten sind brauchbar,
    die **Evolutionsangaben sind veraltet** (Stand der Prüfung: 8 statt 30+).
    Für eine vollständige Evo-Liste die Supercell-Quelle nehmen.

``--cards-json <datei>``
    Lokale Datei, falls du die Liste anderweitig hast.

WICHTIG: Das Ergebnis ist nur so aktuell wie die Kartenliste. Meldet der
Abgleich fast keine Luecken, kann das auch heissen, dass **beide** Seiten
gleich alt sind — genau das ist bei der royaleapi-Quelle der Fall.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from crbot.classes import real_class_names  # noqa: E402
from crbot.cutouts import SPELL_CLASSES  # noqa: E402

ROYALEAPI_URL = (
    "https://raw.githubusercontent.com/RoyaleAPI/cr-api-data/master/docs/json/cards.json"
)
SUPERCELL_URL = "https://api.clashroyale.com/v1/cards?limit=500"

# Der Datensatz benennt **Einheiten**, die Kartenlisten benennen **Karten**.
# Eine Karte kann mehrere Einheiten spawnen oder anders heissen. Ohne diese
# Zuordnung meldet der Abgleich massenhaft Fehlalarme.
CARD_TO_UNITS: dict[str, tuple[str, ...]] = {
    "skeletons": ("skeleton",),
    "skeleton-army": ("skeleton",),
    "graveyard": ("skeleton", "graveyard"),
    "guards": ("guard",),
    "archers": ("archer",),
    "barbarians": ("barbarian",),
    "elite-barbarians": ("elite-barbarian",),
    "bats": ("bat",),
    "minions": ("minion",),
    "minion-horde": ("minion",),
    "goblins": ("goblin",),
    "spear-goblins": ("spear-goblin",),
    "goblin-gang": ("goblin", "spear-goblin"),
    "royal-recruits": ("royal-recruit",),
    "royal-hogs": ("royal-hog",),
    "three-musketeers": ("musketeer",),
    "rascals": ("rascal-boy", "rascal-girl"),
    "lava-hound": ("lava-hound", "lava-pup"),
    "golem": ("golem", "golemite"),
    "goblin-barrel": ("goblin", "goblin-barrel"),
    "barbarian-hut": ("barbarian-hut", "barbarian"),
    "goblin-hut": ("goblin-hut", "spear-goblin"),
    "tombstone": ("tombstone", "skeleton"),
    "furnace": ("furnace", "fire-spirit"),
    "witch": ("witch", "skeleton"),
    "night-witch": ("night-witch", "bat"),
    "skeleton-king": ("skeleton-king", "skeleton"),
    "miner": ("miner", "dirt"),
    "goblin-drill": ("goblin-drill", "goblin", "dirt"),
    "mighty-miner": ("mighty-miner", "dirt"),
    "bowler": ("bowler", "bowl"),
    "executioner": ("executioner", "axe"),
    "battle-ram": ("battle-ram", "barbarian"),
    # Karten, die in mehreren Groessenstufen zerfallen.
    "elixir-golem": ("elixir-golem-big", "elixir-golem-mid", "elixir-golem-small"),
    "phoenix": ("phoenix-big", "phoenix-small", "phoenix-egg"),
    "skeleton-dragons": ("skeleton-dragon",),
    "wall-breakers": ("wall-breaker",),
    "zappies": ("zappy",),
    "party-hut": ("party-hut", "goblin"),
}

# Karten, die nur in Events oder Party-Modi vorkommen. Fuer einen Ladder-Bot
# irrelevant — sonst stehen sie dauerhaft als vermeintliche Luecke in der Liste.
EVENT_ONLY_PREFIXES = ("super-",)
EVENT_ONLY_KEYS = {
    "terry", "raging-prince", "santa-hog-rider", "party-rocket", "party-hut",
    "boss-bandit",
}


def resolve(unit: str, have: set[str]) -> bool:
    """Gilt ``unit`` als abgedeckt?

    Prueft der Reihe nach: exakter Treffer, Singular (Kartenlisten sind oft
    im Plural), und Praefix-Treffer fuer Klassen mit Groessenvarianten
    (``phoenix`` -> ``phoenix-big``).
    """
    if unit in have:
        return True
    if unit.endswith("s") and unit[:-1] in have:
        return True
    if unit.endswith("es") and unit[:-2] in have:
        return True
    return any(h.startswith(unit + "-") for h in have)


def fetch_json(url: str, token: str | None = None) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "crbot-coverage/1.0"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def slug(name: str) -> str:
    """'P.E.K.K.A' -> 'pekka', 'Mini P.E.K.K.A' -> 'mini-pekka'."""
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    s = "".join(out)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")


def load_cards(args: argparse.Namespace) -> list[dict]:
    """Liefert [{key, name, has_evolution}] aus der gewählten Quelle."""
    if args.cards_json:
        raw = json.loads(pathlib.Path(args.cards_json).read_text())
    elif args.source == "supercell":
        if not args.token:
            raise SystemExit("--source supercell braucht --token (developer.clashroyale.com)")
        raw = fetch_json(SUPERCELL_URL, args.token)
    else:
        raw = fetch_json(ROYALEAPI_URL)

    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    cards = []
    for c in items:
        name = c.get("name") or c.get("key") or ""
        key = c.get("key") or slug(name)
        has_evo = bool(c.get("evolved_spells_sc_key")) or int(c.get("maxEvolutionLevel", 0) or 0) > 0
        cards.append({"key": slug(key), "name": name, "has_evolution": has_evo})
    return cards


def expected_units(cards: list[dict]) -> dict[str, set[str]]:
    """Karte -> erwartete Einheitenklassen im Datensatz."""
    out: dict[str, set[str]] = {}
    for c in cards:
        key = c["key"]
        units = set(CARD_TO_UNITS.get(key, (key,)))
        if c["has_evolution"]:
            # Evolutionen heissen im Datensatz "<einheit>-evolution".
            units |= {f"{u}-evolution" for u in units}
        out[key] = units
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset-root", required=True, type=pathlib.Path)
    ap.add_argument("--source", choices=("royaleapi", "supercell"), default="royaleapi")
    ap.add_argument("--token", help="Supercell-API-Token")
    ap.add_argument("--cards-json", type=pathlib.Path)
    ap.add_argument("--md", type=pathlib.Path, help="Ernteliste als Markdown schreiben")
    ap.add_argument("--include-events", action="store_true",
                    help="Event-/Party-Karten mitzaehlen (fuer einen Ladder-Bot irrelevant)")
    args = ap.parse_args()

    have = set(real_class_names(args.dataset_root))
    cards = load_cards(args)
    expect = expected_units(cards)

    missing_by_card: dict[str, list[str]] = {}
    for card, units in sorted(expect.items()):
        if card in EVENT_ONLY_KEYS or card.startswith(EVENT_ONLY_PREFIXES):
            if not args.include_events:
                continue
        gaps = sorted(u for u in units if not resolve(u, have))
        if gaps:
            missing_by_card[card] = gaps

    all_expected = {u for units in expect.values() for u in units}
    extra = sorted(
        c for c in have - all_expected
        if not c.endswith(("-tower", "-bar", "-level"))
        and c not in {"clock", "emote", "text", "elixir", "selected", "bar"}
        and c not in SPELL_CLASSES
    )

    print(f"Kartenliste: {len(cards)} Karten aus Quelle '{args.source}'")
    print(f"Datensatz:   {len(have)} Klassen")
    print(f"Karten mit Luecken: {len(missing_by_card)}")
    print(f"Fehlende Einheitenklassen insgesamt: "
          f"{len({u for v in missing_by_card.values() for u in v})}\n")

    print("--- Zu ernten (Karte -> fehlende Klassen) ---")
    for card, gaps in list(missing_by_card.items())[:60]:
        print(f"  {card:26s} -> {', '.join(gaps)}")
    if len(missing_by_card) > 60:
        print(f"  ... und {len(missing_by_card) - 60} weitere")

    if extra:
        print(f"\n--- Im Datensatz, aber in keiner Kartenliste ({len(extra)}) ---")
        print("  " + ", ".join(extra[:40]))
        print("  (umbenannte Karten, Spawn-Einheiten oder Hilfsklassen — pruefen, nicht loeschen)")

    if args.source == "royaleapi":
        print("\nHINWEIS: Diese Quelle fuehrt die Evolutionen unvollstaendig. Fuer eine "
              "belastbare Evo-Liste:\n  --source supercell --token <dein-key>")

    if args.md:
        L = ["# Ernteliste\n",
             f"Quelle: `{args.source}` · {len(cards)} Karten · Datensatz: {len(have)} Klassen\n",
             "Abzuarbeiten mit `tools/harvest_cutouts.py` — je Zeile eine Aufnahme "
             "im Trainingslager.\n",
             "| Karte | fehlende Klassen | erledigt |", "|---|---|---|"]
        for card, gaps in missing_by_card.items():
            L.append(f"| `{card}` | {', '.join(f'`{g}`' for g in gaps)} | [ ] |")
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text("\n".join(L) + "\n")
        print(f"\ngeschrieben: {args.md}")


if __name__ == "__main__":
    main()
