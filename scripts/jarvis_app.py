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
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import audio
from config import ROOT, load_config, save_config
from memory import Memory
from providers import make_tts
from secrets_store import default_store
from ui import WelcomeWindow, Bridge, ChatWindow, Overlay, PhoneWindow, SettingsWindow, make_tray

VOICES = ["amy", "ryan", "alan", "lessac", "southern"]
LOGO = str(ROOT / "assets" / "logo.png")
INSTANCE = "jarvis-by-apricot-digital"


def apply_values(cfg: dict, v: dict, store, mem):
    """Merge the settings form into the config. Keys go to the encrypted store; blank keeps what's saved."""
    cfg.update({k: v[k] for k in ("owner_name", "assistant_names", "voice", "briefing_enabled",
                                  "briefing_time", "hotkey", "wake_word_enabled", "file_roots", "language")})
    cfg.setdefault("email", {}).update(v.get("email", {}))
    cfg.setdefault("backup", {}).update(v.get("backup", {}))
    for k in ("email_password", "iphone_backup_password", "backup_password"):
        if v.get(k) and (k != "backup_password" or len(v[k]) >= 6):
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
        class _Stamped:  # every log line starts with the time, so slow answers and scans can be traced
            def __init__(self, f): self.f, self.new = f, True
            def write(self, t):
                import time as _t
                for part in t.splitlines(True):
                    if self.new and part.strip():
                        self.f.write(_t.strftime("%H:%M:%S "))
                    self.f.write(part)
                    self.new = part.endswith("\n")
            def flush(self): self.f.flush()
            def isatty(self): return False
        sys.stdout = sys.stderr = _Stamped(open(ROOT / "jarvis.log", "a", buffering=1, encoding="utf-8"))
    else:  # a Windows console can't print Urdu by default - never crash on it
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    if sys.platform == "win32":
        try:  # own identity for the taskbar: shows the Jarvis logo instead of Python's, and groups the windows
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ApricotDigital.Jarvis")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Jarvis by Apricot Digital")
    import ui as _ui
    _ui.load_fonts()
    _ui.set_theme(load_config().get("ui_theme", "dark"), app)
    from PySide6.QtGui import QIcon
    if Path(LOGO).exists():
        app.setWindowIcon(QIcon(LOGO))  # every window (chat, settings, history, phone) wears the logo
    app.setQuitOnLastWindowClosed(False)

    # Only one Jarvis at a time: a second copy would load every model again and run out of memory.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    import os
    import time as _time
    if os.environ.pop("JARVIS_RESTARTING", None):  # we were started by a restart: let the old copy finish closing
        for _ in range(40):
            p = QLocalSocket()
            p.connectToServer(INSTANCE)
            if not p.waitForConnected(200):
                break
            p.abort()
            _time.sleep(0.25)
    probe = QLocalSocket()
    probe.connectToServer(INSTANCE)
    if probe.waitForConnected(500):
        probe.write(b"show")
        probe.waitForBytesWritten(500)
        print("[app] Jarvis is already running; showing it instead.")
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(QMessageBox.Information, "Jarvis by Apricot Digital",
                          "Jarvis is already running.\n\nLook for the Jarvis logo near the clock (click the ^ arrow "
                          "if it's hidden). I've opened its chat window for you.")
        box.setStyleSheet("QWidget{background:#120706;color:#ffe3b8;font-family:'Bahnschrift','Segoe UI'}"
                          "QPushButton{background:transparent;color:#ffb347;border:1px solid #ffb347;padding:7px 18px}")
        box.exec()
        return
    QLocalServer.removeServer(INSTANCE)
    server = QLocalServer()
    server.listen(INSTANCE)
    try:  # a backup restored just before this start: move its files into place before anything opens them
        import backup
        backup.apply_pending()
    except Exception as e:
        print("[backup] could not finish the restore:", e)
    store = default_store()
    migrate_legacy_key(store)
    cfg = load_config()
    mem = Memory()
    bridge = Bridge()
    bridge.recorder = mem.add_chat  # every chat line is kept, so all earlier chats can be read later
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
            keep["chat"] = ChatWindow(bridge, name(), mem)
            keep["chat"].submitted.connect(
                lambda t, sp: keep["assistant"].submit_text(t, sp) if keep["assistant"]
                else keep["chat"].add("assistant", "One moment, I'm still starting up."))
            keep["chat"].action.connect(chat_action)
            keep["chat"].talk.connect(lambda: keep["assistant"] and threading.Thread(target=keep["assistant"].talk, daemon=True).start())
            keep["chat"].theme_changed.connect(lambda t: save_config({**load_config(), "ui_theme": t}))
        keep["chat"].show()
        keep["chat"].raise_()

    def chat_action(a):
        """A button on the chat window's toolbar."""
        if a == "history":
            keep["chat"].show_history()
        elif a == "settings":
            open_settings(False)
        elif a == "phone":
            (keep.get("connect_phone") or (lambda: keep["chat"].add("assistant", "The phone link isn't ready yet.")))()
        elif keep.get("tray_ask"):
            keep["tray_ask"](a)
        elif a.startswith("tool:"):
            keep["chat"].add("assistant", "That button needs the tray icon; use the chat instead.")
        elif keep["assistant"]:
            keep["chat"].add("user", a)
            keep["assistant"].submit_text(a, False)

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
            def tray_ask(text):
                """Tray shortcuts. 'tool:<name>' runs that tool directly (works without the online brain);
                anything else behaves exactly like typing the sentence in the chat."""
                open_chat()
                if text.startswith("tool:"):
                    tool_name = text[5:]
                    waits = {"scan_everything": "Starting the scan of your computer and WhatsApp...",
                             "whatsapp_link": "Opening WhatsApp. On your phone: WhatsApp > Settings > Linked devices > "
                                              "Link a device, then point the phone at the code on the screen.",
                             "whatsapp_sync": "Checking WhatsApp for new files. This can take a minute or two...",
                             "iphone_whatsapp_import": "Looking for an iPhone backup on this laptop...",
                             "backup_now": "Making a full backup. This can take a minute if you have many WhatsApp files..."}
                    bridge.chat("assistant", waits.get(tool_name, "Working on it..."))

                    def work():
                        import tools
                        tools.enabled_tools(cfg)  # make sure the tool is registered even before the brain is up
                        tools.CTX.setdefault("cfg", cfg)
                        tools.CTX.setdefault("notify", lambda t: bridge.chat("assistant", t))
                        threading.current_thread().inline = True  # this worker may wait: run the job right here
                        bridge.chat("assistant", str(tools.run_tool(tool_name, {})))
                    threading.Thread(target=work, daemon=True).start()
                elif keep["assistant"]:
                    keep["chat"].add("user", text)
                    keep["assistant"].submit_text(text, False)
                else:
                    keep["chat"].add("assistant", "One moment, I'm still starting up.")
            class _PhoneSig(QObject):
                ready = Signal(str, str, int)
                fail = Signal(str)
            psig = _PhoneSig()
            psig.ready.connect(lambda l, c, m: (keep.__setitem__("phonewin", PhoneWindow(l, c, m)), keep["phonewin"].show()))
            psig.fail.connect(lambda e: bridge.chat("assistant", e))

            def connect_phone():
                def go():
                    try:
                        import phone_bridge
                        d = phone_bridge.start_pairing(cfg)
                        if phone_bridge.AGENT:
                            phone_bridge.AGENT.poke()
                        psig.ready.emit(d["link"], d["code"], d["expires_in"] // 60)
                    except Exception as e:
                        psig.fail.emit(f"I couldn't start the phone link: {e}")
                threading.Thread(target=go, daemon=True).start()
            keep["tray_ask"], keep["connect_phone"] = tray_ask, connect_phone
            keep["tray"] = make_tray(app, LOGO, name(), ask, open_chat, lambda: open_settings(False), app.quit,
                                     on_selftest=run_selftest, on_speedtest=run_speedtest, on_ask=tray_ask,
                                     on_history=lambda: (open_chat(), keep["chat"].show_history()),
                                     on_phone=connect_phone)
        open_chat()
        threading.Thread(target=work, daemon=True).start()
        if not keep.get("backup_agent"):
            import backup
            keep["backup_agent"] = backup.BackupAgent(cfg, lambda t: bridge.chat("assistant", t))
            keep["backup_agent"].start()

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
                subprocess.Popen([sys.executable] + sys.argv, env=dict(__import__('os').environ, JARVIS_RESTARTING='1'))
                app.quit()

        win.saved.connect(saved)
        keep["settings"] = win
        win.show()
        if first:
            preview("amy", "Hi, I'm Jarvis, by Apricot Digital. Fill in your details and press Start.")

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
        subprocess.Popen([sys.executable] + sys.argv, creationflags=flags, env=dict(os.environ, JARVIS_RESTARTING='1'))
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

    def open_welcome():
        win = WelcomeWindow(LOGO)

        def started(v):
            cfg["owner_name"], cfg["language"], cfg["onboarded"] = v["owner_name"], v["language"], True
            if v["key"]:
                store.set("anthropic", v["key"])
            if v["owner_name"]:
                mem.remember("user_name", v["owner_name"])
            if v.get("backup_email"):
                cfg.setdefault("backup", {})["email"] = v["backup_email"]
            if v.get("backup_password"):
                store.set("backup_password", v["backup_password"])
            save_config(cfg)
            who = cfg["owner_name"] or "friend"
            hello = (f"\u062e\u0648\u0634 \u0622\u0645\u062f\u06cc\u062f {who}\u06d4 \u0645\u06cc\u06ba \u062a\u06cc\u0627\u0631 \u06c1\u0648\u06ba\u06d4"
                     if v["language"] == "ur" else f"All set, {who}. Say hey {name()} whenever you need me.")
            start_assistant(hello)
            if v.get("scan"):
                import deep_scan
                base = {"Documents", "Desktop", "Downloads"}
                import files as _f
                picked = v.get("scan_folders", [])
                roots = [f for f in picked if Path(f).name in base and Path(f).parent == _f.HOME]
                if roots:
                    cfg["file_roots"] = roots  # only the standard folders the owner ticked
                save_config(cfg)
                deep_scan.grant([f for f in picked if not (Path(f).name in base and Path(f).parent == _f.HOME)],
                                v.get("scan_whatsapp", True), v.get("scan_email", True))

                def first_scan():
                    time.sleep(3)
                    bridge.chat("assistant", "Thank you. I'm learning where your documents are now. You can keep "
                                             "working; I'll tell you when it's done.")
                    try:
                        deep_scan.run_scan(cfg, full=True)
                        bridge.chat("assistant", deep_scan._summary("All done."))
                    except Exception as e:
                        bridge.chat("assistant", f"The scan stopped: {e}")
                keep["first_scan"] = first_scan
            if v["link_whatsapp"]:
                def link():
                    try:
                        import whatsapp_reader
                        bridge.chat("assistant", "Opening WhatsApp. On your phone: WhatsApp > Settings > Linked devices > "
                                                 "Link a device, then point the phone at the code on the screen.")
                        msg = whatsapp_reader.link()
                        bridge.chat("assistant", msg + (" I'm collecting your documents in the background now."
                                                        if "linked" in msg else ""))
                        if keep.get("first_scan"):
                            keep.pop("first_scan")()
                    except Exception as e:
                        bridge.chat("assistant", f"WhatsApp could not be linked just now ({e}). You can try again from "
                                                 "the Jarvis icon near the clock: Link WhatsApp.")
                threading.Thread(target=link, daemon=True).start()
            elif keep.get("first_scan"):
                threading.Thread(target=keep.pop("first_scan"), daemon=True).start()

        def do_restore():
            from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox
            import backup
            start = str(backup.default_dir(cfg)) if backup.default_dir(cfg).exists() else ""
            path, _ = QFileDialog.getOpenFileName(win, "Choose your Jarvis backup file", start, "Jarvis backup (*.jbk)")
            if not path:
                return
            try:
                about = backup.info(Path(path))
            except Exception as e:
                QMessageBox.warning(win, "Jarvis", str(e))
                return
            label = f"Backup of {about.get('owner') or 'Jarvis'}, made {about.get('made', '?')}.\n\nBackup password:"
            for _ in range(3):
                pw, ok = QInputDialog.getText(win, "Restore from a backup", label, QLineEdit.Password)
                if not ok:
                    return
                try:
                    backup.restore(Path(path), pw)
                    break
                except PermissionError as e:
                    label = f"{e}\n\nTry the backup password again:"
                except Exception as e:
                    QMessageBox.warning(win, "Jarvis", f"The backup could not be restored: {e}")
                    return
            else:
                return
            QMessageBox.information(win, "Jarvis", "Your backup is restored. Jarvis will now restart with your settings, "
                                                   "notes and reminders.\n\nAfter it starts: link WhatsApp once more "
                                                   "(Jarvis icon > Link WhatsApp).")
            restart_now()

        win.started.connect(started)
        win.restore.connect(do_restore)
        win.more.connect(lambda: (win.close(), open_settings(True)))
        keep["settings"] = win
        win.show()

    if cfg.get("onboarded"):
        start_assistant()
    else:
        open_welcome()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
