# =============================================================================
# setup_projet.ps1 - Script d'initialisation du projet Roll Over Vision
# =============================================================================
# Usage : Clic droit -> "Executer avec PowerShell"
#         OU dans un terminal PowerShell : .\setup_projet.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "     INITIALISATION - Roll Over Vision Project              " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# -------------------------------------------------------------
# 1. Verification de Python
# -------------------------------------------------------------
Write-Host "[1/6] Verification de Python..." -ForegroundColor Yellow

try {
    $pythonVersion = python --version 2>&1
    Write-Host "  OK : $pythonVersion detecte." -ForegroundColor Green
} catch {
    Write-Host "  ERREUR : Python n'est pas installe ou introuvable dans le PATH." -ForegroundColor Red
    Write-Host "  -> Telechargez Python 3.10+ depuis https://www.python.org/downloads/" -ForegroundColor Red
    pause
    exit 1
}

# -------------------------------------------------------------
# 2. Verification du fichier requirements.txt
# -------------------------------------------------------------
Write-Host "[2/6] Verification de requirements.txt..." -ForegroundColor Yellow

$requirementsPath = Join-Path $PSScriptRoot "requirements.txt"
if (-not (Test-Path $requirementsPath)) {
    Write-Host "  ERREUR : Fichier requirements.txt introuvable dans : $PSScriptRoot" -ForegroundColor Red
    pause
    exit 1
}
Write-Host "  OK : requirements.txt trouve." -ForegroundColor Green
Write-Host ""

# -------------------------------------------------------------
# 3. Creation de l'environnement virtuel (.venv)
# -------------------------------------------------------------
Write-Host "[3/6] Environnement virtuel (.venv)..." -ForegroundColor Yellow

$venvPath = Join-Path $PSScriptRoot ".venv"

if (Test-Path $venvPath) {
    Write-Host "  INFO : .venv deja existant - reutilisation." -ForegroundColor Yellow
} else {
    Write-Host "  Creation de .venv en cours..." -ForegroundColor Yellow
    python -m venv $venvPath
    Write-Host "  OK : Environnement virtuel cree." -ForegroundColor Green
}
Write-Host ""

# -------------------------------------------------------------
# 4. Activation de l'environnement virtuel
# -------------------------------------------------------------
Write-Host "[4/6] Activation de l'environnement virtuel..." -ForegroundColor Yellow

$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"

try {
    & $activateScript
    Write-Host "  OK : Environnement virtuel active." -ForegroundColor Green
} catch {
    Write-Host "  AVERTISSEMENT : Impossible d'activer via Activate.ps1." -ForegroundColor Yellow
    Write-Host "  -> Tentative avec le pip du venv directement." -ForegroundColor Yellow
}
Write-Host ""

# -------------------------------------------------------------
# 5. Mise a jour de pip + Installation des dependances
# -------------------------------------------------------------
Write-Host "[5/6] Mise a jour de pip et installation des dependances..." -ForegroundColor Yellow

$pipExe = Join-Path $venvPath "Scripts\pip.exe"

& $pipExe install --upgrade pip | Out-Null
Write-Host "  OK : pip mis a jour." -ForegroundColor Green

& $pipExe install -r $requirementsPath

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "  OK : Toutes les dependances ont ete installees avec succes." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  ERREUR : Une erreur s'est produite lors de l'installation." -ForegroundColor Red
    Write-Host "  Consultez les messages ci-dessus pour plus de details." -ForegroundColor Red
    pause
    exit 1
}
Write-Host ""

# -------------------------------------------------------------
# 6. Verification du fichier .env
# -------------------------------------------------------------
Write-Host "[6/6] Verification du fichier .env..." -ForegroundColor Yellow

$envPath = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envPath)) {
    Write-Host "  AVERTISSEMENT : Fichier .env introuvable." -ForegroundColor Yellow
    Write-Host "  -> Copiez .env.example en .env et configurez vos valeurs." -ForegroundColor Yellow
} else {
    Write-Host "  OK : Fichier .env detecte." -ForegroundColor Green
}
Write-Host ""

# -------------------------------------------------------------
# Verification de Docker (optionnel)
# -------------------------------------------------------------
Write-Host "Verification de Docker (optionnel)..." -ForegroundColor Yellow
try {
    $dockerVersion = docker --version 2>&1
    Write-Host "  OK : $dockerVersion" -ForegroundColor Green
    Write-Host "  Pour demarrer les services : docker-compose up -d" -ForegroundColor Cyan
} catch {
    Write-Host "  AVERTISSEMENT : Docker non detecte." -ForegroundColor Yellow
    Write-Host "  -> Telechargez Docker Desktop : https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
}
Write-Host ""

# -------------------------------------------------------------
# Resume final
# -------------------------------------------------------------
Write-Host "============================================================" -ForegroundColor Green
Write-Host "                    SETUP TERMINE                          " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Pour lancer les services manuellement :" -ForegroundColor Cyan
Write-Host "  Activer le venv    : .venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  Lancer les services: .\demarrer_services.ps1" -ForegroundColor White
Write-Host ""
Write-Host "NOTE : Le script blender_render_simulation.py doit etre" -ForegroundColor Yellow
Write-Host "  execute depuis l'editeur de texte interne de Blender." -ForegroundColor Yellow
Write-Host ""

pause  