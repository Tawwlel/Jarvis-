@echo off
REM One-click update for Jarvis. Double-click any time: pulls the latest version,
REM updates dependencies, fetches any missing voices and starts Jarvis.

echo Updating Jarvis...
git pull
call "%~dp0scripts\after_update.bat"
exit /b
