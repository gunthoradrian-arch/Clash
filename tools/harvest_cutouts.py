"""Erntet eigene Cutouts per Hintergrundsubtraktion — ohne manuelles Labeln.

Das Verfahren nutzt aus, dass du im Trainingslager eine **leere Arena** und
volle Kontrolle über die gelegte Karte hast:

1. Referenzbild der leeren Arena aufnehmen.
2. Genau eine Karte legen, ein paar Frames aufnehmen.
3. Differenz zum Referenzbild -> Maske -> freigestelltes RGBA-Cutout.

Du weißt exakt, **was** es ist (du hast die Karte gelegt) und **wo** es ist
(nur ein Objekt im Bild). Das Label fällt ab, ohne dass jemand eine Box zieht.

Genau das brauchst du für alles, was der Fremddatensatz nicht abdeckt: neue
Karten, Evolutionen, Champions.

Ausgabe landet in der Ordnerstruktur, die ``crbot.cutouts`` erwartet::

    <out>/images/segment/<klasse>/<klasse>_<blong>_<index>.png

Betriebsarten
-------------
``--frames <ordner>``   Frames liegen bereits als Bilder vor (jede Quelle recht:
                        Emulator-Aufnahme, Bildschirmmitschnitt, Video-Export).
``--video <datei>``     Frames aus einem Video ziehen.
``--adb``               Emulator direkt fernsteuern (Karte legen + aufnehmen).
                        Braucht ein laufendes Clash Royale — auf dem PC, nicht hier.
``--selftest``          Prüft die Extraktion gegen ein künstlich gebautes
                        Beispiel mit bekannter Box. Läuft überall.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from crbot import arena  # noqa: E402

# Ab welcher Abweichung gilt ein Pixel als "verändert". Bewusst niedrig:
# Nachbearbeitung entfernt Rauschen zuverlässiger als eine hohe Schwelle,
# die Einheiten mit arenaähnlicher Farbe wegschneidet.
DIFF_THRESHOLD = 26
MIN_AREA_PX = 220


def build_mask(frame: np.ndarray, reference: np.ndarray, threshold: int = DIFF_THRESHOLD) -> np.ndarray:
    """Binärmaske der Pixel, die sich vom Referenzbild unterscheiden."""
    if frame.shape != reference.shape:
        reference = cv2.resize(reference, (frame.shape[1], frame.shape[0]))

    diff = cv2.absdiff(frame, reference)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    # Schatten und Rand aufräumen: erst schließen (Löcher im Sprite), dann
    # öffnen (Einzelpixel-Rauschen).
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=1)
    return mask


def extract_cutouts(
    frame: np.ndarray,
    reference: np.ndarray,
    min_area: int = MIN_AREA_PX,
    max_objects: int = 8,
) -> list[tuple[np.ndarray, tuple[int, int, int, int]]]:
    """Liefert (RGBA-Crop, (x1, y1, x2, y2)) je gefundenem Objekt."""
    mask = build_mask(frame, reference)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    found = []
    order = sorted(range(1, n), key=lambda i: -stats[i, cv2.CC_STAT_AREA])
    for idx in order[:max_objects]:
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        x = int(stats[idx, cv2.CC_STAT_LEFT])
        y = int(stats[idx, cv2.CC_STAT_TOP])
        w = int(stats[idx, cv2.CC_STAT_WIDTH])
        h = int(stats[idx, cv2.CC_STAT_HEIGHT])

        comp = (labels[y:y + h, x:x + w] == idx).astype(np.uint8) * 255
        bgr = frame[y:y + h, x:x + w]
        rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = comp
        found.append((rgba, (x, y, x + w, y + h)))
    return found


def save_cutouts(
    cutouts: list[tuple[np.ndarray, tuple[int, int, int, int]]],
    out_root: pathlib.Path,
    cls_name: str,
    blong: int,
    start_index: int = 0,
) -> int:
    d = out_root / "images" / "segment" / cls_name
    d.mkdir(parents=True, exist_ok=True)
    i = start_index
    for rgba, _rect in cutouts:
        cv2.imwrite(str(d / f"{cls_name}_{blong}_{i:07d}.png"), rgba)
        i += 1
    return i


# --------------------------------------------------------------------- Quellen


def frames_from_dir(path: pathlib.Path):
    for p in sorted(path.iterdir()):
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
            img = cv2.imread(str(p))
            if img is not None:
                yield p.name, img


def frames_from_video(path: pathlib.Path, every: int = 3):
    cap = cv2.VideoCapture(str(path))
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % every == 0:
            yield f"frame_{i:06d}", frame
        i += 1
    cap.release()


# ------------------------------------------------------------------- ADB-Modus


class AdbDriver:
    """Minimaler ADB-Treiber zum Legen von Karten und Aufnehmen von Frames.

    Ungetestet in dieser Umgebung — hier läuft kein Emulator. Die Aufrufe sind
    bewusst simpel gehalten (``exec-out screencap``), damit sie mit jedem
    Emulator funktionieren, der ADB spricht. Für den Dauerbetrieb im Bot ist
    das zu langsam (~100-300 ms/Frame); zum Ernten reicht es.
    """

    def __init__(self, serial: str | None = None) -> None:
        self.base = ["adb"] + (["-s", serial] if serial else [])

    def _run(self, args: list[str], binary: bool = False) -> bytes:
        res = subprocess.run(self.base + args, capture_output=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)} fehlgeschlagen: {res.stderr.decode(errors='replace')}")
        return res.stdout if binary else res.stdout

    def screenshot(self) -> np.ndarray:
        raw = self._run(["exec-out", "screencap", "-p"], binary=True)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("Screenshot konnte nicht dekodiert werden")
        return img

    def tap(self, x: int, y: int) -> None:
        self._run(["shell", "input", "tap", str(int(x)), str(int(y))])

    def play_card(self, slot_xy: tuple[int, int], target_xy: tuple[int, int], settle: float = 0.35) -> None:
        self.tap(*slot_xy)
        time.sleep(settle)
        self.tap(*target_xy)


# ---------------------------------------------------------------------- Selbsttest


def selftest() -> int:
    """Baut eine bekannte Szene und prüft, ob die Extraktion sie zurückgewinnt."""
    rng = np.random.default_rng(0)
    h, w = arena.ARENA_H, arena.ARENA_W

    # Referenz: strukturierter Hintergrund (gleichfarbige Flächen wären zu leicht).
    reference = rng.integers(60, 90, size=(h, w, 3), dtype=np.uint8)
    reference = cv2.GaussianBlur(reference, (9, 9), 0)

    frame = reference.copy()
    truth = (200, 300, 260, 380)  # x1, y1, x2, y2
    x1, y1, x2, y2 = truth
    cv2.ellipse(
        frame,
        ((x1 + x2) // 2, (y1 + y2) // 2),
        ((x2 - x1) // 2, (y2 - y1) // 2),
        0, 0, 360, (30, 200, 220), -1,
    )

    found = extract_cutouts(frame, reference)
    if not found:
        print("FEHLGESCHLAGEN: kein Objekt gefunden")
        return 1

    rgba, rect = found[0]
    ix1, iy1 = max(rect[0], truth[0]), max(rect[1], truth[1])
    ix2, iy2 = min(rect[2], truth[2]), min(rect[3], truth[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    a1 = (rect[2] - rect[0]) * (rect[3] - rect[1])
    a2 = (truth[2] - truth[0]) * (truth[3] - truth[1])
    iou = inter / (a1 + a2 - inter)

    alpha_ratio = float((rgba[:, :, 3] > 0).mean())
    print(f"gefunden: {len(found)} Objekt(e)")
    print(f"Box  ist={rect}  soll={truth}  IoU={iou:.3f}")
    print(f"Alphaanteil im Crop: {alpha_ratio:.2f} (Ellipse in Box ~0.79 erwartet)")

    ok = iou > 0.9 and 0.6 < alpha_ratio < 0.95
    print("SELBSTTEST BESTANDEN" if ok else "SELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


# ---------------------------------------------------------------------- CLI


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--reference", type=pathlib.Path, help="Bild der leeren Arena")
    ap.add_argument("--frames", type=pathlib.Path)
    ap.add_argument("--video", type=pathlib.Path)
    ap.add_argument("--every", type=int, default=3, help="nur jeden n-ten Videoframe")
    ap.add_argument("--card", help="Klassenname der gelegten Karte, z.B. knight")
    ap.add_argument("--blong", type=int, default=0, choices=(0, 1))
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/harvest"))
    ap.add_argument("--min-area", type=int, default=MIN_AREA_PX)
    ap.add_argument("--max-objects", type=int, default=4)
    args = ap.parse_args()

    if args.selftest:
        raise SystemExit(selftest())

    if not args.reference or not args.card:
        raise SystemExit("--reference und --card sind Pflicht (oder --selftest benutzen)")

    reference = cv2.imread(str(args.reference))
    if reference is None:
        raise SystemExit(f"Referenzbild nicht lesbar: {args.reference}")

    if args.frames:
        source = frames_from_dir(args.frames)
    elif args.video:
        source = frames_from_video(args.video, args.every)
    else:
        raise SystemExit("Eine Quelle angeben: --frames oder --video")

    index = 0
    n_frames = 0
    for _name, frame in source:
        n_frames += 1
        cutouts = extract_cutouts(frame, reference, args.min_area, args.max_objects)
        index = save_cutouts(cutouts, args.out, args.card, args.blong, index)

    print(f"{n_frames} Frames verarbeitet -> {index} Cutouts nach "
          f"{args.out / 'images' / 'segment' / args.card}")
    if index == 0:
        print("Nichts gefunden. Stimmt das Referenzbild? Ist --min-area zu hoch?")


if __name__ == "__main__":
    main()
