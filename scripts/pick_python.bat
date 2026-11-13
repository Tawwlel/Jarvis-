@echo off
REM Chooses which Python runs Jarvis. Prefers Jarvis's own python.org Python: the Microsoft Store Python makes
REM Windows show the Python logo on the taskbar instead of the Jarvis logo.
set "PY=python"
set "PYW=pythonw"
set "ORG=%LOCALAPPDATA%\Programs\Python\Python313"
if exist "%ORG%\pythonw.exe" set "PY=%ORG%\python.exe"
if exist "%ORG%\pythonw.exe" set "PYW=%ORG%\pythonw.exe"
