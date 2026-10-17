# Run GoldScalper MT5 Bridge on Windows host
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

$Python = "c:\Users\STUDO\Documents\Project\APPS\trading\AcengGold\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}

Write-Host "Starting GoldScalper MT5 Bridge using $Python..." -ForegroundColor Cyan
& $Python -m bridge.run
