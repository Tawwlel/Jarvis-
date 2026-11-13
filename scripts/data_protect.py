"""Keeps Jarvis's saved data (file index, WhatsApp/email copies, chats, memory) locked on THIS computer.

On Windows Pro/Business the data folder is encrypted with Windows EFS: files are encrypted on disk and only the
customer's own Windows login can open them; new files Jarvis saves there are encrypted automatically.
Windows Home has no EFS, so there the folder is locked to the customer's Windows account (other accounts on the
PC cannot open it) and we say so honestly. Keys and passwords are kept in the Windows Credential Manager."""
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
            # 2) Windows Home: lock the folder to this Windows account (and the system)
            user = os.environ.get("USERNAME", "")
            code2, out2 = _run(["icacls", str(DATA), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F",
                                "/grant:r", "SYSTEM:(OI)(CI)F", "/T", "/C", "/Q"]) if user else (1, "no user")
            st = {"method": "locked" if code2 == 0 else "none",
                  "detail": "locked to this Windows account" if code2 == 0 else "could not lock: " + out2[-200:],
                  "efs_error": out[-200:], "ts": time.time()}
    try:
        STATE.write_text(json.dumps(st), encoding="utf-8")
    except Exception:
        pass
    print("[privacy] data folder:", st.get("detail"))
    return st


def sentence() -> str:
    """What the customer is told."""
    m = state().get("method")
    if m == "efs":
        return ("Everything Jarvis saves stays on this computer, encrypted with Windows, and only your Windows "
                "login can open it.")
    if m == "locked":
        return ("Everything Jarvis saves stays on this computer, locked to your Windows account. (Your Windows "
                "edition has no built-in folder encryption; turning on BitLocker or Device Encryption protects it fully.)")
    return "Everything Jarvis saves stays on this computer."
