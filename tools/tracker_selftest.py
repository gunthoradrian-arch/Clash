"""Prüft den Tracker an Bewegungen mit bekanntem Verlauf.

    python tools/tracker_selftest.py
"""

from __future__ import annotations

import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from crbot.tracker import Detection, Tracker  # noqa: E402

PASS, FAIL = "OK  ", "FEHL"
results: list[tuple[bool, str]] = []
DT = 0.2


def check(name: str, ok: bool, detail: str) -> None:
    results.append((ok, name))
    print(f"[{PASS if ok else FAIL}] {name}\n       {detail}")


def t_velocity() -> None:
    """Gerade Bewegung mit 1,5 Kacheln/s muss als solche erkannt werden."""
    tr = Tracker()
    speed = 1.5
    for i in range(12):
        t = i * DT
        tr.update([Detection("hog-rider", 1, 3.5, 5.0 + speed * t)], t)
    tracks = tr.tracks
    if not tracks:
        check("Geschwindigkeit", False, "kein bestätigter Track")
        return
    v = tracks[0].vy
    check("Geschwindigkeit erkannt",
          abs(v - speed) < 0.2,
          f"gemessen {v:.2f} Kacheln/s (erwartet {speed:.2f}), "
          f"Richtung {'vorwärts' if v > 0 else 'zurück'}")


def t_id_stable() -> None:
    """Über eine ganze Bahn hinweg bleibt die Kennung dieselbe."""
    tr = Tracker()
    ids = set()
    for i in range(20):
        t = i * DT
        tr.update([Detection("knight", 0, 9.0, 20.0 - 0.7 * t)], t)
        ids.update(x.id for x in tr.tracks)
    check("Kennung bleibt stabil",
          len(ids) == 1,
          f"{len(ids)} Kennung(en) über 20 Frames: {sorted(ids)}")


def t_survives_dropout() -> None:
    """Zwei fehlende Frames dürfen den Track nicht töten."""
    tr = Tracker()
    for i in range(6):
        tr.update([Detection("knight", 0, 9.0, 20.0 - 0.7 * i * DT)], i * DT)
    first_id = tr.tracks[0].id

    tr.update([], 6 * DT)         # Aussetzer
    tr.update([], 7 * DT)
    alive_during = len(tr.all_tracks)

    tr.update([Detection("knight", 0, 9.0, 20.0 - 0.7 * 8 * DT)], 8 * DT)
    same = tr.tracks and tr.tracks[0].id == first_id
    check("Übersteht Aussetzer",
          bool(same) and alive_during == 1,
          f"nach 2 fehlenden Frames wieder erkannt, Kennung {first_id} behalten")


def t_dies_when_gone() -> None:
    """Wer dauerhaft weg ist, verschwindet auch aus der Liste."""
    tr = Tracker()
    for i in range(6):
        tr.update([Detection("skeleton", 1, 5.0, 12.0)], i * DT)
    for i in range(6, 14):
        tr.update([], i * DT)
    check("Verschwundene Einheit wird entfernt",
          len(tr.all_tracks) == 0,
          f"nach 8 leeren Frames noch {len(tr.all_tracks)} Tracks")


def t_crossing_units() -> None:
    """Zwei sich kreuzende Einheiten dürfen die Kennungen nicht tauschen.

    Der schwierige Fall. Die Zuordnung über die **vorhergesagte** Position
    loest ihn, reine Naehe zur letzten Position nicht.
    """
    tr = Tracker()
    ids_a: list[int] = []
    ids_b: list[int] = []
    for i in range(24):
        t = i * DT
        ya = 8.0 + 0.7 * t          # laeuft nach unten
        yb = 14.0 - 0.7 * t         # laeuft nach oben
        dets = [Detection("knight", 0, 9.0, ya), Detection("musketeer", 1, 9.0, yb)]
        tr.update(dets, t)
        for track in tr.tracks:
            (ids_a if track.cls == "knight" else ids_b).append(track.id)
    check("Kreuzende Einheiten tauschen nicht",
          len(set(ids_a)) == 1 and len(set(ids_b)) == 1,
          f"Ritter behielt {len(set(ids_a))} Kennung(en), Musketier "
          f"{len(set(ids_b))} — sie laufen bei ~4,3 s durcheinander")


def t_noise_rejection() -> None:
    """Ein einzelner Fehlalarm darf nicht als bestätigte Einheit durchgehen."""
    tr = Tracker(min_hits=2)
    tr.update([Detection("pekka", 1, 2.0, 3.0)], 0.0)
    confirmed_after_one = len(tr.tracks)
    tr.update([], DT)
    check("Einzelner Fehlalarm wird gefiltert",
          confirmed_after_one == 0,
          f"nach einem Frame {confirmed_after_one} bestätigte Tracks "
          f"(min_hits=2 verlangt eine zweite Sichtung)")


def t_noisy_positions() -> None:
    """Messrauschen darf die Verfolgung nicht zerreissen.

    Geprüft wird der **Schätzer**, nicht eine einzelne Ziehung. Bei 0,12
    Kacheln Rauschen streut die Temposchätzung mit rund 0,16 — ein einzelner
    Lauf kann deshalb auch bei fehlerfreiem Code deutlich danebenliegen. Nur
    der Mittelwert über viele Läufe sagt etwas darüber aus, ob systematisch
    falsch gerechnet wird.
    """
    speeds: list[float] = []
    ids_per_run: list[int] = []
    for seed in range(20):
        rng = random.Random(seed)
        tr = Tracker()
        ids = set()
        for i in range(25):
            t = i * DT
            x = 9.0 + rng.gauss(0, 0.12)
            y = 6.0 + 1.1 * t + rng.gauss(0, 0.12)
            tr.update([Detection("hog-rider", 1, x, y)], t)
            ids.update(k.id for k in tr.tracks)
        ids_per_run.append(len(ids))
        if tr.tracks:
            speeds.append(tr.tracks[0].vy)

    mean = sum(speeds) / len(speeds) if speeds else 0.0
    spread = (sum((v - mean) ** 2 for v in speeds) / len(speeds)) ** 0.5 if speeds else 0.0
    check("Robust gegen Messrauschen",
          all(n == 1 for n in ids_per_run) and abs(mean - 1.1) < 0.1,
          f"20 Läufe: je 1 Kennung, Tempo im Mittel {mean:.3f} ± {spread:.3f} "
          f"(erwartet 1,10) — unverzerrt, aber verrauscht")


def main() -> int:
    for fn in (t_velocity, t_id_stable, t_survives_dropout, t_dies_when_gone,
               t_crossing_units, t_noise_rejection, t_noisy_positions):
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
