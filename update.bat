@echo off
REM One-click update for Jarvis. Double-click any time: pulls the latest version,
REM updates dependencies, fetches any missing voices and starts Jarvis.

echo Updating Jarvis...
git pull

echo Updating dependencies...
pip install -r requirements.txt --quiet

echo Checking voices...
python scripts\download_voices.py

echo.
echo Done. Starting Jarvis...
start "" pythonw scripts\jarvis_app.py
pause
