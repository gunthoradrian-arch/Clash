"""Vorwärtsmodell: simuliert viele Handlungsalternativen gleichzeitig.

Das ist der Baustein, der Rechenleistung in Spielstärke umwandelt. Statt einen
Zug per Reflex zu wählen, werden hunderte Kandidaten **parallel durchgerechnet**
und der beste gewinnt — dasselbe Muster wie Suche im Schach, nur viel flacher.

Alles ist über eine Batch-Achse vektorisiert: ``(B, U)`` für B Szenarien mit je
bis zu U Einheiten. Kein Python-Loop über Einheiten, nur über Zeitschritte.
Damit ist der Sprung auf GPU später ein Backend-Wechsel, keine Neufassung —
die Rechnungen sind bereits Array-Operationen.

Was modelliert wird
-------------------
* Zielwahl nach Nähe, unter Beachtung von Luft/Boden und "nur Gebäude"
* Bewegung mit echtem Tempo, Bodeneinheiten **über die Brücken**
* Schaden über DPS, Flächenschaden im Umkreis
* Türme als unbewegliche Einheiten — dadurch kein Sonderfall in der Zielwahl

Was bewusst fehlt
-----------------
Wegfindung um Gebäude, Aggro-Wechsel, Ladeangriffe, Verlangsamung, Schilde,
Spawner. Das Modell ist eine **Näherung** — aber selbst eine grobe Vorhersage
schlägt eine Policy, die gar nicht vorausrechnet. Fehler wachsen mit dem
Horizont; über 3–6 Sekunden ist es brauchbar, über 20 nicht.

Schaden wird kontinuierlich angerechnet (``dps * dt``) statt in diskreten
Treffern. Über kurze Horizonte ist der Unterschied klein, es spart aber pro
Einheit einen Nachladezähler.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from crbot import arena
from crbot.cardstats import UnitStats, load_table

# Türme, umgerechnet in Kacheln. Reihenfolge: side 0 (wir) zuerst.
TOWER_LAYOUT: tuple[tuple[str, int, tuple[float, float]], ...] = (
    ("princess-tower", 0, arena.px_to_tile(114.0, 684.0)),
    ("princess-tower", 0, arena.px_to_tile(456.0, 684.0)),
    ("king-tower", 0, arena.px_to_tile(284.0, 776.0)),
    ("princess-tower", 1, arena.px_to_tile(112.0, 211.0)),
    ("princess-tower", 1, arena.px_to_tile(455.0, 212.0)),
    ("king-tower", 1, arena.px_to_tile(284.0, 116.0)),
)

# HP auf Turnierstufe — die Tabelle führt Stufe 1.
TOURNAMENT_TOWER_HP = {"king-tower": 4824.0, "princess-tower": 3052.0}

RIVER_Y_TILES = arena.px_to_tile(0.0, arena.RIVER_Y)[1]
BRIDGE_X_TILES = tuple(arena.px_to_tile(bx, 0.0)[0] for bx in arena.BRIDGE_X)

# Abstand, ab dem eine Einheit als "am Ziel" gilt, zusätzlich zur Waffenreichweite.
CONTACT_SLACK = 0.15


@dataclasses.dataclass
class StatArrays:
    """Kampfwerte als Arrays, indiziert über den Typ-Index."""

    keys: list[str]
    index: dict[str, int]
    hp: np.ndarray
    dps: np.ndarray
    range: np.ndarray
    speed: np.ndarray
    attacks_ground: np.ndarray
    attacks_air: np.ndarray
    buildings_only: np.ndarray
    is_air: np.ndarray
    splash: np.ndarray
    radius: np.ndarray
    is_building: np.ndarray

    @classmethod
    def from_table(cls, table: dict[str, UnitStats]) -> "StatArrays":
        keys = sorted(table)
        idx = {k: i for i, k in enumerate(keys)}
        g = lambda f: np.array([getattr(table[k], f) for k in keys], dtype=np.float32)  # noqa: E731
        b = lambda f: np.array([getattr(table[k], f) for k in keys], dtype=bool)        # noqa: E731
        speed = g("speed")
        return cls(
            keys=keys, index=idx,
            hp=g("hp"), dps=g("dps"), range=g("range"), speed=speed,
            attacks_ground=b("attacks_ground"), attacks_air=b("attacks_air"),
            buildings_only=b("targets_buildings_only"), is_air=b("is_air"),
            splash=g("splash_radius"), radius=g("collision_radius"),
            is_building=(speed <= 0.0),
        )


@dataclasses.dataclass
class BatchState:
    """Zustand von B Szenarien mit je bis zu U Einheiten."""

    pos: np.ndarray      # (B, U, 2) float32, Kacheln
    hp: np.ndarray       # (B, U) float32
    side: np.ndarray     # (B, U) int8, 0 = wir, 1 = Gegner
    type_idx: np.ndarray  # (B, U) int32
    alive: np.ndarray    # (B, U) bool

    @property
    def batch(self) -> int:
        return self.pos.shape[0]

    @property
    def capacity(self) -> int:
        return self.pos.shape[1]

    def copy(self) -> "BatchState":
        return BatchState(self.pos.copy(), self.hp.copy(), self.side.copy(),
                          self.type_idx.copy(), self.alive.copy())

    def tower_hp(self, stats: StatArrays, side: int) -> np.ndarray:
        """Summe der Turm-HP einer Seite, je Szenario. Form (B,)."""
        is_tower = stats.is_building[self.type_idx]
        m = is_tower & (self.side == side) & self.alive
        return np.where(m, self.hp, 0.0).sum(axis=1)


class ForwardModel:
    def __init__(self, table: dict[str, UnitStats] | None = None) -> None:
        self.stats = StatArrays.from_table(table or load_table())

    # ------------------------------------------------------------ Aufbau

    def empty_state(self, batch: int, capacity: int) -> BatchState:
        return BatchState(
            pos=np.zeros((batch, capacity, 2), np.float32),
            hp=np.zeros((batch, capacity), np.float32),
            side=np.zeros((batch, capacity), np.int8),
            type_idx=np.zeros((batch, capacity), np.int32),
            alive=np.zeros((batch, capacity), bool),
        )

    def with_towers(self, batch: int, capacity: int,
                    tower_hp: dict[str, float] | None = None) -> BatchState:
        """Zustand mit den sechs Türmen auf den ersten Plätzen."""
        if capacity < len(TOWER_LAYOUT):
            raise ValueError(f"capacity muss >= {len(TOWER_LAYOUT)} sein")
        st = self.empty_state(batch, capacity)
        hp_map = {**TOURNAMENT_TOWER_HP, **(tower_hp or {})}
        for slot, (key, side, (x, y)) in enumerate(TOWER_LAYOUT):
            st.pos[:, slot] = (x, y)
            st.hp[:, slot] = hp_map.get(key, self.stats.hp[self.stats.index[key]])
            st.side[:, slot] = side
            st.type_idx[:, slot] = self.stats.index[key]
            st.alive[:, slot] = True
        return st

    def add_unit(self, st: BatchState, slot: int, key: str, side: int,
                 x: float, y: float, hp: float | None = None,
                 batch_mask: np.ndarray | None = None) -> None:
        """Setzt eine Einheit auf einen Platz — optional nur in Teilen des Batches."""
        ti = self.stats.index[key]
        sel = slice(None) if batch_mask is None else batch_mask
        st.pos[sel, slot] = (x, y)
        st.hp[sel, slot] = self.stats.hp[ti] if hp is None else hp
        st.side[sel, slot] = side
        st.type_idx[sel, slot] = ti
        st.alive[sel, slot] = True

    # ------------------------------------------------------------ Simulation

    def _targets(self, st: BatchState) -> tuple[np.ndarray, np.ndarray]:
        """Zielindex je Einheit und Distanz dorthin. Formen (B, U)."""
        s = self.stats
        d = np.linalg.norm(st.pos[:, :, None, :] - st.pos[:, None, :, :], axis=-1)

        enemy = st.side[:, :, None] != st.side[:, None, :]
        alive_t = st.alive[:, None, :]
        target_air = s.is_air[st.type_idx][:, None, :]
        target_bld = s.is_building[st.type_idx][:, None, :]

        can_air = s.attacks_air[st.type_idx][:, :, None]
        can_ground = s.attacks_ground[st.type_idx][:, :, None]
        only_bld = s.buildings_only[st.type_idx][:, :, None]

        reachable = np.where(target_air, can_air, can_ground)
        allowed = enemy & alive_t & reachable & (~only_bld | target_bld)

        # Einheiten, die nur Gebäude angreifen, aber keines mehr finden,
        # gehen auf alles los — so verhält sich das Spiel ebenfalls.
        none_left = ~allowed.any(axis=2, keepdims=True)
        fallback = enemy & alive_t & reachable
        allowed = np.where(none_left, fallback, allowed)

        masked = np.where(allowed, d, np.inf)
        tgt = np.argmin(masked, axis=2)
        dist = np.take_along_axis(masked, tgt[:, :, None], axis=2)[:, :, 0]
        return tgt.astype(np.int32), dist

    def _goal_positions(self, st: BatchState, tgt: np.ndarray) -> np.ndarray:
        """Wohin eine Einheit läuft — Bodeneinheiten über die Brücke.

        Ohne diesen Umweg laufen Bodentruppen quer durchs Wasser und jede
        Zeitschätzung ist zu optimistisch.
        """
        s = self.stats
        tgt_pos = np.take_along_axis(st.pos, tgt[..., None].repeat(2, axis=-1), axis=1)
        own_y = st.pos[..., 1]
        tgt_y = tgt_pos[..., 1]

        crosses = (own_y - RIVER_Y_TILES) * (tgt_y - RIVER_Y_TILES) < 0
        ground = ~s.is_air[st.type_idx]
        need_bridge = crosses & ground

        own_x = st.pos[..., 0]
        bridges = np.array(BRIDGE_X_TILES, dtype=np.float32)
        nearest = bridges[np.argmin(np.abs(own_x[..., None] - bridges), axis=-1)]

        goal = tgt_pos.copy()
        goal[..., 0] = np.where(need_bridge, nearest, goal[..., 0])
        goal[..., 1] = np.where(need_bridge, RIVER_Y_TILES, goal[..., 1])
        return goal

    def step(self, st: BatchState, dt: float) -> None:
        """Ein Zeitschritt, in-place."""
        s = self.stats
        tgt, dist = self._targets(st)

        my_range = s.range[st.type_idx]
        my_radius = s.radius[st.type_idx]
        tgt_radius = np.take_along_axis(my_radius, tgt, axis=1)
        contact = my_range + my_radius + tgt_radius + CONTACT_SLACK

        in_range = (dist <= contact) & st.alive & np.isfinite(dist)
        moving = st.alive & ~in_range & np.isfinite(dist) & (s.speed[st.type_idx] > 0)

        # --- Bewegung
        goal = self._goal_positions(st, tgt)
        delta = goal - st.pos
        norm = np.linalg.norm(delta, axis=-1, keepdims=True)
        direction = np.divide(delta, norm, out=np.zeros_like(delta), where=norm > 1e-6)
        stepsize = (s.speed[st.type_idx] * dt)[..., None]
        st.pos += np.where(moving[..., None], direction * np.minimum(stepsize, norm), 0.0)

        # --- Schaden am Einzelziel
        dmg = np.where(in_range, s.dps[st.type_idx] * dt, 0.0)
        inflicted = np.zeros_like(st.hp)
        np.add.at(inflicted, (np.arange(st.batch)[:, None], tgt), dmg)

        # --- Flächenschaden im Umkreis des Ziels
        splash = s.splash[st.type_idx]
        if np.any(splash > 0):
            attackers = in_range & (splash > 0)
            if attackers.any():
                tgt_pos = np.take_along_axis(
                    st.pos, tgt[..., None].repeat(2, axis=-1), axis=1)
                # Abstand jeder Einheit zum jeweiligen Zielpunkt
                d_to_tp = np.linalg.norm(
                    st.pos[:, None, :, :] - tgt_pos[:, :, None, :], axis=-1)
                hit = (d_to_tp <= splash[..., None]) & attackers[..., None]
                hit &= (st.side[:, :, None] != st.side[:, None, :]) & st.alive[:, None, :]
                # Das Primärziel wurde oben bereits getroffen.
                np.put_along_axis(hit, tgt[:, :, None], False, axis=2)
                inflicted += (hit * dmg[..., None]).sum(axis=1)

        st.hp -= inflicted
        st.alive &= st.hp > 0.0
        st.hp = np.maximum(st.hp, 0.0)

    def rollout(self, st: BatchState, horizon_s: float, dt: float = 0.25) -> BatchState:
        out = st.copy()
        for _ in range(max(1, int(round(horizon_s / dt)))):
            self.step(out, dt)
        return out

    # ------------------------------------------------------------ Bewertung

    def score(self, before: BatchState, after: BatchState,
              elixir_cost: np.ndarray | None = None,
              elixir_weight: float = 120.0) -> np.ndarray:
        """Netto-Turmschaden aus unserer Sicht. Höher ist besser. Form (B,)."""
        ours = before.tower_hp(self.stats, 0) - after.tower_hp(self.stats, 0)
        theirs = before.tower_hp(self.stats, 1) - after.tower_hp(self.stats, 1)
        value = theirs - ours
        if elixir_cost is not None:
            value = value - elixir_weight * elixir_cost
        return value
