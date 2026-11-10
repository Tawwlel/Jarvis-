"""
Jarvis by Apricot Digital - the app.

    python scripts/jarvis_app.py        (or double-click start.bat)

First run shows a welcome screen; after that Jarvis lives in the tray and pops up
in the corner of the screen when called (shortcut key, "Hey Jarvis", or tray).
"""
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import audio
from config import ROOT, load_config, save_config
from memory import Memory
from tts import JarvisVoice
from ui import Bridge, Overlay, SettingsWindow, make_tray

VOICES = ["amy", "ryan", "alan", "lessac", "southern"]
LOGO = str(ROOT / "assets" / "logo.png")


def apply_values(cfg: dict, v: dict):
    """Merge the settings form into the config (blank secret fields keep what's saved)."""
    cfg.update({k: v[k] for k in ("owner_name", "assistant_names", "voice", "briefing_enabled",
                                  "briefing_time", "hotkey", "wake_word_enabled")})
    if v["api_key"]:
        cfg["anthropic_api_key"] = v["api_key"]
    if v["calendar_url"]:
        cfg.setdefault("integrations", {})["calendar_ics_url"] = v["calendar_url"]
    flags = cfg.setdefault("tools_enabled", {})
    flags["calendar"] = bool(cfg.get("integrations", {}).get("calendar_ics_url"))
    flags["computer_control"], flags["notes"] = v["computer_control"], v["notes"]
    cfg["onboarded"] = True
    mem = Memory()
    if v["owner_name"]:
        mem.remember("user_name", v["owner_name"])
    if v["working_on"]:
        mem.remember("currently_working_on", v["working_on"])


def main():
    if sys.stdout is None:  # launched without a console (pythonw): keep a log instead
        sys.stdout = sys.stderr = open(ROOT / "jarvis.log", "a", buffering=1, encoding="utf-8")

    app = QApplication(sys.argv)
    app.setApplicationName("Jarvis by Apricot Digital")
    app.setQuitOnLastWindowClosed(False)
    cfg = load_config()
    bridge = Bridge()
    name = lambda: (cfg.get("assistant_names") or ["Jarvis"])[0]
    overlay = Overlay(bridge, LOGO, name, cfg.get("overlay_corner", "bottom-right"),
                      cfg.get("overlay_caption", True))
    keep = {"assistant": None, "tray": None, "settings": None}
    mouth, mouth_lock = JarvisVoice(), threading.Lock()

    def preview(voice, text=None):
        def run():
            with mouth_lock:
                try:
                    p = mouth.speak(text or f"Hi, I'm {name()}. This is the {voice} voice.", voice_name=voice)
                    audio.play_wav(p)
                except Exception as e:
                    print("[preview]", e)
        threading.Thread(target=run, daemon=True).start()

    def start_assistant():
        from assistant import Assistant

        keep["assistant"] = Assistant(cfg, bridge)
        keep["assistant"].start()
        if QSystemTrayIcon.isSystemTrayAvailable():
            keep["tray"] = make_tray(app, LOGO, name(), lambda: keep["assistant"].triggers.put(""),
                                     lambda: open_settings(False), app.quit)

    def open_settings(first):
        win = SettingsWindow(cfg, LOGO, first, VOICES, preview,
                             working_on=Memory().get_fact("currently_working_on") or "")

        def saved(v):
            apply_values(cfg, v)
            save_config(cfg)
            if first:
                start_assistant()
                keep["assistant"].say(
                    f"All set, {cfg['owner_name'] or 'friend'}. Press {cfg.get('hotkey', 'ctrl+alt+j')} "
                    f"or say hey {name()} whenever you need me.")
            else:  # restart so shortcut, wake word and abilities take effect
                subprocess.Popen([sys.executable] + sys.argv)
                app.quit()

        win.saved.connect(saved)
        keep["settings"] = win
        win.show()
        if first:
            preview("amy", "Hi, I'm Jarvis, by Apricot Digital. Tell me your name and what you are "
                           "working on, and I'll take care of your meetings, notes and reminders. "
                           "I can even take control of your computer to make life easier.")

    if cfg.get("onboarded"):
        start_assistant()
    else:
        open_settings(True)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
