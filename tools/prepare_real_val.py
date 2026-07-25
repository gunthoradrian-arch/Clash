"""Baut aus den echten, gelabelten Frames ein Validierungsset.

Der Quelldatensatz liefert 6.966 annotierte Arena-Frames aus aufgezeichneten
Spielen. Die sind zu kostbar zum Mittrainieren: **Validiert wird ausschließlich
auf echten Bildern.** Ein mAP auf synthetischen Daten misst nur, wie gut der
Generator sich selbst reproduziert.

    python tools/prepare_real_val.py --dataset-root <klon> --out data/real \\
        --val-ratio 0.5

Der Split läuft **nach Episode**, nicht nach Frame. Aufeinanderfolgende Frames
derselben Episode sind fast identisch — ein zufälliger Frame-Split würde
Nachbarbilder auf Train und Val verteilen und das Ergebnis schönrechnen.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from crbot.classes import load_id_to_name, write_data_yaml  # noqa: E402
from crbot.labels import read_label, to_ultralytics, write_label  # noqa: E402


def find_pairs(root: pathlib.Path) -> list[tuple[pathlib.Path, pathlib.Path]]:
    """Sucht (Bild, Label)-Paare unter images/part2."""
    part2 = root / "images" / "part2"
    pairs = []
    for img in sorted(part2.rglob("*.jpg")):
        txt = img.with_suffix(".txt")
        if txt.exists():
            pairs.append((img, txt))
    return pairs


def episode_key(img: pathlib.Path, root: pathlib.Path) -> str:
    """Gruppenschlüssel: alles bis auf den Frame-Namen."""
    return str(img.parent.relative_to(root))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-root", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--val-ratio", type=float, default=0.5,
                    help="Anteil der Episoden, der ins Val-Set geht")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--symlink", action="store_true",
                    help="Bilder verlinken statt kopieren (spart Platz)")
    args = ap.parse_args()

    pairs = find_pairs(args.dataset_root)
    if not pairs:
        raise SystemExit(f"Keine Bild/Label-Paare unter {args.dataset_root}/images/part2")

    by_episode: dict[str, list[tuple[pathlib.Path, pathlib.Path]]] = collections.defaultdict(list)
    for img, txt in pairs:
        by_episode[episode_key(img, args.dataset_root)].append((img, txt))

    episodes = sorted(by_episode)
    random.Random(args.seed).shuffle(episodes)
    n_val = max(1, int(len(episodes) * args.val_ratio))
    val_eps = set(episodes[:n_val])

    id_to_name = load_id_to_name(args.dataset_root)
    counts = {"train": collections.Counter(), "val": collections.Counter()}
    n_imgs = {"train": 0, "val": 0}

    for ep in episodes:
        split = "val" if ep in val_eps else "train"
        img_dir = args.out / "images" / split
        lbl_dir = args.out / "labels" / split
        yolo_dir = args.out / "labels_yolo" / split
        for d in (img_dir, lbl_dir, yolo_dir):
            d.mkdir(parents=True, exist_ok=True)

        for img, txt in by_episode[ep]:
            stem = f"{ep.replace('/', '_')}_{img.stem}"
            dst = img_dir / f"{stem}.jpg"
            if args.symlink:
                if not dst.exists():
                    dst.symlink_to(img.resolve())
            else:
                shutil.copy2(img, dst)

            boxes = read_label(txt)
            write_label(lbl_dir / f"{stem}.txt", boxes)
            (yolo_dir / f"{stem}.txt").write_text(to_ultralytics(boxes))

            for b in boxes:
                counts[split][id_to_name.get(b.cls_id, str(b.cls_id))] += 1
            n_imgs[split] += 1

    write_data_yaml(
        args.dataset_root,
        args.out / "data.yaml",
        train_dir="images/train",
        val_dir="images/val",
    )

    stats = {
        "episodes_total": len(episodes),
        "episodes_val": len(val_eps),
        "images": n_imgs,
        "boxes": {k: int(v.total()) for k, v in counts.items()},
        "val_classes_covered": len(counts["val"]),
        "val_per_class": dict(counts["val"].most_common()),
    }
    (args.out / "stats_real.json").write_text(json.dumps(stats, indent=2))

    print(f"Episoden: {len(episodes)} ({len(val_eps)} -> val)")
    print(f"Bilder:   train {n_imgs['train']}  val {n_imgs['val']}")
    print(f"Boxen:    train {counts['train'].total()}  val {counts['val'].total()}")
    print(f"Klassen im Val-Set belegt: {len(counts['val'])}")
    thin = [c for c, n in counts["val"].items() if n < 10]
    print(f"Klassen mit <10 Val-Boxen: {len(thin)}  <- fuer die ist das mAP nicht aussagekraeftig")


if __name__ == "__main__":
    main()
