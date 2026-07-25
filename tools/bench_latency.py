"""Misst dein Latenzbudget Schritt für Schritt durch.

Ohne Messung optimierst du blind. Dieses Skript sagt dir, **wo die
Millisekunden tatsächlich hingehen** — und die Antwort ist erfahrungsgemäß
nicht die GPU, sondern Capture und Eingabe.

    python tools/bench_latency.py --all
    python tools/bench_latency.py --detector yolov8s.pt --imgsz 768 1024 1280

Alles, was in deiner Umgebung fehlt (kein ADB, kein CUDA, kein Modell), wird
übersprungen statt zu knallen — das Skript soll überall etwas ausgeben.

Zielmarke: **unter 150 ms** von Bildschirm bis Tap. Menschliche Pro-Reaktion
liegt bei ~250 ms, KataCR meldet ~360 ms und schlägt damit nur die eingebaute
KI. Timing ist in Clash Royale das eigentliche Skill.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import statistics
import subprocess
import time

import numpy as np

ARENA_SHAPE = (896, 568, 3)
TARGET_BUDGET_MS = 150.0


def have(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


class Timing:
    """Sammelt Messwerte und liefert Perzentile."""

    def __init__(self, name: str, note: str = "") -> None:
        self.name = name
        self.note = note
        self.samples: list[float] = []

    def add(self, seconds: float) -> None:
        self.samples.append(seconds * 1000.0)

    @property
    def ok(self) -> bool:
        return len(self.samples) >= 3

    def row(self) -> tuple[str, str, str, str, str]:
        if not self.ok:
            return (self.name, "-", "-", "-", self.note or "uebersprungen")
        s = sorted(self.samples)
        p50 = statistics.median(s)
        p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
        return (self.name, f"{p50:.1f}", f"{p95:.1f}", f"{min(s):.1f}", self.note)


def measure(fn, n: int, warmup: int = 3) -> list[float]:
    for _ in range(warmup):
        try:
            fn()
        except Exception:
            return []
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t0)
    return out


# ----------------------------------------------------------------- Capture


def bench_capture_adb(n: int) -> Timing:
    t = Timing("Capture: adb exec-out screencap")
    if not shutil.which("adb"):
        t.note = "adb nicht gefunden"
        return t

    import cv2

    def once():
        raw = subprocess.run(["adb", "exec-out", "screencap", "-p"],
                             capture_output=True, check=True).stdout
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("decode fehlgeschlagen")

    for s in measure(once, n):
        t.add(s)
    if not t.ok:
        t.note = "kein Geraet verbunden?"
    return t


def bench_capture_mss(n: int) -> Timing:
    """Direkte Fensteraufnahme — der schnelle Weg auf Windows."""
    t = Timing("Capture: mss (Bildschirmbereich)")
    if not have("mss"):
        t.note = "pip install mss"
        return t

    import mss

    with mss.mss() as sct:
        region = {"top": 0, "left": 0, "width": 568, "height": 896}

        def once():
            np.asarray(sct.grab(region))

        for s in measure(once, n):
            t.add(s)
    return t


# ---------------------------------------------------------------- Detektor


def bench_detector(weights: str, sizes: list[int], n: int, half: bool) -> list[Timing]:
    out: list[Timing] = []
    if not have("ultralytics"):
        t = Timing("Detektor", "pip install ultralytics")
        out.append(t)
        return out

    import torch
    from ultralytics import YOLO

    device = "cuda" if torch.cuda.is_available() else "cpu"
    gpu = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"

    try:
        model = YOLO(weights)
    except Exception as e:  # Gewichte fehlen
        out.append(Timing("Detektor", f"{weights} nicht ladbar: {e}"))
        return out

    for size in sizes:
        label = f"Detektor {weights}@{size}{' fp16' if half and device == 'cuda' else ''}"
        t = Timing(label, gpu)
        frame = np.random.randint(0, 255, (size, size, 3), dtype=np.uint8)

        def once():
            model.predict(frame, imgsz=size, device=device, half=half and device == "cuda",
                          verbose=False)
            if device == "cuda":
                torch.cuda.synchronize()

        for s in measure(once, n):
            t.add(s)
        out.append(t)
    return out


# ------------------------------------------------------------------ Eingabe


def bench_input(n: int) -> Timing:
    t = Timing("Eingabe: adb input tap")
    if not shutil.which("adb"):
        t.note = "adb nicht gefunden"
        return t

    def once():
        subprocess.run(["adb", "shell", "input", "tap", "1", "1"],
                       capture_output=True, check=True)

    for s in measure(once, max(4, n // 4)):
        t.add(s)
    if not t.ok:
        t.note = "kein Geraet verbunden?"
    return t


# ------------------------------------------------------------------- Ausgabe


def report(timings: list[Timing]) -> None:
    rows = [t.row() for t in timings]
    w0 = max(len(r[0]) for r in rows) + 2

    print(f"\n{'Schritt':{w0}s} {'p50':>8s} {'p95':>8s} {'min':>8s}  Hinweis")
    print("-" * (w0 + 34))
    for r in rows:
        print(f"{r[0]:{w0}s} {r[1]:>8s} {r[2]:>8s} {r[3]:>8s}  {r[4]}")

    # Schnellste Variante je Kategorie fuer das Budget heranziehen.
    def best(prefix: str) -> float | None:
        vals = [statistics.median(t.samples) for t in timings
                if t.ok and t.name.startswith(prefix)]
        return min(vals) if vals else None

    cap, det, inp = best("Capture"), best("Detektor"), best("Eingabe")
    parts = [("Capture", cap), ("Detektor", det), ("Eingabe", inp)]
    known = [v for _, v in parts if v is not None]
    if not known:
        return

    total = sum(known)
    print(f"\nBudget (schnellste gemessene Variante je Schritt): {total:.1f} ms")
    for name, v in parts:
        if v is None:
            print(f"  {name:10s}      ?  nicht gemessen")
        else:
            print(f"  {name:10s} {v:6.1f} ms  ({100 * v / total:.0f} %)")
    print(f"  + Tracker/Policy grob 3-6 ms, noch nicht enthalten")

    hint = {
        "Capture": "  -> scrcpy-Videostrom oder direkte Fensteraufnahme statt adb screencap.",
        "Eingabe": "  -> minitouch oder scrcpy-Steuerkanal statt 'adb input tap'.",
        "Detektor": "  -> TensorRT FP16 exportieren, ggf. kleinere imgsz.",
    }
    worst = max((p for p in parts if p[1] is not None), key=lambda p: p[1])

    if total > TARGET_BUDGET_MS:
        print(f"\nUEBER ZIEL ({TARGET_BUDGET_MS:.0f} ms). Groesster Posten: {worst[0]} "
              f"mit {worst[1]:.1f} ms.")
        print(hint[worst[0]])
    else:
        print(f"\nIm Ziel ({TARGET_BUDGET_MS:.0f} ms).")
        # Auch unter Ziel lohnt der Hinweis, wenn ein einzelner Posten dominiert:
        # dort liegt die gesamte Reserve, nicht in den anderen beiden.
        share = worst[1] / total
        if share > 0.5:
            print(f"Aber {worst[0]} allein macht {100 * share:.0f} % aus — dort liegt "
                  "deine gesamte Reserve.")
            print(hint[worst[0]])
        else:
            print("Reserve gehoert in hoehere Aufloesung oder Rollout-Suche, "
                  "nicht in ein tieferes Netz.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="alles messen")
    ap.add_argument("--capture", action="store_true")
    ap.add_argument("--input", action="store_true")
    ap.add_argument("--detector", metavar="WEIGHTS")
    ap.add_argument("--imgsz", type=int, nargs="+", default=[768])
    ap.add_argument("--half", action="store_true", default=True)
    ap.add_argument("-n", "--runs", type=int, default=30)
    args = ap.parse_args()

    do_all = args.all or not (args.capture or args.input or args.detector)
    timings: list[Timing] = []

    if do_all or args.capture:
        timings.append(bench_capture_mss(args.runs))
        timings.append(bench_capture_adb(args.runs))

    weights = args.detector or ("yolov8s.pt" if do_all else None)
    if weights:
        timings.extend(bench_detector(weights, args.imgsz, args.runs, args.half))

    if do_all or args.input:
        timings.append(bench_input(args.runs))

    report(timings)


if __name__ == "__main__":
    main()
