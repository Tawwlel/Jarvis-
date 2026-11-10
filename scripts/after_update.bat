@echo off
REM Runs after update.bat has pulled the new code (kept separate so the update can change it safely).
cd /d "%~dp0.."

echo Updating dependencies...
pip install -r requirements.txt --quiet

echo Checking voices...
python scripts\download_voices.py

echo Setting up free local AI (Ollama, light + heavy model)...
python scripts\setup_local_ai.py
if errorlevel 1 echo Local AI isn't fully set up yet - Jarvis still works online. Run update again later.

echo.
echo Done. Starting Jarvis...
start "" pythonw scripts\jarvis_app.py
pause
