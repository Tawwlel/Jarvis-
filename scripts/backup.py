"""
Backup and restore - so a client can move to a new laptop (or survive a broken one) and keep "their" Jarvis.

One file, Jarvis-backup-<date>.jbk, locked with a password only the owner knows:
  - settings, the saved keys and passwords, and the key that unlocks the memory
  - memory: notes, reminders, to-dos, remembered facts
  - learned invoice layouts, the built-in calendar
  - (full backups only) the documents and photos already downloaded from WhatsApp

Not included, because it rebuilds itself or belongs to the device: the search index, voices and models, the
WhatsApp link (scan the QR code once on the new laptop), the owner's own Documents folder.

Automatic: a small backup once a day into the owner's OneDrive (or Documents) "Jarvis Backups" folder, last 7 kept,
and once a week the same small file emailed to the owner's own backup address when their email is connected.

Locking: scrypt turns the password into a key; the file is encrypted in 1 MB pieces with AES-256-GCM, each piece
numbered so pieces cannot be dropped, reordered or altered. A forgotten password cannot be recovered by anyone.
"""
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import struct
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import config
from tools import CTX, tool

MAGIC = b"JBK1"
CHUNK = 1 << 20
SECRET_NAMES = ["anthropic", "openai", "elevenlabs", "email_password", "iphone_backup_password", "_memory_key", "phone_secret", "phone_key"]
SMALL_FILES = ["config.local.json", "calendar_local.json", "phone.json"]
SMTP = {"gmail.com": "smtp.gmail.com", "googlemail.com": "smtp.gmail.com", "yahoo.com": "smtp.mail.yahoo.com",
        "icloud.com": "smtp.mail.me.com", "me.com": "smtp.mail.me.com", "zoho.com": "smtp.zoho.com"}
_lock = threading.Lock()


def _root() -> Path:
    return config.ROOT


def _store():
    from secrets_store import default_store
    return default_store()


def settings(cfg) -> dict:
    b = cfg.setdefault("backup", {})
    b.setdefault("email", "")
    b.setdefault("folder", "")
    b.setdefault("auto", True)
    return b


def default_dir(cfg=None) -> Path:
    """The owner's OneDrive if this laptop has one (so the copy is off the laptop), else Documents."""
    custom = settings(cfg)["folder"] if cfg is not None else ""
    if custom:
        return Path(custom)
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        p = os.environ.get(var)
        if p and Path(p).is_dir():
            return Path(p) / "Jarvis Backups"
    if (Path.home() / "OneDrive").is_dir():
        return Path.home() / "OneDrive" / "Jarvis Backups"
    return Path.home() / "Documents" / "Jarvis Backups"


# ---------------- locking / unlocking ----------------
def _key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode("utf-8"))


def _lock_file(src: Path, dst: Path, password: str, meta: dict):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(16)
    aes = AESGCM(_key(password, salt))
    head = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    tag = hashlib.sha256(head).digest()  # ties every piece to this header
    size, done, i = src.stat().st_size, 0, 0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(MAGIC + salt + struct.pack(">I", len(head)) + head)
        while True:
            chunk = fi.read(CHUNK)
            done += len(chunk)
            last = done >= size
            ct = aes.encrypt(i.to_bytes(12, "big"), chunk, tag + (b"L" if last else b"M"))
            fo.write(struct.pack(">I", len(ct)) + ct)
            i += 1
            if last:
                break


def info(path: Path) -> dict:
    """What a backup file says about itself (readable without the password)."""
    with open(path, "rb") as f:
        if f.read(4) != MAGIC:
            raise ValueError("This is not a Jarvis backup file.")
        f.read(16)
        (n,) = struct.unpack(">I", f.read(4))
        return json.loads(f.read(n).decode("utf-8"))


def _unlock_file(src: Path, dst: Path, password: str) -> dict:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        if fi.read(4) != MAGIC:
            raise ValueError("This is not a Jarvis backup file.")
        salt = fi.read(16)
        (n,) = struct.unpack(">I", fi.read(4))
        head = fi.read(n)
        tag = hashlib.sha256(head).digest()
        aes = AESGCM(_key(password, salt))
        i, finished = 0, False
        while True:
            raw = fi.read(4)
            if not raw:
                break
            ct = fi.read(struct.unpack(">I", raw)[0])
            rest = fi.peek(1) if hasattr(fi, "peek") else b""
            last = not rest
            try:
                fo.write(aes.decrypt(i.to_bytes(12, "big"), ct, tag + (b"L" if last else b"M")))
            except InvalidTag:
                raise PermissionError("Wrong password, or the backup file is damaged.") from None
            finished = last
            i += 1
        if not finished:
            raise PermissionError("The backup file is incomplete.")
    return json.loads(head.decode("utf-8"))


# ---------------- making a backup ----------------
def create(password: str, dest_dir: Path | None = None, full: bool = False, cfg: dict | None = None,
           label: str = "") -> Path:
    if not password or len(password) < 6:
        raise ValueError("The backup password needs at least 6 characters.")
    cfg = cfg if cfg is not None else CTX.get("cfg") or config.load_config()
    root, store = _root(), _store()
    dest_dir = Path(dest_dir) if dest_dir else default_dir(cfg)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H%M")
    out = dest_dir / f"Jarvis-backup-{label + '-' if label else ''}{stamp}.jbk"
    meta = {"app": "Jarvis by Apricot Digital", "format": 1, "made": time.strftime("%Y-%m-%d %H:%M"),
            "owner": cfg.get("owner_name", ""), "email": settings(cfg)["email"], "kind": "full" if full else "small",
            "computer": socket.gethostname(), "home": str(Path.home())}
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_bk_"))
    try:
        with _lock:
            z_path = tmp / "b.zip"
            with zipfile.ZipFile(z_path, "w", zipfile.ZIP_DEFLATED) as z:
                for name in SMALL_FILES:
                    if (root / name).exists():
                        z.write(root / name, name)
                db = root / "jarvis_memory.db"
                if db.exists():  # a clean copy even while Jarvis is using it
                    snap = tmp / "jarvis_memory.db"
                    src = sqlite3.connect(db)
                    dst = sqlite3.connect(snap)
                    src.backup(dst)
                    src.close()
                    dst.close()
                    z.write(snap, "jarvis_memory.db")
                folders = ["data/invoice_templates"] + (["data/whatsapp"] if full else [])
                for folder in folders:
                    base = root / folder
                    if base.is_dir():
                        for p in base.rglob("*"):
                            if p.is_file():
                                z.write(p, p.relative_to(root).as_posix())
                secrets = {n: store.get(n) for n in SECRET_NAMES if store.get(n)}
                z.writestr("secrets.json", json.dumps(secrets))
                z.writestr("manifest.json", json.dumps(meta, ensure_ascii=False))
            part = out.with_suffix(".part")
            _lock_file(z_path, part, password, meta)
            part.replace(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


# ---------------- restoring ----------------
def restore(path: Path, password: str) -> dict:
    """Unlocks a backup and stages it; the files move into place at the next start (apply_pending), because the
    running app has the memory file open. Keys and passwords go into this laptop's secure storage right away."""
    root, store = _root(), _store()
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_rs_"))
    try:
        meta = _unlock_file(Path(path), tmp / "b.zip", password)
        stage = root / "restore_pending"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        with zipfile.ZipFile(tmp / "b.zip") as z:
            for item in z.infolist():
                dest = (stage / item.filename).resolve()
                if stage.resolve() not in dest.parents or item.is_dir():  # nothing may land outside the folder
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(item))
        sec = stage / "secrets.json"
        if sec.exists():
            for name, value in json.loads(sec.read_text()).items():
                if name in SECRET_NAMES and value:
                    store.set(name, value)
            sec.unlink()
        store.set("backup_password", password)  # so automatic backups continue on the new laptop
        return meta
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def apply_pending() -> bool:
    """Called first thing at start-up: moves a staged restore into place. Returns True if one was applied."""
    root = _root()
    stage = root / "restore_pending"
    if not stage.is_dir():
        return False
    try:
        meta = json.loads((stage / "manifest.json").read_text(encoding="utf-8")) if (stage / "manifest.json").exists() else {}
        for p in list(stage.rglob("*")):
            if not p.is_file() or p.name == "manifest.json":
                continue
            rel = p.relative_to(stage)
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if rel.as_posix() == "config.local.json":
                cfg = json.loads(p.read_text(encoding="utf-8"))
                _fit_to_this_laptop(cfg, meta.get("home", ""))
                dest.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            else:
                shutil.copy2(p, dest)
        # device-bound leftovers must not survive a move
        for stale in ("data/docs.db", "data/wa_agent.json", "data/iphone_import.json"):
            try:
                (root / stale).unlink()
            except OSError:
                pass
        print(f"[backup] restored the backup made {meta.get('made', '?')} on {meta.get('computer', '?')}")
        return True
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _fit_to_this_laptop(cfg: dict, old_home: str):
    """Folder settings from the old laptop: point them at this user's folders, drop the ones that don't exist."""
    new_home = str(Path.home())

    def fix(p):
        if old_home and str(p).lower().startswith(old_home.lower()):
            p = new_home + str(p)[len(old_home):]
        return p
    for key in ("file_roots", "doc_folders"):
        if cfg.get(key):
            kept = [fix(p) for p in cfg[key]]
            kept = [p for p in kept if Path(p).expanduser().exists()]
            if kept:
                cfg[key] = kept
            else:
                cfg.pop(key)  # fall back to Documents / Desktop / Downloads
    cfg.get("backup", {}).pop("folder", None)
    cfg.pop("iphone_backup_dir", None)
    cfg["onboarded"] = True


# ---------------- emailing the small backup to the owner's own address ----------------
def email_copy(path: Path, cfg: dict) -> str:
    """Sends the locked file from the owner's own mailbox to the owner's own backup address. Nothing else is ever
    emailed by Jarvis. Returns '' on success or the reason it was not sent."""
    to = settings(cfg)["email"].strip()
    e = cfg.get("email", {})
    sender, pw = (e.get("address") or "").strip(), _store().get("email_password")
    if not to:
        return "no backup email set"
    if not sender or not pw:
        return "email is not connected"
    host = SMTP.get(sender.split("@")[-1].lower()) or (e.get("server") or "").replace("imap", "smtp") or None
    if not host:
        return "this email provider can't send from Jarvis"
    if path.stat().st_size > 20 * 1024 * 1024:
        return "the backup is too large to email"
    import smtplib
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"], m["To"] = sender, to
    m["Subject"] = f"Jarvis backup {time.strftime('%d %b %Y')}"
    m.set_content("This is your Jarvis backup, sent by your own Jarvis.\n\nKeep this email. To restore on a new laptop: "
                  "install Jarvis, press 'Restore from a backup' on the welcome screen, choose the attached file and "
                  "type your backup password.\n\nThe file is locked. Without your password nobody can open it.")
    m.add_attachment(path.read_bytes(), maintype="application", subtype="octet-stream", filename=path.name)
    with smtplib.SMTP_SSL(host, 465, timeout=60) as s:
        s.login(sender, pw)
        s.send_message(m)
    return ""


# ---------------- automatic daily backup ----------------
def _state_file() -> Path:
    return _root() / "data" / "backup_state.json"


def _state() -> dict:
    try:
        return json.loads(_state_file().read_text())
    except Exception:
        return {}


def _save_state(st: dict):
    _state_file().parent.mkdir(parents=True, exist_ok=True)
    _state_file().write_text(json.dumps(st))


def auto_backup(cfg: dict, notify=None, keep=7) -> str:
    """One small backup a day; a copy by email once a week. Returns what happened (for the log)."""
    b = settings(cfg)
    if not b["auto"]:
        return "off"
    st = _state()
    pw = _store().get("backup_password")
    if not pw:
        if notify and not st.get("asked"):
            st["asked"] = time.time()
            _save_state(st)
            notify("Tip: set a backup password in Settings > Email & WhatsApp > Backup, and I'll keep a locked copy of "
                   "your settings and notes every day, ready for a new laptop.")
        return "no password"
    if time.time() - st.get("last", 0) < 23 * 3600:
        return "not due"
    out = create(pw, None, full=False, cfg=cfg, label="auto")
    autos = sorted(out.parent.glob("Jarvis-backup-auto-*.jbk"), key=lambda p: p.stat().st_mtime)
    for old in autos[:-keep]:
        old.unlink(missing_ok=True)
    st["last"] = time.time()
    result = f"saved {out.name}"
    if time.time() - st.get("emailed", 0) > 6.5 * 86400:
        try:
            why = email_copy(out, cfg)
        except Exception as e:
            why = str(e)
        if not why:
            st["emailed"] = time.time()
            result += ", emailed"
        else:
            result += f", not emailed ({why})"
    _save_state(st)
    return result


class BackupAgent(threading.Thread):
    def __init__(self, cfg, notify):
        super().__init__(daemon=True, name="backup-agent")
        self.cfg, self.notify = cfg, notify

    def run(self):
        time.sleep(120)
        while True:
            try:
                r = auto_backup(self.cfg, self.notify)
                if r not in ("not due", "off", "no password"):
                    print("[backup]", r)
            except Exception as e:
                print("[backup] failed:", e)
            time.sleep(3600)


@tool("backup_now",
      "Make a locked backup file of Jarvis (settings, keys, notes, reminders, learned layouts and the saved WhatsApp "
      "files) for moving to a new laptop or keeping safe. Uses the owner's backup password.", {}, [])
def backup_now():
    cfg = CTX.get("cfg") or config.load_config()
    pw = _store().get("backup_password")
    if not pw:
        return "No backup password is set yet. Ask the owner to set one in Settings > Email & WhatsApp > Backup."
    try:
        out = create(pw, None, full=True, cfg=cfg)
    except Exception as e:
        return f"The backup failed: {e}"
    size = out.stat().st_size / 1e6
    try:
        if os.name == "nt":
            os.startfile(out.parent)  # noqa
    except Exception:
        pass
    return (f"Backup saved: {out.name} ({size:.1f} MB) in the folder {out.parent}. Tell the owner to copy it to a USB "
            "drive too, and that it opens only with their backup password.")
