@echo off
REM One-click update for Jarvis. Double-click this file any time to pull
REM the latest version from GitHub and update dependencies.

echo Updating Jarvis...
git pull

echo Updating dependencies...
pip install -r requirements.txt --quiet

echo.
echo Done. Jarvis is up to date.
pause
