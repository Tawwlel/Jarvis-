"""
Jarvis by Apricot Digital - interface.

- Overlay: translucent, always-on-top orb in a screen corner. It pops up when
  Jarvis is called and pulses (shrinks/expands) with your voice and his.
- SettingsWindow: first-run welcome and the settings screen (same form).
- Tray icon: talk / settings / quit.
"""
import math

from PySide6.QtCore import (QObject, QPointF, QPropertyAnimation, QRectF, Qt, QTime, QTimer, Signal)
from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QPushButton, QSystemTrayIcon, QTabWidget,
                               QTextBrowser, QTimeEdit, QVBoxLayout, QWidget)

RED, GOLD = QColor(255, 48, 48), QColor(245, 193, 74)
STATE_TEXT = {"idle": "", "listening": "LISTENING", "thinking": "THINKING",
              "speaking": "SPEAKING", "working": "WORKING", "notes": "TAKING NOTES"}


class Bridge(QObject):
    """Thread-safe link: the assistant thread calls these, the UI thread reacts."""
    show_sig, hide_sig = Signal(), Signal(int)
    state_sig, level_sig = Signal(str), Signal(float)
    chat_sig = Signal(str, str)  # role, text

    def show(self): self.show_sig.emit()
    def hide_later(self, ms=2500): self.hide_sig.emit(ms)
    def state(self, s): self.state_sig.emit(s)
    def level(self, v): self.level_sig.emit(float(v))
    def chat(self, role, text): self.chat_sig.emit(role, text)


class Overlay(QWidget):
    W, H = 280, 330

    def __init__(self, bridge: Bridge, logo_path: str, get_name, corner="bottom-right", caption=True):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(self.W, self.H)
        self.logo = QPixmap(logo_path)
        self.get_name, self.corner, self.caption = get_name, corner, caption
        self.state, self.level, self._ext, self.t = "idle", 0.0, 0.0, 0.0
        self._token, self._moved, self._drag = 0, False, None
        self.anim = QPropertyAnimation(self, b"windowOpacity", self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        bridge.show_sig.connect(self.pop)
        bridge.hide_sig.connect(self.hide_later)
        bridge.state_sig.connect(self.set_state)
        bridge.level_sig.connect(self.set_level)

    # ----- behaviour -----
    def set_state(self, s): self.state = s
    def set_level(self, v): self._ext = max(0.0, min(1.0, v))

    def _place(self):
        if self._moved:
            return
        from PySide6.QtGui import QGuiApplication

        g = QGuiApplication.primaryScreen().availableGeometry()
        x = g.left() + 24 if "left" in self.corner else g.right() - self.W - 24
        y = g.top() + 24 if "top" in self.corner else g.bottom() - self.H - 24
        self.move(x, y)

    def pop(self):
        self._token += 1
        self._place()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
        self.anim.stop()
        self.anim.setDuration(220)
        self.anim.setStartValue(self.windowOpacity())
        self.anim.setEndValue(1.0)
        self.anim.start()

    def hide_later(self, ms):
        token = self._token
        QTimer.singleShot(ms, lambda: self._fade_out(token))

    def _fade_out(self, token):
        if token != self._token or not self.isVisible():
            return
        self.anim.stop()
        self.anim.setDuration(400)
        self.anim.setStartValue(self.windowOpacity())
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self._after_fade)
        self.anim.start()

    def _after_fade(self):
        try:
            self.anim.finished.disconnect(self._after_fade)
        except (TypeError, RuntimeError):
            pass
        if self.windowOpacity() < 0.05:
            self.hide()

    def _tick(self):
        self.t += 0.016
        if self.state == "thinking" or self.state == "working":
            target = 0.28 + 0.2 * math.sin(self.t * 5)
        elif self.state == "notes":
            target = 0.12 + 0.08 * math.sin(self.t * 1.6)
        elif self.state in ("listening", "speaking"):
            target = self._ext
        else:
            target = 0.0
        self.level += (target - self.level) * 0.35
        if self.isVisible():
            self.update()

    # ----- painting -----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform
                         | QPainter.TextAntialiasing)
        cx, cy, lv, t = self.W / 2, 140.0, self.level, self.t
        glow = QRadialGradient(cx, cy, 118)
        glow.setColorAt(0, QColor(255, 60, 60, int(95 * lv + 28)))
        glow.setColorAt(1, QColor(255, 60, 60, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), 118, 118)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 80, 80, 55), 1))
        p.drawEllipse(QPointF(cx, cy), 82 + lv * 9, 82 + lv * 9)
        # HUD arcs, like an arc-reactor read-out
        for i, (r, w, speed, span, n) in enumerate([(92, 2.2, 1.0, 62, 3), (105, 1.6, -1.5, 34, 4),
                                                   (118, 1.1, 0.7, 20, 6)]):
            rad = r + lv * (10 + 6 * i)
            col = QColor(GOLD)
            col.setAlpha(190 if i == 0 else 120)
            pen = QPen(col, w)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            for k in range(n):
                start = (t * speed * 42 + k * 360 / n) % 360
                p.drawArc(QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad), int(start * 16), int(span * 16))
        # the logo: grows and shrinks with the voice
        s = 128 * (1 + 0.30 * lv + 0.02 * math.sin(t * 2))
        p.drawPixmap(QRectF(cx - s / 2, cy - s / 2, s, s), self.logo, QRectF(self.logo.rect()))
        if self.caption:
            f = QFont("Segoe UI", 9, QFont.Bold)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 3)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 225))
            p.drawText(QRectF(0, 268, self.W, 20), Qt.AlignCenter, self.get_name().upper())
            f.setPointSize(8)
            p.setFont(f)
            p.setPen(QColor(GOLD.red(), GOLD.green(), GOLD.blue(), 220))
            p.drawText(QRectF(0, 290, self.W, 18), Qt.AlignCenter, STATE_TEXT.get(self.state, ""))

    # ----- drag to move -----
    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)
            self._moved = True

    def mouseReleaseEvent(self, _):
        self._drag = None


QSS = """
QWidget{background:#0a0d14;color:#e6ebf5;font-family:'Segoe UI';font-size:13px}
QLineEdit,QComboBox,QTimeEdit{background:#111826;border:1px solid #2a3346;border-radius:6px;padding:7px}
QLineEdit:focus,QComboBox:focus,QTimeEdit:focus{border:1px solid #ff3030}
QComboBox QAbstractItemView{background:#111826;selection-background-color:#ff3030}
QPushButton{background:#ff3030;color:white;border:none;border-radius:6px;padding:10px 18px;font-weight:600}
QPushButton:hover{background:#ff5252}
QPushButton#ghost{background:transparent;border:1px solid #2a3346;padding:7px 12px}
QPushButton#ghost:hover{border-color:#f5c14a}
QCheckBox{spacing:8px}
QLabel#section{color:#f5c14a;font-size:10px;letter-spacing:3px;font-weight:600}
QLabel#sub{color:#8b95aa}
QTabWidget::pane{border:1px solid #1f283a;border-radius:6px;top:-1px}
QTabBar::tab{background:#0a0d14;color:#8b95aa;padding:9px 14px;border:none;border-bottom:2px solid transparent}
QTabBar::tab:selected{color:#e6ebf5;border-bottom:2px solid #ff3030}
QTextBrowser{background:#0d121c;border:1px solid #1f283a;border-radius:6px;padding:8px}
"""

PROVIDERS = {
    "llm": [("Anthropic (Claude)", "anthropic"), ("OpenAI-compatible (OpenAI, OpenRouter, Groq...)", "openai_compatible")],
    "stt": [("Local Whisper (free, private)", "local_whisper"), ("OpenAI Whisper (online)", "openai_whisper")],
    "tts": [("Piper voices (free, private)", "piper"), ("ElevenLabs (online)", "elevenlabs")],
}
LANGS = [("Auto - Urdu or English, whichever I speak", "auto"), ("English only", "en"), ("Urdu only", "ur")]
URDU_VOICES = [("Asad (male)", "ur-PK-AsadNeural"), ("Uzma (female)", "ur-PK-UzmaNeural"),
               ("Salman (male, India)", "ur-IN-SalmanNeural"), ("Gul (female, India)", "ur-IN-GulNeural")]
WHISPER_SIZES = ["base.en", "small", "medium", "large-v3"]


def _section(text):
    lab = QLabel(text.upper())
    lab.setObjectName("section")
    return lab


def _note(text):
    lab = QLabel(text)
    lab.setObjectName("sub")
    lab.setWordWrap(True)
    return lab


def _combo(pairs, current):
    c = QComboBox()
    for label, value in pairs:
        c.addItem(label, value)
    i = c.findData(current)
    c.setCurrentIndex(max(0, i))
    return c


def _csv(text):
    return [t.strip() for t in text.split(",") if t.strip()]


class SettingsWindow(QWidget):
    saved = Signal(dict)

    def __init__(self, cfg: dict, logo_path: str, first_run: bool, voices: list, preview,
                 store=None, roles: dict | None = None, profile: dict | None = None):
        super().__init__()
        self.setWindowTitle("Jarvis by Apricot Digital")
        self.setStyleSheet(QSS)
        self.setMinimumWidth(560)
        self.cfg, self.preview, self.store = cfg, preview, store
        self.roles = (roles or {}).get("roles", {})
        profile = profile or {}
        has = lambda k: bool(store and store.has(k))
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(10)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(logo_path).scaled(58, 58, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        titles = QVBoxLayout()
        title = QLabel("JARVIS")
        title.setStyleSheet("font-size:26px;font-weight:700;letter-spacing:8px;")
        by = QLabel("BY APRICOT DIGITAL")
        by.setStyleSheet("color:#f5c14a;font-size:10px;letter-spacing:4px;")
        titles.addWidget(title)
        titles.addWidget(by)
        head.addWidget(logo)
        head.addSpacing(10)
        head.addLayout(titles)
        head.addStretch()
        root.addLayout(head)
        root.addWidget(_note("Hi, I'm your Jarvis. Tell me a little about you and I'll take it from there."
                             if first_run else "Settings"))
        tabs = QTabWidget()
        root.addWidget(tabs)

        # ---------------- You ----------------
        you = QWidget()
        f = QFormLayout(you)
        f.setSpacing(9)
        self.name = QLineEdit(cfg.get("owner_name", ""))
        self.name.setPlaceholderText("What's your name?")
        self.work = QLineEdit(profile.get("working_on", ""))
        self.work.setPlaceholderText("What are you currently working on?")
        self.role = QComboBox()
        self.role.addItem("Choose...", "")
        for key, r in self.roles.items():
            self.role.addItem(r["label"], key)
        self.role.setCurrentIndex(max(0, self.role.findData(profile.get("role", ""))))
        self.company = QLineEdit(profile.get("company", ""))
        self.website = QLineEdit(profile.get("website", ""))
        self.website.setPlaceholderText("https://")
        self.role_box = QFormLayout()
        self.role_fields: dict[str, QLineEdit] = {}
        self._profile = profile
        f.addRow(_section("You"))
        f.addRow("Name", self.name)
        f.addRow("I am a", self.role)
        f.addRow("Company", self.company)
        f.addRow("Website", self.website)
        f.addRow("Working on", self.work)
        f.addRow(self.role_box)
        self.role.currentIndexChanged.connect(self._rebuild_role)
        self._rebuild_role()
        tabs.addTab(you, "You")

        # ---------------- Assistant ----------------
        asst = QWidget()
        f = QFormLayout(asst)
        f.setSpacing(9)
        self.names = QLineEdit(", ".join(cfg.get("assistant_names", ["Jarvis"])))
        self.voice = QComboBox()
        self.voice.addItems(voices)
        self.voice.setCurrentText(cfg.get("voice", "amy"))
        pv = QPushButton("Preview")
        pv.setObjectName("ghost")
        pv.clicked.connect(lambda: self.preview(self.voice.currentText()))
        vrow = QHBoxLayout()
        vrow.addWidget(self.voice, 1)
        vrow.addWidget(pv)
        self.lang = _combo(LANGS, cfg.get("language", "auto"))
        self.urdu_voice = _combo(URDU_VOICES, cfg.get("slots", {}).get("tts", {}).get("urdu_voice", "ur-PK-AsadNeural"))
        self.brief_on = QCheckBox("Daily brief at")
        self.brief_on.setChecked(cfg.get("briefing_enabled", True))
        self.brief_time = QTimeEdit()
        self.brief_time.setDisplayFormat("HH:mm")
        h, m = map(int, cfg.get("briefing_time", "08:30").split(":"))
        self.brief_time.setTime(QTime(h, m))
        brow = QHBoxLayout()
        brow.addWidget(self.brief_on)
        brow.addWidget(self.brief_time)
        brow.addStretch()
        self.hotkey = QLineEdit(cfg.get("hotkey", "ctrl+alt+j"))
        self.wake = QCheckBox('Answer to "Hey <name>" (always listening, on this PC only)')
        self.wake.setChecked(cfg.get("wake_word_enabled", True))
        f.addRow(_section("Assistant"))
        f.addRow("Call me", self.names)
        f.addRow("Voice", vrow)
        f.addRow("Language", self.lang)
        f.addRow("Urdu voice", self.urdu_voice)
        f.addRow(_note("Urdu needs the Whisper model 'small' or bigger for listening (set automatically) and "
                       "internet for the Urdu voice."))
        f.addRow(_section("Routine"))
        f.addRow("", brow)
        f.addRow("Shortcut", self.hotkey)
        f.addRow(self.wake)
        tabs.addTab(asst, "Assistant")

        # ---------------- Keys & models ----------------
        km = QWidget()
        f = QFormLayout(km)
        f.setSpacing(9)
        slots = cfg.get("slots", {})
        self.llm_p = _combo(PROVIDERS["llm"], slots.get("llm", {}).get("provider", "anthropic"))
        self.base_url = QLineEdit(slots.get("llm", {}).get("base_url", "https://api.openai.com/v1"))
        self.m_fast = QLineEdit(cfg["models"].get("tier1_cloud", ""))
        self.m_strong = QLineEdit(cfg["models"].get("tier2_cloud", ""))
        self.m_local = QLineEdit(cfg["models"].get("tier0_local") or "")
        self.m_local.setPlaceholderText("Light Ollama model, e.g. gemma3:1b (optional)")
        self.k_anthropic = self._secret("Anthropic key (sk-ant-...)", has("anthropic"))
        self.k_openai = self._secret("OpenAI-compatible key", has("openai"))
        self.stt_p = _combo(PROVIDERS["stt"], slots.get("stt", {}).get("provider", "local_whisper"))
        self.stt_m = _combo([(x, x) for x in WHISPER_SIZES], slots.get("stt", {}).get("model", "base.en"))
        self.tts_p = _combo(PROVIDERS["tts"], slots.get("tts", {}).get("provider", "piper"))
        self.k_eleven = self._secret("ElevenLabs key", has("elevenlabs"))
        self.eleven_voice = QLineEdit(slots.get("tts", {}).get("elevenlabs_voice_id", ""))
        self.eleven_voice.setPlaceholderText("ElevenLabs voice ID")
        f.addRow(_note("Keys are stored encrypted in Windows Credential Manager, never in a file. "
                       "Leave a key blank to keep the saved one."))
        f.addRow(_section("Language model"))
        f.addRow("Provider", self.llm_p)
        f.addRow("Base URL", self.base_url)
        f.addRow("Fast model", self.m_fast)
        f.addRow("Strong model", self.m_strong)
        f.addRow("Local model", self.m_local)
        f.addRow(_note("A small model that runs free on this PC through Ollama (e.g. gemma3:1b) for quick, simple "
                       "chat and topics you keep private. Bigger models need 16 GB of RAM."))
        f.addRow("Anthropic key", self.k_anthropic)
        f.addRow("OpenAI key", self.k_openai)
        f.addRow(_section("Speech recognition"))
        f.addRow("Provider", self.stt_p)
        f.addRow("Local model", self.stt_m)
        f.addRow(_note("base.en is English only. Choose small, medium or large-v3 for Urdu (slower, more accurate)."))
        f.addRow(_section("Voice"))
        f.addRow("Provider", self.tts_p)
        f.addRow("ElevenLabs key", self.k_eleven)
        f.addRow("ElevenLabs voice", self.eleven_voice)
        tabs.addTab(km, "Keys and models")

        # ---------------- Privacy ----------------
        pr = QWidget()
        f = QFormLayout(pr)
        f.setSpacing(9)
        p = cfg.get("privacy", {})
        self.priv_mode = _combo([("Balanced - hide private details before going online", "balanced"),
                                 ("Strict - keep anything private on this PC", "strict"),
                                 ("Off - no filtering", "off")], p.get("mode", "balanced"))
        self.priv_terms = QLineEdit(", ".join(p.get("private_terms", [])))
        self.priv_terms.setPlaceholderText("Client names, project code names...")
        self.priv_local = QLineEdit(", ".join(p.get("local_only_terms", [])))
        self.priv_local.setPlaceholderText("salary, medical, legal...")
        f.addRow(_note("Emails, phone numbers, card and ID numbers, keys and passwords are always swapped for "
                       "placeholders before anything goes online, and put back in the answer."))
        f.addRow("Mode", self.priv_mode)
        f.addRow("Always hide", self.priv_terms)
        f.addRow("Keep on this PC", self.priv_local)
        f.addRow(_note("Topics in 'Keep on this PC' are never sent online. This needs a local model (Ollama)."))
        tabs.addTab(pr, "Privacy")

        # ---------------- Abilities ----------------
        ab = QWidget()
        f = QFormLayout(ab)
        f.setSpacing(9)
        flags = cfg.get("tools_enabled", {})
        self.cal = QLineEdit()
        self.cal.setEchoMode(QLineEdit.Password)
        self.cal.setPlaceholderText("Calendar iCal link (saved)" if cfg.get("integrations", {}).get(
            "calendar_ics_url") else "Private iCal link from Google/Outlook (optional)")
        self.computer = QCheckBox("Let me take control of the computer (always asks first)")
        self.computer.setChecked(flags.get("computer_control", False))
        self.notes = QCheckBox("Offer to take meeting notes and summaries")
        self.notes.setChecked(flags.get("notes", True))
        self.roots = QLineEdit(", ".join(cfg.get("file_roots", [])))
        self.roots.setPlaceholderText("Default: Documents, Desktop, Downloads")
        f.addRow(_section("Abilities"))
        f.addRow("Calendar", self.cal)
        f.addRow(self.notes)
        f.addRow(self.computer)
        f.addRow("My files", self.roots)
        f.addRow(_note("Jarvis can find, read and edit files only in these folders. Deleting always asks, "
                       "and files go to the Recycle Bin."))
        tabs.addTab(ab, "Abilities")

        go = QPushButton("Start Jarvis" if first_run else "Save")
        go.clicked.connect(self._save)
        root.addWidget(go)

    def _secret(self, placeholder, saved):
        e = QLineEdit()
        e.setEchoMode(QLineEdit.Password)
        e.setPlaceholderText(placeholder + ("  (saved)" if saved else ""))
        return e

    def _rebuild_role(self):
        while self.role_box.rowCount():
            self.role_box.removeRow(0)
        self.role_fields = {}
        key = self.role.currentData()
        for q in self.roles.get(key, {}).get("questions", []):
            e = QLineEdit(self._profile.get(f"q.{q['key']}", ""))
            self.role_fields[q["key"]] = e
            self.role_box.addRow(q["prompt"], e)

    def values(self) -> dict:
        return {
            "owner_name": self.name.text().strip(), "working_on": self.work.text().strip(),
            "role": self.role.currentData() or "", "company": self.company.text().strip(),
            "website": self.website.text().strip(),
            "role_answers": {k: e.text().strip() for k, e in self.role_fields.items()},
            "assistant_names": _csv(self.names.text()) or ["Jarvis"], "voice": self.voice.currentText(),
            "briefing_enabled": self.brief_on.isChecked(),
            "briefing_time": self.brief_time.time().toString("HH:mm"),
            "hotkey": self.hotkey.text().strip() or "ctrl+alt+j",
            "wake_word_enabled": self.wake.isChecked(),
            "llm_provider": self.llm_p.currentData(), "llm_base_url": self.base_url.text().strip(),
            "model_fast": self.m_fast.text().strip(), "model_strong": self.m_strong.text().strip(),
            "model_local": self.m_local.text().strip(),
            "stt_provider": self.stt_p.currentData(), "stt_model": self.stt_m.currentData(),
            "language": self.lang.currentData(), "urdu_voice": self.urdu_voice.currentData(),
            "tts_provider": self.tts_p.currentData(), "elevenlabs_voice_id": self.eleven_voice.text().strip(),
            "keys": {"anthropic": self.k_anthropic.text().strip(), "openai": self.k_openai.text().strip(),
                     "elevenlabs": self.k_eleven.text().strip()},
            "privacy_mode": self.priv_mode.currentData(), "private_terms": _csv(self.priv_terms.text()),
            "local_only_terms": _csv(self.priv_local.text()),
            "calendar_url": self.cal.text().strip(), "computer_control": self.computer.isChecked(),
            "notes": self.notes.isChecked(), "file_roots": _csv(self.roots.text()),
        }

    def _save(self):
        self.saved.emit(self.values())
        self.close()


class ChatWindow(QWidget):
    """Plain text chat with the assistant. Spoken conversations show up here too."""
    submitted = Signal(str, bool)

    def __init__(self, bridge: Bridge, name: str):
        super().__init__()
        self.setWindowTitle(f"{name} - chat")
        self.setStyleSheet(QSS)
        self.resize(440, 560)
        lay = QVBoxLayout(self)
        self.log = QTextBrowser()
        self.log.setOpenExternalLinks(True)
        self.input = QLineEdit()
        self.input.setPlaceholderText(f"Message {name}...")
        self.input.returnPressed.connect(self._send)
        self.speak = QCheckBox("Speak replies aloud")
        send = QPushButton("Send")
        send.clicked.connect(self._send)
        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(send)
        lay.addWidget(self.log, 1)
        lay.addLayout(row)
        lay.addWidget(self.speak)
        bridge.chat_sig.connect(self.add)

    def add(self, role: str, text: str):
        who, color = ("You", "#8b95aa") if role == "user" else ("Jarvis", "#f5c14a")
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        self.log.append(f'<p style="margin:6px 0"><b style="color:{color}">{who}</b><br>{safe}</p>')

    def _send(self):
        t = self.input.text().strip()
        if t:
            self.input.clear()
            self.submitted.emit(t, self.speak.isChecked())


def make_tray(app, logo_path, name, on_talk, on_chat, on_settings, on_quit, on_selftest=None, on_speedtest=None):
    tray = QSystemTrayIcon(QIcon(logo_path), app)
    tray.setToolTip(f"{name} by Apricot Digital")
    menu = QMenu()
    items = [(f"Talk to {name}", on_talk), ("Open chat", on_chat)]
    if on_selftest:
        items.append(("Run document test", on_selftest))
    if on_speedtest:
        items.append(("Run speed test", on_speedtest))
    items += [("Settings", on_settings), ("Quit", on_quit)]
    for label, fn in items:
        act = QAction(label, menu)
        act.triggered.connect(fn)
        menu.addAction(act)
    tray.setContextMenu(menu)
    tray.show()
    tray._menu = menu  # keep a reference
    return tray
