@echo off
REM First-time setup. Run once. Then Jarvis opens a welcome screen - no files to edit.
echo Installing dependencies...
pip install -r requirements.txt
echo Installing photo reader (optional, lets Jarvis read invoices inside photos)...
pip install rapidocr-onnxruntime
echo.
echo Downloading voices (this may take a few minutes)...
python scripts\download_voices.py
if errorlevel 1 echo Some voices did not download. Run update.bat later to retry.
if not exist config.local.json copy config.example.json config.local.json >nul
echo.
echo Starting Jarvis...
start "" pythonw scripts\jarvis_app.py
echo Jarvis is starting. You can close this window.
pause
