"""
Jarvis by Apricot Digital - the app.

    python scripts/jarvis_app.py        (or double-click start.bat)

First run shows a welcome screen; after that Jarvis lives in the tray and pops up
in the corner of the screen when called (shortcut key, "Hey Jarvis", or tray).
"""
import json
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import audio
from config import ROOT, load_config, save_config
from memory import Memory
from providers import make_tts
from secrets_store import default_store
from ui import Bridge, ChatWindow, Overlay, SettingsWindow, make_tray

VOICES = ["amy", "ryan", "alan", "lessac", "southern"]
LOGO = str(ROOT / "assets" / "logo.png")
INSTANCE = "jarvis-by-apricot-digital"


def apply_values(cfg: dict, v: dict, store, mem):
    """Merge the settings form into the config. Keys go to the encrypted store; blank keeps what's saved."""
    cfg.update({k: v[k] for k in ("owner_name", "assistant_names", "voice", "briefing_enabled",
                                  "briefing_time", "hotkey", "wake_word_enabled", "file_roots", "language")})
    cfg.setdefault("email", {}).update(v.get("email", {}))
    for k in ("email_password", "iphone_backup_password"):
        if v.get(k):
            store.set(k, v[k])
    for name, val in v["keys"].items():
        if val:
            store.set(name, val)
    if v["calendar_url"]:
        cfg.setdefault("integrations", {})["calendar_ics_url"] = v["calendar_url"]
    flags = cfg.setdefault("tools_enabled", {})
    flags["calendar"] = bool(cfg.get("integrations", {}).get("calendar_ics_url"))
    flags["computer_control"], flags["notes"] = v["computer_control"], v["notes"]
    slots = cfg.setdefault("slots", {})
    slots.setdefault("llm", {}).update(provider=v["llm_provider"], base_url=v["llm_base_url"])
    slots.setdefault("stt", {}).update(provider=v["stt_provider"], model=v["stt_model"])
    slots.setdefault("tts", {}).update(provider=v["tts_provider"], elevenlabs_voice_id=v["elevenlabs_voice_id"],
                                       urdu_voice=v["urdu_voice"])
    models = cfg.setdefault("models", {})
    if v["model_fast"]:
        models["tier1_cloud"] = v["model_fast"]
    if v["model_strong"]:
        models["tier2_cloud"] = v["model_strong"]
    models["tier0_local"] = v["model_local"] or None
    models["tier0_local_heavy"] = None
    priv = cfg.setdefault("privacy", {})
    priv.update(mode=v["privacy_mode"], private_terms=v["private_terms"], local_only_terms=v["local_only_terms"])
    cfg["onboarded"] = True
    facts = {"user_name": v["owner_name"], "currently_working_on": v["working_on"],
             "profile.role": v["role"], "profile.company": v["company"], "profile.website": v["website"]}
    for k, ans in v["role_answers"].items():
        facts[f"q.{k}"] = ans
    for k, val in facts.items():
        if val:
            mem.remember(k, val)


def load_profile(mem) -> dict:
    keys = {"working_on": "currently_working_on", "role": "profile.role",
            "company": "profile.company", "website": "profile.website"}
    p = {k: mem.get_fact(f) or "" for k, f in keys.items()}
    for key in ("institution", "field", "courses", "lecture_language", "industry", "team_size",
                "priorities", "job_title", "team", "main_projects"):
        p[f"q.{key}"] = mem.get_fact(f"q.{key}") or ""
    return p


def load_roles() -> dict:
    p = ROOT / "roles.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"roles": {}}


def migrate_legacy_key(store):
    """Older installs kept the API key in config.local.json: move it into the encrypted store."""
    p = ROOT / "config.local.json"
    if not p.exists():
        return
    raw = json.loads(p.read_text(encoding="utf-8"))
    key = raw.pop("anthropic_api_key", None)
    if key:
        if not store.has("anthropic"):
            store.set("anthropic", key)
        p.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def main():
    if sys.stdout is None:  # launched without a console (pythonw): keep a log instead
        sys.stdout = sys.stderr = open(ROOT / "jarvis.log", "a", buffering=1, encoding="utf-8")
    else:  # a Windows console can't print Urdu by default - never crash on it
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    app = QApplication(sys.argv)
    app.setApplicationName("Jarvis by Apricot Digital")
    app.setQuitOnLastWindowClosed(False)

    # Only one Jarvis at a time: a second copy would load every model again and run out of memory.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    probe = QLocalSocket()
    probe.connectToServer(INSTANCE)
    if probe.waitForConnected(500):
        probe.write(b"show")
        probe.waitForBytesWritten(500)
        print("[app] Jarvis is already running; showing it instead.")
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(QMessageBox.Information, "Jarvis by Apricot Digital",
                          "Jarvis is already running.\n\nLook for the red logo near the clock (click the ^ arrow "
                          "if it's hidden). I've opened its chat window for you.")
        box.setStyleSheet("QWidget{background:#0a0d14;color:#e6ebf5;font-family:'Segoe UI'}"
                          "QPushButton{background:#ff3030;color:white;border:none;border-radius:6px;padding:7px 18px}")
        box.exec()
        return
    QLocalServer.removeServer(INSTANCE)
    server = QLocalServer()
    server.listen(INSTANCE)
    store = default_store()
    migrate_legacy_key(store)
    cfg = load_config()
    mem = Memory()
    bridge = Bridge()
    name = lambda: (cfg.get("assistant_names") or ["Jarvis"])[0]
    overlay = Overlay(bridge, LOGO, name, cfg.get("overlay_corner", "bottom-right"),
                      cfg.get("overlay_caption", True))
    keep = {"assistant": None, "tray": None, "settings": None, "chat": None}
    mouth, mouth_lock = make_tts(cfg, store), threading.Lock()

    def preview(voice, text=None):
        def run():
            with mouth_lock:
                try:
                    p = mouth.speak(text or f"Hi, I'm {name()}. This is the {voice} voice.", voice_name=voice)
                    audio.play_wav(p)
                except Exception as e:
                    print("[preview]", e)
        threading.Thread(target=run, daemon=True).start()

    def open_chat():
        if keep["chat"] is None:
            keep["chat"] = ChatWindow(bridge, name())
            keep["chat"].submitted.connect(
                lambda t, sp: keep["assistant"].submit_text(t, sp) if keep["assistant"]
                else keep["chat"].add("assistant", "One moment, I'm still starting up."))
        keep["chat"].show()
        keep["chat"].raise_()

    def run_selftest():
        open_chat()

        def work():
            try:
                import selftest
                selftest.run(cfg, lambda t: bridge.chat("assistant", t))
            except Exception as e:
                import traceback
                traceback.print_exc()
                bridge.chat("assistant", f"The test stopped: {e}")
        threading.Thread(target=work, daemon=True).start()

    def run_speedtest():
        open_chat()
        if not keep["assistant"]:
            bridge.chat("assistant", "I'm still starting up. Try again in a moment.")
            return

        def work():
            try:
                import selftest
                selftest.speed_test(keep["assistant"], lambda t: bridge.chat("assistant", t))
            except Exception as e:
                import traceback
                traceback.print_exc()
                bridge.chat("assistant", f"The speed test stopped: {e}")
        threading.Thread(target=work, daemon=True).start()

    def start_assistant(welcome: str | None = None):
        """Loads models on a background thread so the window never freezes (first run downloads them)."""
        def work():
            try:
                from assistant import Assistant

                bridge.chat("assistant", "Getting ready... the first start downloads the listening model, "
                                         "so this can take a few minutes.")
                a = Assistant(cfg, bridge, store)
                a.start()
                keep["assistant"] = a
                bridge.chat("assistant", f"I'm ready. Press {cfg.get('hotkey', 'ctrl+alt+j')} or say hey {name()}.")
                if welcome:
                    a.say(welcome)
            except Exception as e:
                import traceback
                traceback.print_exc()
                bridge.chat("assistant", f"I couldn't start: {e}")

        if QSystemTrayIcon.isSystemTrayAvailable() and keep["tray"] is None:
            ask = lambda: keep["assistant"] and keep["assistant"].talk()
            keep["tray"] = make_tray(app, LOGO, name(), ask, open_chat, lambda: open_settings(False), app.quit,
                                     on_selftest=run_selftest, on_speedtest=run_speedtest)
        open_chat()
        threading.Thread(target=work, daemon=True).start()

    def open_settings(first):
        win = SettingsWindow(cfg, LOGO, first, VOICES, preview, store=store,
                             roles=load_roles(), profile=load_profile(mem))

        def saved(v):
            apply_values(cfg, v, store, mem)
            save_config(cfg)
            if first:
                start_assistant(f"All set, {cfg['owner_name'] or 'friend'}. Press {cfg.get('hotkey', 'ctrl+alt+j')} "
                                f"or say hey {name()} whenever you need me.")
            else:  # restart so shortcut, wake word, slots and abilities take effect
                subprocess.Popen([sys.executable] + sys.argv)
                app.quit()

        win.saved.connect(saved)
        keep["settings"] = win
        win.show()
        if first:
            preview("amy", "Hi, I'm Jarvis, by Apricot Digital. Tell me your name and what you are "
                           "working on, and I'll take care of your meetings, notes and reminders. "
                           "I can even take control of your computer to make life easier.")

    def on_second_copy():
        conn = server.nextPendingConnection()
        if conn:
            conn.readAll()
        open_chat()
        keep["chat"].activateWindow()
        if keep["tray"]:
            keep["tray"].showMessage("Jarvis", "Jarvis is already running.", QSystemTrayIcon.Information, 3000)

    server.newConnection.connect(on_second_copy)

    # ----- automatic updates (zip installs): check at start and every 6 hours -----
    from PySide6.QtCore import QObject, QTimer, Signal
    import updater

    class _Upd(QObject):
        done = Signal(str)
    upd = _Upd()

    def restart_now():
        flags = 0x00000008 if sys.platform == "win32" else 0  # detached
        subprocess.Popen([sys.executable] + sys.argv, creationflags=flags)
        app.quit()

    def on_updated(note):
        msg = "I just updated myself" + (f" ({note})" if note else "") + ". Restarting in a few seconds..."
        bridge.chat("assistant", msg)
        if keep["tray"]:
            keep["tray"].showMessage("Jarvis", "Updated - restarting.", QSystemTrayIcon.Information, 3000)
        QTimer.singleShot(8000, restart_now)

    upd.done.connect(lambda r: on_updated(r) if r != "none" else None)

    def check_updates():
        def work():
            if updater.check_and_update(print) == "updated":
                upd.done.emit(updater.whats_new())
        threading.Thread(target=work, daemon=True).start()

    if updater.enabled():
        QTimer.singleShot(20000, check_updates)
        tick = QTimer(app)
        tick.timeout.connect(check_updates)
        tick.start(6 * 3600 * 1000)
        keep["upd_timer"] = tick

    if cfg.get("onboarded"):
        start_assistant()
    else:
        open_settings(True)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
