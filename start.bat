@echo off
REM Everyday launcher: starts Jarvis in the background (tray icon + corner pop-up).
REM If something goes wrong, check jarvis.log in this folder.
cd /d "%~dp0"
call scripts\pick_python.bat
start "" "%PYW%" scripts\jarvis_app.py
