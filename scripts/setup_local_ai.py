"""
Sets up free local AI for Jarvis: installs Ollama (if missing), downloads a light and a heavy
model, and fills them into Jarvis's settings. Safe to run again: finished steps are skipped.

    python scripts/setup_local_ai.py            (called by setup.bat and update.bat)

Skip it with:  set JARVIS_NO_LOCAL_AI=1
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIGHT = "gemma3:1b"
OLD_HEAVY = "gemma3:4b"  # no longer used: too big for 8 GB laptops
HOST = "http://localhost:11434"


def ram_gb() -> float:
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullTotalPhys / 1024 ** 3
    except Exception:
        return 16.0


def find_ollama() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
              Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Ollama" / "ollama.exe"):
        if p.exists():
            return str(p)
    return None


def install_ollama() -> str | None:
    if not shutil.which("winget"):
        print("Can't install Ollama automatically (winget is missing). Install it from https://ollama.com/download")
        return None
    print("Installing Ollama (free local AI)... a Windows prompt may ask for permission.")
    subprocess.run(["winget", "install", "-e", "--id", "Ollama.Ollama", "--silent",
                    "--accept-package-agreements", "--accept-source-agreements"])
    for _ in range(10):
        exe = find_ollama()
        if exe:
            return exe
        time.sleep(2)
    print("Ollama didn't finish installing. Install it from https://ollama.com/download and run update again.")
    return None


def server_up() -> bool:
    try:
        import requests
        return requests.get(HOST + "/api/tags", timeout=2).ok
    except Exception:
        return False


def start_server(exe: str) -> bool:
    if server_up():
        return True
    flags = 0x00000008 | 0x08000000 if os.name == "nt" else 0  # detached, no window
    subprocess.Popen([exe, "serve"], creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if server_up():
            return True
        time.sleep(1)
    return False


def save_models(light: str | None):
    p = ROOT / "config.local.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    models = cfg.setdefault("models", {})
    changed = False
    if light and not models.get("tier0_local"):
        models["tier0_local"], changed = light, True
    if models.get("tier0_local_heavy"):
        models["tier0_local_heavy"], changed = None, True
    if changed:
        p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print("Jarvis settings updated: local model =", models.get("tier0_local"))


def main() -> int:
    if os.environ.get("JARVIS_NO_LOCAL_AI"):
        return 0
    print("\n=== Local AI (free, runs on this PC) ===")
    exe = find_ollama() or install_ollama()
    if not exe:
        return 1
    if not start_server(exe):
        print("Ollama is installed but not running. Open 'Ollama' from the Start menu, then run update again.")
        return 1
    # remove the big model from earlier versions (frees about 3 GB of disk and any memory it holds)
    installed = subprocess.run([exe, "list"], capture_output=True, text=True).stdout
    if OLD_HEAVY in installed:
        print(f"Removing {OLD_HEAVY} (too big for this setup)...")
        subprocess.run([exe, "rm", OLD_HEAVY])
    print(f"Downloading {LIGHT} (skipped if already there)...")
    ok = subprocess.run([exe, "pull", LIGHT]).returncode == 0
    if not ok:
        print(f"Could not download {LIGHT}. Run update again later.")
    save_models(LIGHT if ok else None)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
