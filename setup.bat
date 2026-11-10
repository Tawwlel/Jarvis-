@echo off
REM First-time setup for Jarvis. Run once after downloading. Then Jarvis starts
REM and introduces itself - no files to edit by hand.

echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Downloading voices (this may take a few minutes)...
python scripts\download_voices.py

if not exist config.local.json copy config.example.json config.local.json >nul

echo.
echo Starting Jarvis...
python scripts\listen_and_respond.py
pause
