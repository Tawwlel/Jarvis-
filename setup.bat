@echo off
REM First-time setup for Jarvis. Run this once after cloning the repo.

echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Downloading voices (this may take a few minutes)...
python scripts\download_voices.py

echo.
if not exist config.local.json (
    copy config.example.json config.local.json
    echo Created config.local.json - open it and add your Anthropic API key.
) else (
    echo config.local.json already exists, leaving it as is.
)

echo.
echo Setup complete. Try: python scripts\listen_and_respond.py --voice amy
pause
