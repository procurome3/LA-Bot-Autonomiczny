$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

Write-Host "Instalacja / aktualizacja zaleznosci Live Arena..." -ForegroundColor Cyan
& py -m pip install -r ".\requirements_livearena.txt"

if ($LASTEXITCODE -ne 0) {
    throw "pip zakonczyl sie bledem."
}

Write-Host ""
Write-Host "Test importow..." -ForegroundColor Cyan
& py -c 'import mss, cv2, numpy, pyautogui, keyboard; print("OK"); print("OpenCV:", cv2.__version__); print("MSS:", getattr(mss, "__version__", "unknown"))'

if ($LASTEXITCODE -ne 0) {
    throw "Test importow zakonczyl sie bledem."
}

Write-Host "Gotowe." -ForegroundColor Green
