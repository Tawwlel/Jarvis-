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
LIGHT, HEAVY = "gemma3:1b", "gemma3:4b"
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


def save_models(light: str | None, heavy: str | None):
    p = ROOT / "config.local.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    models = cfg.setdefault("models", {})
    changed = False
    if light and not models.get("tier0_local"):
        models["tier0_local"], changed = light, True
    if heavy and not models.get("tier0_local_heavy"):
        models["tier0_local_heavy"], changed = heavy, True
    if changed:
        p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print("Jarvis settings updated: light =", models.get("tier0_local"), "| heavy =", models.get("tier0_local_heavy"))


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
    ram = ram_gb()
    wanted = [LIGHT] + ([HEAVY] if ram >= 7.5 else [])
    if HEAVY not in wanted:
        print(f"This PC has {ram:.0f} GB of memory, so only the light model is installed.")
    got = []
    for m in wanted:
        print(f"Downloading {m} (skipped if already there)...")
        if subprocess.run([exe, "pull", m]).returncode == 0:
            got.append(m)
        else:
            print(f"Could not download {m}. Run update again later.")
    save_models(LIGHT if LIGHT in got else None, HEAVY if HEAVY in got else None)
    return 0 if len(got) == len(wanted) else 1


if __name__ == "__main__":
    sys.exit(main())
