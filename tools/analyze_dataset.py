"""Analysiert den Clash-Royale-Detection-Datensatz von wty-yy.

Liefert die Zahlen, auf denen Generator- und Detektor-Design aufbauen:
Klassenverteilung, Boxgrößen (fuer den Small/Large-Split), Cutout-Bestand.

    python tools/analyze_dataset.py --root <pfad/zum/dataset> [--md docs/dataset-report.md]
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import statistics

import numpy as np
import yaml
from PIL import Image

# Label-Layout aus "Clash Royale dataset annotation.md":
# class cx cy w h | blong movement shield visible rage slow heal_clone
STATE_NAMES = ["blong", "movement", "shield", "visible", "rage", "slow", "heal_clone"]
N_FIELDS = 5 + len(STATE_NAMES)


def load_names(root: pathlib.Path) -> dict[int, str]:
    cfg = yaml.safe_load((root / "images/part2/ClashRoyale_detection.yaml").read_text())
    return {int(k): v for k, v in cfg["names"].items()}


def iter_labels(root: pathlib.Path):
    """Liefert (txt_pfad, zeilen_als_float_listen). Ueberspringt kaputte Zeilen."""
    for txt in sorted((root / "images/part2").rglob("*.txt")):
        rows = []
        for line in txt.read_text().splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                rows.append([float(p) for p in parts])
            except ValueError:
                continue
        if rows:
            yield txt, rows


def analyze(root: pathlib.Path) -> dict:
    names = load_names(root)

    per_class = collections.Counter()
    per_class_blong = collections.defaultdict(collections.Counter)
    areas_by_class = collections.defaultdict(list)
    diags: list[float] = []
    n_frames = 0
    field_counts = collections.Counter()

    # Referenzaufloesung der Arena-Crops bestimmen (Boxen sind normalisiert).
    sample_imgs = list((root / "images/part2").rglob("*.jpg"))[:200]
    sizes = collections.Counter(Image.open(p).size for p in sample_imgs)
    ref_w, ref_h = sizes.most_common(1)[0][0]

    for _txt, rows in iter_labels(root):
        n_frames += 1
        for r in rows:
            field_counts[len(r)] += 1
            cid = int(r[0])
            w_px, h_px = r[3] * ref_w, r[4] * ref_h
            per_class[cid] += 1
            areas_by_class[cid].append((w_px, h_px))
            diags.append((w_px**2 + h_px**2) ** 0.5)
            if len(r) > 5:
                per_class_blong[cid][int(r[5])] += 1

    # Cutout-Bestand
    seg = root / "images/segment"
    cutouts = {d.name: len(list(d.glob("*.png"))) + len(list(d.glob("*.jpg")))
               for d in sorted(seg.iterdir()) if d.is_dir()}

    diags_arr = np.array(diags)
    return {
        "ref_resolution": [ref_w, ref_h],
        "n_frames": n_frames,
        "n_boxes": int(per_class.total()),
        "field_counts": dict(field_counts),
        "resolutions_seen": {f"{w}x{h}": c for (w, h), c in sizes.items()},
        "names": names,
        "per_class": dict(per_class),
        "per_class_blong": {k: dict(v) for k, v in per_class_blong.items()},
        "areas_by_class": {k: v for k, v in areas_by_class.items()},
        "diag_percentiles": {
            f"p{p}": float(np.percentile(diags_arr, p)) for p in (1, 5, 10, 25, 50, 75, 90, 95, 99)
        },
        "cutouts": cutouts,
        "n_cutouts": sum(cutouts.values()),
    }


def to_markdown(a: dict) -> str:
    names = a["names"]
    L: list[str] = []
    add = L.append

    add("# Datensatz-Report\n")
    add("Automatisch erzeugt von `tools/analyze_dataset.py`. Quelle: "
        "[wty-yy/Clash-Royale-Detection-Dataset](https://github.com/wty-yy/Clash-Royale-Detection-Dataset) (MIT).\n")

    add("## Umfang\n")
    add(f"- Echte gelabelte Arena-Frames: **{a['n_frames']}**")
    add(f"- Annotierte Boxen: **{a['n_boxes']}**")
    add(f"- Referenzaufloesung der Arena-Crops: **{a['ref_resolution'][0]}x{a['ref_resolution'][1]}**")
    add(f"- Cutouts fuer die Synthese: **{a['n_cutouts']}** in **{len(a['cutouts'])}** Ordnern")
    add(f"- Klassen laut YAML: **{len(names)}**")
    add(f"- Felder pro Labelzeile: {a['field_counts']}\n")

    add("## Boxgroessen (Diagonale in px @ Referenzaufloesung)\n")
    add("| Perzentil | " + " | ".join(a["diag_percentiles"]) + " |")
    add("|---|" + "---|" * len(a["diag_percentiles"]))
    add("| px | " + " | ".join(f"{v:.1f}" for v in a["diag_percentiles"].values()) + " |\n")

    add("## Klassen nach Haeufigkeit\n")
    add("| # | Klasse | Boxen | Anteil | med. w x h (px) | Cutouts |")
    add("|---|---|---|---|---|---|")
    total = a["n_boxes"]
    for cid, n in sorted(a["per_class"].items(), key=lambda kv: -kv[1]):
        nm = names.get(cid, f"?{cid}")
        wh = a["areas_by_class"][cid]
        mw = statistics.median(w for w, _ in wh)
        mh = statistics.median(h for _, h in wh)
        add(f"| {cid} | `{nm}` | {n} | {100 * n / total:.2f}% | {mw:.0f} x {mh:.0f} "
            f"| {a['cutouts'].get(nm, 0)} |")

    add("\n## Klassen ohne jede Box in den echten Frames\n")
    missing = [names[c] for c in sorted(names) if a["per_class"].get(c, 0) == 0]
    add(f"{len(missing)} von {len(names)}: " + (", ".join(f"`{m}`" for m in missing) if missing else "-"))
    add("\n> Genau diese Klassen muss der Generator kuenstlich hochziehen - aus echten "
        "Spielen kommen dafuer zu wenige oder gar keine Beispiele.\n")

    add("## Cutout-Ordner ohne Bilder\n")
    empty = [k for k, v in a["cutouts"].items() if v == 0]
    add(f"{len(empty)}: " + (", ".join(f"`{e}`" for e in empty) if empty else "-"))
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=pathlib.Path)
    ap.add_argument("--md", type=pathlib.Path)
    ap.add_argument("--json", type=pathlib.Path)
    args = ap.parse_args()

    a = analyze(args.root)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        slim = {k: v for k, v in a.items() if k != "areas_by_class"}
        args.json.write_text(json.dumps(slim, indent=2))
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(to_markdown(a))
        print(f"geschrieben: {args.md}")

    print(f"Frames {a['n_frames']} | Boxen {a['n_boxes']} | Cutouts {a['n_cutouts']} "
          f"| Ref {a['ref_resolution']}")
    print("Diagonalen:", {k: round(v, 1) for k, v in a["diag_percentiles"].items()})


if __name__ == "__main__":
    main()
