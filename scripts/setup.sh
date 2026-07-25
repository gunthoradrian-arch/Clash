#!/usr/bin/env bash
# Richtet die Umgebung ein und prueft, dass alles laeuft.
#
#   ./scripts/setup.sh
#
# Legt .venv an, installiert die Abhaengigkeiten, holt den Cutout-Datensatz
# nach ../crds und laesst alle Selbsttests durchlaufen.
set -euo pipefail

cd "$(dirname "$0")/.."
DATASET_DIR="${DATASET_DIR:-../crds}"

echo "== virtuelle Umgebung =="
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "   fertig: $(python --version)"

echo "== Datensatz =="
if [ -d "$DATASET_DIR/images/segment" ]; then
  echo "   liegt bereits unter $DATASET_DIR"
else
  echo "   klone nach $DATASET_DIR (~1,3 GB, dauert etwas)"
  git clone --depth 1 https://github.com/wty-yy/Clash-Royale-Detection-Dataset.git "$DATASET_DIR"
fi

echo "== Selbsttests =="
failed=0
for t in forward opponent decision tracker pipeline; do
  printf '   %-10s ' "$t"
  if out=$(python "tools/${t}_selftest.py" 2>&1); then
    echo "$out" | grep -E '^[0-9]+/[0-9]+ bestanden'
  else
    echo "$out" | tail -3
    failed=1
  fi
done

if [ "$failed" -ne 0 ]; then
  echo
  echo "Mindestens ein Test ist durchgefallen. Erst nachrechnen, dann Code anfassen —"
  echo "in der Entwicklung waren die meisten Fehlschlaege falsche Testerwartungen."
  exit 1
fi

cat <<'DONE'

Alles gruen. Naechster Schritt: das Latenzbudget messen.

  pip install ultralytics mss
  python tools/bench_latency.py --all --detector yolov8s.pt --imgsz 768 1024 1280

Details und Reihenfolge stehen in docs/handover.md
DONE
