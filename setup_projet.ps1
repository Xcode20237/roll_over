# =============================================================================
# setup_projet.ps1 — Script d'initialisation du projet Roll Over Vision
# =============================================================================
# Usage : Clic droit → "Exécuter avec PowerShell"
#         OU dans un terminal PowerShell : .\setup_projet.ps1
#         OU avec un Python spécifique : .\setup_projet.ps1 -PythonExe "C:\chemin\vers\python.exe"
# =============================================================================

param (
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║      INITIALISATION — Roll Over Vision Project           ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 1. Vérification de Python
# ─────────────────────────────────────────────────────────────
Write-Host "🔍 Vérification de Python..." -ForegroundColor Yellow

try {
    $pythonVersion = & $PythonExe --version 2>&1
    Write-Host "   ✅ $pythonVersion détecté (via $PythonExe)." -ForegroundColor Green
} catch {
    Write-Host "   ❌ Python n'est pas installé ou introuvable dans le PATH." -ForegroundColor Red
    Write-Host "      → Téléchargez Python 3.10+ depuis https://www.python.org/downloads/" -ForegroundColor Red
    pause
    exit 1
}

# ─────────────────────────────────────────────────────────────
# 2. Vérification du fichier requirements.txt
# ─────────────────────────────────────────────────────────────
$requirementsPath = Join-Path $PSScriptRoot "requirements.txt"
if (-not (Test-Path $requirementsPath)) {
    Write-Host "   ❌ Fichier requirements.txt introuvable dans : $PSScriptRoot" -ForegroundColor Red
    pause
    exit 1
}
Write-Host "   ✅ requirements.txt trouvé." -ForegroundColor Green
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 3. Création de l'environnement virtuel (.venv)
# ─────────────────────────────────────────────────────────────
$venvPath = Join-Path $PSScriptRoot ".venv"

if (Test-Path $venvPath) {
    Write-Host "⚙️  Environnement virtuel (.venv) déjà existant — réutilisation." -ForegroundColor Yellow
} else {
    Write-Host "⚙️  Création de l'environnement virtuel (.venv)..." -ForegroundColor Yellow
    & $PythonExe -m venv $venvPath
    Write-Host "   ✅ Environnement virtuel créé." -ForegroundColor Green
}
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 4. Activation de l'environnement virtuel
# ─────────────────────────────────────────────────────────────
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"

Write-Host "⚙️  Activation de l'environnement virtuel..." -ForegroundColor Yellow
try {
    & $activateScript
    Write-Host "   ✅ Environnement virtuel activé." -ForegroundColor Green
} catch {
    Write-Host "   ⚠️  Impossible d'activer via Activate.ps1 (politiques d'exécution)." -ForegroundColor Yellow
    Write-Host "      → Tentative avec le pip du venv directement." -ForegroundColor Yellow
}
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 5. Mise à jour de pip
# ─────────────────────────────────────────────────────────────
$pythonVenvExe = Join-Path $venvPath "Scripts\python.exe"

Write-Host "📦 Mise à jour de pip..." -ForegroundColor Yellow
& $pythonVenvExe -m pip install --upgrade pip | Out-Null
Write-Host "   ✅ pip mis à jour." -ForegroundColor Green
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 6. Installation des dépendances
# ─────────────────────────────────────────────────────────────
Write-Host "📦 Installation des dépendances depuis requirements.txt..." -ForegroundColor Yellow
Write-Host ""

& $pythonVenvExe -m pip install -r $requirementsPath

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "   ✅ Toutes les dépendances ont été installées avec succès." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "   ❌ Une erreur s'est produite lors de l'installation des dépendances." -ForegroundColor Red
    Write-Host "      Consultez les messages ci-dessus pour plus de détails." -ForegroundColor Red
    pause
    exit 1
}
Write-Host ""

Write-Host "📦 Installation du projet en mode éditable..." -ForegroundColor Yellow
& $pythonVenvExe -m pip install -e .

if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ Projet installé en mode éditable avec succès." -ForegroundColor Green
} else {
    Write-Host "   ❌ Erreur lors de l'installation du projet." -ForegroundColor Red
}
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 7. Vérification du fichier .env
# ─────────────────────────────────────────────────────────────
$envPath = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envPath)) {
    Write-Host "⚠️  Fichier .env introuvable." -ForegroundColor Yellow
    Write-Host "   → Copiez le fichier .env.example en .env et configurez vos valeurs." -ForegroundColor Yellow
} else {
    Write-Host "✅ Fichier .env détecté." -ForegroundColor Green
}
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 8. Vérification de Docker (pour MinIO et MQTT Broker)
# ─────────────────────────────────────────────────────────────
Write-Host "🐳 Vérification de Docker..." -ForegroundColor Yellow
try {
    $dockerVersion = docker --version 2>&1
    Write-Host "   ✅ $dockerVersion" -ForegroundColor Green
    Write-Host ""
    Write-Host "   💡 Pour démarrer les services Docker (MinIO + MQTT Broker) :" -ForegroundColor Cyan
    Write-Host "      docker-compose up -d" -ForegroundColor White
} catch {
    Write-Host "   ⚠️  Docker non détecté. Les services MinIO et MQTT ne seront pas disponibles." -ForegroundColor Yellow
    Write-Host "      → Téléchargez Docker Desktop depuis https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
}
Write-Host ""

# ─────────────────────────────────────────────────────────────
# 9. Résumé final
# ─────────────────────────────────────────────────────────────
Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║                  ✅ SETUP TERMINÉ                        ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "📋 Pour lancer les services manuellement :" -ForegroundColor Cyan
Write-Host "   Activer le venv  : .venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "   Lancer les services : .\demarrer_services.ps1" -ForegroundColor White
Write-Host ""
Write-Host "⚠️  Note : Le script 'blender_render_simulation.py' doit être" -ForegroundColor Yellow
Write-Host "   exécuté depuis l'éditeur de texte interne de Blender." -ForegroundColor Yellow
Write-Host ""

pause
