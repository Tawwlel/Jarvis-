"""
Computer control tools: screenshot, click, type, keys, scroll, open app.

Safety:
- The user must approve once per task before Jarvis touches mouse/keyboard.
- Dangerous key combos need their own approval.
- Hard cap on actions per task. Slam the mouse into a screen corner to abort
  (pyautogui failsafe).
- Screenshots are downscaled (~1024px wide, JPEG) to keep token cost low.
"""
import base64
import io
import os
import subprocess
import time

from tools import CTX, tool

MAX_ACTIONS_PER_TASK = 40
SCREENSHOT_WIDTH = 1024
RISKY_KEYS = {"alt+f4", "ctrl+alt+delete", "ctrl+shift+delete", "win+l", "delete", "shift+delete"}

_state = {"approved": False, "actions": 0, "scale": 1.0}


def reset():
    """Called at the start of every new user request."""
    _state.update(approved=False, actions=0)


def _confirm(question: str) -> bool:
    fn = CTX.get("confirm")
    return bool(fn(question)) if fn else False


def _gate(description: str, risky: bool = False) -> str | None:
    """Returns an error string if the action is not allowed, else None."""
    if _state["actions"] >= MAX_ACTIONS_PER_TASK:
        return "Action limit reached for this task. Stop and tell the user where you got to."
    if not _state["approved"]:
        if not _confirm("Jarvis wants to control your computer. Allow for this task?"):
            return "The user declined computer control. Stop and tell them."
        _state["approved"] = True
    if risky and not _confirm(f"Risky action: {description}. Allow?"):
        return "The user declined this action. Choose another approach or stop."
    _state["actions"] += 1
    return None


def _pg():
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.25
    return pyautogui


def _real(x, y):
    s = _state["scale"] or 1.0
    return int(x / s), int(y / s)


@tool("computer_screenshot", "Take a screenshot of the user's screen. Coordinates in later "
      "actions refer to this image. Take one before clicking and after important actions.")
def computer_screenshot():
    err = _gate("screenshot")
    if err:
        return err
    img = _pg().screenshot()
    w, h = img.size
    scale = min(1.0, SCREENSHOT_WIDTH / w)
    small = img.resize((int(w * scale), int(h * scale))).convert("RGB")
    _state["scale"] = scale
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=70)
    return {"image_b64": base64.b64encode(buf.getvalue()).decode(),
            "note": f"Screenshot {small.size[0]}x{small.size[1]}. Use these coordinates."}


@tool("computer_click", "Click at (x, y) from the latest screenshot.",
      {"x": {"type": "number"}, "y": {"type": "number"},
       "button": {"type": "string", "enum": ["left", "right"]},
       "double": {"type": "boolean"}}, ["x", "y"])
def computer_click(x, y, button="left", double=False):
    err = _gate(f"click at {x},{y}")
    if err:
        return err
    rx, ry = _real(x, y)
    _pg().click(rx, ry, button=button, clicks=2 if double else 1)
    return f"Clicked ({x},{y})."


@tool("computer_type", "Type text into the focused field. Never type passwords, card numbers "
      "or other secrets - ask the user to do that themselves.",
      {"text": {"type": "string"}}, ["text"])
def computer_type(text):
    err = _gate("type text")
    if err:
        return err
    _pg().write(text, interval=0.02)
    return "Typed."


@tool("computer_key", "Press a key or combo, e.g. 'enter', 'ctrl+c', 'alt+tab'.",
      {"keys": {"type": "string"}}, ["keys"])
def computer_key(keys):
    k = keys.lower().replace(" ", "")
    err = _gate(f"press {keys}", risky=k in RISKY_KEYS)
    if err:
        return err
    _pg().hotkey(*k.split("+"))
    return f"Pressed {keys}."


@tool("computer_scroll", "Scroll at (x, y). Positive amount scrolls up, negative down.",
      {"x": {"type": "number"}, "y": {"type": "number"}, "amount": {"type": "integer"}},
      ["x", "y", "amount"])
def computer_scroll(x, y, amount):
    err = _gate("scroll")
    if err:
        return err
    rx, ry = _real(x, y)
    _pg().moveTo(rx, ry)
    _pg().scroll(int(amount))
    return "Scrolled."


@tool("computer_open_app", "Open an application, file, or URL by name (Windows), e.g. 'notepad', "
      "'chrome', 'https://example.com'.", {"target": {"type": "string"}}, ["target"])
def computer_open_app(target):
    err = _gate(f"open {target}", risky=True)
    if err:
        return err
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", target])
    else:
        subprocess.Popen(["xdg-open", target])
    time.sleep(2)
    return f"Opened {target}."


@tool("computer_wait", "Wait a few seconds for something to load.",
      {"seconds": {"type": "number"}}, ["seconds"])
def computer_wait(seconds):
    time.sleep(min(float(seconds), 10))
    return "Waited."
