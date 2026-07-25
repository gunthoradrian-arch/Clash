# Richtet die Umgebung unter Windows ein und prueft, dass alles laeuft.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Legt .venv an, installiert die Abhaengigkeiten, holt den Cutout-Datensatz
# nach ..\crds und laesst alle Selbsttests durchlaufen.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$DatasetDir = if ($env:DATASET_DIR) { $env:DATASET_DIR } else { "..\crds" }

Write-Host "== virtuelle Umgebung =="
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
Write-Host "   fertig: $(python --version)"

Write-Host "== Datensatz =="
if (Test-Path (Join-Path $DatasetDir "images\segment")) {
    Write-Host "   liegt bereits unter $DatasetDir"
} else {
    Write-Host "   klone nach $DatasetDir (~1,3 GB, dauert etwas)"
    git clone --depth 1 https://github.com/wty-yy/Clash-Royale-Detection-Dataset.git $DatasetDir
}

Write-Host "== Selbsttests =="
$failed = $false
foreach ($t in "forward", "opponent", "decision", "tracker", "pipeline") {
    Write-Host -NoNewline ("   {0,-10} " -f $t)
    $out = python "tools\${t}_selftest.py" 2>&1
    if ($LASTEXITCODE -eq 0) {
        ($out | Select-String -Pattern '^\d+/\d+ bestanden').Line
    } else {
        $out | Select-Object -Last 3
        $failed = $true
    }
}

if ($failed) {
    Write-Host ""
    Write-Host "Mindestens ein Test ist durchgefallen. Erst nachrechnen, dann Code anfassen -"
    Write-Host "in der Entwicklung waren die meisten Fehlschlaege falsche Testerwartungen."
    exit 1
}

Write-Host ""
Write-Host "Alles gruen. Naechster Schritt: das Latenzbudget messen."
Write-Host ""
Write-Host "  pip install ultralytics mss"
Write-Host "  python tools\bench_latency.py --all --detector yolov8s.pt --imgsz 768 1024 1280"
Write-Host ""
Write-Host "Details und Reihenfolge stehen in docs\handover.md"
