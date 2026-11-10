"""Global keyboard shortcut that works from any app (pynput)."""
import re

NAMED = {"ctrl", "alt", "shift", "cmd", "space", "enter", "tab", "esc"}


def to_pynput(spec: str) -> str:
    """'ctrl+alt+j' -> '<ctrl>+<alt>+j'; 'win' is treated as the Windows key."""
    out = []
    for part in re.split(r"\s*\+\s*", spec.strip().lower()):
        part = {"win": "cmd", "windows": "cmd", "control": "ctrl", "escape": "esc"}.get(part, part)
        if not part:
            continue
        if part in NAMED or re.fullmatch(r"f\d{1,2}", part):
            out.append(f"<{part}>")
        elif len(part) == 1:
            out.append(part)
        else:
            raise ValueError(f"Unknown key '{part}' in shortcut '{spec}'")
    if not out:
        raise ValueError("Empty shortcut")
    return "+".join(out)


def start_hotkey(spec: str, callback):
    from pynput import keyboard

    listener = keyboard.GlobalHotKeys({to_pynput(spec): callback})
    listener.daemon = True
    listener.start()
    return listener
