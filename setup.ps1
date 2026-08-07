# One-time setup for WhisperKey.
# Creates a virtual environment and installs dependencies.
#
# Usage (from the project folder):
#   powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "WhisperKey - setup" -ForegroundColor Cyan

# Find a usable Python 3 (3.9+ recommended).
$python = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $v = & $candidate --version 2>&1
        if ($v -match "Python 3") { $python = $candidate; break }
    } catch { }
}

if (-not $python) {
    Write-Host "Python 3 not found." -ForegroundColor Red
    Write-Host "Install it from https://www.python.org/downloads/ or run:"
    Write-Host "  winget install --id Python.Python.3.11 -e"
    exit 1
}

Write-Host "Using: $(& $python --version)"

$venv = Join-Path $root ".venv"
if (-not (Test-Path $venv)) {
    Write-Host "Creating virtual environment..."
    & $python -m venv $venv
} else {
    Write-Host "Virtual environment already exists."
}

$venvPy = Join-Path $venv "Scripts\python.exe"
Write-Host "Installing dependencies (this can take a few minutes)..."
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r (Join-Path $root "requirements.txt")

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Read-aloud (F10) works now using the built-in Windows voices."
Write-Host "For a much more natural neural voice, opt in to Piper:" -ForegroundColor Cyan
Write-Host "  .venv\Scripts\python.exe -m pip install piper-tts"
Write-Host "  .venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir models"
Write-Host "  (piper-tts is GPL-3.0-or-later - see the README license notes)"
Write-Host ""
Write-Host "Start it:            .\run.bat"
Write-Host "Run at login:        powershell -ExecutionPolicy Bypass -File install-startup.ps1"
Write-Host ""
Write-Host "The first launch downloads the Whisper model (~140 MB) once."
