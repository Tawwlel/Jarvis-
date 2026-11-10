"""
Automatic updates. Works for the downloaded zip install (no git needed).

Every few hours Jarvis asks GitHub whether the main branch has a newer version. If so it downloads the
new code, copies it over the app files (never touching your settings, data, voices or models), installs
any new libraries, and tells the app to restart.

Installs made with git (developers) are left to update.bat.
"""
import io
import json
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from config import ROOT

REPO = "Tawwlel/Jarvis-"
BRANCH = "main"
VERSION_FILE = ROOT / "VERSION"
KEEP = {"data", "audio", "whisper_model", "config.local.json", "jarvis.log", "VERSION", ".git", "wa_profile"}
UA = {"User-Agent": "Jarvis-updater"}


def current() -> str:
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        return ""


def latest() -> str:
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}", headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["sha"]


def enabled() -> bool:
    return not (ROOT / ".git").exists()  # git installs update through update.bat


def _download() -> bytes:
    req = urllib.request.Request(f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip", headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def check_and_update(log=print) -> str:
    """Returns 'none' (up to date / disabled / offline), or 'updated' when new files were installed."""
    if not enabled():
        return "none"
    try:
        new = latest()
    except Exception as e:  # offline or rate limited: try again later
        log(f"[update] check failed: {e}")
        return "none"
    if new == current():
        return "none"
    log(f"[update] new version {new[:7]} found, downloading...")
    try:
        data = _download()
        old_req = (ROOT / "requirements.txt").read_text() if (ROOT / "requirements.txt").exists() else ""
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            top = z.namelist()[0].split("/")[0] + "/"
            for info in z.infolist():
                rel = info.filename[len(top):]
                if not rel or info.is_dir():
                    continue
                first = Path(rel).parts[0]
                if first in KEEP or first.startswith(".") or first == "tests":
                    continue
                dest = ROOT / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(info))
        new_req = (ROOT / "requirements.txt").read_text() if (ROOT / "requirements.txt").exists() else ""
        if new_req != old_req:
            log("[update] installing new libraries...")
            flags = 0x08000000 if sys.platform == "win32" else 0  # no console window
            subprocess.run([sys.executable.replace("pythonw", "python"), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"), "--quiet",
                            "--disable-pip-version-check"], creationflags=flags, timeout=900)
        VERSION_FILE.write_text(new)
        log("[update] installed.")
        return "updated"
    except Exception as e:
        log(f"[update] failed, keeping the current version: {e}")
        return "none"


def whats_new() -> str:
    """One line for the user: the newest commit message."""
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}", headers=UA)
        with urllib.request.urlopen(req, timeout=10) as r:
            msg = json.load(r)["commit"]["message"].splitlines()[0]
        return re.sub(r"\s+", " ", msg)[:100]
    except Exception:
        return ""
