"""Klassenliste — eine einzige Quelle der Wahrheit für synthetische und echte Daten.

Die IDs stammen aus der YAML des Quelldatensatzes. Wer eigene Klassen anhängt,
hängt sie **hinten** an: Bestehende IDs zu verschieben macht jedes vorher
erzeugte Label und jedes trainierte Gewicht still ungültig.
"""

from __future__ import annotations

import pathlib

import yaml

DEFAULT_YAML_REL = "images/part2/ClashRoyale_detection.yaml"

# Platzhalter-Einträge des Quelldatensatzes (reservierte Slots ohne Bedeutung).
PAD_PREFIX = "pad_"


def load_class_map(dataset_root: pathlib.Path) -> dict[str, int]:
    """Liest ``name -> id`` aus der Datensatz-YAML."""
    path = pathlib.Path(dataset_root) / DEFAULT_YAML_REL
    if not path.exists():
        raise FileNotFoundError(f"Klassen-YAML nicht gefunden: {path}")
    names = yaml.safe_load(path.read_text())["names"]
    return {str(v): int(k) for k, v in names.items()}


def load_id_to_name(dataset_root: pathlib.Path) -> dict[int, str]:
    return {v: k for k, v in load_class_map(dataset_root).items()}


def real_class_names(dataset_root: pathlib.Path) -> list[str]:
    """Klassenliste ohne die ``pad_*``-Platzhalter, nach ID sortiert."""
    id_to_name = load_id_to_name(dataset_root)
    return [id_to_name[i] for i in sorted(id_to_name) if not id_to_name[i].startswith(PAD_PREFIX)]


def write_data_yaml(
    dataset_root: pathlib.Path,
    out_path: pathlib.Path,
    train_dir: str,
    val_dir: str,
) -> None:
    """Schreibt die Ultralytics-``data.yaml`` mit vollständiger Klassenliste.

    Die ``pad_*``-Slots bleiben drin: Sie halten die IDs stabil, damit unsere
    Labels zu denen des Quelldatensatzes passen.
    """
    id_to_name = load_id_to_name(dataset_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "path": str(out_path.parent.resolve()),
        "train": train_dir,
        "val": val_dir,
        "names": {i: id_to_name[i] for i in sorted(id_to_name)},
    }
    out_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
