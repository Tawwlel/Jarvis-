@echo off
REM Runs after update.bat has pulled the new code (kept separate so the update can change it safely).
cd /d "%~dp0.."

echo Updating dependencies...
pip install -r requirements.txt --quiet

echo Setting up WhatsApp reader...
python -m playwright install chromium

echo Urdu reader (Tesseract)...
where tesseract >nul 2>nul || if not exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" winget install -e --id UB-Mannheim.TesseractOCR --silent --accept-package-agreements --accept-source-agreements

echo Checking voices...
python scripts\download_voices.py

echo Setting up free local AI (Ollama, small model)...
python scripts\setup_local_ai.py
if errorlevel 1 echo Local AI isn't fully set up yet - Jarvis still works online. Run update again later.

echo Closing the old Jarvis so the new version starts...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'pythonw*' -and $_.CommandLine -like '*jarvis_app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" 2>nul
timeout /t 2 /nobreak >nul

echo.
echo Done. Starting Jarvis...
start "" pythonw scripts\jarvis_app.py
pause
