"""Jarvis.exe - tiny launcher. Starts the bundled Python runtime with the Jarvis app (no console window)."""
import ctypes
import subprocess
import sys
from pathlib import Path

here = Path(sys.executable).resolve().parent
py = here / "runtime" / "pythonw.exe"
script = here / "app" / "scripts" / "jarvis_app.py"
if not py.exists() or not script.exists():
    ctypes.windll.user32.MessageBoxW(0, "Jarvis files are missing. Please extract the whole Jarvis folder from the "
                                        "zip (don't run it from inside the zip) and try again.", "Jarvis", 0x10)
    sys.exit(1)
subprocess.Popen([str(py), str(script)], cwd=str(here / "app"), creationflags=0x00000008 | 0x08000000)
