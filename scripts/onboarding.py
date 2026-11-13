"""First start, as the customer sees it, in this order:

  1. Welcome + activation key (from Apricot Digital; no API keys, credits or tokens are ever shown)
  2. Your privacy: everything stays on this computer, encrypted; nothing comes to Apricot Digital
  3. About you: what Jarvis calls you, language, tone, voice, your business
  4. Permissions: computer folders, Jarvis's own browser window, email, WhatsApp
  5. Backup (optional)
  -> START: syncing begins in the background and the Jarvis guide shows the app (TourWindow) meanwhile.

Staff can still paste a brain key on the first page with Ctrl+Shift+K (hidden from customers)."""
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget, QFileDialog)

from lang import TONE_RULES, tone_rule  # noqa: F401
from ui import BODY, DISPLAY, MONO, P, URDU_VOICES, _note

PRIVACY = ("Everything Jarvis learns - your files, WhatsApp, email and chats - is saved only on this computer, "
           "encrypted and locked to your Windows login. Nothing is sent to Apricot Digital. We never see your "
           "documents, messages or passwords. We respect your privacy.")
PRIVACY_UR = ("آپ کا سارا ڈیٹا صرف "
              "اسی کمپیوٹر پر محفوظ "
              "رہتا ہے۔ ہم آپ کی پرائیویسی "
              "کا احترام کرتے ہیں۔")
TONES = [("Friendly", "friendly"), ("Professional", "professional"), ("Short and direct", "short"),
         ("Respectful (Aap / Sir)", "respectful")]
EN_VOICES = [("Amy (female)", "amy"), ("Ryan (male)", "ryan"), ("Alan (male, British)", "alan"),
             ("Lessac (female, clear)", "lessac"), ("Southern (female, British)", "southern")]
BUSINESS = ["Trading / shop", "Manufacturing", "Services / agency", "Construction", "Transport / logistics",
            "Doctor / clinic", "Lawyer / accountant", "Personal use", "Other"]
STEPS = ["Welcome", "Privacy", "About you", "Permissions", "Backup"]


def _combo(pairs, current):
    c = QComboBox()
    for label, val in pairs:
        c.addItem(label, val)
    i = c.findData(current)
    c.setCurrentIndex(max(i, 0))
    return c


class OnboardingWizard(QWidget):
    """Same `started` dict as the old WelcomeWindow, plus: licence_key, tone, voice, urdu_voice, business,
    work, browser_ok, email_address, email_password."""
    started = Signal(dict)
    more = Signal()
    restore = Signal()

    def __init__(self, logo_path: str, preview=None, customer=True):
        super().__init__()
        self.preview, self.customer = preview, customer
        self.setWindowTitle("Welcome to Jarvis")
        self.setMinimumWidth(640)
        self.setStyleSheet(
            f"QLabel#h{{font-family:'{DISPLAY}';font-size:21px;font-weight:500;color:{P['fg']}}}"
            f"QLabel#dot{{font-family:'{MONO}';font-size:11px;color:{P['line']}}}"
            f"QLabel#doton{{font-family:'{MONO}';font-size:11px;color:{P['accent']}}}"
            f"QLabel#promise{{border:1px solid {P['accent']};padding:12px;font-size:14px;color:{P['fg']}}}"
            "QPushButton#go{font-size:13px;padding:11px 34px}")
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 18, 34, 16)
        root.setSpacing(10)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(logo_path).scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        top.addWidget(logo)
        self.dots = []
        for i, s in enumerate(STEPS):
            d = QLabel(f"{i + 1} {s.upper()}")
            self.dots.append(d)
            top.addSpacing(10)
            top.addWidget(d)
        top.addStretch()
        root.addLayout(top)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        for build in (self._p_welcome, self._p_privacy, self._p_you, self._p_perms, self._p_backup):
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(0, 6, 0, 0)
            lay.setSpacing(9)
            build(lay)
            lay.addStretch()
            self.pages.addWidget(w)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color:{P['accent']}")
        root.addWidget(self.warn)
        nav = QHBoxLayout()
        self.back = QPushButton("Back")
        self.back.setObjectName("ghost")
        self.back.clicked.connect(lambda: self._go_to(self.pages.currentIndex() - 1))
        rs = QPushButton("Restore from a backup")
        rs.setObjectName("ghost")
        rs.clicked.connect(self.restore.emit)
        nav.addWidget(self.back)
        nav.addWidget(rs)
        if not customer:
            adv = QPushButton("More settings")
            adv.setObjectName("ghost")
            adv.clicked.connect(self.more.emit)
            nav.addWidget(adv)
        nav.addStretch()
        self.next = QPushButton("NEXT")
        self.next.setObjectName("go")
        self.next.clicked.connect(self._next)
        nav.addWidget(self.next)
        root.addLayout(nav)
        QShortcut(QKeySequence("Ctrl+Shift+K"), self, activated=self._show_staff)
        self._go_to(0)
        self.resize(660, 600)

    # ---------- pages ----------
    def _h(self, lay, text, note=""):
        h = QLabel(text)
        h.setObjectName("h")
        h.setWordWrap(True)
        lay.addWidget(h)
        if note:
            lay.addWidget(_note(note))

    def _p_welcome(self, lay):
        self._h(lay, "Welcome to Jarvis",
                "Your personal assistant by Apricot Digital. It finds any invoice, receipt or document on this "
                "computer, in WhatsApp and in your email - just ask, in Urdu or English. Setup takes about 3 minutes.")
        lay.addWidget(QLabel("Activation key"))
        self.lic = QLineEdit()
        self.lic.setPlaceholderText("JRV-XXXX-XXXX-XXXX (from Apricot Digital)")
        lay.addWidget(self.lic)
        lay.addWidget(_note("Don't have it yet? You can continue and add it later; Apricot Digital will activate "
                            "Jarvis for you."))
        self.staff = QWidget()
        sl = QVBoxLayout(self.staff)
        sl.setContentsMargins(0, 6, 0, 0)
        sl.addWidget(QLabel("Staff only: brain key"))
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("sk-ant-...")
        sl.addWidget(self.key)
        self.staff.setVisible(not self.customer)
        lay.addWidget(self.staff)

    def _p_privacy(self, lay):
        self._h(lay, "Your data stays with you")
        pr = QLabel(PRIVACY)
        pr.setObjectName("promise")
        pr.setWordWrap(True)
        lay.addWidget(pr)
        ur = QLabel(PRIVACY_UR)
        ur.setWordWrap(True)
        ur.setAlignment(Qt.AlignRight)
        ur.setStyleSheet("font-size:16px")
        lay.addWidget(ur)
        for t in ("Jarvis only reads. It never changes, sends or deletes your files or messages.",
                  "Your passwords are kept in Windows' own locked password store.",
                  "The only things Jarvis tells Apricot Digital are that your licence is active and simple counts "
                  "like 'how many errors today', so we can fix problems. Never files, messages, names or questions.",
                  "You can stop Jarvis at any time, and ask it to forget everything it learned."):
            lay.addWidget(_note("• " + t))
        self.agree = QCheckBox("I understand. Let's continue.")
        self.agree.setChecked(True)
        lay.addWidget(self.agree)

    def _p_you(self, lay):
        self._h(lay, "A few questions about you", "Jarvis uses these to talk to you the way you like.")
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Talal, Talal bhai, Sir, Dr. Ahmed")
        lay.addWidget(QLabel("What should Jarvis call you?"))
        lay.addWidget(self.name)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Language"))
        self.lang = _combo([("Urdu and English (both)", "auto"), ("Urdu", "ur"), ("English", "en")], "auto")
        col.addWidget(self.lang)
        row.addLayout(col)
        col = QVBoxLayout()
        col.addWidget(QLabel("Tone"))
        self.tone = _combo(TONES, "friendly")
        col.addWidget(self.tone)
        row.addLayout(col)
        lay.addLayout(row)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("English voice"))
        vr = QHBoxLayout()
        self.voice = _combo(EN_VOICES, "amy")
        vr.addWidget(self.voice, 1)
        b = QPushButton("Listen")
        b.setObjectName("ghost")
        b.clicked.connect(lambda: self.preview and self.preview(self.voice.currentData()))
        vr.addWidget(b)
        col.addLayout(vr)
        row.addLayout(col)
        col = QVBoxLayout()
        col.addWidget(QLabel("Urdu voice"))
        self.uvoice = _combo(URDU_VOICES, "ur-PK-AsadNeural")
        col.addWidget(self.uvoice)
        row.addLayout(col)
        lay.addLayout(row)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Your work"))
        self.business = QComboBox()
        self.business.addItems(BUSINESS)
        col.addWidget(self.business)
        row.addLayout(col)
        col = QVBoxLayout()
        col.addWidget(QLabel("Business name (optional)"))
        self.work = QLineEdit()
        self.work.setPlaceholderText("e.g. Khan Traders")
        col.addWidget(self.work)
        row.addLayout(col)
        lay.addLayout(row)
        self.aname = QLineEdit("Jarvis")
        lay.addWidget(QLabel("What do you want to call your assistant? (you say this name to wake it)"))
        lay.addWidget(self.aname)

    def _p_perms(self, lay):
        self._h(lay, "Let Jarvis find your documents",
                "Tick what Jarvis may read. Remember: it stays on this computer, and Jarvis only reads.")
        # computer
        self.consent = QCheckBox("This computer - read my documents and photos in:")
        self.consent.setChecked(True)
        lay.addWidget(self.consent)
        import files as _files
        home = _files.HOME
        cand = [home / n for n in ("Documents", "Desktop", "Downloads", "Pictures")] + sorted(home.glob("OneDrive*"))
        frow = QHBoxLayout()
        frow.setContentsMargins(24, 0, 0, 0)
        self.folder_boxes = []
        for pth in [c for c in cand if c.is_dir()]:
            cb = QCheckBox(pth.name)
            cb.setChecked(True)
            cb.setProperty("path", str(pth))
            self.folder_boxes.append(cb)
            frow.addWidget(cb)
        add = QPushButton("+ Folder")
        add.setObjectName("ghost")
        add.clicked.connect(self._add_folder)
        frow.addWidget(add)
        frow.addStretch()
        lay.addLayout(frow)
        self.extra_lbl = _note("")
        self.extra_lbl.setContentsMargins(24, 0, 0, 0)
        lay.addWidget(self.extra_lbl)
        # browser
        self.browser_ok = QCheckBox("Browser - let Jarvis open its own browser window for WhatsApp Web")
        self.browser_ok.setChecked(True)
        lay.addWidget(self.browser_ok)
        # whatsapp
        self.wa = QCheckBox("WhatsApp - link my WhatsApp now (scan one QR code with your phone)")
        self.wa.setChecked(True)
        lay.addWidget(self.wa)
        wn = _note("Jarvis opens WhatsApp Web in its own browser window. On your phone: WhatsApp > Settings > Linked "
                   "devices > Link a device, and scan the code. Jarvis then syncs your WhatsApp in that same browser "
                   "window, where WhatsApp is logged in. Keep your phone on the internet while it syncs.")
        wn.setContentsMargins(24, 0, 0, 0)
        lay.addWidget(wn)
        # email
        self.mail_on = QCheckBox("Email - read attachments (invoices, receipts) from my email")
        lay.addWidget(self.mail_on)
        self.mail_box = QWidget()
        ml = QHBoxLayout(self.mail_box)
        ml.setContentsMargins(24, 0, 0, 0)
        self.e_addr = QLineEdit()
        self.e_addr.setPlaceholderText("you@gmail.com")
        self.e_pw = QLineEdit()
        self.e_pw.setEchoMode(QLineEdit.Password)
        self.e_pw.setPlaceholderText("App password")
        how = QPushButton("How?")
        how.setObjectName("ghost")
        how.clicked.connect(self._email_help)
        ml.addWidget(self.e_addr, 3)
        ml.addWidget(self.e_pw, 2)
        ml.addWidget(how)
        self.mail_box.setVisible(False)
        self.mail_on.toggled.connect(self.mail_box.setVisible)
        lay.addWidget(self.mail_box)
        self.mail_note = _note("Gmail: open myaccount.google.com/apppasswords, create one named Jarvis and paste the "
                               "16 letters here (needs 2-step verification on). Outlook/Hotmail: leave the password "
                               "empty; Jarvis will ask you to sign in with Microsoft.")
        self.mail_note.setVisible(False)
        lay.addWidget(self.mail_note)

    def _p_backup(self, lay):
        self._h(lay, "Backup (recommended)",
                "A locked daily copy of your settings, notes and reminders, saved on this computer and emailed to "
                "you if email is connected. Only your backup password opens it - write it down.")
        self.bk_email = QLineEdit()
        self.bk_email.setPlaceholderText("Your email, for backups (optional)")
        self.bk_pw = QLineEdit()
        self.bk_pw.setEchoMode(QLineEdit.Password)
        self.bk_pw.setPlaceholderText("Choose a backup password (6+ characters)")
        lay.addWidget(self.bk_email)
        lay.addWidget(self.bk_pw)
        lay.addSpacing(10)
        lay.addWidget(_note("When you press START, Jarvis starts learning your documents in the background, and the "
                            "Jarvis guide shows you around the app while it works."))

    # ---------- helpers ----------
    def _show_staff(self):
        self.staff.setVisible(True)
        self._go_to(0)
        self.key.setFocus()

    def _email_help(self):
        self.mail_note.setVisible(True)
        QDesktopServices.openUrl(QUrl("https://myaccount.google.com/apppasswords"))

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder for Jarvis to read")
        if d:
            self.extra = getattr(self, "extra", []) + [d]
            from pathlib import Path
            self.extra_lbl.setText("Also: " + ", ".join(Path(x).name for x in self.extra))

    def _go_to(self, i):
        i = max(0, min(i, self.pages.count() - 1))
        self.pages.setCurrentIndex(i)
        for n, d in enumerate(self.dots):
            d.setObjectName("doton" if n <= i else "dot")
            d.style().unpolish(d)
            d.style().polish(d)
        self.back.setVisible(i > 0)
        self.next.setText("START JARVIS" if i == self.pages.count() - 1 else "NEXT")
        self.warn.setText("")

    def _check(self, i) -> str:
        if i == 0:
            k = self.lic.text().strip().upper()
            if k and not re.fullmatch(r"JRV(-[A-Z0-9]{4}){3}", k):
                return "That activation key doesn't look right. It looks like JRV-XXXX-XXXX-XXXX. Leave it empty to add it later."
            b = self.key.text().strip()
            if b and not b.startswith("sk-"):
                return "That brain key doesn't look right (it starts with sk-)."
        if i == 1 and not self.agree.isChecked():
            return "Please tick the box to continue."
        if i == 3 and self.mail_on.isChecked():
            a = self.e_addr.text().strip()
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a):
                return "Please check the email address (or untick Email to skip it)."
        if i == 4:
            mail, bpw = self.bk_email.text().strip(), self.bk_pw.text()
            if mail and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", mail):
                return "Please check the backup email address."
            if bpw and len(bpw) < 6:
                return "The backup password needs at least 6 characters."
        return ""

    def _next(self):
        i = self.pages.currentIndex()
        err = self._check(i)
        if err:
            self.warn.setText(err)
            return
        if i < self.pages.count() - 1:
            self._go_to(i + 1)
            return
        self.started.emit(self.values())
        self.close()

    def values(self) -> dict:
        mail = self.mail_on.isChecked()
        wa = self.wa.isChecked() and self.browser_ok.isChecked()
        return {
            "licence_key": self.lic.text().strip().upper(), "key": self.key.text().strip(),
            "owner_name": self.name.text().strip(), "language": self.lang.currentData(),
            "tone": self.tone.currentData(), "voice": self.voice.currentData(), "urdu_voice": self.uvoice.currentData(),
            "business": self.business.currentText(), "work": self.work.text().strip(),
            "assistant_name": self.aname.text().strip() or "Jarvis",
            "scan": self.consent.isChecked(),
            "scan_folders": [b.property("path") for b in self.folder_boxes if b.isChecked()] + getattr(self, "extra", []),
            "scan_whatsapp": wa, "scan_email": mail, "scan_mode": "fast",
            "browser_ok": self.browser_ok.isChecked(), "link_whatsapp": wa,
            "email_address": self.e_addr.text().strip() if mail else "",
            "email_password": self.e_pw.text().strip() if mail else "",
            "backup_email": self.bk_email.text().strip(), "backup_password": self.bk_pw.text(),
        }


# ---------------- the Jarvis guide: shows the app while the first sync runs ----------------
TOUR = [
    ("Ask for any document", "Say \"Hey Jarvis\" or type in the chat:",
     ["find the latest sales invoice of Khan Traders", "Meezan Bank receipts from last month",
      "زاہد اینڈ سنز کی انوائس"]),
    ("Jarvis tells you where it found it", "Every answer says what, whose, the date and where: WhatsApp chat, "
     "email or the folder on this computer.", ["quotations we sent to Bilal Steel"]),
    ("Amounts, dates and numbers", "Search by amount, month or document number.",
     ["invoices above 3 lakh", "receipts march 2026", "invoice INV-1007"]),
    ("Open, collect and share", "Jarvis can open a file, or gather several into one folder for you.",
     ["open the latest quotation", "collect all invoices of Zahid and Sons in one folder"]),
    ("Email and reminders", "A daily summary of your email, and reminders by voice.",
     ["what's in my email today", "remind me at 5 pm to call the bank"]),
    ("Your phone", "Use the tray icon > Connect phone to ask Jarvis from your mobile.", []),
    ("Your plan", "The PLAN button shows if your plan is active. If it ever runs out, Jarvis will ask you to "
     "renew with Apricot Digital - your files stay safe.", []),
    ("Help is built in", "Ask Jarvis how to do anything. A care team quietly checks Jarvis every 30 minutes and "
     "fixes small problems by itself.", ["how do I link WhatsApp again", "is everything working"]),
]


class TourWindow(QWidget):
    """Shows the app's features one card at a time, with a live line saying what the sync has done so far.
    `try_it(text)` sends an example question to the chat."""
    def __init__(self, logo_path: str, status_fn=None, try_it=None):
        super().__init__()
        self.status_fn, self.try_it, self.i = status_fn, try_it, 0
        self.setWindowTitle("Jarvis guide")
        self.setMinimumWidth(520)
        self.setStyleSheet(f"QLabel#h{{font-family:'{DISPLAY}';font-size:20px;color:{P['fg']}}}"
                           f"QLabel#live{{font-family:'{MONO}';font-size:12px;color:{P['accent']}}}"
                           f"QPushButton#ex{{text-align:left;padding:8px 12px;border:1px solid {P['line']};"
                           f"background:transparent;color:{P['fg']};font-family:'{BODY}'}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 18, 28, 16)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(logo_path).scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        top.addWidget(logo)
        t = QLabel("JARVIS GUIDE  -  while I learn your documents")
        t.setStyleSheet(f"font-family:'{MONO}';font-size:11px;color:{P['fg']}")
        top.addWidget(t, 1)
        lay.addLayout(top)
        self.live = QLabel("Starting...")
        self.live.setObjectName("live")
        self.live.setWordWrap(True)
        lay.addWidget(self.live)
        self.count = QLabel("")
        self.count.setStyleSheet(f"font-family:'{MONO}';font-size:11px;color:{P['line']}")
        lay.addWidget(self.count)
        self.h = QLabel("")
        self.h.setObjectName("h")
        self.h.setWordWrap(True)
        lay.addWidget(self.h)
        self.body = _note("")
        lay.addWidget(self.body)
        self.ex_box = QVBoxLayout()
        lay.addLayout(self.ex_box)
        lay.addStretch()
        nav = QHBoxLayout()
        self.prev_b = QPushButton("Back")
        self.prev_b.setObjectName("ghost")
        self.prev_b.clicked.connect(lambda: self.show_card(self.i - 1))
        self.next_b = QPushButton("NEXT")
        self.next_b.clicked.connect(lambda: self.show_card(self.i + 1) if self.i < len(TOUR) - 1 else self.close())
        nav.addWidget(self.prev_b)
        nav.addStretch()
        nav.addWidget(self.next_b)
        lay.addLayout(nav)
        self.show_card(0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.refresh()
        self.resize(560, 420)

    def show_card(self, i):
        self.i = max(0, min(i, len(TOUR) - 1))
        title, text, examples = TOUR[self.i]
        self.count.setText(f"{self.i + 1} / {len(TOUR)}")
        self.h.setText(title)
        self.body.setText(text)
        while self.ex_box.count():
            w = self.ex_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        for e in examples:
            b = QPushButton(("Try:  " if self.try_it else "") + e)
            b.setObjectName("ex")
            if self.try_it:
                b.clicked.connect(lambda _=False, q=e: self.try_it(q))
            self.ex_box.addWidget(b)
        self.prev_b.setVisible(self.i > 0)
        self.next_b.setText("DONE" if self.i == len(TOUR) - 1 else "NEXT")

    def refresh(self):
        if not self.status_fn:
            self.live.setText("")
            return
        try:
            self.live.setText(self.status_fn())
        except Exception as e:
            self.live.setText(f"Learning your documents... ({e})")


def sync_status() -> str:
    """One line for the guide: what the first sync has found so far."""
    import deep_scan
    c = deep_scan._counts()
    running = getattr(deep_scan, "_lock", None) is not None and deep_scan._lock.locked()
    head = "Learning your documents now..." if running else "Your documents are ready."
    return (f"{head}  {c['total']} files so far: {c['computer']} on this computer, {c['whatsapp']} from WhatsApp, "
            f"{c['email']} from email.")
