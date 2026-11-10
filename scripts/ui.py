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
                               QLineEdit, QMenu, QPushButton, QSystemTrayIcon, QTimeEdit,
                               QVBoxLayout, QWidget)

RED, GOLD = QColor(255, 48, 48), QColor(245, 193, 74)
STATE_TEXT = {"idle": "", "listening": "LISTENING", "thinking": "THINKING",
              "speaking": "SPEAKING", "working": "WORKING", "notes": "TAKING NOTES"}


class Bridge(QObject):
    """Thread-safe link: the assistant thread calls these, the UI thread reacts."""
    show_sig, hide_sig = Signal(), Signal(int)
    state_sig, level_sig = Signal(str), Signal(float)

    def show(self): self.show_sig.emit()
    def hide_later(self, ms=2500): self.hide_sig.emit(ms)
    def state(self, s): self.state_sig.emit(s)
    def level(self, v): self.level_sig.emit(float(v))


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
"""


def _section(text):
    lab = QLabel(text.upper())
    lab.setObjectName("section")
    return lab


class SettingsWindow(QWidget):
    saved = Signal(dict)

    def __init__(self, cfg: dict, logo_path: str, first_run: bool, voices: list, preview, working_on=""):
        super().__init__()
        self.setWindowTitle("Jarvis by Apricot Digital")
        self.setStyleSheet(QSS)
        self.setMinimumWidth(480)
        self.cfg, self.preview = cfg, preview
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
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
        intro = QLabel("Hi, I'm your Jarvis. Tell me a little about you and I'll take it from there."
                       if first_run else "Settings")
        intro.setObjectName("sub")
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(9)
        self.name = QLineEdit(cfg.get("owner_name", ""))
        self.name.setPlaceholderText("What's your name?")
        self.work = QLineEdit(working_on)
        self.work.setPlaceholderText("What are you currently working on?")
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
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("sk-ant-...  (saved)" if self._has_key() else "sk-ant-...")
        self.cal = QLineEdit()
        self.cal.setEchoMode(QLineEdit.Password)
        self.cal.setPlaceholderText("Calendar iCal link (saved)" if cfg.get("integrations", {}).get(
            "calendar_ics_url") else "Private iCal link from Google/Outlook (optional)")
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
        flags = cfg.get("tools_enabled", {})
        self.wake = QCheckBox("Answer to \"Hey <name>\" (always listening, on this PC only)")
        self.wake.setChecked(cfg.get("wake_word_enabled", True))
        self.computer = QCheckBox("Let me take control of the computer (always asks first)")
        self.computer.setChecked(flags.get("computer_control", False))
        self.notes = QCheckBox("Offer to take meeting notes and summaries")
        self.notes.setChecked(flags.get("notes", True))

        form.addRow(_section("You"))
        form.addRow("Name", self.name)
        form.addRow("Working on", self.work)
        form.addRow(_section("Assistant"))
        form.addRow("Call me", self.names)
        form.addRow("Voice", vrow)
        form.addRow(_section("Connections"))
        form.addRow("API key", self.key)
        form.addRow("Calendar", self.cal)
        form.addRow(_section("Routine"))
        form.addRow("", brow)
        form.addRow("Shortcut", self.hotkey)
        form.addRow(_section("Abilities"))
        form.addRow(self.wake)
        form.addRow(self.computer)
        form.addRow(self.notes)
        root.addLayout(form)
        root.addSpacing(6)
        go = QPushButton("Start Jarvis" if first_run else "Save")
        go.clicked.connect(self._save)
        root.addWidget(go)

    def _has_key(self):
        k = self.cfg.get("anthropic_api_key", "")
        return bool(k) and k != "sk-ant-..."

    def values(self) -> dict:
        names = [n.strip() for n in self.names.text().split(",") if n.strip()] or ["Jarvis"]
        return {
            "owner_name": self.name.text().strip(), "working_on": self.work.text().strip(),
            "assistant_names": names, "voice": self.voice.currentText(),
            "api_key": self.key.text().strip(), "calendar_url": self.cal.text().strip(),
            "briefing_enabled": self.brief_on.isChecked(),
            "briefing_time": self.brief_time.time().toString("HH:mm"),
            "hotkey": self.hotkey.text().strip() or "ctrl+alt+j",
            "wake_word_enabled": self.wake.isChecked(),
            "computer_control": self.computer.isChecked(), "notes": self.notes.isChecked(),
        }

    def _save(self):
        self.saved.emit(self.values())
        self.close()


def make_tray(app, logo_path, name, on_talk, on_settings, on_quit):
    tray = QSystemTrayIcon(QIcon(logo_path), app)
    tray.setToolTip(f"{name} by Apricot Digital")
    menu = QMenu()
    for label, fn in ((f"Talk to {name}", on_talk), ("Settings", on_settings), ("Quit", on_quit)):
        act = QAction(label, menu)
        act.triggered.connect(fn)
        menu.addAction(act)
    tray.setContextMenu(menu)
    tray.show()
    tray._menu = menu  # keep a reference
    return tray
