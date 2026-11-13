"""Keeps Jarvis's saved data (file index, WhatsApp/email copies, chats, memory) locked on THIS computer.

On Windows Pro/Business the data folder is encrypted with Windows EFS: files are encrypted on disk and only the
customer's own Windows login can open them; new files Jarvis saves there are encrypted automatically.
Windows Home has no EFS; there we say so honestly (folder permissions are left alone: changing them locked Jarvis
out of its own data). Keys and passwords are kept in the Windows Credential Manager."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
STATE = DATA / "protection.json"
_NO_WINDOW = 0x08000000


def state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run(args, timeout=600) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW if sys.platform == "win32" else 0)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def protect(force: bool = False) -> dict:
    """Encrypt (or at least lock) the data folder. Safe to call often: does the work once, then only new files."""
    DATA.mkdir(exist_ok=True)
    st = state()
    if st.get("method") and not force and time.time() - st.get("ts", 0) < 7 * 86400:
        return st
    if sys.platform != "win32":
        st = {"method": "none", "detail": "not Windows", "ts": time.time()}
    else:
        # 1) Windows EFS: encrypts the folder and everything in it, now and later
        code, out = _run(["cipher", "/e", "/s:" + str(DATA)])
        if code == 0 and "error" not in out.lower():
            st = {"method": "efs", "detail": "encrypted with Windows EFS", "ts": time.time()}
        else:
            # Windows Home has no EFS. We do NOT change folder permissions: that locked Jarvis out of its own data.
            st = {"method": "none", "detail": "no EFS on this Windows edition", "efs_error": out[-200:], "ts": time.time()}
    try:
        STATE.write_text(json.dumps(st), encoding="utf-8")
    except Exception:
        pass
    print("[privacy] data folder:", st.get("detail"))
    return st


def repair() -> str:
    """Undo the old 'lock to this account' step if it locked Jarvis out of its own data folder (Permission denied).
    Called at every start, before anything reads the data folder."""
    if sys.platform != "win32" or not DATA.exists():
        return "ok"
    probe = DATA / ".write_test"
    try:
        probe.write_text("1")
        probe.unlink()
        if state().get("method") != "locked":
            return "ok"
    except Exception:
        pass
    user = os.environ.get("USERNAME", "")
    code, out = _run(["icacls", str(DATA), "/reset", "/T", "/C", "/Q"])
    if user:
        _run(["icacls", str(DATA), "/grant", f"{user}:(OI)(CI)F", "/T", "/C", "/Q"])
    try:
        STATE.write_text(json.dumps({"method": "none", "detail": "access restored", "ts": time.time()}), encoding="utf-8")
        probe.write_text("1")
        probe.unlink()
        print("[privacy] data folder access restored")
        return "repaired"
    except Exception as e:
        print("[privacy] could not restore access:", e, out[-200:])
        return f"failed: {e}"


def sentence() -> str:
    """What the customer is told."""
    m = state().get("method")
    if m == "efs":
        return ("Everything Jarvis saves stays on this computer, encrypted with Windows, and only your Windows "
                "login can open it.")
    if m == "none" and sys.platform == "win32":
        return ("Everything Jarvis saves stays on this computer. (Your Windows edition has no folder encryption; "
                "turning on Device Encryption or BitLocker in Windows Settings protects it fully.)")
    return "Everything Jarvis saves stays on this computer."
