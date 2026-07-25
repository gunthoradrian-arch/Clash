"""Nachanalyse verlorener Spiele: woran hat es gelegen?

Ein Bot, der verliert und nicht weiß warum, wiederholt den Fehler. Dieses Modul
liest ein Match-Protokoll (``crbot.matchlog``) und beantwortet konkrete Fragen
mit Zahlen statt Gefühl:

* Wie viel Elixir ist ungenutzt verfallen, weil der Balken auf 10 stand?
* **Welche gegnerische Karte hat wie viel Turmschaden gemacht?**
* Waren die Elixir-Tausche positiv oder negativ?
* Wie schnell wurde auf gegnerische Pushes reagiert?
* Wo lag der entscheidende Moment?

Die Schadenszuordnung ist der Kern. Beobachtbar ist nur, *dass* Turm-HP fallen —
*wer* sie verursacht hat, wird erschlossen: alle gegnerischen Einheiten in
Reichweite des Turms teilen sich den Schaden, gewichtet nach ihrem DPS. Das ist
eine Heuristik und bei mehreren Angreifern ungenau, aber es beantwortet die
Frage, die zählt: *was* hat dich umgebracht.
"""

from __future__ import annotations

import collections
import dataclasses
import math

from crbot import arena
from crbot.cardstats import UnitStats, load_table
from crbot.matchlog import ELIXIR_MAX, ELIXIR_PER_S_SINGLE, MatchLog, Play

# Turmpositionen in Kacheln, aus den datenabgeleiteten Pixelankern.
TOWER_POS_TILES: dict[str, tuple[float, float]] = {
    "self_king": arena.px_to_tile(284.0, 776.0),
    "self_left": arena.px_to_tile(114.0, 684.0),
    "self_right": arena.px_to_tile(456.0, 684.0),
    "opp_king": arena.px_to_tile(284.0, 116.0),
    "opp_left": arena.px_to_tile(112.0, 211.0),
    "opp_right": arena.px_to_tile(455.0, 212.0),
}

# Radius des Turm-Kollisionskoerpers; Angreifer stehen davor, nicht darin.
TOWER_RADIUS_TILES = 1.7

# Bis hierhin gilt eine Karte als Antwort auf den gegnerischen Zug.
RESPONSE_WINDOW_S = 4.0

# Ab so vielen Sekunden auf vollem Balken zaehlt es als vergeudetes Elixir.
LEAK_MIN_S = 0.5


@dataclasses.dataclass(slots=True)
class DamageSource:
    card: str
    damage: float
    hits: int

    @property
    def share(self) -> float:
        return self.damage


@dataclasses.dataclass
class Finding:
    """Ein Befund mit Gewicht, damit das Urteil sortierbar wird."""

    key: str
    headline: str
    detail: str
    severity: float  # 0..1, grob "wie sehr hat das das Spiel gekostet"


@dataclasses.dataclass
class Postmortem:
    outcome: str | None
    duration_s: float
    crowns: tuple[int, int]

    elixir_leaked: float
    leak_events: int

    damage_taken: float
    damage_dealt: float
    damage_by_card: list[DamageSource]

    trade_balance: float
    trades: list[tuple[float, str, str, float]]  # t, gegnerkarte, antwort, delta

    reaction_times: list[float]
    unanswered_pushes: int

    cards_played: dict[str, int]
    unused_cards: list[str]

    decisive_t: float | None
    decisive_loss: float

    findings: list[Finding]


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _stats_for(cls: str, table: dict[str, UnitStats]) -> UnitStats | None:
    st = table.get(cls)
    if st is not None:
        return st
    for suffix in ("-evolution", "-big", "-mid", "-small"):
        if cls.endswith(suffix):
            return table.get(cls[: -len(suffix)])
    return None


def analyze(log: MatchLog, table: dict[str, UnitStats] | None = None) -> Postmortem:
    table = table or load_table()

    elixir_leaked, leak_events = _elixir_leak(log)
    dmg_taken, dmg_dealt, by_card = _damage_attribution(log, table)
    trade_balance, trades = _trades(log, table)
    reactions, unanswered = _reactions(log)
    played, unused = _card_usage(log)
    decisive_t, decisive_loss = _decisive_window(log)

    pm = Postmortem(
        outcome=log.outcome, duration_s=log.duration_s, crowns=log.crowns,
        elixir_leaked=elixir_leaked, leak_events=leak_events,
        damage_taken=dmg_taken, damage_dealt=dmg_dealt, damage_by_card=by_card,
        trade_balance=trade_balance, trades=trades,
        reaction_times=reactions, unanswered_pushes=unanswered,
        cards_played=played, unused_cards=unused,
        decisive_t=decisive_t, decisive_loss=decisive_loss,
        findings=[],
    )
    pm.findings = _verdict(pm)
    return pm


# ------------------------------------------------------------------ Bausteine


def _elixir_leak(log: MatchLog) -> tuple[float, int]:
    """Elixir, das bei vollem Balken verfallen ist.

    Der haeufigste und billigste Fehler ueberhaupt: Wer auf 10 sitzt,
    verschenkt kontinuierlich Ressourcen.
    """
    leaked = 0.0
    events = 0
    in_leak = False

    for prev, cur in zip(log.ticks, log.ticks[1:]):
        dt = cur.t - prev.t
        if dt <= 0 or dt > 5.0:   # Luecke im Protokoll -> nicht hochrechnen
            in_leak = False
            continue
        if prev.elixir >= ELIXIR_MAX - 0.05 and cur.elixir >= ELIXIR_MAX - 0.05:
            if dt >= LEAK_MIN_S:
                leaked += dt * ELIXIR_PER_S_SINGLE
                if not in_leak:
                    events += 1
                    in_leak = True
        else:
            in_leak = False
    return leaked, events


def _damage_attribution(
    log: MatchLog, table: dict[str, UnitStats]
) -> tuple[float, float, list[DamageSource]]:
    """Ordnet Turmschaden den verursachenden Einheiten zu.

    Beobachtbar ist nur der HP-Abfall. Wer ihn verursacht hat, wird ueber
    Reichweite und DPS erschlossen und bei mehreren Angreifern anteilig
    verteilt.
    """
    taken = 0.0
    dealt = 0.0
    by_card: dict[str, DamageSource] = {}

    for prev, cur in zip(log.ticks, log.ticks[1:]):
        for key, hp_now in cur.towers.items():
            hp_before = prev.towers.get(key)
            if hp_before is None:
                continue
            drop = hp_before - hp_now
            if drop <= 0.5:
                continue

            ours = key.startswith("self_")
            if ours:
                taken += drop
            else:
                dealt += drop
                continue  # Zuordnung interessiert uns fuer erlittenen Schaden

            tower_xy = TOWER_POS_TILES.get(key)
            if tower_xy is None:
                continue

            # Angreifer: gegnerische Einheiten in Waffenreichweite des Turms.
            attackers: list[tuple[str, float]] = []
            for u in prev.units:
                if u.side != 1:
                    continue
                st = _stats_for(u.cls, table)
                if st is None or st.dps <= 0:
                    continue
                reach = st.range + TOWER_RADIUS_TILES
                if _dist((u.x, u.y), tower_xy) <= reach:
                    attackers.append((u.cls, st.dps))

            if not attackers:
                src = by_card.setdefault("unbekannt", DamageSource("unbekannt", 0.0, 0))
                src.damage += drop
                src.hits += 1
                continue

            total_dps = sum(d for _, d in attackers)
            for cls, dps in attackers:
                src = by_card.setdefault(cls, DamageSource(cls, 0.0, 0))
                src.damage += drop * (dps / total_dps)
                src.hits += 1

    ranked = sorted(by_card.values(), key=lambda s: -s.damage)
    return taken, dealt, ranked


def _elixir_cost(play: Play, table: dict[str, UnitStats]) -> float:
    if play.elixir_cost is not None:
        return float(play.elixir_cost)
    st = _stats_for(play.card, table)
    return float(st.elixir) if st and st.elixir else 4.0


def _trades(
    log: MatchLog, table: dict[str, UnitStats]
) -> tuple[float, list[tuple[float, str, str, float]]]:
    """Paart gegnerische Zuege mit unserer Antwort und bilanziert das Elixir.

    Positiv = wir haben guenstiger geantwortet als der Gegner gespielt hat.
    """
    opp = sorted(log.plays_of(1), key=lambda p: p.t)
    mine = sorted(log.plays_of(0), key=lambda p: p.t)

    balance = 0.0
    out: list[tuple[float, str, str, float]] = []
    used: set[int] = set()

    for op in opp:
        answer = None
        for i, mp in enumerate(mine):
            if i in used or mp.t < op.t:
                continue
            if mp.t - op.t <= RESPONSE_WINDOW_S:
                answer, used_idx = mp, i
                break
        if answer is None:
            continue
        used.add(used_idx)
        delta = _elixir_cost(op, table) - _elixir_cost(answer, table)
        balance += delta
        out.append((op.t, op.card, answer.card, delta))
    return balance, out


def _reactions(log: MatchLog) -> tuple[list[float], int]:
    """Reaktionszeit auf gegnerische Zuege auf unserer Haelfte."""
    river_y = arena.px_to_tile(0, arena.RIVER_Y)[1]
    reactions: list[float] = []
    unanswered = 0

    mine = sorted(log.plays_of(0), key=lambda p: p.t)
    for op in sorted(log.plays_of(1), key=lambda p: p.t):
        # Nur Zuege, die auf uns zulaufen (unsere Haelfte oder direkt an der Bruecke).
        if op.y < river_y - 2:
            continue
        later = [m.t - op.t for m in mine if 0 <= m.t - op.t <= RESPONSE_WINDOW_S * 2]
        if later:
            reactions.append(min(later))
        else:
            unanswered += 1
    return reactions, unanswered


def _card_usage(log: MatchLog) -> tuple[dict[str, int], list[str]]:
    played = collections.Counter(p.card for p in log.plays_of(0))
    deck = list(log.meta.get("deck", []))
    unused = [c for c in deck if played.get(c, 0) == 0]
    return dict(played.most_common()), unused


def _decisive_window(log: MatchLog, window_s: float = 12.0) -> tuple[float | None, float]:
    """Findet das Zeitfenster mit dem groessten Netto-HP-Verlust."""
    if len(log.ticks) < 2:
        return None, 0.0

    def own_hp(tick) -> float:
        return sum(v for k, v in tick.towers.items() if k.startswith("self_"))

    def opp_hp(tick) -> float:
        return sum(v for k, v in tick.towers.items() if k.startswith("opp_"))

    worst_t, worst = None, 0.0
    for i, start in enumerate(log.ticks):
        end = None
        for j in range(i + 1, len(log.ticks)):
            if log.ticks[j].t - start.t >= window_s:
                end = log.ticks[j]
                break
        if end is None:
            break
        swing = (own_hp(start) - own_hp(end)) - (opp_hp(start) - opp_hp(end))
        if swing > worst:
            worst, worst_t = swing, start.t
    return worst_t, worst


# -------------------------------------------------------------------- Urteil


def _verdict(pm: Postmortem) -> list[Finding]:
    """Sortiert die Befunde danach, wie viel sie plausibel gekostet haben."""
    out: list[Finding] = []

    if pm.elixir_leaked >= 3.0:
        # Grob: verschenktes Elixir entspricht nicht gespielten Karten.
        sev = min(1.0, pm.elixir_leaked / 25.0)
        out.append(Finding(
            "elixir_leak",
            f"{pm.elixir_leaked:.1f} Elixir bei vollem Balken verfallen",
            f"In {pm.leak_events} Phasen stand der Balken auf {ELIXIR_MAX:.0f}. "
            f"Das entspricht etwa {pm.elixir_leaked / 4:.1f} nicht gespielten Karten. "
            "Gegenmittel: eine untere Elixir-Schwelle, ab der guenstig zykliert wird.",
            sev,
        ))

    if pm.damage_by_card:
        top = pm.damage_by_card[0]
        share = top.damage / pm.damage_taken if pm.damage_taken > 0 else 0.0
        if share >= 0.25:
            out.append(Finding(
                "main_threat",
                f"`{top.card}` verursachte {top.damage:.0f} Schaden ({100 * share:.0f} %)",
                f"Diese eine Karte machte den Grossteil des erlittenen Schadens. "
                f"Pruefen: Gibt es im Deck einen guenstigen Konter, und wurde er "
                f"gespielt? Falls ja, offenbar zu spaet oder falsch platziert.",
                min(1.0, share + 0.2),
            ))

    if not pm.trades and pm.reaction_times:
        # Kein einziger Zug fiel ins Antwortfenster. Das ist kein ausgeglichenes
        # Spiel, sondern die Abwesenheit von Reaktion - und muss als solches
        # gemeldet werden, sonst liest sich die Bilanz "+0.0" wie in Ordnung.
        out.append(Finding(
            "no_trades",
            f"Kein einziger Zug kam innerhalb von {RESPONSE_WINDOW_S:.0f} s als Antwort",
            "Es gab Zuege von beiden Seiten, aber keiner davon war zeitlich eine "
            "Reaktion auf den anderen. Der Bot spielt nach Zeitplan statt auf die "
            "Lage - genau das Muster, das reine Regel-Bots zeigen.",
            0.8,
        ))

    if pm.trade_balance < -3.0:
        out.append(Finding(
            "bad_trades",
            f"Elixir-Bilanz der Tausche: {pm.trade_balance:+.1f}",
            f"Ueber {len(pm.trades)} erkannte Austausche wurde durchschnittlich "
            f"{pm.trade_balance / max(1, len(pm.trades)):+.1f} Elixir pro Tausch "
            "verloren. Teurer zu antworten als der Gegner spielt, verliert das "
            "Spiel langsam aber sicher.",
            min(1.0, abs(pm.trade_balance) / 20.0),
        ))

    if pm.reaction_times:
        avg = sum(pm.reaction_times) / len(pm.reaction_times)
        if avg > 2.0:
            out.append(Finding(
                "slow_reaction",
                f"Mittlere Reaktionszeit {avg:.1f} s",
                "Ab etwa zwei Sekunden hat eine schnelle Einheit die Bruecke schon "
                "passiert. Erst im Latenzbudget nachsehen (tools/bench_latency.py), "
                "bevor an der Policy gedreht wird.",
                min(1.0, avg / 6.0),
            ))

    if pm.unanswered_pushes >= 3:
        out.append(Finding(
            "unanswered",
            f"{pm.unanswered_pushes} gegnerische Zuege ohne jede Antwort",
            "Entweder war kein Elixir da (siehe Elixir-Bilanz) oder die Bedrohung "
            "wurde nicht erkannt (siehe Wahrnehmung).",
            min(1.0, pm.unanswered_pushes / 10.0),
        ))

    if pm.unused_cards:
        out.append(Finding(
            "unused_cards",
            f"Nie gespielt: {', '.join(pm.unused_cards)}",
            "Karten, die das ganze Spiel in der Hand lagen, blockieren den Zyklus. "
            "Oft ein Zeichen, dass die Policy sie nicht bewerten kann.",
            0.25,
        ))

    out.sort(key=lambda f: -f.severity)
    return out


# ------------------------------------------------------------------- Ausgabe


def to_markdown(pm: Postmortem) -> str:
    L: list[str] = []
    add = L.append

    verdict = {"loss": "Niederlage", "win": "Sieg", "draw": "Unentschieden"}
    add(f"# Nachanalyse — {verdict.get(pm.outcome or '', pm.outcome or 'unbekannt')}"
        f" ({pm.crowns[0]}:{pm.crowns[1]}, {pm.duration_s:.0f} s)\n")

    if not pm.findings:
        add("Keine auffaelligen Muster gefunden. Entweder war es knapp, oder das "
            "Protokoll ist zu duenn — mehr Ticks aufzeichnen.\n")
    else:
        add("## Woran es lag\n")
        for i, f in enumerate(pm.findings, 1):
            bar = "#" * max(1, round(f.severity * 10))
            add(f"**{i}. {f.headline}**  `{bar}`\n")
            add(f"{f.detail}\n")

    add("## Zahlen\n")
    add("| Kennzahl | Wert |")
    add("|---|---|")
    add(f"| Schaden erlitten | {pm.damage_taken:.0f} |")
    add(f"| Schaden ausgeteilt | {pm.damage_dealt:.0f} |")
    add(f"| Elixir verfallen | {pm.elixir_leaked:.1f} |")
    add(f"| Elixir-Bilanz der Tausche | "
        f"{f'{pm.trade_balance:+.1f}' if pm.trades else 'keine Tausche erkannt'} |")
    if pm.reaction_times:
        rt = sorted(pm.reaction_times)
        add(f"| Reaktionszeit Median | {rt[len(rt) // 2]:.1f} s |")
    add(f"| Zuege ohne Antwort | {pm.unanswered_pushes} |")
    if pm.decisive_t is not None:
        add(f"| Entscheidendes Fenster | ab {pm.decisive_t:.0f} s "
            f"({pm.decisive_loss:.0f} HP netto) |")
    add("")

    if pm.damage_by_card:
        add("## Schaden an unseren Tuermen, nach Verursacher\n")
        add("| Karte | Schaden | Anteil |")
        add("|---|---|---|")
        for src in pm.damage_by_card[:10]:
            share = 100 * src.damage / pm.damage_taken if pm.damage_taken else 0
            add(f"| `{src.card}` | {src.damage:.0f} | {share:.0f} % |")
        add("")
        add("> Zuordnung ueber Reichweite und DPS geschaetzt. Bei mehreren "
            "Angreifern gleichzeitig wird anteilig verteilt.\n")

    if pm.trades:
        worst = sorted(pm.trades, key=lambda t: t[3])[:5]
        add("## Schlechteste Tausche\n")
        add("| Zeit | Gegner spielt | Wir antworten | Elixir |")
        add("|---|---|---|---|")
        for t, oc, mc, d in worst:
            add(f"| {t:.0f} s | `{oc}` | `{mc}` | {d:+.1f} |")
        add("")

    return "\n".join(L) + "\n"
