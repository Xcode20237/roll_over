@echo off
echo =========================================================
echo       LANCEMENT DU SYSTEME ROLL OVER VISION (CMD)        
echo =========================================================
echo.

:: Vérification de l'environnement virtuel
if not exist .venv\Scripts\activate.bat goto ERREUR_VENV
goto SUITE_VENV

:ERREUR_VENV
echo [ERREUR] L'environnement virtuel .venv n'existe pas.
echo Veuillez d'abord lancer l'installation (setup_projet.ps1).
pause
exit /b

:SUITE_VENV

echo Demarrage des terminaux pour chaque service...
echo (Ne fermez pas cette fenetre tant que les services demarrent)
echo.

:: Fix pour les imports locaux (module 'shared')
set PYTHONPATH=%cd%

:: 1. Dashboard Web
start "Dashboard Web" cmd /k ".\.venv\Scripts\activate.bat && python dashboard\main_dashboard.py"
:: Petite pause pour laisser le dashboard demarrer avant les autres (optionnel)
timeout /t 2 /nobreak >nul

:: 2. Orchestrateur
start "Orchestrateur" cmd /k ".\.venv\Scripts\activate.bat && python services\service_switch_orchestrateur.py"

:: 3. Moteurs d'inspection (Algorithmes)
start "Moteur Colorimetrique" cmd /k ".\.venv\Scripts\activate.bat && python services\service_colorimetrique.py"
start "Moteur Gradient" cmd /k ".\.venv\Scripts\activate.bat && python services\service_gradient.py"
start "Moteur Geometrique" cmd /k ".\.venv\Scripts\activate.bat && python services\service_geometrique.py"
start "Moteur Check Position" cmd /k ".\.venv\Scripts\activate.bat && python services\service_check_position.py"
start "Moteur Fusion IA" cmd /k ".\.venv\Scripts\activate.bat && python services\service_fusion_ia.py"
start "Moteur IA Pretraitement" cmd /k ".\.venv\Scripts\activate.bat && python services\service_ia.py"

:: 4. Le Juge Final
start "Juge Final" cmd /k ".\.venv\Scripts\activate.bat && python services\service_decision_finale.py"

:: 5. Acquisition Camera (Lancer en dernier)
start "Acquisition test" cmd /k ".\.venv\Scripts\activate.bat && python services\service_acquisition_test.py"


echo.
echo =========================================================
echo        TOUS LES SERVICES ONT ETE LANCES !                
echo  Vous pouvez reduire les fenetres d'invite de commandes. 
echo =========================================================
echo.
pause
