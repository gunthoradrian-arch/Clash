"""Kampfwerte aller Einheiten — die Faktenbasis des Vorwärtsmodells.

Was man nachschlagen kann, darf man nicht lernen lassen. Ein Netz, das erst
herausfinden muss, dass ein Ritter 690 HP hat, verschwendet seine Kapazität an
Wissen, das exakt und kostenlos verfügbar ist.

Quelle ist der öffentliche Spieldaten-Dump von RoyaleAPI (`cards_stats.json`).
``build_table()`` normalisiert ihn einmalig in eine kompakte Tabelle, die ins
Repo eingecheckt wird — zur Laufzeit ist dann kein Netzzugriff nötig.

Einheiten nach der Normalisierung
---------------------------------
========== ============================ ==================================
Feld       Einheit                      Quelle
========== ============================ ==================================
``hp``     Trefferpunkte                ``hitpoints``
``dps``    Schaden pro Sekunde          ``damage / (hit_speed/1000)``
``damage`` Schaden pro Treffer          ``damage``, sonst aus dem Projektil
``range``  Kacheln                      ``range / 1000``
``speed``  Kacheln pro Sekunde          ``speed * 0.0125``
``hit_s``  Sekunden zwischen Treffern   ``hit_speed / 1000``
========== ============================ ==================================

Der Faktor ``0.0125`` bildet die internen Stufen auf die gelaeufigen Werte ab:
45 → 0,56 · 60 → 0,75 · 90 → 1,13 · 120 → 1,50 Kacheln/s.

**Fallstrick:** Fernkaempfer haben ``damage: 0`` — ihr Schaden steckt im
Projektil (Musketier, Bogenschuetze, Minion). Ohne Aufloesung ueber
``projectile`` richten sie im Modell keinen Schaden an.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import urllib.request

STATS_URL = (
    "https://raw.githubusercontent.com/RoyaleAPI/cr-api-data/master/docs/json/cards_stats.json"
)
CARDS_URL = (
    "https://raw.githubusercontent.com/RoyaleAPI/cr-api-data/master/docs/json/cards.json"
)

# Interne Geschwindigkeitsstufe -> Kacheln pro Sekunde.
SPEED_TO_TILES_PER_S = 0.0125

# Mitgelieferte Tabelle; wird von build_table() erzeugt.
TABLE_PATH = pathlib.Path(__file__).resolve().parent / "data" / "unit_stats.json"


@dataclasses.dataclass(slots=True)
class UnitStats:
    """Kampfwerte einer Einheit auf Turnierstufe."""

    key: str
    name: str
    hp: float
    damage: float
    dps: float
    hit_s: float
    range: float          # Kacheln
    speed: float          # Kacheln/s, 0 bei Gebaeuden
    sight: float          # Kacheln
    attacks_ground: bool
    attacks_air: bool
    targets_buildings_only: bool
    is_air: bool
    splash_radius: float  # Kacheln, 0 = Einzelziel
    collision_radius: float
    mass: float
    deploy_s: float
    elixir: float | None
    is_spell: bool = False

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _milli(v, default: float = 0.0) -> float:
    """Milli-Kacheln bzw. Millisekunden -> Kacheln bzw. Sekunden."""
    try:
        return float(v) / 1000.0
    except (TypeError, ValueError):
        return default


def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch_raw(url: str = STATS_URL) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "crbot-cardstats/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def build_table(raw: dict, cards: list[dict] | None = None) -> dict[str, UnitStats]:
    """Normalisiert den Rohdump in ``key -> UnitStats``.

    ``cards`` ist die separate Kartenliste (``cards.json``). Sie wird gebraucht,
    weil Schadenszauber wie Feuerball, Pfeile und Rakete **nur** als Projektil
    im Dump stehen — ihre Elixirkosten stehen ausschliesslich in der
    Kartenliste. Ohne sie fehlt der Suche ein Viertel jedes Decks.
    """
    projectiles = {p["name"]: p for p in raw.get("projectile", []) if p.get("name")}
    elixir_by_key = {}
    for c in cards or []:
        key = normalize_key(c.get("key") or c.get("name", ""))
        if key and c.get("elixir") is not None:
            elixir_by_key[key] = _num(c.get("elixir"))
    for section in ("troop", "spell", "building"):
        for c in raw.get(section, []):
            k = c.get("key") or c.get("name", "")
            if k and c.get("mana_cost") is not None:
                elixir_by_key[normalize_key(k)] = _num(c.get("mana_cost"))

    out: dict[str, UnitStats] = {}

    # Zauber zuerst: sie haben keine HP und keine Bewegung, aber Kosten,
    # Radius und Sofortschaden. Ohne sie kann die Suche ein Viertel jedes
    # Decks nicht einmal in Betracht ziehen.
    for c in raw.get("spell", []):
        name = c.get("name")
        if not name:
            continue
        key = normalize_key(c.get("key") or name)
        damage = _num(c.get("damage"))
        if damage <= 0:
            proj = projectiles.get(c.get("projectile") or "")
            if proj:
                damage = _num(proj.get("damage"))
        radius = _milli(c.get("radius"))
        if radius <= 0:
            proj = projectiles.get(c.get("projectile") or "")
            if proj:
                radius = _milli(proj.get("radius"))
        out[key] = UnitStats(
            key=key, name=name, hp=0.0, damage=damage, dps=damage, hit_s=1.0,
            range=0.0, speed=0.0, sight=0.0,
            attacks_ground=bool(c.get("hits_ground", True)),
            attacks_air=bool(c.get("hits_air", True)),
            targets_buildings_only=False, is_air=False,
            splash_radius=radius, collision_radius=0.0, mass=0.0,
            deploy_s=0.0, elixir=resolve_elixir(key, elixir_by_key),
            is_spell=True,
        )

    # Schadenszauber stehen nur als Projektil im Dump. Wir nehmen genau die,
    # fuer die auch eine Karte mit Elixirpreis existiert — das filtert interne
    # Projektile (Turmpfeile, Bomben) zuverlaessig heraus.
    for pname, proj in projectiles.items():
        key = normalize_key(pname)
        if key.endswith("-spell"):
            key = key[: -len("-spell")]
        key = PROJECTILE_TO_CARD.get(key, key)
        if key in out or key not in elixir_by_key:
            continue
        damage = _num(proj.get("damage"))
        radius = _milli(proj.get("radius"))
        if damage <= 0 and radius <= 0:
            continue
        out[key] = UnitStats(
            key=key, name=pname, hp=0.0, damage=damage, dps=damage, hit_s=1.0,
            range=0.0, speed=0.0, sight=0.0,
            attacks_ground=bool(proj.get("aoe_to_ground", True)),
            attacks_air=bool(proj.get("aoe_to_air", True)),
            targets_buildings_only=False, is_air=False,
            splash_radius=radius, collision_radius=0.0, mass=0.0,
            deploy_s=0.0, elixir=elixir_by_key.get(key), is_spell=True,
        )

    for section, movable in (("characters", True), ("building", False)):
        for c in raw.get(section, []):
            name = c.get("name")
            if not name:
                continue
            key = normalize_key(c.get("key") or name)

            damage = _num(c.get("damage"))
            hit_s = _num(c.get("hit_speed"), 1000.0) / 1000.0 or 1.0

            # Fernkaempfer tragen ihren Schaden im Projektil.
            if damage <= 0:
                proj = projectiles.get(c.get("projectile") or "")
                if proj:
                    damage = _num(proj.get("damage"))

            splash = _milli(c.get("area_damage_radius"))
            if splash <= 0:
                proj = projectiles.get(c.get("projectile") or "")
                if proj:
                    splash = _milli(proj.get("radius"))

            hp = _num(c.get("hitpoints"))
            if hp <= 0 and movable:
                continue  # keine kampffaehige Einheit

            out[key] = UnitStats(
                key=key,
                name=name,
                hp=hp,
                damage=damage,
                dps=damage / hit_s if hit_s > 0 else 0.0,
                hit_s=hit_s,
                range=_milli(c.get("range")),
                speed=_num(c.get("speed")) * SPEED_TO_TILES_PER_S if movable else 0.0,
                sight=_milli(c.get("sight_range"), 5.5),
                attacks_ground=bool(c.get("attacks_ground", True)),
                attacks_air=bool(c.get("attacks_air", False)),
                targets_buildings_only=bool(c.get("target_only_buildings", False)),
                is_air=_num(c.get("flying_height")) > 0,
                splash_radius=splash,
                collision_radius=_milli(c.get("collision_radius"), 0.5),
                mass=_num(c.get("mass"), 1.0),
                deploy_s=_num(c.get("deploy_time"), 1000.0) / 1000.0,
                elixir=resolve_elixir(key, elixir_by_key),
                is_spell=False,
            )
    return out


# Projektilnamen, die nicht per Namensregel auf ihre Karte fuehren.
PROJECTILE_TO_CARD: dict[str, str] = {
    "log-projectile": "the-log",
    "snowball": "giant-snowball",
    "barb-log-projectile": "barbarian-barrel",
    "goblin-barrel": "goblin-barrel",
}


# Einheiten, deren Karte anders heisst als die Einheit selbst. Der Plural wird
# automatisch probiert; hier stehen nur die Faelle, die davon abweichen.
UNIT_TO_CARD: dict[str, str] = {
    "elite-barbarian": "elite-barbarians",
    "royal-recruit": "royal-recruits",
    "royal-hog": "royal-hogs",
    "rascal-boy": "rascals",
    "rascal-girl": "rascals",
    "lava-pup": "lava-hound",
    "golemite": "golem",
    "elixir-golemite": "elixir-golem",
    "phoenix-egg": "phoenix",
    "phoenix-small": "phoenix",
    "phoenix-big": "phoenix",
    "gurad": "guards",       # Schreibweise aus dem Quelldatensatz
    "guard": "guards",
    "zappy": "zappies",
    "skeleton-dragon": "skeleton-dragons",
    "wall-breaker": "wall-breakers",
    "spear-goblin": "spear-goblins",
    "three-musketeer": "three-musketeers",
    "dirt": "miner",
    "bowl": "bowler",
    "axe": "executioner",
}


def resolve_elixir(key: str, elixir_by_key: dict[str, float]) -> float | None:
    """Findet die Elixirkosten der **Karte** zu einer Einheit.

    Der Spieldaten-Dump fuehrt Kampfwerte je Einheit (``skeleton``), Kosten aber
    je Karte (``skeletons``). Ohne diese Aufloesung bleiben 147 von 208
    Einheiten ohne Preis — und jede Bezahlbarkeitspruefung rechnet mit einem
    Ersatzwert statt mit der Wahrheit.

    Fuer Karten, die mehrere Einheiten stellen, traegt **jede** Einheit die
    Kosten der ganzen Karte. Das ist fuer die Frage "kann er sich das leisten?"
    genau richtig, fuer "was ist diese eine Einheit wert?" dagegen zu hoch.
    """
    for candidate in (key, UNIT_TO_CARD.get(key), f"{key}s", f"{key}es"):
        if candidate and candidate in elixir_by_key:
            return elixir_by_key[candidate]
    return None


def normalize_key(name: str) -> str:
    """'HogRider' / 'hog_rider' -> 'hog-rider'. Passt zu den Detektor-Klassen."""
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("-")
        out.append("-" if ch in " _" else ch.lower())
    s = "".join(out)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")


def save_table(table: dict[str, UnitStats], path: pathlib.Path = TABLE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v.to_dict() for k, v in sorted(table.items())}
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))


def load_table(path: pathlib.Path = TABLE_PATH) -> dict[str, UnitStats]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} fehlt. Einmalig erzeugen mit:\n"
            "  python tools/build_cardstats.py"
        )
    raw = json.loads(path.read_text())
    return {k: UnitStats(**v) for k, v in raw.items()}


def stats_for_classes(class_names: list[str],
                      table: dict[str, UnitStats] | None = None) -> tuple[list[UnitStats | None], list[str]]:
    """Ordnet den Detektor-Klassen ihre Kampfwerte zu.

    Gibt (Werte-in-Klassenreihenfolge, Liste-ohne-Treffer) zurueck. Die
    Fehlliste ist wichtig: fuer diese Klassen rechnet das Vorwaertsmodell mit
    Ersatzwerten, und das soll sichtbar sein statt still zu passieren.
    """
    table = table or load_table()
    resolved: list[UnitStats | None] = []
    missing: list[str] = []
    for name in class_names:
        st = table.get(name)
        if st is None:
            # Groessenvarianten und Evolutionen auf die Basiseinheit zurueckfuehren.
            for suffix in ("-evolution", "-big", "-mid", "-small"):
                if name.endswith(suffix) and name[: -len(suffix)] in table:
                    st = table[name[: -len(suffix)]]
                    break
        if st is None:
            missing.append(name)
        resolved.append(st)
    return resolved, missing
