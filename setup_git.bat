@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo PokemonRadar - Git einmalig einrichten
echo ==============================================

git --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo [FEHLER] Git wurde nicht gefunden.
  echo Installiere zuerst Git for Windows und starte diese Datei danach erneut.
  pause
  exit /b 1
)

if exist .git (
  echo [INFO] Git ist in diesem Ordner bereits eingerichtet.
) else (
  git init
  if errorlevel 1 goto :error
)

git add .
git commit -m "PokemonRadar Grundversion"
if errorlevel 1 (
  echo.
  echo [HINWEIS] Falls Git nach Name und E-Mail fragt, fuehre diese Befehle aus:
  echo git config --global user.name "Dein Name"
  echo git config --global user.email "deine@email.ch"
  echo Danach setup_git.bat erneut starten.
  pause
  exit /b 1
)

echo.
echo [OK] Git wurde eingerichtet und die erste Version gespeichert.
echo Der Ordner data und die Datei .env werden absichtlich nicht in Git gespeichert.
pause
exit /b 0

:error
echo.
echo [FEHLER] Git konnte nicht eingerichtet werden.
pause
exit /b 1
