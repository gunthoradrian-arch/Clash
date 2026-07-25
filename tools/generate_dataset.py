"""Erzeugt synthetische, gelabelte Arena-Bilder.

    python tools/generate_dataset.py --dataset-root <klon> --out data/synth -n 20000

Schreibt Ultralytics-Layout::

    data/synth/images/train/000000.jpg
    data/synth/labels/train/000000.txt   # 12 Felder (Superset)
    data/synth/labels_yolo/train/000000.txt  # 5 Felder, für stock-Ultralytics

Mit ``--preview k`` werden zusätzlich k Bilder mit eingezeichneten Boxen nach
``<out>/preview/`` gelegt — zur Sichtkontrolle, bevor Rechenzeit verbrannt wird.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from crbot import arena  # noqa: E402
from crbot.classes import load_class_map, load_id_to_name, write_data_yaml  # noqa: E402
from crbot.compose import SceneComposer, SceneConfig  # noqa: E402
from crbot.cutouts import CutoutLibrary  # noqa: E402
from crbot.labels import Box, to_ultralytics, write_label  # noqa: E402

TEAM_COLOR = {0: (80, 170, 255), 1: (255, 90, 90)}


def draw_preview(img: Image.Image, boxes: list[Box], id_to_name: dict[int, str]) -> Image.Image:
    out = img.copy().convert("RGB")
    d = ImageDraw.Draw(out)
    for b in boxes:
        x1 = (b.cx - b.w / 2) * arena.ARENA_W
        y1 = (b.cy - b.h / 2) * arena.ARENA_H
        x2 = (b.cx + b.w / 2) * arena.ARENA_W
        y2 = (b.cy + b.h / 2) * arena.ARENA_H
        color = TEAM_COLOR.get(b.blong, (255, 255, 255))
        d.rectangle([x1, y1, x2, y2], outline=color, width=2)
        d.text((x1 + 2, max(0, y1 - 10)), id_to_name.get(b.cls_id, "?"), fill=color)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-root", required=True, type=pathlib.Path,
                    help="Klon von wty-yy/Clash-Royale-Detection-Dataset")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("-n", "--num", type=int, default=1000)
    ap.add_argument("--split", default="train")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--preview", type=int, default=0)
    ap.add_argument("--max-units", type=int, default=None)
    ap.add_argument("--no-uniform", action="store_true",
                    help="Klassenverteilung NICHT ausgleichen (reproduziert die Schieflage)")
    args = ap.parse_args()

    lib = CutoutLibrary(args.dataset_root, seed=args.seed)
    print(lib.summary())

    class_map = load_class_map(args.dataset_root)
    id_to_name = load_id_to_name(args.dataset_root)

    cfg = SceneConfig(uniform_over_classes=not args.no_uniform)
    if args.max_units:
        cfg.max_units = args.max_units
    comp = SceneComposer(lib, class_map, cfg, seed=args.seed)

    img_dir = args.out / "images" / args.split
    lbl_dir = args.out / "labels" / args.split
    yolo_dir = args.out / "labels_yolo" / args.split
    for d in (img_dir, lbl_dir, yolo_dir):
        d.mkdir(parents=True, exist_ok=True)
    prev_dir = args.out / "preview"
    if args.preview:
        prev_dir.mkdir(parents=True, exist_ok=True)

    per_class = collections.Counter()
    per_team = collections.Counter()
    n_boxes = 0

    for i in range(args.num):
        img, boxes = comp.compose()
        stem = f"{i:06d}"
        img.save(img_dir / f"{stem}.jpg", quality=comp.jpeg_quality())
        write_label(lbl_dir / f"{stem}.txt", boxes)
        (yolo_dir / f"{stem}.txt").write_text(to_ultralytics(boxes))

        for b in boxes:
            per_class[id_to_name.get(b.cls_id, str(b.cls_id))] += 1
            per_team[b.blong] += 1
        n_boxes += len(boxes)

        if i < args.preview:
            draw_preview(img, boxes, id_to_name).save(prev_dir / f"{stem}_boxes.jpg", quality=92)

        if (i + 1) % 250 == 0 or i + 1 == args.num:
            print(f"  {i + 1}/{args.num} Bilder, {n_boxes} Boxen", flush=True)

    if comp.unknown_classes:
        print(f"WARNUNG: {len(comp.unknown_classes)} Cutout-Ordner ohne Klassen-ID "
              f"(übersprungen): {sorted(comp.unknown_classes)[:10]}")

    stats = {
        "images": args.num,
        "boxes": n_boxes,
        "boxes_per_image": round(n_boxes / max(1, args.num), 2),
        "distinct_classes": len(per_class),
        "per_team": dict(per_team),
        "per_class": dict(per_class.most_common()),
        "unknown_cutout_dirs": sorted(comp.unknown_classes),
    }
    (args.out / f"stats_{args.split}.json").write_text(json.dumps(stats, indent=2))

    write_data_yaml(
        args.dataset_root,
        args.out / "data.yaml",
        train_dir=f"images/{args.split}",
        val_dir="images/val",
    )

    print(f"\n{args.num} Bilder, {n_boxes} Boxen, {len(per_class)} Klassen belegt")
    print(f"Team-Verteilung: {dict(per_team)}")
    rare = [c for c, v in per_class.items() if v < 5]
    print(f"Klassen mit <5 Boxen: {len(rare)}")


if __name__ == "__main__":
    main()
