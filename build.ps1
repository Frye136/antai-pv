# Construit dist\AntaiPV.exe (exécutable unique, aucune installation requise sur le poste cible).
# Prérequis : Python 3.11 (py -3.11). L'environnement virtuel est créé hors OneDrive.
$venv = "$env:LOCALAPPDATA\antai-pv-venv"
$py = "$venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    py -3.11 -m venv $venv
    & $py -m pip install --upgrade pip
}
& $py -m pip install -q -r "$PSScriptRoot\requirements.txt"

& $py "$PSScriptRoot\tests\test_core.py"
if ($LASTEXITCODE -ne 0) { throw "Tests en échec : construction annulée." }

# PyInstaller écrit ses logs sur stderr : on les capture via cmd pour que PowerShell 5.1 ne les prenne pas pour des erreurs
cmd /c "`"$py`" -m PyInstaller --noconfirm --clean --log-level WARN --workpath `"$env:LOCALAPPDATA\antai-pv-build`" --distpath `"$PSScriptRoot\dist`" `"$PSScriptRoot\AntaiPV.spec`" 2>&1"
if ($LASTEXITCODE -ne 0) { throw "Échec de PyInstaller." }
Write-Host "OK : $PSScriptRoot\dist\AntaiPV.exe"
