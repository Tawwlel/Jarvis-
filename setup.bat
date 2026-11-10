@echo off
REM First-time setup. Run once. Then Jarvis opens a welcome screen - no files to edit.
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Downloading voices (this may take a few minutes)...
python scripts\download_voices.py
if not exist config.local.json copy config.example.json config.local.json >nul
echo.
echo Starting Jarvis...
start "" pythonw scripts\jarvis_app.py
echo Jarvis is starting. You can close this window.
pause
